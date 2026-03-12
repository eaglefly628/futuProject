"""后台工作线程"""
from PySide6.QtCore import QThread, Signal


class WorkerThread(QThread):
    """通用后台工作线程"""
    progress = Signal(str)    # 进度消息
    finished_ok = Signal(object)  # 成功结果
    error = Signal(str)       # 错误消息

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished_ok.emit(result)
        except Exception as e:
            self.error.emit(str(e))
