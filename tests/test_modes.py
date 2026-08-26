import unittest
from unittest.mock import patch

from camera.modes import get_camera_modes


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


class CameraModesTests(unittest.TestCase):
    @patch("camera.modes.run_cmd", return_value=V4L2_OUTPUT)
    def test_list_formats_ext_is_parsed(self, _run_cmd):
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


if __name__ == "__main__":
    unittest.main()
