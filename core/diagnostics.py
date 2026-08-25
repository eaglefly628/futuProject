"""
环境诊断 —— 返回结构化结果，供命令行和 GUI 共用
"""
import importlib
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Callable

PROJECT_ROOT = Path(__file__).parent.parent

# (模块名, pip 包名, 是否必需, 说明)
DEPS = [
    ("PySide6", "PySide6", True, "GUI 框架"),
    ("pandas", "pandas", True, "数据处理"),
    ("numpy", "numpy", True, "数值计算"),
    ("yaml", "pyyaml", True, "配置文件"),
    ("loguru", "loguru", True, "日志"),
    ("requests", "requests", True, "东财直连"),
    ("pyarrow", "pyarrow", False, "Parquet 备份/导出"),
    ("futu", "futu-api", False, "港美股行情（A股可不装）"),
    ("akshare", "akshare", False, "A股回退源（东财直连正常时可不装）"),
]

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Check:
    """单项检查结果"""
    name: str
    status: str          # ok / warn / fail / info
    detail: str = ""
    hint: str = ""


@dataclass
class Report:
    sections: dict = field(default_factory=dict)   # {段名: [Check, ...]}
    missing_required: List[str] = field(default_factory=list)
    missing_optional: List[str] = field(default_factory=list)
    eastmoney_ok: bool = False

    def add(self, section: str, check: Check):
        self.sections.setdefault(section, []).append(check)

    @property
    def can_run(self) -> bool:
        return not self.missing_required


def run_diagnostics(progress: Optional[Callable[[str], None]] = None,
                    check_network: bool = True) -> Report:
    """执行全部检查"""
    def step(msg):
        if progress:
            progress(msg)

    rep = Report()

    # ── 运行环境 ──
    step("检查运行环境...")
    rep.add("运行环境", Check(
        "系统", INFO,
        f"{platform.system()} {platform.release()} ({platform.machine()})"))
    py_ver = sys.version.split()[0]
    ok_ver = sys.version_info[:2] >= (3, 10)
    rep.add("运行环境", Check(
        "Python", OK if ok_ver else FAIL, py_ver,
        "" if ok_ver else "需要 Python 3.10 或更高版本"))
    rep.add("运行环境", Check("解释器", INFO, sys.executable))
    rep.add("运行环境", Check("项目目录", INFO, str(PROJECT_ROOT)))

    # ── 依赖 ──
    step("检查依赖...")
    for mod, pkg, required, desc in DEPS:
        t = time.perf_counter()
        try:
            m = importlib.import_module(mod)
            cost = time.perf_counter() - t
            ver = getattr(m, "__version__", "?")
            detail = f"{ver}  · {desc}"
            if cost > 2:
                detail += f"  [加载耗时 {cost:.1f}s]"
            rep.add("依赖", Check(pkg, OK, detail))
        except ImportError:
            (rep.missing_required if required else rep.missing_optional).append(pkg)
            rep.add("依赖", Check(
                pkg, FAIL if required else WARN,
                f"未安装 · {desc}",
                f"pip install {pkg}"))

    # ── 配置与数据 ──
    step("检查配置与数据...")
    cfg_path = PROJECT_ROOT / "config" / "default.yaml"
    rep.add("配置与数据", Check(
        "default.yaml", OK if cfg_path.exists() else FAIL,
        str(cfg_path) if cfg_path.exists() else "缺失"))

    local_path = PROJECT_ROOT / "config" / "local.yaml"
    rep.add("配置与数据", Check(
        "local.yaml",
        OK if local_path.exists() else WARN,
        "已保存本地账号配置" if local_path.exists()
        else "不存在（在「连接管理」填账号密码并勾选记住即可生成）"))

    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from config import Config
        cfg = Config(str(cfg_path))
        db_path = Path(cfg.get("storage", "sqlite_path"))
        if db_path.exists():
            size = db_path.stat().st_size / 1024 / 1024
            try:
                from storage.database import Database
                db = Database(str(db_path))
                s = db.get_stats()
                db.close()
                rep.add("配置与数据", Check(
                    "数据库", OK,
                    f"{size:.2f} MB · K线 {s['kline_total']:,} 条 / "
                    f"{s['kline_stocks']} 个标的"))
            except Exception as e:
                rep.add("配置与数据", Check("数据库", WARN, f"读取失败: {e}"))
        else:
            rep.add("配置与数据", Check(
                "数据库", WARN, "尚未创建（首次采集时自动生成）"))
    except Exception as e:
        rep.add("配置与数据", Check("配置加载", FAIL, str(e)))

    # ── OpenD ──
    step("查找 OpenD...")
    try:
        from core.opend_launcher import list_opend_candidates
        found = list_opend_candidates()
        if found:
            for f in found[:5]:
                rep.add("OpenD", Check("已找到", OK, str(f)))
        else:
            rep.add("OpenD", Check(
                "未找到", WARN, "项目目录和系统常见位置均未发现",
                "只做 A 股可以不装 OpenD；港美股需要"))
    except Exception as e:
        rep.add("OpenD", Check("检查失败", WARN, str(e)))

    # ── 网络 ──
    if check_network:
        step("测试东方财富连通性...")
        try:
            import requests
            t = time.perf_counter()
            r = requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params={"secid": "0.159338", "klt": "101", "fqt": "1",
                        "fields1": "f1,f2,f3,f4,f5,f6",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                        "ut": "7eea3edcaed734bea9cbfc24409ed989",
                        "beg": "0", "end": "20500000"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/122.0.0.0 Safari/537.36",
                    "Referer": "https://quote.eastmoney.com/"},
                timeout=12)
            cost = time.perf_counter() - t
            klines = ((r.json().get("data") or {}).get("klines")) or []
            if klines:
                rep.eastmoney_ok = True
                rep.add("行情源", Check(
                    "东方财富", OK,
                    f"{cost:.1f}s · 返回 {len(klines):,} 条 · 最新 {klines[-1][:20]}"))
            else:
                rep.add("行情源", Check(
                    "东方财富", WARN, f"有响应但无数据: {str(r.text)[:100]}"))
        except Exception as e:
            rep.add("行情源", Check(
                "东方财富", FAIL, f"{type(e).__name__}: {str(e)[:110]}",
                "A股数据将无法下载，检查网络 / VPN / 防火墙"))

    step("完成")
    return rep


def format_report_text(rep: Report) -> str:
    """纯文本格式（命令行用）"""
    mark = {OK: "✓", WARN: "!", FAIL: "✗", INFO: " "}
    lines = []
    for section, checks in rep.sections.items():
        lines.append(f"\n【{section}】")
        for c in checks:
            lines.append(f"  {mark[c.status]} {c.name:14s} {c.detail}")
            if c.hint:
                lines.append(f"      → {c.hint}")
    lines.append("")
    if rep.missing_required:
        lines.append(f"缺少必需依赖: pip install {' '.join(rep.missing_required)}")
    else:
        lines.append("必需依赖齐全")
    if rep.missing_optional:
        lines.append(f"可选未装: pip install {' '.join(rep.missing_optional)}")
    return "\n".join(lines)
