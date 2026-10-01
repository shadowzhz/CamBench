import sys
import unittest
from unittest.mock import MagicMock, patch

from camera.capture import configure_v4l2, open_capture, open_windows_capture
from camera.models import CameraInfo, CameraMode
from camera.utils import camera_device_present, device_sort_key
from camera.windows_backend import (
    build_modes_for_resolutions,
    diagnose_windows_camera,
    get_windows_camera_modes,
    get_windows_camera_names,
    probe_resolutions_from_capture,
    scan_windows_cameras,
)


class WindowsBackendTests(unittest.TestCase):
    def test_get_windows_camera_modes(self):
        modes = get_windows_camera_modes("0")
        self.assertTrue(len(modes) > 0)
        # 确保首位为 MJPG 且分辨率最高
        first_mode = modes[0]
        self.assertEqual(first_mode.pixel_format, "MJPG")
        self.assertGreaterEqual(first_mode.width, 1920)
        # 格式应包含 MJPG 与 YUY2
        formats = {m.pixel_format for m in modes}
        self.assertIn("MJPG", formats)
        self.assertIn("YUY2", formats)

    @patch("camera.windows_backend.run_cmd", return_value='["Integrated Camera", "USB Camera"]')
    @patch("shutil.which", return_value="powershell")
    def test_get_windows_camera_names_from_json(self, _which, _run):
        names = get_windows_camera_names()
        self.assertEqual(names, ["Integrated Camera", "USB Camera"])

    @patch("camera.windows_backend.run_cmd", return_value="Logitech Webcam\n")
    @patch("shutil.which", return_value="powershell")
    def test_get_windows_camera_names_fallback_text(self, _which, _run):
        names = get_windows_camera_names()
        self.assertEqual(names, ["Logitech Webcam"])

    @patch("camera.windows_backend.cv2.VideoCapture")
    @patch("camera.windows_backend.get_windows_camera_names", return_value=["Webcam 1"])
    def test_scan_windows_cameras(self, _mock_names, mock_cap_cls):
        # 模拟 index 0 成功打开, 1 失败
        mock_cap0 = MagicMock()
        mock_cap0.isOpened.return_value = True

        mock_cap1 = MagicMock()
        mock_cap1.isOpened.return_value = False

        mock_cap_cls.side_effect = [mock_cap0, mock_cap1, mock_cap1]

        cameras = scan_windows_cameras(max_devices=3)
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].device, "0")
        self.assertEqual(cameras[0].name, "Webcam 1")
        self.assertTrue(len(cameras[0].modes) > 0)

    def test_diagnose_windows_camera(self):
        camera = CameraInfo(device="0", name="HD Webcam", bus_info="DirectShow", modes=())
        mode = CameraMode("MJPG", 1920, 1080, 60.0)
        report = diagnose_windows_camera(camera, mode)

        self.assertIn("Windows 摄像头诊断报告", report)
        self.assertIn("HD Webcam", report)
        self.assertIn("曝光与跑不满帧率说明", report)
        self.assertIn("USB 总线带宽建议", report)

    def test_probe_resolutions_from_capture(self):
        mock_cap = MagicMock()
        # 模拟相机只支持 1280x720 与 640x480
        def fake_get(prop):
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return mock_cap._cur_w
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return mock_cap._cur_h
            return 0

        def fake_set(prop, val):
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                mock_cap._cur_w = 1280 if val >= 1280 else 640
            elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
                mock_cap._cur_h = 720 if val >= 720 else 480
            return True

        mock_cap.get.side_effect = fake_get
        mock_cap.set.side_effect = fake_set
        res = probe_resolutions_from_capture(mock_cap)
        self.assertIn((1280, 720), res)
        self.assertIn((640, 480), res)

    def test_build_modes_for_resolutions(self):
        resolutions = [(1920, 1080), (1280, 720)]
        modes = build_modes_for_resolutions(resolutions)
        self.assertTrue(len(modes) > 0)
        formats = {m.pixel_format for m in modes}
        self.assertIn("MJPG", formats)
        self.assertIn("YUY2", formats)
        res_set = {(m.width, m.height) for m in modes}
        self.assertEqual(res_set, {(1920, 1080), (1280, 720)})


class WindowsCaptureTests(unittest.TestCase):
    def test_device_sort_key_windows(self):
        self.assertEqual(device_sort_key(0), 0)
        self.assertEqual(device_sort_key("1"), 1)
        self.assertEqual(device_sort_key("/dev/video2"), 2)

    def test_camera_device_present_windows(self):
        with patch("sys.platform", "win32"):
            cam = CameraInfo(device="0", name="Cam", bus_info="", modes=())
            self.assertTrue(camera_device_present(cam))

    @patch("camera.capture.cv2.VideoCapture")
    def test_open_windows_capture_success(self, mock_cap_cls):
        camera = CameraInfo(device="0", name="Cam", bus_info="", modes=())
        mode = CameraMode("MJPG", 1280, 720, 30.0)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            3: 1280.0,  # CAP_PROP_FRAME_WIDTH
            4: 720.0,   # CAP_PROP_FRAME_HEIGHT
            5: 30.0,    # CAP_PROP_FPS
        }.get(prop, 0.0)
        fake_frame = MagicMock()
        fake_frame.shape = (720, 1280, 3)
        mock_cap.read.return_value = (True, fake_frame)

        mock_cap_cls.return_value = mock_cap

        errors = []
        cap, backend, frame, device = open_windows_capture(camera, mode, errors)
        self.assertIsNotNone(cap)
        self.assertIn("DirectShow", backend)
        self.assertEqual(device, "0")
        self.assertIsNotNone(frame)

    @patch("camera.capture.open_windows_capture")
    def test_open_capture_dispatches_to_windows(self, mock_win_cap):
        camera = CameraInfo(device="0", name="Cam", bus_info="", modes=())
        mode = CameraMode("MJPG", 1280, 720, 30.0)
        fake_frame = MagicMock()
        mock_win_cap.return_value = (MagicMock(), "DirectShow 0", fake_frame, "0")

        with patch("sys.platform", "win32"):
            cap, backend, frame, device, errors = open_capture(camera, mode)
            self.assertIsNotNone(cap)
            self.assertEqual(backend, "DirectShow 0")
            mock_win_cap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
