"""配置管理模块"""
import os, yaml
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger

class Config:
    """全局配置管理器(单例)"""
    _instance = None
    _config: Dict[str, Any] = {}
    _config_path: Optional[str] = None

    def __new__(cls, config_path=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path=None):
        if not self._config and config_path:
            self.load(config_path)

    def load(self, config_path: str):
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        self._config_path = str(path)
        self._base_dir = path.parent.parent

        # 合并本地覆盖配置(local.yaml, 已 gitignore, 存放账号密码等敏感项)
        self._local_path = path.parent / "local.yaml"
        if self._local_path.exists():
            try:
                with open(self._local_path, "r", encoding="utf-8") as f:
                    local = yaml.safe_load(f) or {}
                self._deep_merge(self._config, local)
                logger.info(f"本地配置已合并: {self._local_path}")
            except Exception as e:
                logger.warning(f"本地配置加载失败: {e}")

        self._resolve_paths()
        logger.info(f"配置加载完成: {config_path}")

    @staticmethod
    def _deep_merge(base: dict, override: dict):
        """递归合并 override 到 base"""
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Config._deep_merge(base[k], v)
            else:
                base[k] = v

    def save_local(self, data: dict):
        """
        保存敏感配置到 config/local.yaml (已 gitignore)。
        会与现有 local.yaml 合并而非覆盖。
        """
        path = getattr(self, "_local_path", None)
        if path is None:
            path = Path(self._config_path).parent / "local.yaml"
            self._local_path = path

        existing = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

        self._deep_merge(existing, data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
        # 同步到运行时配置
        self._deep_merge(self._config, data)
        logger.info(f"本地配置已保存: {path}")

    def _resolve_paths(self):
        path_keys = [
            ("storage","sqlite_path"),("storage","parquet_dir"),
            ("storage","csv_dir"),("logging","file"),("analysis","model_dir"),
        ]
        for sec, key in path_keys:
            if sec in self._config and key in self._config[sec]:
                val = self._config[sec][key]
                if val and not os.path.isabs(val):
                    self._config[sec][key] = str(self._base_dir / val)

    def get(self, *keys, default=None) -> Any:
        obj = self._config
        for k in keys:
            if isinstance(obj, dict):
                obj = obj.get(k, default)
            else:
                return default
        return obj

    def set(self, *keys_and_value):
        if len(keys_and_value) < 2:
            raise ValueError("需要key和value")
        keys, value = keys_and_value[:-1], keys_and_value[-1]
        obj = self._config
        for k in keys[:-1]:
            obj = obj.setdefault(k, {})
        obj[keys[-1]] = value

    def save(self, config_path=None):
        path = Path(config_path or self._config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"配置已保存: {path}")

    @property
    def raw(self):
        return self._config

    def get_watchlist_all(self) -> list:
        wl = self.get("watchlist", default={})
        return [c for codes in wl.values() if isinstance(codes, list) for c in codes]

    def add_to_watchlist(self, market: str, code: str):
        m = market.upper()
        self._config.setdefault("watchlist", {}).setdefault(m, [])
        if code not in self._config["watchlist"][m]:
            self._config["watchlist"][m].append(code)
            logger.info(f"已添加 {code} -> {m}")

    def remove_from_watchlist(self, market: str, code: str):
        m = market.upper()
        wl = self._config.get("watchlist", {}).get(m, [])
        if code in wl:
            wl.remove(code)
            logger.info(f"已移除 {code} <- {m}")
