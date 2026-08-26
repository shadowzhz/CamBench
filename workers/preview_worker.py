import queue
import time
from collections import deque

from workers.base import BaseWorker

from camera.capture import open_capture
from camera.utils import camera_device_present

from core.config import (
    PREVIEW_UPDATE_FPS,
    STATS_ONLY_UPDATE_FPS,
    PREVIEW_FPS_HISTORY_SIZE,
)

from core.events import (
    make_frame_event,
    make_stats_event,
    make_error_event,
    make_device_lost_event,
    make_stopped_event,
)


class PreviewWorker(BaseWorker):

    def __init__(self, camera, mode, event_queue, preview_enabled):
        super().__init__(event_queue)
        self.camera = camera
        self.mode = mode
        self.preview_enabled = preview_enabled
        self.cap = None

    def stop(self):
        super().stop()

    def put_event(self, event):
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass

    def _preview_enabled(self):
        value = self.preview_enabled
        if hasattr(value, "is_set"):
            return value.is_set()
        return bool(value)

    @staticmethod
    def _fps(timestamps):
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(timestamps) - 1) / elapsed

    def publish(
        self,
        frame,
        opened_device,
        backend,
        counter,
        start_time,
        capture_fps,
        display_fps,
    ):
        elapsed = max(time.perf_counter() - start_time, 0.001)
        avg = counter / elapsed

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

        if self._preview_enabled():
            self.put_event(make_frame_event(frame, stats))
        else:
            self.put_event(make_stats_event(stats))

    def run(self):
        cap = None
        try:
            cap, backend, first, device, errors = open_capture(
                self.camera,
                self.mode,
                self.stop_event,
            )

            if cap is None:
                self.put_event(make_error_event("\n".join(errors)))
                return

            self.cap = cap
            counter = 0
            capture_timestamps = deque(maxlen=PREVIEW_FPS_HISTORY_SIZE)
            display_timestamps = deque(maxlen=PREVIEW_FPS_HISTORY_SIZE)
            start = time.perf_counter()
            last_publish = 0.0

            if first is not None:
                counter += 1
                now = time.perf_counter()
                capture_timestamps.append(now)
                self.publish(
                    first,
                    device,
                    backend,
                    counter,
                    start,
                    self._fps(capture_timestamps),
                    self._fps(display_timestamps),
                )

            while not self.stopped():
                # 采集循环不等待 GUI；GUI 只接收当前最新帧。
                ok, frame = cap.read()

                if not ok:
                    if not camera_device_present(self.camera):
                        self.put_event(make_device_lost_event("camera removed"))
                    break

                counter += 1
                now = time.perf_counter()
                capture_timestamps.append(now)
                capture_fps = self._fps(capture_timestamps)

                interval = (
                    1 / PREVIEW_UPDATE_FPS
                    if self._preview_enabled()
                    else 1 / STATS_ONLY_UPDATE_FPS
                )

                if now - last_publish >= interval:
                    last_publish = now
                    display_timestamps.append(now)
                    self.publish(
                        frame,
                        device,
                        backend,
                        counter,
                        start,
                        capture_fps,
                        self._fps(display_timestamps),
                    )

        finally:
            if cap:
                cap.release()
            self.cap = None
            self.put_event(make_stopped_event())
