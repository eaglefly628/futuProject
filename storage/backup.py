"""
数据库备份 / 恢复

把整个 K 线库导出成 Parquet（列存+压缩，比 SQLite 小一个数量级），
换机器后可完整恢复。用于跨设备搬运数据，避免把二进制 .db 塞进 git。

目录结构:
    backup_dir/
        manifest.json           标的/周期/条数/时间范围
        kline/SZ_159338__K_DAY.parquet
        kline/SZ_159338__K_5M.parquet
        ...
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, List, Dict

import pandas as pd
from loguru import logger

MANIFEST_NAME = "manifest.json"
KLINE_DIR = "kline"
SCHEMA_VERSION = 1


def _safe_name(code: str, ktype: str) -> str:
    return f"{code.replace('.', '_')}__{ktype}.parquet"


def _parse_name(fname: str) -> Optional[tuple]:
    """SZ_159338__K_DAY.parquet -> ("SZ.159338", "K_DAY")"""
    stem = Path(fname).stem
    if "__" not in stem:
        return None
    code_part, ktype = stem.rsplit("__", 1)
    parts = code_part.split("_", 1)
    code = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else code_part
    return code, ktype


def export_backup(db, out_dir: str,
                  progress: Optional[Callable[[str], None]] = None) -> dict:
    """
    导出全部 K 线数据到 Parquet。

    Returns:
        {"files": n, "rows": n, "size_mb": x, "path": str}
    """
    def log(msg):
        logger.info(msg)
        if progress:
            progress(msg)

    out = Path(out_dir)
    kdir = out / KLINE_DIR
    kdir.mkdir(parents=True, exist_ok=True)

    stats = db.get_stats()
    detail = stats.get("kline_detail", [])
    if not detail:
        raise RuntimeError("数据库中没有K线数据，无需备份")

    entries: List[Dict] = []
    total_rows = 0

    for i, row in enumerate(detail, 1):
        code, ktype, count = row[0], row[1], row[2]
        try:
            df = db.get_kline(code, ktype)
        except Exception as e:
            log(f"读取失败 {code} {ktype}: {e}")
            continue
        if df is None or df.empty:
            continue

        # id 是自增主键，恢复时重新生成，不必带走
        df = df.drop(columns=[c for c in ("id",) if c in df.columns])

        fname = _safe_name(code, ktype)
        df.to_parquet(kdir / fname, index=False,
                      engine="pyarrow", compression="snappy")

        entries.append({
            "code": code,
            "ktype": ktype,
            "rows": int(len(df)),
            "start": str(df["time_key"].iloc[0]),
            "end": str(df["time_key"].iloc[-1]),
            "file": f"{KLINE_DIR}/{fname}",
        })
        total_rows += len(df)
        log(f"[{i}/{len(detail)}] {code} {ktype}: {len(df):,} 条")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_files": len(entries),
        "total_rows": total_rows,
        "entries": entries,
    }
    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    size_mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1024 / 1024
    log(f"备份完成: {len(entries)} 个文件, {total_rows:,} 条, {size_mb:.2f} MB")

    return {"files": len(entries), "rows": total_rows,
            "size_mb": round(size_mb, 2), "path": str(out)}


def inspect_backup(backup_dir: str) -> dict:
    """读取备份清单，不做导入"""
    path = Path(backup_dir) / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(f"未找到备份清单: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def import_backup(db, backup_dir: str,
                  progress: Optional[Callable[[str], None]] = None) -> dict:
    """
    从备份恢复到数据库。

    走 save_kline 的 INSERT OR REPLACE，按 (code, ktype, time_key) 去重，
    因此可安全地对已有数据增量合并，不会产生重复。
    """
    def log(msg):
        logger.info(msg)
        if progress:
            progress(msg)

    root = Path(backup_dir)
    manifest_path = root / MANIFEST_NAME

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("entries", [])
        ver = manifest.get("schema_version")
        if ver != SCHEMA_VERSION:
            log(f"警告: 备份 schema 版本 {ver}，当前 {SCHEMA_VERSION}")
    else:
        # 没有清单就扫目录
        log("未找到清单，改为扫描 parquet 文件")
        entries = []
        for f in sorted((root / KLINE_DIR).glob("*.parquet")
                        if (root / KLINE_DIR).is_dir() else root.glob("*.parquet")):
            parsed = _parse_name(f.name)
            if parsed:
                entries.append({"code": parsed[0], "ktype": parsed[1],
                                "file": str(f.relative_to(root))})

    if not entries:
        raise RuntimeError("备份中没有可导入的数据")

    imported = 0
    failed = 0
    for i, e in enumerate(entries, 1):
        fpath = root / e["file"]
        if not fpath.exists():
            log(f"缺失文件: {e['file']}")
            failed += 1
            continue
        try:
            df = pd.read_parquet(fpath, engine="pyarrow")
            saved = db.save_kline(e["code"], e["ktype"], df)
            imported += saved
            log(f"[{i}/{len(entries)}] {e['code']} {e['ktype']}: {saved:,} 条")
        except Exception as ex:
            log(f"导入失败 {e.get('code')} {e.get('ktype')}: {ex}")
            failed += 1

    log(f"恢复完成: {imported:,} 条，失败 {failed} 个")
    return {"rows": imported, "failed": failed, "entries": len(entries)}


def make_archive(backup_dir: str, archive_path: str = None) -> str:
    """把备份目录打包成 zip，便于拷贝或上传"""
    src = Path(backup_dir)
    if archive_path:
        base = str(Path(archive_path).with_suffix(""))
    else:
        base = str(src.parent / f"{src.name}_{datetime.now():%Y%m%d_%H%M%S}")
    out = shutil.make_archive(base, "zip", root_dir=str(src))
    logger.info(f"已打包: {out}")
    return out


def extract_archive(archive_path: str, dest_dir: str = None) -> str:
    """解开 zip 备份，返回解压目录"""
    ap = Path(archive_path)
    dest = Path(dest_dir) if dest_dir else ap.parent / ap.stem
    dest.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(ap), str(dest))
    logger.info(f"已解压: {dest}")
    return str(dest)
