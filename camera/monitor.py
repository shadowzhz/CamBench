"""
摄像头热插拔监控模块。

在后台线程监听或轮询摄像头设备的插入和移除事件:
- Linux: 优先尝试 pyudev 监听 netlink 的 video4linux 子系统事件;
  无 pyudev 时使用 /dev/video* 节点集合轮询(1秒间隔)。
- Windows: 轮询系统摄像头列表变化。
- 探测到设备变动后,通过回调函数或事件队列通知主线程/GUI。
"""

import glob
import sys
import threading
import time
from typing import Callable, List, Optional, Set

from camera.utils import device_sort_key
from core import log


def get_current_device_identifiers() -> List[str]:
    """获取当前系统中所有摄像头的唯一标识列表。"""
    if sys.platform.startswith("win"):
        from camera.windows_backend import get_windows_camera_names
        names = get_windows_camera_names()
        if names:
            return [f"win:{i}:{name}" for i, name in enumerate(names)]
        # 若无法读取名称,则无法通过此方式做低成本无损轮询,回退空列表
        return []

    # Linux: 列举 /dev/video*
    nodes = sorted(glob.glob("/dev/video*"), key=device_sort_key)
    return nodes


class DeviceMonitor:
    """跨平台摄像头插拔监控器。"""

    def __init__(
        self,
        on_change: Callable[[List[str], List[str]], None],
        poll_interval: float = 1.0,
    ):
        """
        :param on_change: 回调函数 fn(added_devices, removed_devices)
        :param poll_interval: 轮询检测周期(秒)
        """
        self.on_change = on_change
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known_devices: Set[str] = set()

    def start(self):
        """启动监控线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._known_devices = set(get_current_device_identifiers())
        self._thread = threading.Thread(
            target=self._run,
            name="CameraDeviceMonitor",
            daemon=True,
        )
        self._thread.start()
        log("monitor: device monitor started")

    def stop(self):
        """停止监控线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        log("monitor: device monitor stopped")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        # Linux 下尝试 pyudev
        if not sys.platform.startswith("win"):
            if self._try_run_udev():
                return

        # 轮询降级运行
        self._run_polling()

    def _try_run_udev(self) -> bool:
        """尝试使用 pyudev 监听 netlink 事件;成功运行返回 True,不支持/报错返回 False。"""
        try:
            import pyudev
        except ImportError:
            return False

        try:
            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem="video4linux")
            monitor.start()
        except Exception as e:
            log(f"monitor: pyudev init failed ({e}), fallback to polling")
            return False

        log("monitor: using pyudev netlink monitor")
        import select

        # 使用 select 监听 monitor.fileno(),兼顾 stop_event
        while not self._stop_event.is_set():
            try:
                r, _, _ = select.select([monitor], [], [], 0.5)
            except Exception:
                break

            if self._stop_event.is_set():
                break

            if r:
                for device in iter(monitor.poll, None):
                    action = device.action
                    dev_node = device.device_node
                    if not dev_node:
                        continue
                    if action == "add":
                        log(f"monitor: udev device added {dev_node}")
                        # 短暂等待内核创建完整 sysfs 节点
                        time.sleep(0.15)
                        current = set(get_current_device_identifiers())
                        added = list(current - self._known_devices)
                        self._known_devices = current
                        if added:
                            self.on_change(added, [])
                    elif action == "remove":
                        log(f"monitor: udev device removed {dev_node}")
                        current = set(get_current_device_identifiers())
                        removed = list(self._known_devices - current)
                        self._known_devices = current
                        if removed or dev_node:
                            self.on_change([], removed or [dev_node])
        return True

    def _run_polling(self):
        """低开销轮询检查设备集合变化。"""
        log("monitor: using polling device monitor")
        while not self._stop_event.wait(self.poll_interval):
            current = set(get_current_device_identifiers())
            if current != self._known_devices:
                added = sorted(list(current - self._known_devices))
                removed = sorted(list(self._known_devices - current))
                self._known_devices = current
                log(f"monitor: change detected (added={added}, removed={removed})")
                try:
                    self.on_change(added, removed)
                except Exception as e:
                    log(f"monitor: error in on_change callback: {e}")
