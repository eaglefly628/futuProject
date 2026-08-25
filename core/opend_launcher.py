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

# 项目目录之外的常见安装位置（OpenD 通常不会放进项目里）
EXTRA_ROOTS = {
    "Windows": [
        "C:/FutuOpenD", "C:/Program Files/FutuOpenD",
        "~/Downloads", "~/Desktop", "~/Documents",
    ],
    "Darwin": [
        "/Applications", "~/Applications",
        "~/Downloads", "~/Desktop", "~/Documents",
    ],
    "Linux": [
        "/opt", "~/Downloads", "~/Desktop", "~",
    ],
}

# 在上述根目录下用这些模式找（限制深度，避免全盘扫描）
EXTRA_PATTERNS = {
    "Windows": ["FutuOpenD.exe", "*/FutuOpenD.exe", "*/*/FutuOpenD.exe"],
    "Darwin": [
        "FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "*/FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "*/*/FutuOpenD.app/Contents/MacOS/FutuOpenD",
        "OpenD.app/Contents/MacOS/OpenD",
        "*/OpenD.app/Contents/MacOS/OpenD",
        "*/*/OpenD.app/Contents/MacOS/OpenD",
    ],
    "Linux": ["FutuOpenD", "*/FutuOpenD", "*/*/FutuOpenD"],
}


def md5_password(pwd: str) -> str:
    """将明文密码转为 OpenD 需要的 32 位小写 MD5"""
    return hashlib.md5(pwd.encode("utf-8")).hexdigest()


def find_config_file(exe_path: Path) -> Optional[Path]:
    """
    定位 FutuOpenD.xml。

    macOS 上可执行文件在 .app 包内三层深，配置文件通常在包外同级目录：
        Futu_OpenD_x.x.x_Mac/
            FutuOpenD.xml            <- 这里
            FutuOpenD.app/Contents/MacOS/FutuOpenD
    """
    exe = Path(exe_path)
    candidates = []

    # 从可执行文件往上找若干层
    parent = exe.parent
    for _ in range(5):
        candidates.append(parent / "FutuOpenD.xml")
        candidates.append(parent / "OpenD.xml")
        if parent.parent == parent:
            break
        parent = parent.parent

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def write_config_credentials(cfg_path: Path, account: str, pwd_md5: str,
                             api_ip: str = None, api_port: int = None,
                             lang: str = None) -> bool:
    """
    把账号密码写进 FutuOpenD.xml，让 OpenD 启动时自动登录。

    macOS 上 .app 运行时路径会被随机化，OpenD 找不到自己的配置文件，
    因此「记住密码」存不住、命令行参数也常常不生效。把凭据直接写进
    配置文件、再用 -cfg_file 指定绝对路径，是官方文档给的解法。

    Returns:
        是否写入成功
    """
    import xml.etree.ElementTree as ET

    cfg_path = Path(cfg_path)
    try:
        tree = ET.parse(cfg_path)
        root = tree.getroot()

        def set_field(name, value):
            if value is None or value == "":
                return
            node = root.find(name)
            if node is None:
                node = ET.SubElement(root, name)
            node.text = str(value)

        set_field("login_account", account)
        set_field("login_pwd_md5", pwd_md5)
        # 明文密码字段清空，避免和密文冲突（文档：两者都在时只用密文）
        plain = root.find("login_pwd")
        if plain is not None:
            plain.text = ""
        set_field("ip", api_ip)
        set_field("api_port", api_port)
        set_field("lang", lang)

        # 先备份原文件，避免写坏了没法回退
        backup = cfg_path.with_suffix(".xml.bak")
        if not backup.exists():
            try:
                backup.write_bytes(cfg_path.read_bytes())
            except Exception:
                pass

        tree.write(cfg_path, encoding="utf-8", xml_declaration=True)
        logger.info(f"已写入 OpenD 配置: {cfg_path}")
        return True
    except Exception as e:
        logger.warning(f"写入 OpenD 配置失败 ({cfg_path}): {e}")
        return False


def discover_opend(base_dir: Optional[Path] = None) -> Optional[Path]:
    """
    在项目目录下自动发现 OpenD 可执行文件。

    Returns:
        找到的可执行文件绝对路径，未找到返回 None
    """
    found = list_opend_candidates(base_dir)
    if found:
        logger.info(f"发现 OpenD: {found[0]}")
        return found[0]
    return None


def list_opend_candidates(base_dir: Optional[Path] = None,
                          include_system: bool = True) -> List[Path]:
    """
    列出所有可能的 OpenD 路径。

    先找项目目录，再找系统常见安装位置（/Applications、下载目录等）。
    """
    system = platform.system()
    found: List[Path] = []

    def scan(root: Path, patterns):
        if not root.is_dir():
            return
        for pattern in patterns:
            try:
                for match in root.glob(pattern):
                    if match.is_file():
                        r = match.resolve()
                        if r not in found:
                            found.append(r)
            except (OSError, PermissionError):
                continue

    # 1) 项目目录
    base = Path(base_dir) if base_dir else PROJECT_ROOT
    scan(base, SEARCH_PATTERNS.get(system, SEARCH_PATTERNS["Linux"]))

    # 2) 系统常见位置
    if include_system:
        extra_patterns = EXTRA_PATTERNS.get(system, EXTRA_PATTERNS["Linux"])
        for root in EXTRA_ROOTS.get(system, []):
            scan(Path(root).expanduser(), extra_patterns)

    return found


class OpenDLauncher:
    """OpenD 进程管理器"""

    def __init__(self, exe_path: Optional[str] = None):
        self._exe_path: Optional[Path] = Path(exe_path) if exe_path else None
        self._process: Optional[subprocess.Popen] = None
        self._output_lines: List[str] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._on_output: Optional[Callable[[str], None]] = None
        self._needs_verify: bool = False
        self._logged_in: bool = False
        self._cfg_file: Optional[Path] = None

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

        pwd_md5 = ""
        if password:
            pwd_md5 = password if password_is_md5 else md5_password(password)

        # 把凭据写进 FutuOpenD.xml 并用 -cfg_file 指定绝对路径。
        # macOS 上 .app 路径会被随机化，OpenD 找不到自己的配置文件，
        # 只靠命令行参数经常仍会弹交互式登录。
        cfg_file = find_config_file(self._exe_path)
        if cfg_file and account and pwd_md5:
            if write_config_credentials(cfg_file, account, pwd_md5,
                                        api_ip=api_ip, api_port=api_port,
                                        lang=lang):
                self._cfg_file = cfg_file
                args.append(f"-cfg_file={cfg_file}")
        elif cfg_file:
            args.append(f"-cfg_file={cfg_file}")
        else:
            logger.warning("未找到 FutuOpenD.xml，OpenD 可能会要求交互式登录")

        # 命令行参数优先级高于配置文件，两条路都给上
        if account:
            args.append(f"-login_account={account}")
        if pwd_md5:
            args.append(f"-login_pwd_md5={pwd_md5}")

        args.append(f"-api_ip={api_ip}")
        args.append(f"-api_port={api_port}")
        args.append(f"-lang={lang}")
        # 必须开控制台：登录进度、验证码提示都走它，
        # 关掉的话 stdout 收不到任何交互信息，界面只能干等。
        # 输出已经重定向到本程序的终端组件，不会额外弹窗。
        args.append("-console=1")

        self._on_output = on_output
        self._output_lines = []
        self._needs_verify = False
        self._logged_in = False

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
                stdin=subprocess.PIPE,   # 保留输入通道，用于应答验证码等交互
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
        """后台读取 OpenD 输出（按字符读，兼容无换行的 >>> 提示符）"""
        if not self._process or not self._process.stdout:
            return
        buf = ""
        try:
            while True:
                ch = self._process.stdout.read(1)
                if ch == "":
                    break
                if ch in ("\n", "\r"):
                    if buf.strip():
                        self._emit_line(buf.rstrip())
                    buf = ""
                    continue
                buf += ch
                # OpenD 的输入提示符不带换行，读到就先吐出去
                if buf.endswith(">>>"):
                    self._emit_line(buf)
                    buf = ""
        except Exception as e:
            logger.debug(f"读取 OpenD 输出结束: {e}")
        finally:
            if buf.strip():
                self._emit_line(buf.rstrip())

    def _emit_line(self, line: str):
        """记录并分发一行输出"""
        self._output_lines.append(line)
        if len(self._output_lines) > 1000:
            self._output_lines = self._output_lines[-1000:]

        # 状态识别
        if "登录成功" in line:
            self._logged_in = True
            self._needs_verify = False
        elif "需要手机验证码" in line or "req_phone_verify_code" in line:
            self._needs_verify = True
        elif "登录失败" in line or "密码不匹配" in line:
            self._logged_in = False

        if self._on_output:
            try:
                self._on_output(line)
            except Exception:
                pass

    # ─── 交互 ───
    def send_command(self, cmd: str) -> bool:
        """
        向 OpenD 控制台发送一行命令。

        常用命令:
            input_phone_verify_code -code=123456   提交手机验证码
            help                                    命令列表
            exit                                    退出 OpenD
        """
        if not self.is_running() or not self._process.stdin:
            logger.warning("OpenD 未运行，无法发送命令")
            return False
        try:
            self._process.stdin.write(cmd + "\n")
            self._process.stdin.flush()
            safe = cmd if "pwd" not in cmd.lower() else "***"
            logger.info(f"发送 OpenD 命令: {safe}")
            self._emit_line(f">>> {safe}")
            return True
        except Exception as e:
            logger.error(f"发送命令失败: {e}")
            return False

    def submit_verify_code(self, code: str) -> bool:
        """提交手机验证码"""
        return self.send_command(f"input_phone_verify_code -code={code.strip()}")

    def request_verify_code(self) -> bool:
        """请求重发手机验证码"""
        return self.send_command("req_phone_verify_code")

    @property
    def needs_verify(self) -> bool:
        """是否正在等待手机验证码"""
        return getattr(self, "_needs_verify", False)

    @property
    def logged_in(self) -> bool:
        """OpenD 是否已登录成功"""
        return getattr(self, "_logged_in", False)

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
        port_seen = False

        while time.time() < deadline:
            # 等待手机验证码时不要空耗超时，交给上层处理
            if self._needs_verify and not self._logged_in:
                logger.info("OpenD 正在等待手机验证码")
                return False

            alive = self.is_running()
            try:
                with socket.create_connection((host, port), timeout=1.0):
                    port_seen = True
            except (OSError, socket.timeout):
                port_seen = False

            if not alive:
                # 进程没了但端口还在 —— 说明监听方是别的实例，
                # 我们这个多半因端口冲突退出了
                if port_seen:
                    raise RuntimeError(
                        f"OpenD 进程已退出，但 {host}:{port} 仍被占用。\n"
                        f"通常是之前启动的 OpenD 还在运行导致端口冲突。\n"
                        f"可直接点「仅连接」使用已有实例，"
                        f"或先关掉旧实例（pkill -f FutuOpenD）再重试。")
                raise RuntimeError(
                    "OpenD 进程已退出。请查看下方终端输出确认原因"
                    "（勾选「显示 OpenD 控制台窗口」可看到完整信息）。")

            if port_seen:
                logger.info(f"OpenD 端口就绪: {host}:{port}")
                return True

            time.sleep(0.5)

        logger.warning(f"等待 OpenD 端口超时: {host}:{port}")
        return False
