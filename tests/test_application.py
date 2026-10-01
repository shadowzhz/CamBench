import queue
import unittest
from unittest.mock import MagicMock, patch

from camera.models import CameraInfo, CameraMode
from core import EventType, make_devices_changed_event, make_device_lost_event


class FakeCombobox(dict):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self._idx = 0
        self._val = ""
        self.bind_calls = []

    def bind(self, event, cb):
        self.bind_calls.append((event, cb))

    def pack(self, *args, **kwargs):
        pass

    def grid(self, *args, **kwargs):
        pass

    def current(self, new_idx=None):
        if new_idx is not None:
            self._idx = new_idx
            vals = self.get("values", [])
            if 0 <= new_idx < len(vals):
                self._val = str(vals[new_idx])
        return self._idx

    def set(self, val):
        self._val = val

    def get(self, key=None, default=None):
        if key is None:
            return self._val
        return super().get(key, default)


class ApplicationLogicTests(unittest.TestCase):
    @patch("tkinter.ttk.Style")
    @patch("camera.scanner.scan_cameras")
    @patch("camera.monitor.DeviceMonitor")
    def test_app_init_and_cascaded_selection(self, mock_monitor_cls, mock_scan, _mock_style):
        # 准备相机和模式
        modes = (
            CameraMode("MJPG", 1920, 1080, 60.0),
            CameraMode("MJPG", 1920, 1080, 30.0),
            CameraMode("MJPG", 1280, 720, 60.0),
            CameraMode("YUY2", 640, 480, 30.0),
        )
        cam = CameraInfo(device="/dev/video0", name="TestCam", bus_info="usb", modes=modes)
        mock_scan.return_value = [cam]

        mock_root = MagicMock()
        mock_root.winfo_width.return_value = 640
        mock_root.winfo_height.return_value = 480

        with patch("app.application.ttk") as mock_ttk:
            mock_ttk.Combobox.side_effect = lambda *a, **k: FakeCombobox()
            with patch("app.application.tk") as mock_tk:
                mock_tk.StringVar.return_value = MagicMock()
                mock_tk.StringVar.return_value.get.return_value = ""
                with patch("app.application.create_stat_panel", return_value=(MagicMock(), {})):
                    from app.application import CameraFpsApp

                    app = CameraFpsApp(mock_root)

                    # 验证相机列表填充
                    self.assertEqual(len(app.cameras), 1)
                    self.assertEqual(app.format_combo["values"], ["MJPG", "YUY2"])

                    # 验证默认首选项
                    selected_mode = app.get_current_selected_mode()
                    self.assertIsNotNone(selected_mode)
                    self.assertEqual(selected_mode.pixel_format, "MJPG")

                    # 模拟设备插拔事件处理
                    app._put_event(make_devices_changed_event(added=["/dev/video1"]))
                    app._process_events()

                    # 模拟设备丢失事件处理
                    app._put_event(make_device_lost_event("disconnected"))
                    app._process_events()

                    # 验证镜像开关存在且默认开启
                    self.assertTrue(app.mirror_var.get())

                    # 验证 show_frame 调用正常且发生镜像翻转
                    import numpy as np
                    fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)
                    app.preview.winfo_width.return_value = 640
                    app.preview.winfo_height.return_value = 480
                    with patch("cv2.flip", side_effect=lambda f, c: f) as mock_flip, patch("cv2.imencode", return_value=(True, b"fake")):
                        app.show_frame(fake_frame)
                        mock_flip.assert_called_once_with(fake_frame, 1)

                    # 关闭应用
                    app.close()
                    self.assertTrue(app._closed)


class StatPanelWidgetsTests(unittest.TestCase):
    def test_create_stat_panel_keys(self):
        mock_parent = MagicMock()
        with patch("app.widgets.ttk") as mock_ttk, patch("app.widgets.tk") as mock_tk:
            mock_tk.StringVar.return_value = MagicMock()
            from app.widgets import create_stat_panel
            panel, variables = create_stat_panel(mock_parent)
            expected_keys = (
                "camera", "device", "backend", "preview", "format",
                "requested_size", "actual_size", "target_fps",
                "realtime_fps", "avg_fps", "frames", "elapsed"
            )
            for k in expected_keys:
                self.assertIn(k, variables)


if __name__ == "__main__":
    unittest.main()
