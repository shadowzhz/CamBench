"""帧率计量:滚动窗口(最近 N 个时间戳)算实时值,累计时间算平均值。"""

import time
from collections import deque


class FpsMeter:
    """Measure total/rolling capture FPS from monotonic timestamps."""

    def __init__(self, history_size=240, clock=time.perf_counter):
        if history_size < 2:
            raise ValueError("history_size must be at least 2")
        self._clock = clock
        self._history = deque(maxlen=history_size)
        self._count = 0
        self._start = None

    def reset(self):
        self._history.clear()
        self._count = 0
        self._start = None

    def tick(self, timestamp=None):
        now = self._clock() if timestamp is None else timestamp
        if self._start is None:
            self._start = now
        self._count += 1
        self._history.append(now)

    @property
    def frames(self):
        return self._count

    @property
    def elapsed(self):
        if self._start is None:
            return 0.0
        return max(self._history[-1] - self._start, 0.0)

    @property
    def average_fps(self):
        if self._count < 2 or self.elapsed <= 0:
            return 0.0
        return (self._count - 1) / self.elapsed

    @property
    def current_fps(self):
        if len(self._history) < 2:
            return 0.0
        elapsed = self._history[-1] - self._history[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._history) - 1) / elapsed

    def stats(self):
        return {
            "frames": self.frames,
            "elapsed": self.elapsed,
            "avg_fps": self.average_fps,
            "current_fps": self.current_fps,
        }
