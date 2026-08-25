#!/usr/bin/env python3
"""
环境自检（命令行版）

界面里也有：系统设置 → 🩺 环境诊断 → 开始检测

    python -m scripts.doctor
    python -m scripts.doctor --no-net     跳过网络测试
"""
import sys


def main():
    from core.diagnostics import run_diagnostics, format_report_text

    check_net = "--no-net" not in sys.argv

    print("=" * 60)
    print("  FutuQuant 环境自检")
    print("=" * 60)

    rep = run_diagnostics(
        progress=lambda m: print(f"  ... {m}", flush=True),
        check_network=check_net)

    print(format_report_text(rep))
    print()

    if check_net:
        if rep.a_share_ok:
            srcs = " / ".join(rep.usable_sources)
            print(f"A股数据源可用（{srcs}）—— 可在「A500中心 → 数据采集」开始采集")
            if not rep.eastmoney_ok:
                print("  东财不可达，但 Yahoo 通；下载面板的「数据源」选 Yahoo 或自动即可")
        else:
            print("东财与 Yahoo 均不可访问 —— A股数据无法下载，需检查网络/代理")
    print()

    return 0 if rep.can_run else 1


if __name__ == "__main__":
    sys.exit(main())
