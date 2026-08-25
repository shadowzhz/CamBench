"""
日志模块
"""

import time
import threading


_log_lock = threading.Lock()


def log(message):
    """
    简单线程安全日志
    """

    timestamp = time.strftime("%H:%M:%S")

    with _log_lock:
        print(
            f"[{timestamp}] {message}",
            flush=True
        )
        