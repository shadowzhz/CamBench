import unittest

from camera.fps import FpsMeter


class FpsMeterTests(unittest.TestCase):
    def test_average_and_current_fps(self):
        meter = FpsMeter(history_size=4, clock=lambda: 0.0)
        for timestamp in (0.0, 0.1, 0.2, 0.3):
            meter.tick(timestamp)

        self.assertEqual(meter.frames, 4)
        self.assertAlmostEqual(meter.elapsed, 0.3)
        self.assertAlmostEqual(meter.average_fps, 10.0)
        self.assertAlmostEqual(meter.current_fps, 10.0)

    def test_current_fps_uses_rolling_window(self):
        meter = FpsMeter(history_size=3)
        for timestamp in (0.0, 0.2, 0.4, 0.6, 0.8):
            meter.tick(timestamp)

        self.assertEqual(meter.frames, 5)
        self.assertAlmostEqual(meter.average_fps, 5.0)
        self.assertAlmostEqual(meter.current_fps, 5.0)

    def test_single_frame_has_no_fps(self):
        meter = FpsMeter(history_size=4)
        meter.tick(1.0)

        self.assertEqual(meter.frames, 1)
        self.assertEqual(meter.elapsed, 0.0)
        self.assertEqual(meter.average_fps, 0.0)
        self.assertEqual(meter.current_fps, 0.0)


if __name__ == "__main__":
    unittest.main()
