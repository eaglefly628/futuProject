#!/usr/bin/env python3
"""
环境自检 —— 一条命令查清依赖、平台、OpenD、数据库、网络

    python -m scripts.doctor
"""
import importlib
import platform
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

OK = "\033[92m✓\033[0m"
NO = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"

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


def section(title):
    print()
    print("─" * 60)
    print(f"【{title}】")
    print("─" * 60)


def main():
    print("=" * 60)
    print("  FutuQuant 环境自检")
    print("=" * 60)

    # ── 平台 ──
    section("运行环境")
    print(f"  系统      : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  Python    : {sys.version.split()[0]}")
    print(f"  解释器    : {sys.executable}")
    print(f"  项目目录  : {PROJECT_ROOT}")

    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        print(f"  {NO} 需要 Python 3.10+，当前 {major}.{minor}")
    else:
        print(f"  {OK} Python 版本满足要求")

    # ── 依赖 ──
    section("依赖检查")
    missing_required, missing_optional = [], []
    for mod, pkg, required, desc in DEPS:
        t = time.perf_counter()
        try:
            m = importlib.import_module(mod)
            cost = time.perf_counter() - t
            ver = getattr(m, "__version__", "?")
            slow = f"  \033[93m[加载 {cost:.1f}s]\033[0m" if cost > 2 else ""
            print(f"  {OK} {pkg:12s} {ver:12s} {desc}{slow}")
        except ImportError:
            mark = NO if required else WARN
            tag = "必需" if required else "可选"
            print(f"  {mark} {pkg:12s} {'未安装':12s} {desc}  [{tag}]")
            (missing_required if required else missing_optional).append(pkg)

    # ── 配置 ──
    section("配置与数据")
    cfg_path = PROJECT_ROOT / "config" / "default.yaml"
    print(f"  {OK if cfg_path.exists() else NO} config/default.yaml")

    local_path = PROJECT_ROOT / "config" / "local.yaml"
    if local_path.exists():
        print(f"  {OK} config/local.yaml（本地账号配置）")
    else:
        print(f"  {WARN} config/local.yaml 不存在 —— 需在「连接管理」里填账号密码")

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from config import Config
        cfg = Config(str(cfg_path))
        db_path = Path(cfg.get("storage", "sqlite_path"))
        if db_path.exists():
            size = db_path.stat().st_size / 1024 / 1024
            print(f"  {OK} 数据库 {db_path.name}  ({size:.2f} MB)")
            try:
                from storage.database import Database
                db = Database(str(db_path))
                s = db.get_stats()
                print(f"      K线 {s['kline_total']:,} 条 / {s['kline_stocks']} 个标的")
                db.close()
            except Exception as e:
                print(f"  {WARN} 数据库读取失败: {e}")
        else:
            print(f"  {WARN} 数据库尚未创建（首次启动会自动建）")
    except Exception as e:
        print(f"  {NO} 配置加载失败: {e}")

    # ── OpenD ──
    section("OpenD")
    try:
        from core.opend_launcher import list_opend_candidates, SEARCH_PATTERNS
        found = list_opend_candidates()
        if found:
            for f in found:
                print(f"  {OK} {f}")
        else:
            print(f"  {WARN} 未找到 OpenD。当前系统的搜索路径：")
            for p in SEARCH_PATTERNS.get(platform.system(), []):
                print(f"        {p}")
            print("      （只拉 A 股可以不装 OpenD）")
    except Exception as e:
        print(f"  {NO} 检查失败: {e}")

    # ── 网络 ──
    section("行情源连通性")
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
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/122.0.0.0 Safari/537.36",
                     "Referer": "https://quote.eastmoney.com/"},
            timeout=12)
        cost = time.perf_counter() - t
        klines = ((r.json().get("data") or {}).get("klines")) or []
        if klines:
            print(f"  {OK} 东方财富可访问  ({cost:.1f}s, 返回 {len(klines):,} 条)")
            print(f"      最新: {klines[-1][:40]}")
        else:
            print(f"  {WARN} 东财有响应但无数据: {str(r.text)[:120]}")
    except Exception as e:
        print(f"  {NO} 东财不可访问: {type(e).__name__}: {str(e)[:110]}")
        print("      A股数据将无法下载 —— 检查网络/VPN/防火墙")

    # ── 结论 ──
    section("结论")
    if missing_required:
        print(f"  {NO} 缺少必需依赖，先装这些：")
        print(f"      pip install {' '.join(missing_required)}")
    else:
        print(f"  {OK} 必需依赖齐全，可以运行  python main.py")
    if missing_optional:
        print(f"  {WARN} 可选依赖未装: {', '.join(missing_optional)}")
        print(f"      需要时再装:  pip install {' '.join(missing_optional)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
