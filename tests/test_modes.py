import unittest
from unittest.mock import patch

from camera.models import CameraMode
from camera.modes import (
    find_mode,
    get_available_formats,
    get_camera_modes,
    get_fps_for_resolution,
    get_resolutions_for_format,
    group_modes,
)


V4L2_OUTPUT = """\
[0]: 'MJPG' (Motion-JPEG, compressed)
\tSize: Discrete 1280x720
\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tInterval: Discrete 0.016s (60.000 fps)
\tSize: Discrete 640x480
\t\tInterval: Discrete 0.033s (30.000 fps)
[1]: 'YUYV' (YUYV 4:2:2)
\tSize: Discrete 1280x720
\t\tInterval: Discrete 0.033s (30.000 fps)
"""


IOCTL_MODES = [
    ("MJPG", 1280, 720, 60.0),
    ("H264", 1280, 720, 30.0),
    ("YUYV", 640, 480, 30.0),
]


class CameraModesTests(unittest.TestCase):
    @patch("camera.modes.run_cmd", return_value=V4L2_OUTPUT)
    @patch("camera.modes.enumerate_device_modes", return_value=None)
    def test_list_formats_ext_is_parsed(self, _enum, _run_cmd):
        modes = get_camera_modes("/dev/video0")

        values = {
            (m.pixel_format, m.width, m.height, m.fps)
            for m in modes
        }

        self.assertEqual(
            values,
            {
                ("MJPG", 1280, 720, 30.0),
                ("MJPG", 1280, 720, 60.0),
                ("MJPG", 640, 480, 30.0),
                ("YUYV", 1280, 720, 30.0),
            },
        )

    @patch("camera.modes.run_cmd")
    @patch("camera.modes.enumerate_device_modes", return_value=IOCTL_MODES)
    def test_ioctl_modes_take_priority(self, _enum, run_cmd):
        modes = get_camera_modes("/dev/video0")

        run_cmd.assert_not_called()

        values = {
            (m.pixel_format, m.width, m.height, m.fps)
            for m in modes
        }

        self.assertEqual(
            values,
            {
                ("MJPG", 1280, 720, 60.0),
                ("YUYV", 640, 480, 30.0),
            },
        )

    @patch("camera.modes.run_cmd")
    @patch("camera.modes.enumerate_device_modes", return_value=[])
    def test_ioctl_empty_result_is_authoritative(self, _enum, run_cmd):
        self.assertEqual(get_camera_modes("/dev/video0"), ())
        run_cmd.assert_not_called()


class ModeGroupingTests(unittest.TestCase):
    def setUp(self):
        self.modes = (
            CameraMode("MJPG", 1920, 1080, 30.0),
            CameraMode("MJPG", 1280, 720, 60.0),
            CameraMode("MJPG", 1280, 720, 30.0),
            CameraMode("YUYV", 1280, 720, 10.0),
            CameraMode("YUYV", 640, 480, 30.0),
        )

    def test_group_modes(self):
        grouped = group_modes(self.modes)
        self.assertIn("MJPG", grouped)
        # YUYV 被 normalize_format 规范为 YUY2
        self.assertIn("YUY2", grouped)
        self.assertEqual(grouped["MJPG"][(1280, 720)], [60.0, 30.0])
        self.assertEqual(grouped["YUY2"][(640, 480)], [30.0])

    def test_get_available_formats(self):
        formats = get_available_formats(self.modes)
        self.assertEqual(formats, ["MJPG", "YUY2"])

    def test_get_resolutions_for_format(self):
        mjpg_res = get_resolutions_for_format(self.modes, "MJPG")
        self.assertEqual(mjpg_res, [(1920, 1080), (1280, 720)])

    def test_get_fps_for_resolution(self):
        fps_list = get_fps_for_resolution(self.modes, "MJPG", 1280, 720)
        self.assertEqual(fps_list, [60.0, 30.0])

    def test_find_mode(self):
        mode = find_mode(self.modes, "MJPG", 1280, 720, 60.0)
        self.assertIsNotNone(mode)
        self.assertEqual(mode.pixel_format, "MJPG")
        self.assertEqual(mode.width, 1280)
        self.assertEqual(mode.fps, 60.0)

        # 模糊 FPS 匹配最近项
        mode_approx = find_mode(self.modes, "MJPG", 1280, 720, 59.94)
        self.assertIsNotNone(mode_approx)
        self.assertEqual(mode_approx.fps, 60.0)

        # 不存在的模式返回 None
        self.assertIsNone(find_mode(self.modes, "NV12", 640, 480, 30.0))


if __name__ == "__main__":
    unittest.main()
