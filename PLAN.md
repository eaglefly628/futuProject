# Futu OpenD 集成到 daily_stock_analysis_eagle 计划

## 一、项目概述

将 futuProject（Futu OpenD GUI 客户端）的数据获取能力作为一个新的 **FutuFetcher** 数据源，
集成到 daily_stock_analysis_eagle 的 DataFetcherManager 策略模式中。

---

## 二、整体架构（合并后）

```
daily_stock_analysis_eagle/
├── data_provider/
│   ├── base.py                    # BaseFetcher + DataFetcherManager
│   ├── efinance_fetcher.py        # 东方财富 (priority 0)
│   ├── akshare_fetcher.py         # AkShare (priority 1)
│   ├── tushare_fetcher.py         # Tushare (priority 2/-1)
│   ├── pytdx_fetcher.py           # 通达信 (priority 2)
│   ├── baostock_fetcher.py        # Baostock (priority 3)
│   ├── yfinance_fetcher.py        # Yahoo Finance (priority 4)
│   └── futu_fetcher.py            # 🆕 Futu OpenD (priority 可配置)
```

---

## 三、实现步骤

### Step 1: 创建 FutuFetcher 类
- 文件: `data_provider/futu_fetcher.py`
- 继承 `BaseFetcher`
- 使用 `futu-api` SDK 连接 OpenD
- 实现必须的接口:
  - `_fetch_raw_data(stock_code, start_date, end_date)` — 调用 Futu K线接口
  - `_normalize_data(df, stock_code)` — 标准化列名为 `['date','open','high','low','close','volume','amount','pct_chg']`
- 实现可选增强接口:
  - `get_realtime_quote()` — 实时报价（Futu 数据质量高）
  - `get_stock_name()` — 股票名称
  - `get_main_indices()` — 主要指数

### Step 2: 股票代码转换
- daily_stock_analysis_eagle 用纯数字 `600519`
- Futu API 需要 `SH.600519` / `HK.00700` / `US.AAPL` 格式
- 在 FutuFetcher 内部做转换，对外保持统一接口

### Step 3: 注册到 DataFetcherManager
- 在 `base.py` 的 `_init_default_fetchers()` 中添加 FutuFetcher
- 通过 `.env` 配置:
  ```
  FUTU_ENABLED=true
  FUTU_OPEND_HOST=127.0.0.1
  FUTU_OPEND_PORT=11111
  FUTU_PRIORITY=0              # 可设为最高优先级
  ```

### Step 4: 依赖管理
- 在 `requirements.txt` 添加 `futu-api>=9.1.0`（可选依赖）
- FutuFetcher 用 try/import 模式，无 futu-api 时优雅跳过

---

## 四、LLM Token 省钱方案

### 现状
- 项目通过 LiteLLM 调用云端大模型（Gemini/Claude/GPT/DeepSeek）
- 每只股票分析约消耗 3K-8K tokens（输入）+ 2K-4K tokens（输出）
- 10只自选股/天 ≈ 50K-120K tokens/天

### 🆓 免费/零成本方案

#### 方案 A: Ollama 本地模型（推荐）
项目**已内置支持** Ollama，配置即用：

```env
# .env 配置
LLM_CHANNELS=ollama
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen2.5:14b
```

**推荐模型（按硬件选择）:**
| 显存 | 推荐模型 | 效果 |
|------|---------|------|
| 8GB | qwen2.5:7b | 基本可用 |
| 16GB | qwen2.5:14b | 效果好 |
| 24GB+ | qwen2.5:32b / deepseek-v3 | 接近云端 |
| CPU only | qwen2.5:3b | 能用但慢 |

**启动:**
```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh
# 下载模型
ollama pull qwen2.5:14b
# 模型自动在后台运行，无需额外操作
```

#### 方案 B: vLLM / LM Studio（OpenAI 兼容）
```env
LLM_CHANNELS=local
LLM_LOCAL_BASE_URL=http://localhost:8000/v1
LLM_LOCAL_API_KEY=not-needed
LLM_LOCAL_MODELS=your-local-model
```

#### 方案 C: Gemini 免费额度
- Google AI Studio 提供免费 Gemini API 额度
- 个人使用通常够用
```env
GEMINI_API_KEY=your_free_key
LITELLM_MODEL=gemini/gemini-2.0-flash
```

#### 方案 D: DeepSeek（极低成本）
- DeepSeek API 价格约为 GPT-4o 的 1/50
- 10只股票/天 成本 < ¥0.1
```env
DEEPSEEK_API_KEY=sk-xxx
LITELLM_MODEL=deepseek/deepseek-chat
```

---

## 五、合并后的使用流程

### 前提条件
1. **Futu OpenD 客户端** 运行中（本地 127.0.0.1:11111）
2. **Ollama** 运行中（如果选方案 A）

### 日常使用
```bash
# 1. 确保 OpenD 已启动（Futu 牛牛客户端里开启）

# 2. 确保 Ollama 模型已运行
ollama serve  # 如果没有自动启动

# 3. 运行分析
cd daily_stock_analysis_eagle
python main.py
```

### .env 配置总览
```env
# === 数据源：Futu OpenD ===
FUTU_ENABLED=true
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_PRIORITY=0                    # 最高优先级，Futu 数据质量最好

# === LLM：Ollama 本地（零成本） ===
LLM_CHANNELS=ollama
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen2.5:14b     # 或你安装的模型

# === 自选股 ===
�STOCK_LIST=600519,000858,300750,HK00700,AAPL

# === 其他保持默认 ===
```

### 数据获取优先级（合并后）
```
1. FutuFetcher (priority 0)     ← 🆕 Futu OpenD，港股/美股数据最佳
2. EfinanceFetcher (priority 0) ← A股免费数据
3. AkshareFetcher (priority 1)  ← 备用
4. TushareFetcher (priority 2)  ← 需要 token
5. Others...                    ← 兜底
```

当 Futu OpenD 未运行时，自动 fallback 到 Efinance/AkShare，不影响使用。

---

## 六、Futu 相比现有数据源的优势

| 特性 | Futu OpenD | Efinance/AkShare |
|------|-----------|-----------------|
| A股数据 | ✅ | ✅ |
| 港股数据 | ✅ 原生支持 | ❌ 有限 |
| 美股数据 | ✅ 原生支持 | ❌ 需 yfinance |
| 实时报价 | ✅ 毫秒级 | ⚠️ 有延迟 |
| 分钟K线 | ✅ 完整 | ⚠️ 部分 |
| 逐笔成交 | ✅ | ❌ |
| 反封禁风险 | ✅ 本地客户端 | ⚠️ 爬虫可能被封 |
| 费用 | 免费(基础) | 免费 |

---

## 七、实现工作量预估

| 步骤 | 内容 | 文件 |
|------|------|------|
| 1 | 创建 FutuFetcher | `data_provider/futu_fetcher.py` (新建) |
| 2 | 股票代码转换逻辑 | 在 futu_fetcher.py 内部 |
| 3 | 注册到 Manager | `data_provider/base.py` (改几行) |
| 4 | .env 配置项 | `.env.example` (加几行) |
| 5 | 可选: 单元测试 | `tests/test_futu_fetcher.py` (新建) |
