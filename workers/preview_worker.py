import queue
import threading
import time
from collections import deque

from camera.capture import HighFpsGStreamerCapture, open_capture
from camera.diagnostics import diagnose_open_failure
from camera.fps import FpsMeter
from camera.utils import camera_device_present
from core import (
    PREVIEW_FPS_HISTORY_SIZE,
    PREVIEW_UPDATE_FPS,
    STATS_ONLY_UPDATE_FPS,
    make_device_lost_event,
    make_error_event,
    make_frame_event,
    make_stats_event,
    make_stopped_event,
)
from core import EventType


class BaseWorker(threading.Thread):
    """后台采集线程基类,提供统一的停止标志。"""

    def __init__(self, event_queue):
        super().__init__(daemon=True)
        self.event_queue = event_queue
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def stopped(self):
        return self.stop_event.is_set()


class PreviewWorker(BaseWorker):
    """采集线程:持续读帧、统计 FPS,按固定频率向 GUI 发布事件。"""

    def __init__(self, camera, mode, event_queue, preview_enabled):
        super().__init__(event_queue)
        self.camera = camera
        self.mode = mode
        self.preview_enabled = preview_enabled
        self.cap = None

    def put_event(self, event):
        # 队列只保留最新事件(maxsize 由 GUI 决定):GUI 跟不上时宁可丢事件,
        # 也不能让 put 阻塞拖慢采集端。
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass

    @staticmethod
    def _fps(timestamps):
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(timestamps) - 1) / elapsed

    def publish(self, frame, opened_device, backend, counter, start_time,
                capture_fps, display_fps):
        elapsed = max(time.perf_counter() - start_time, 0.001)
        avg = max(counter - 1, 0) / elapsed if counter >= 2 else 0.0
        stats = {
            "device": opened_device,
            "camera": self.camera.name,
            "backend": backend,
            "format": self.mode.pixel_format,
            "requested_size": f"{self.mode.width}x{self.mode.height}",
            "actual_size": f"{frame.shape[1]}x{frame.shape[0]}",
            "target_fps": f"{self.mode.fps:.2f}",
            "realtime_fps": f"{capture_fps:.2f}",
            "avg_fps": f"{avg:.2f}",
            "display_fps": f"{display_fps:.2f}",
            "frames": str(counter),
            "elapsed": f"{elapsed:.1f}s",
        }
        if self.preview_enabled:
            self.put_event(make_frame_event(frame, stats))
        else:
            self.put_event(make_stats_event(stats))

    def run(self):
        cap = None
        try:
            cap, backend, first, device, errors = open_capture(
                self.camera, self.mode, self.stop_event
            )
            if cap is None:
                detailed_error = diagnose_open_failure(self.camera, self.mode, errors)
                self.put_event(make_error_event(detailed_error))
                return

            self.cap = cap
            counter = 0
            capture_meter = FpsMeter(PREVIEW_FPS_HISTORY_SIZE)
            display_timestamps = deque(maxlen=PREVIEW_FPS_HISTORY_SIZE)

            # 首帧只用于确认设备已经成功打开;正式 FPS 测试从此刻开始。
            if isinstance(cap, HighFpsGStreamerCapture):
                cap.reset_source_stats()
            capture_meter.reset()
            start = time.perf_counter()
            last_publish = start

            if first is not None:
                self.publish(first, device, backend, 0, start, 0.0, 0.0)

            while not self.stopped():
                ok, frame = cap.read()
                now = time.perf_counter()
                if not ok:
                    if not camera_device_present(self.camera):
                        self.put_event(make_device_lost_event("摄像头已拔出"))
                    break

                if isinstance(cap, HighFpsGStreamerCapture):
                    # 高帧率路径:统计来自 v4l2src 源端,不受预览刷新影响
                    counter, capture_fps = cap.source_stats()
                else:
                    capture_meter.tick(now)
                    counter = capture_meter.frames
                    capture_fps = capture_meter.current_fps

                interval = 1 / PREVIEW_UPDATE_FPS if self.preview_enabled \
                    else 1 / STATS_ONLY_UPDATE_FPS
                if now - last_publish >= interval:
                    last_publish = now
                    display_timestamps.append(now)
                    self.publish(
                        frame, device, backend, counter, start,
                        capture_fps, self._fps(display_timestamps)
                    )

        except Exception as exc:
            self.put_event(make_error_event(f"采集线程异常: {exc}"))
        finally:
            if cap:
                cap.release()
            self.cap = None
            self.put_event(make_stopped_event())
