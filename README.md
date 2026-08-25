# FutuQuant - 富途量化数据平台

A500 ETF 量化交易系统，基于 Futu OpenD + PySide6。

## 快速开始

```bash
git clone https://github.com/eaglefly628/futuProject.git
cd futuProject
pip install -e .

# 启动 Futu OpenD 后运行
python main.py
```

## 命令行工具

```bash
python -m scripts.fetch_a500          # 采集 A500 ETF 全周期数据
python -m analysis.a500_analyzer SZ.159338  # 分析某只 ETF
```

## 项目结构

```
futuProject/
├── main.py              # GUI 入口
├── pyproject.toml        # 项目配置 (pip install -e .)
├── config/default.yaml   # 运行配置（费率/刷新间隔等）
├── core/                 # OpenD 客户端 + 实时行情订阅
├── downloaders/          # K线下载 + 逐笔采集
├── storage/              # SQLite 数据库 (WAL模式)
├── trading/              # 模拟交易引擎 + 费用计算
├── strategy/             # 策略引擎 + 回测 + 技术指标
├── analysis/             # 数据质量 + A500量价分析
├── gui/panels/           # 12个功能面板
├── scripts/              # 批量采集脚本
└── docs/                 # Futu API 文档
```

## 功能

| 模块 | 说明 |
|------|------|
| 实时行情 | 3秒刷新 + 价格预警 |
| 模拟交易 | 全市场CNY统一账户，A股/港股/美股真实费率 |
| 策略编辑 | 可视化条件 + Python脚本双模式 |
| 回测 | 收益率/回撤/夏普/胜率 |
| A500分析 | 5因子趋势预测 + 量价结构 + 支撑阻力 |
| 数据采集 | K线(9周期) + Tick，增量下载 |

## 依赖

Python >= 3.10 + Futu OpenD（本地）
