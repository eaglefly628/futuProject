"""后台工作线程"""
import threading
from PySide6.QtCore import QThread, Signal


class WorkerThread(QThread):
    """
    通用后台工作线程。

    取消用协作式，不用 QThread.terminate():
      - 线程阻塞在 socket 上时 terminate 根本不生效，点了停止没反应
      - 真生效了也可能停在 SQLite 写一半的位置，留下半截事务

    任务函数需要在循环点检查 should_stop()，尽快收尾返回。
    """
    progress = Signal(str)        # 进度消息
    finished_ok = Signal(object)  # 成功结果
    error = Signal(str)           # 错误消息

    def __init__(self, func=None, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._cancel = threading.Event()

    # ─── 任务体 ───
    @classmethod
    def deferred(cls) -> "WorkerThread":
        """
        先建线程、后设任务体。

        任务体要引用 worker 自身时用（比如把 should_stop 传给下载器），
        否则会陷入「构造时还没有 worker 变量」的死结。
        """
        return cls(None)

    def set_task(self, func, *args, **kwargs) -> "WorkerThread":
        self._func = func
        self._args = args
        self._kwargs = kwargs
        return self

    # ─── 取消 ───
    def cancel(self):
        """请求停止。任务在下一个检查点退出，不保证立刻。"""
        self._cancel.set()

    def should_stop(self) -> bool:
        """任务函数的检查点"""
        return self._cancel.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def sleep_or_stop(self, seconds: float) -> bool:
        """可被取消打断的 sleep。返回 True 表示已被取消。"""
        return self._cancel.wait(seconds)

    def emit_progress(self, msg: str):
        """给任务函数当 on_progress 回调用"""
        self.progress.emit(msg)

    def run(self):
        if self._func is None:
            self.error.emit("任务未设置")
            return
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished_ok.emit(result)
        except Exception as e:
            self.error.emit(str(e))
