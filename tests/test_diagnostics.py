import unittest
from unittest.mock import patch

from camera.diagnostics import (
    diagnose_camera,
    read_exposure_state,
    speed_label,
    uvcvideo_bandwidth_warnings,
)
from camera.models import CameraInfo, CameraMode


DMESG_SAMPLE = """\
[   12.345678] uvcvideo: Found UVC 1.00 device Fake Cam (1234:5678)
[   13.000001] uvcvideo: No streaming interface found, unable to allocate bandwidth.
[   14.000001] usb 1-2: not enough bandwidth for altsetting 2
[   15.000001] uvcvideo: Non-zero status (-71) in video completion handler.
[   16.000001] uvcvideo: Isochronous endpoints on this device cannot maintain Bandwidth.
"""


CTRL_LISTING = """\

                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 current=128
                     auto_exposure 0x00990901 (menu)   : min=0 max=3 default=3 current=3
                     exposure_auto_priority 0x00990902 (bool)   : default=0 value=1
"""


class UvcvideoWarningTests(unittest.TestCase):
    def test_extracts_uvcvideo_bandwidth_lines_only(self):
        warnings = uvcvideo_bandwidth_warnings(DMESG_SAMPLE)

        self.assertEqual(len(warnings), 2)
        self.assertIn("allocate bandwidth", warnings[0])
        self.assertIn("Bandwidth", warnings[1])

    def test_empty_log_has_no_warnings(self):
        self.assertEqual(uvcvideo_bandwidth_warnings(""), [])


class SpeedLabelTests(unittest.TestCase):
    def test_known_speeds(self):
        self.assertEqual(
            speed_label("480"),
            "USB 2.0 High-Speed (480 Mbps)",
        )
        self.assertEqual(
            speed_label("5000"),
            "USB 3.x SuperSpeed (5 Gbps)",
        )

    def test_unknown_speeds(self):
        self.assertEqual(speed_label(""), "未知")
        self.assertEqual(speed_label("1234"), "1234 Mbps")


class ReadExposureStateTests(unittest.TestCase):
    @patch("camera.diagnostics.run_cmd")
    def test_reads_auto_exposure(self, run_cmd):
        run_cmd.side_effect = [CTRL_LISTING, "auto_exposure: 3"]

        state = read_exposure_state("/dev/video0")

        self.assertEqual(state, ("auto_exposure", "3", "自动(光圈优先)"))
        run_cmd.assert_any_call(
            ["v4l2-ctl", "-d", "/dev/video0", "--get-ctrl=auto_exposure"]
        )

    @patch("camera.diagnostics.run_cmd")
    def test_reads_legacy_exposure_auto(self, run_cmd):
        legacy_listing = CTRL_LISTING.replace(
            "auto_exposure 0x", "exposure_auto 0x", 1
        ).replace("exposure_auto_priority", "exposure_auto_prio", 1)
        run_cmd.side_effect = [legacy_listing, "exposure_auto: 1"]

        state = read_exposure_state("/dev/video0")

        self.assertEqual(state, ("exposure_auto", "1", "手动"))

    @patch(
        "camera.diagnostics.run_cmd",
        return_value="                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 current=128",
    )
    def test_missing_control_returns_none(self, _run_cmd):
        self.assertIsNone(read_exposure_state("/dev/video0"))


class DiagnoseCameraTests(unittest.TestCase):
    @patch("camera.diagnostics.kernel_uvcvideo_warnings", return_value=[])
    @patch(
        "camera.diagnostics.read_exposure_state",
        return_value=("auto_exposure", "3", "自动(光圈优先)"),
    )
    @patch(
        "camera.diagnostics.usb_speed",
        return_value=("480", "USB 2.0 High-Speed (480 Mbps)"),
    )
    def test_high_fps_mode_on_usb2_reports_hints(self, _usb, _expo, _warn):
        camera = CameraInfo(
            device="/dev/video0",
            name="Fake Cam",
            bus_info="usb-0000:00:14.0-2",
            modes=(),
        )
        mode = CameraMode("MJPG", 1280, 720, 120.0)

        report = diagnose_camera(camera, mode)

        self.assertIn("USB 2.0", report)
        self.assertIn("带宽紧张", report)
        self.assertIn("--set-ctrl=auto_exposure=1", report)
        self.assertIn("未发现", report)

    @patch("camera.diagnostics.kernel_uvcvideo_warnings", return_value=[])
    @patch("camera.diagnostics.read_exposure_state", return_value=None)
    @patch("camera.diagnostics.usb_speed", return_value=(None, None))
    def test_unknown_everything_still_produces_report(self, _usb, _expo, _warn):
        camera = CameraInfo(
            device="/dev/video0",
            name="Fake Cam",
            bus_info="",
            modes=(),
        )

        report = diagnose_camera(camera)

        self.assertIn("/dev/video0", report)
        self.assertIn("未知", report)
        self.assertIn("无法读取", report)


if __name__ == "__main__":
    unittest.main()
