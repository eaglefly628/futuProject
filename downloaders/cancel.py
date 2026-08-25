"""
下载任务的协作式取消 + 进度回调

不用 QThread.terminate() 强杀线程：
  - 线程阻塞在 socket 上时 terminate 根本不生效，点了停止没反应
  - 真生效了也可能停在 SQLite 写一半的位置，留下半截事务

改成任务自己在循环点检查 should_stop()，尽快收尾返回。
已经落库的数据保留，不回滚 —— 采集是增量去重的，下次接着补即可。
"""
import time
from typing import Callable, Optional

# 返回 True 表示「请停止」
StopFn = Optional[Callable[[], bool]]
# 进度消息回调
ProgressFn = Optional[Callable[[str], None]]


def stopped(should_stop: StopFn) -> bool:
    """检查是否已请求停止（should_stop 为 None 时永远 False）"""
    return bool(should_stop and should_stop())


def report(on_progress: ProgressFn, msg: str) -> None:
    """发一条进度消息，没挂回调就丢弃"""
    if on_progress:
        on_progress(msg)


def sleep_unless_stopped(seconds: float, should_stop: StopFn = None) -> bool:
    """
    分片 sleep，期间可被打断。返回 True 表示被要求停止。

    退避等待动辄好几秒，直接 time.sleep 的话点了停止得等它睡完才有反应。
    """
    if seconds <= 0:
        return stopped(should_stop)
    if should_stop is None:
        time.sleep(seconds)
        return False

    deadline = time.time() + seconds
    while True:
        if should_stop():
            return True
        remain = deadline - time.time()
        if remain <= 0:
            return False
        time.sleep(min(0.1, remain))


class Cancelled(Exception):
    """任务被用户停止。不是错误，界面按「已停止」处理"""
