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

    def publish(self, frame, opened_device, backend, counter, timestamps, start_time):
        now = time.perf_counter()
        timestamps.append(now)

        while timestamps and now - timestamps[0] > 1:
            timestamps.popleft()

        realtime = 0
        if len(timestamps) >= 2:
            realtime = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])

        elapsed = max(now - start_time, 0.001)
        avg = counter / elapsed

        stats = {
            "device": opened_device,
            "camera": self.camera.name,
            "backend": backend,
            "format": self.mode.pixel_format,
            "requested_size": f"{self.mode.width}x{self.mode.height}",
            "actual_size": f"{frame.shape[1]}x{frame.shape[0]}",
            "target_fps": f"{self.mode.fps:.2f}",
            "realtime_fps": f"{realtime:.2f}",
            "avg_fps": f"{avg:.2f}",
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
            timestamps = deque(maxlen=PREVIEW_FPS_HISTORY_SIZE)
            start = time.perf_counter()

            if first is not None:
                counter += 1
                self.publish(first, device, backend, counter, timestamps, start)

            last_publish = 0

            while not self.stopped():
                ok, frame = cap.read()

                if not ok:
                    if not camera_device_present(self.camera):
                        self.put_event(make_device_lost_event("camera removed"))
                    break

                counter += 1
                now = time.perf_counter()

                interval = (
                    1 / PREVIEW_UPDATE_FPS
                    if self._preview_enabled()
                    else 1 / STATS_ONLY_UPDATE_FPS
                )

                if now - last_publish >= interval:
                    last_publish = now
                    self.publish(frame, device, backend, counter, timestamps, start)

        finally:
            if cap:
                cap.release()
            self.cap = None
            self.put_event(make_stopped_event())
