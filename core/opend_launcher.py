"""
OpenD 网关启动器
自动发现项目内的 OpenD 可执行文件，以命令行参数方式启动/停止
"""
import hashlib
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, List, Callable

from loguru import logger

PROJECT_ROOT = Path(__file__).parent.parent

# OpenD 可执行文件搜索路径（相对项目根目录）
SEARCH_PATTERNS = {
    "Windows": [
        "FutuOpenD/windows/*/FutuOpenD.exe",
        "FutuOpenD/*/FutuOpenD.exe",
        "FutuOpenD/FutuOpenD.exe",
        "opend/**/FutuOpenD.exe",
    ],
    "Darwin": [
        "FutuOpenD/mac/*/FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "FutuOpenD/*/FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "FutuOpenD/**/FutuOpenD",
        "opend/**/FutuOpenD",
    ],
    "Linux": [
        "FutuOpenD/linux/*/FutuOpenD",
        "FutuOpenD/*/FutuOpenD",
        "FutuOpenD/FutuOpenD",
        "opend/**/FutuOpenD",
    ],
}


def md5_password(pwd: str) -> str:
    """将明文密码转为 OpenD 需要的 32 位小写 MD5"""
    return hashlib.md5(pwd.encode("utf-8")).hexdigest()


def discover_opend(base_dir: Optional[Path] = None) -> Optional[Path]:
    """
    在项目目录下自动发现 OpenD 可执行文件。

    Returns:
        找到的可执行文件绝对路径，未找到返回 None
    """
    base = Path(base_dir) if base_dir else PROJECT_ROOT
    system = platform.system()
    patterns = SEARCH_PATTERNS.get(system, SEARCH_PATTERNS["Linux"])

    for pattern in patterns:
        for match in sorted(base.glob(pattern)):
            if match.is_file():
                logger.info(f"发现 OpenD: {match}")
                return match.resolve()
    return None


def list_opend_candidates(base_dir: Optional[Path] = None) -> List[Path]:
    """列出所有可能的 OpenD 路径（用于让用户选择）"""
    base = Path(base_dir) if base_dir else PROJECT_ROOT
    system = platform.system()
    patterns = SEARCH_PATTERNS.get(system, SEARCH_PATTERNS["Linux"])

    found = []
    for pattern in patterns:
        for match in base.glob(pattern):
            if match.is_file():
                resolved = match.resolve()
                if resolved not in found:
                    found.append(resolved)
    return found


class OpenDLauncher:
    """OpenD 进程管理器"""

    def __init__(self, exe_path: Optional[str] = None):
        self._exe_path: Optional[Path] = Path(exe_path) if exe_path else None
        self._process: Optional[subprocess.Popen] = None
        self._output_lines: List[str] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._on_output: Optional[Callable[[str], None]] = None

    # ─── 路径管理 ───
    @property
    def exe_path(self) -> Optional[Path]:
        return self._exe_path

    def set_exe_path(self, path: str):
        self._exe_path = Path(path) if path else None

    def auto_discover(self, base_dir: Optional[Path] = None) -> bool:
        """自动发现并设置 OpenD 路径"""
        found = discover_opend(base_dir)
        if found:
            self._exe_path = found
            return True
        return False

    def is_available(self) -> bool:
        return self._exe_path is not None and self._exe_path.is_file()

    # ─── 进程管理 ───
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, account: str = "", password: str = "",
              password_is_md5: bool = False,
              api_port: int = 11111, api_ip: str = "127.0.0.1",
              lang: str = "chs", show_console: bool = False,
              on_output: Optional[Callable[[str], None]] = None) -> bool:
        """
        启动 OpenD。

        Args:
            account: 牛牛号/邮箱/手机号
            password: 登录密码（明文或 MD5，由 password_is_md5 决定）
            password_is_md5: password 是否已是 MD5 密文
            api_port: API 监听端口
            api_ip: API 监听地址
            lang: chs / en
            show_console: 是否显示 OpenD 控制台窗口
            on_output: 输出行回调

        Returns:
            是否成功拉起进程
        """
        if self.is_running():
            logger.warning("OpenD 已在运行")
            return True

        if not self.is_available():
            raise FileNotFoundError(
                f"OpenD 可执行文件不存在: {self._exe_path}\n"
                f"请确认已将 OpenD 放入项目 FutuOpenD/ 目录，或手动指定路径")

        args = [str(self._exe_path)]

        if account:
            args.append(f"-login_account={account}")
        if password:
            if password_is_md5:
                args.append(f"-login_pwd_md5={password}")
            else:
                args.append(f"-login_pwd_md5={md5_password(password)}")

        args.append(f"-api_ip={api_ip}")
        args.append(f"-api_port={api_port}")
        args.append(f"-lang={lang}")
        args.append(f"-console={1 if show_console else 0}")

        self._on_output = on_output
        self._output_lines = []

        # 工作目录设为 OpenD 所在目录（它需要读同目录的 FutuOpenD.xml / Appdata.dat）
        cwd = str(self._exe_path.parent)

        # Windows 下隐藏控制台窗口
        creation_flags = 0
        if platform.system() == "Windows" and not show_console:
            creation_flags = subprocess.CREATE_NO_WINDOW

        safe_args = [a if not a.startswith("-login_pwd") else "-login_pwd_md5=***"
                     for a in args]
        logger.info(f"启动 OpenD: {' '.join(safe_args)}")

        try:
            self._process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except Exception as e:
            logger.error(f"启动 OpenD 失败: {e}")
            raise

        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        return True

    def _read_output(self):
        """后台读取 OpenD 输出"""
        if not self._process or not self._process.stdout:
            return
        try:
            for line in self._process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._output_lines.append(line)
                if len(self._output_lines) > 500:
                    self._output_lines = self._output_lines[-500:]
                if self._on_output:
                    try:
                        self._on_output(line)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"读取 OpenD 输出结束: {e}")

    def stop(self, timeout: float = 5.0) -> bool:
        """停止 OpenD 进程"""
        if not self.is_running():
            return True

        logger.info("正在停止 OpenD...")
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("OpenD 未响应 terminate，强制结束")
                self._process.kill()
                self._process.wait(timeout=2)
        except Exception as e:
            logger.error(f"停止 OpenD 出错: {e}")
            return False
        finally:
            self._process = None
        logger.info("OpenD 已停止")
        return True

    def get_output(self, last_n: int = 100) -> List[str]:
        return self._output_lines[-last_n:]

    def wait_until_ready(self, host: str = "127.0.0.1", port: int = 11111,
                         timeout: float = 30.0) -> bool:
        """
        等待 OpenD 端口可连接。

        Returns:
            端口就绪返回 True，超时返回 False
        """
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                logger.error("OpenD 进程已退出")
                return False
            try:
                with socket.create_connection((host, port), timeout=1.0):
                    logger.info(f"OpenD 端口就绪: {host}:{port}")
                    return True
            except (OSError, socket.timeout):
                time.sleep(0.5)
        logger.warning(f"等待 OpenD 端口超时: {host}:{port}")
        return False
