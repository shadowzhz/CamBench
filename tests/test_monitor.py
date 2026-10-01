import time
import unittest
from unittest.mock import MagicMock, patch

from camera.monitor import DeviceMonitor, get_current_device_identifiers


class DeviceMonitorTests(unittest.TestCase):
    def test_get_current_device_identifiers_linux(self):
        with patch("sys.platform", "linux"):
            with patch("glob.glob", return_value=["/dev/video1", "/dev/video0"]):
                devices = get_current_device_identifiers()
                self.assertEqual(devices, ["/dev/video0", "/dev/video1"])

    def test_get_current_device_identifiers_windows(self):
        with patch("sys.platform", "win32"):
            with patch(
                "camera.windows_backend.get_windows_camera_names",
                return_value=["Cam A", "Cam B"],
            ):
                devices = get_current_device_identifiers()
                self.assertEqual(devices, ["win:0:Cam A", "win:1:Cam B"])

    def test_monitor_start_and_stop(self):
        callback = MagicMock()
        monitor = DeviceMonitor(on_change=callback, poll_interval=0.05)
        self.assertFalse(monitor.is_alive())

        monitor.start()
        self.assertTrue(monitor.is_alive())

        # 重复调用 start 无害
        monitor.start()
        self.assertTrue(monitor.is_alive())

        monitor.stop()
        self.assertFalse(monitor.is_alive())

    def test_polling_detects_addition_and_removal(self):
        calls = []

        def on_change(added, removed):
            calls.append((added, removed))

        sequence = [
            ["/dev/video0", "/dev/video1"],  # 插入 video1
            ["/dev/video1"],                  # 拔出 video0
        ]
        seq_iter = iter(sequence)

        def mock_get_devices():
            try:
                return next(seq_iter)
            except StopIteration:
                return ["/dev/video1"]

        with patch("camera.monitor.get_current_device_identifiers", side_effect=mock_get_devices):
            monitor = DeviceMonitor(on_change=on_change, poll_interval=0.02)
            monitor._known_devices = {"/dev/video0"}

            # 第 1 轮: 增加 video1
            current = set(mock_get_devices())
            added = sorted(list(current - monitor._known_devices))
            removed = sorted(list(monitor._known_devices - current))
            monitor._known_devices = current
            if added or removed:
                on_change(added, removed)

            self.assertEqual(calls, [(["/dev/video1"], [])])

            # 第 2 轮: 拔掉 video0
            current = set(mock_get_devices())
            added = sorted(list(current - monitor._known_devices))
            removed = sorted(list(monitor._known_devices - current))
            monitor._known_devices = current
            if added or removed:
                on_change(added, removed)

            self.assertEqual(
                calls,
                [
                    (["/dev/video1"], []),
                    ([], ["/dev/video0"]),
                ],
            )


if __name__ == "__main__":
    unittest.main()
