# 富途量化数据平台 v2.0 GUI

> 富途风格深色主题 · 全图形界面 · 基于 Futu OpenD API

## 截图预览

- 深蓝黑色主题，左侧导航栏
- 仪表盘总览、K线下载、批量操作、逐笔采集
- 监控列表管理、数据导出、质量检查、系统设置

## 功能

| 模块 | 功能 | 状态 |
|------|------|------|
| 数据总览 | 仪表盘、统计卡片、数据明细表 | ✅ |
| K线下载 | 多周期K线、增量/全量模式、日期选择 | ✅ |
| 批量下载 | 监控列表一键下载、多K线类型 | ✅ |
| 逐笔采集 | 实时逐笔成交数据 | ✅ |
| 监控列表 | 添加/删除/快捷添加股票 | ✅ |
| 数据导出 | Parquet / CSV 导出 | ✅ |
| 质量检查 | 异常检测、缺失、跳价 | ✅ |
| 系统设置 | OpenD连接、下载参数、存储配置 | ✅ |
| 连接管理 | OpenD连接/断开、状态监控 | ✅ |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Futu OpenD

从 [Futu OpenD](https://openapi.futunn.com/) 下载并启动。

### 3. 启动 GUI

```bash
python main.py
```

### 4. 使用流程

1. 侧栏点击「连接管理」→ 连接 OpenD
2. 「监控列表」→ 添加股票代码
3. 「K线下载」或「批量下载」→ 获取数据
4. 「数据总览」查看统计，「质量检查」验证数据
5. 「数据导出」→ 导出 Parquet/CSV

## 项目结构

```
futu-quant-gui/
├── main.py                  # GUI 入口
├── requirements.txt
├── config/
│   ├── __init__.py          # 配置管理器
│   └── default.yaml         # 默认配置
├── core/
│   └── client.py            # Futu OpenD 客户端
├── downloaders/
│   ├── kline_downloader.py  # K线下载器
│   └── tick_collector.py    # 逐笔采集器
├── storage/
│   └── database.py          # SQLite 存储
├── analysis/
│   └── basic_stats.py       # 数据分析
├── gui/
│   ├── __init__.py
│   ├── theme.py             # 富途深色主题
│   ├── main_window.py       # 主窗口
│   ├── panels/
│   │   ├── base.py          # 面板基类
│   │   ├── dashboard.py     # 数据总览
│   │   ├── kline_download.py
│   │   ├── batch_download.py
│   │   ├── tick_collect.py
│   │   ├── watchlist.py
│   │   ├── export.py
│   │   ├── quality_check.py
│   │   ├── settings.py
│   │   └── connection.py
│   └── widgets/
│       └── worker.py        # 后台线程
├── data/                    # 数据目录
├── logs/                    # 日志
└── models/                  # ML模型 (预留)
```

## 技术栈

- **GUI**: PySide6 (Qt6)
- **主题**: 自定义深色 QSS，富途配色
- **后端**: 复用 v1.0 核心模块
- **多线程**: QThread 后台下载，界面不卡顿
