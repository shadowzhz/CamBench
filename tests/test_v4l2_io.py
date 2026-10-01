import ctypes
import errno
import unittest
from unittest.mock import patch

from camera import v4l2_io


# 与 linux/videodev2.h 中的一致,防止结构体改动后 ioctl 号漂移
KNOWN_IOCTL_NUMBERS = {
    "VIDIOC_QUERYCAP": 0x80685600,
    "VIDIOC_ENUM_FMT": 0xC0405602,
    "VIDIOC_ENUM_FRAMESIZES": 0xC02C564A,
    "VIDIOC_ENUM_FRAMEINTERVALS": 0xC034564B,
}


# {fourcc: {(width, height): [(numerator, denominator), ...]}}
FAKE_DEVICE_FORMATS = {
    "MJPG": {
        (1280, 720): [(1, 120), (1, 60), (1001, 30000)],
        (640, 480): [(1, 30)],
    },
    "YUYV": {
        (1280, 720): [(1, 30)],
    },
    "H264": {
        (1280, 720): [(1, 30)],
    },
}


class FakeV4l2Device:
    """按真实语义响应 V4L2 枚举 ioctl 的内存设备。"""

    def __init__(self, formats, card="Fake Cam", bus="usb-0000:00:14.0-2",
                 capabilities=0x00000001 | 0x00000002 | 0x04000000,
                 capture_type=v4l2_io._BUF_TYPE_VIDEO_CAPTURE):
        self.formats = formats
        self.card = card
        self.bus = bus
        self.capabilities = capabilities
        self.capture_type = capture_type

    def __call__(self, fd, request, buf):
        if request == v4l2_io.VIDIOC_QUERYCAP:
            buf.driver = b"uvcvideo"
            buf.card = self.card.encode("ascii")
            buf.bus_info = self.bus.encode("ascii")
            buf.version = 0x0005040B
            buf.capabilities = self.capabilities
            buf.device_caps = self.capabilities
            return 0

        if request == v4l2_io.VIDIOC_ENUM_FMT:
            if buf.type != self.capture_type:
                raise OSError(errno.EINVAL, "wrong buf type")
            codes = list(self.formats.keys())
            if buf.index >= len(codes):
                raise OSError(errno.EINVAL, "no more formats")
            code = codes[buf.index]
            buf.pixelformat = v4l2_io.fourcc_to_int(code)
            buf.flags = 0
            buf.description = code.encode("ascii")
            return 0

        if request == v4l2_io.VIDIOC_ENUM_FRAMESIZES:
            code = v4l2_io.int_to_fourcc(buf.pixel_format)
            sizes = sorted(self.formats[code].keys())
            if buf.index >= len(sizes):
                raise OSError(errno.EINVAL, "no more sizes")
            # 内核值 V4L2_FRMSIZE_TYPE_DISCRETE = 1,硬编码以校验模块常量
            buf.type = 1
            buf.union_.discrete.width = sizes[buf.index][0]
            buf.union_.discrete.height = sizes[buf.index][1]
            return 0

        if request == v4l2_io.VIDIOC_ENUM_FRAMEINTERVALS:
            code = v4l2_io.int_to_fourcc(buf.pixel_format)
            intervals = self.formats[code][(buf.width, buf.height)]
            if buf.index >= len(intervals):
                raise OSError(errno.EINVAL, "no more intervals")
            numerator, denominator = intervals[buf.index]
            # 内核值 V4L2_FRMIVAL_TYPE_DISCRETE = 1,硬编码以校验模块常量
            buf.type = 1
            buf.union_.discrete.numerator = numerator
            buf.union_.discrete.denominator = denominator
            return 0

        raise OSError(errno.ENOTTY, "unexpected ioctl request")


class FourccTests(unittest.TestCase):
    def test_round_trip(self):
        for code in ("MJPG", "YUYV", "H264"):
            self.assertEqual(
                v4l2_io.int_to_fourcc(v4l2_io.fourcc_to_int(code)),
                code,
            )

    def test_mjpg_integer_value(self):
        self.assertEqual(v4l2_io.fourcc_to_int("MJPG"), 0x47504A4D)


class IoctlNumberTests(unittest.TestCase):
    def test_match_kernel_constants(self):
        for name, expected in KNOWN_IOCTL_NUMBERS.items():
            self.assertEqual(getattr(v4l2_io, name), expected, name)


class QueryCapabilityTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("camera.v4l2_io._close_device")
        self.mock_close = patcher.start()
        self.addCleanup(patcher.stop)

    @patch(
        "camera.v4l2_io._call_ioctl",
        new_callable=lambda: FakeV4l2Device(FAKE_DEVICE_FORMATS),
    )
    @patch("camera.v4l2_io._open_device", return_value=3)
    def test_decodes_capability(self, _open, _ioctl):
        capability = v4l2_io.query_capability("/dev/video0")

        self.assertIsNotNone(capability)
        self.assertEqual(capability.driver, "uvcvideo")
        self.assertEqual(capability.card, "Fake Cam")
        self.assertEqual(capability.bus_info, "usb-0000:00:14.0-2")
        self.assertTrue(capability.is_capture())

    @patch(
        "camera.v4l2_io._call_ioctl",
        new_callable=lambda: FakeV4l2Device(
            FAKE_DEVICE_FORMATS,
            capabilities=0x00008000,
        ),
    )
    @patch("camera.v4l2_io._open_device", return_value=3)
    def test_metadata_node_is_not_capture(self, _open, _ioctl):
        capability = v4l2_io.query_capability("/dev/video0")

        self.assertIsNotNone(capability)
        self.assertFalse(capability.is_capture())

    @patch(
        "camera.v4l2_io._open_device",
        side_effect=OSError(errno.EACCES, "permission denied"),
    )
    def test_open_failure_returns_none(self, _open):
        self.assertIsNone(v4l2_io.query_capability("/dev/video0"))


class EnumerateDeviceModesTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("camera.v4l2_io._close_device")
        self.mock_close = patcher.start()
        self.addCleanup(patcher.stop)

    @patch(
        "camera.v4l2_io._call_ioctl",
        new_callable=lambda: FakeV4l2Device(FAKE_DEVICE_FORMATS),
    )
    @patch("camera.v4l2_io._open_device", return_value=3)
    def test_enumerates_all_formats_sizes_intervals(self, _open, _ioctl):
        modes = v4l2_io.enumerate_device_modes("/dev/video0")

        self.assertIsNotNone(modes)
        self.assertEqual(
            set(modes),
            {
                ("MJPG", 1280, 720, 120.0),
                ("MJPG", 1280, 720, 60.0),
                ("MJPG", 1280, 720, 30000 / 1001),
                ("MJPG", 640, 480, 30.0),
                ("YUYV", 1280, 720, 30.0),
                ("H264", 1280, 720, 30.0),
            },
        )

    @patch(
        "camera.v4l2_io._call_ioctl",
        new_callable=lambda: FakeV4l2Device(
            FAKE_DEVICE_FORMATS,
            capture_type=v4l2_io._BUF_TYPE_VIDEO_CAPTURE_MPLANE,
        ),
    )
    @patch("camera.v4l2_io._open_device", return_value=3)
    def test_mplane_capture_falls_through(self, _open, _ioctl):
        modes = v4l2_io.enumerate_device_modes("/dev/video0")

        self.assertIsNotNone(modes)
        self.assertTrue(any(code == "MJPG" for code, *_ in modes))

    @patch(
        "camera.v4l2_io._call_ioctl",
        new_callable=lambda: FakeV4l2Device({}),
    )
    @patch("camera.v4l2_io._open_device", return_value=3)
    def test_device_without_capture_formats_is_empty(self, _open, _ioctl):
        self.assertEqual(
            v4l2_io.enumerate_device_modes("/dev/video0"),
            [],
        )

    @patch(
        "camera.v4l2_io._open_device",
        side_effect=OSError(errno.ENOENT, "no such device"),
    )
    def test_unopenable_device_returns_none(self, _open):
        self.assertIsNone(
            v4l2_io.enumerate_device_modes("/dev/video0")
        )


class StructLayoutTests(unittest.TestCase):
    def test_struct_sizes_match_kernel(self):
        self.assertEqual(
            ctypes.sizeof(v4l2_io.V4l2Capability), 104
        )
        self.assertEqual(
            ctypes.sizeof(v4l2_io.V4l2FmtDesc), 64
        )
        self.assertEqual(
            ctypes.sizeof(v4l2_io.V4l2FrmsizeEnum), 44
        )
        self.assertEqual(
            ctypes.sizeof(v4l2_io.V4l2FrmivalEnum), 52
        )

    def test_discrete_type_values_match_kernel(self):
        # V4L2_FRMSIZE_TYPE_DISCRETE / V4L2_FRMIVAL_TYPE_DISCRETE 均为 1
        self.assertEqual(v4l2_io._SIZE_TYPE_DISCRETE, 1)
        self.assertEqual(v4l2_io._IVAL_TYPE_DISCRETE, 1)


if __name__ == "__main__":
    unittest.main()
