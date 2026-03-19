# FutuFetcher 集成指南

## 将 Futu OpenD 接入 daily_stock_analysis_eagle

### 1. 复制 FutuFetcher

```bash
cp integration/data_provider/futu_fetcher.py \
   /path/to/daily_stock_analysis_eagle/data_provider/futu_fetcher.py
```

### 2. 修改 data_provider/base.py

在 `_init_default_fetchers()` 方法末尾（`self._fetchers = [...]` 之后）添加：

```python
        # Futu OpenD 数据源（可选，需要 futu-api 和 OpenD 运行）
        from src.config import parse_env_bool
        if parse_env_bool(os.environ.get("FUTU_ENABLED"), default=False):
            try:
                from .futu_fetcher import FutuFetcher
                futu = FutuFetcher()
                self._fetchers.append(futu)
            except Exception as e:
                logger.info(f"FutuFetcher 初始化跳过: {e}")
```

同时确保文件顶部有 `import os`。

### 3. 修改 data_provider/__init__.py

添加导入和导出：

```python
try:
    from .futu_fetcher import FutuFetcher
except ImportError:
    FutuFetcher = None

# 在 __all__ 中添加 'FutuFetcher'
```

### 4. 安装依赖

```bash
pip install futu-api
```

### 5. 配置 .env

```env
# Futu OpenD 数据源
FUTU_ENABLED=true
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_PRIORITY=-1
```

### 6. LLM 零成本方案 (Ollama)

```env
# 使用 Ollama 本地模型，不花 token
LLM_CHANNELS=ollama
LLM_OLLAMA_BASE_URL=http://localhost:11434
LLM_OLLAMA_MODELS=qwen2.5:14b
```

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:14b
```

### 7. 运行

```bash
# 确保 Futu OpenD 客户端已启动
# 确保 Ollama 已运行 (ollama serve)
cd daily_stock_analysis_eagle
python main.py
```

数据获取优先级: FutuFetcher(P-1) > EfinanceFetcher(P0) > AkshareFetcher(P1) > ...

当 OpenD 未运行时自动 fallback 到其他免费数据源。
