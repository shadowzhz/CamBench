"""
V4L2 ioctl 直接枚举。

通过 VIDIOC_QUERYCAP / ENUM_FMT / ENUM_FRAMESIZES / ENUM_FRAMEINTERVALS
直接向内核请求设备能力与模式,不再解析 v4l2-ctl 文本输出。
结构体布局对应 linux/videodev2.h。
"""

import ctypes
import fcntl
import os


_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2

# enum v4l2_buf_type
_BUF_TYPE_VIDEO_CAPTURE = 1
_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9

# V4L2_CAP_*
_CAP_VIDEO_CAPTURE = 0x00000001
_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000

# enum v4l2_frmsizetypes / frmivaltypes(V4L2_FRMSIZE_TYPE_DISCRETE / V4L2_FRMIVAL_TYPE_DISCRETE)
_SIZE_TYPE_DISCRETE = 1
_IVAL_TYPE_DISCRETE = 1

# 单个枚举序号的安全上限,防止异常驱动导致死循环
_ENUM_INDEX_LIMIT = 1024


def _ioctl_nr(direction, type_char, number, size):
    return (
        (direction << _IOC_DIRSHIFT)
        | (size << _IOC_SIZESHIFT)
        | (ord(type_char) << _IOC_TYPESHIFT)
        | number
    )


class V4l2Capability(ctypes.Structure):
    _fields_ = (
        ("driver", ctypes.c_char * 16),
        ("card", ctypes.c_char * 32),
        ("bus_info", ctypes.c_char * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    )


class V4l2FmtDesc(ctypes.Structure):
    _fields_ = (
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_char * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_code", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    )


class V4l2FrmsizeDiscrete(ctypes.Structure):
    _fields_ = (
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
    )


class V4l2FrmsizeStepwise(ctypes.Structure):
    _fields_ = (
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("step_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
        ("step_height", ctypes.c_uint32),
    )


class V4l2FrmsizeUnion(ctypes.Union):
    _fields_ = (
        ("discrete", V4l2FrmsizeDiscrete),
        ("stepwise", V4l2FrmsizeStepwise),
    )


class V4l2FrmsizeEnum(ctypes.Structure):
    _fields_ = (
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("union_", V4l2FrmsizeUnion),
        ("reserved", ctypes.c_uint32 * 2),
    )


class V4l2Fraction(ctypes.Structure):
    _fields_ = (
        ("numerator", ctypes.c_uint32),
        ("denominator", ctypes.c_uint32),
    )


class V4l2FrmivalStepwise(ctypes.Structure):
    _fields_ = (
        ("min", V4l2Fraction),
        ("max", V4l2Fraction),
        ("step", V4l2Fraction),
    )


class V4l2FrmivalUnion(ctypes.Union):
    _fields_ = (
        ("discrete", V4l2Fraction),
        ("stepwise", V4l2FrmivalStepwise),
    )


class V4l2FrmivalEnum(ctypes.Structure):
    _fields_ = (
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("union_", V4l2FrmivalUnion),
        ("reserved", ctypes.c_uint32 * 2),
    )


VIDIOC_QUERYCAP = _ioctl_nr(
    _IOC_READ, "V", 0, ctypes.sizeof(V4l2Capability)
)
VIDIOC_ENUM_FMT = _ioctl_nr(
    _IOC_READ | _IOC_WRITE, "V", 2, ctypes.sizeof(V4l2FmtDesc)
)
VIDIOC_ENUM_FRAMESIZES = _ioctl_nr(
    _IOC_READ | _IOC_WRITE, "V", 74, ctypes.sizeof(V4l2FrmsizeEnum)
)
VIDIOC_ENUM_FRAMEINTERVALS = _ioctl_nr(
    _IOC_READ | _IOC_WRITE, "V", 75, ctypes.sizeof(V4l2FrmivalEnum)
)


def fourcc_to_int(code):
    return int.from_bytes(
        code.encode("ascii")[:4].ljust(4, b"\x00"),
        "little",
    )


def int_to_fourcc(value):
    raw = value.to_bytes(4, "little").rstrip(b"\x00")
    return raw.decode("ascii", "replace")


def _decode_text(raw):
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


class DeviceCapability:
    """QUERYCAP 结果,用于替代 v4l2-ctl -D 的文本解析。"""

    def __init__(self, driver, card, bus_info, capabilities):
        self.driver = driver
        self.card = card
        self.bus_info = bus_info
        self.capabilities = capabilities

    def is_capture(self):
        return bool(
            self.capabilities
            & (_CAP_VIDEO_CAPTURE | _CAP_VIDEO_CAPTURE_MPLANE)
        )


def _open_device(path):
    return os.open(
        path,
        os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK,
    )


def _call_ioctl(fd, request, buffer):
    fcntl.ioctl(fd, request, buffer, True)


def query_capability(device):
    """返回 DeviceCapability;设备无法打开或 ioctl 失败时返回 None。"""
    try:
        fd = _open_device(device)
    except OSError:
        return None

    try:
        capability = V4l2Capability()
        _call_ioctl(fd, VIDIOC_QUERYCAP, capability)
        return DeviceCapability(
            driver=_decode_text(capability.driver),
            card=_decode_text(capability.card),
            bus_info=_decode_text(capability.bus_info),
            capabilities=capability.capabilities,
        )
    except OSError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def is_capture_device(device):
    capability = query_capability(device)
    return capability is not None and capability.is_capture()


def _enum_formats(fd, buf_type):
    desc = V4l2FmtDesc()
    desc.type = buf_type

    formats = []
    for index in range(_ENUM_INDEX_LIMIT):
        desc.index = index
        try:
            _call_ioctl(fd, VIDIOC_ENUM_FMT, desc)
        except OSError:
            break
        formats.append(desc.pixelformat)

    return formats


def _enum_frame_sizes(fd, fourcc):
    item = V4l2FrmsizeEnum()
    item.pixel_format = fourcc

    sizes = []
    for index in range(_ENUM_INDEX_LIMIT):
        item.index = index
        try:
            _call_ioctl(fd, VIDIOC_ENUM_FRAMESIZES, item)
        except OSError:
            break

        if item.type == _SIZE_TYPE_DISCRETE:
            sizes.append(
                (
                    item.union_.discrete.width,
                    item.union_.discrete.height,
                )
            )
        else:
            # 连续/步进尺寸(UVC 摄像头几乎不会出现),记录范围两端
            stepwise = item.union_.stepwise
            sizes.append((stepwise.min_width, stepwise.min_height))
            sizes.append((stepwise.max_width, stepwise.max_height))

    return sizes


def _enum_frame_intervals(fd, fourcc, width, height):
    item = V4l2FrmivalEnum()
    item.pixel_format = fourcc
    item.width = width
    item.height = height

    fps_values = []
    for index in range(_ENUM_INDEX_LIMIT):
        item.index = index
        try:
            _call_ioctl(fd, VIDIOC_ENUM_FRAMEINTERVALS, item)
        except OSError:
            break

        if item.type == _IVAL_TYPE_DISCRETE:
            interval = item.union_.discrete
        else:
            # 步进帧间隔取最小间隔,即最高帧率
            interval = item.union_.stepwise.min

        if interval.numerator > 0:
            fps_values.append(
                interval.denominator / interval.numerator
            )

    return fps_values


def enumerate_device_modes(device):
    """
    枚举设备所有采集模式。

    返回 (fourcc, width, height, fps) 元组的列表;
    设备无法打开时返回 None,设备可打开但无采集格式时返回空列表。
    """
    try:
        fd = _open_device(device)
    except OSError:
        return None

    try:
        for buf_type in (
            _BUF_TYPE_VIDEO_CAPTURE,
            _BUF_TYPE_VIDEO_CAPTURE_MPLANE,
        ):
            formats = _enum_formats(fd, buf_type)
            if not formats:
                continue

            modes = []
            for fourcc in formats:
                code = int_to_fourcc(fourcc)
                for width, height in _enum_frame_sizes(fd, fourcc):
                    for fps in _enum_frame_intervals(
                        fd, fourcc, width, height
                    ):
                        modes.append((code, width, height, fps))
            return modes

        return []
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
