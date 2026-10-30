"""Capture behavior tests that do not require a physical camera or GPU."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import app.main as main
from app.core.booth import BoothProcessor, Recording
from app.ui.booth_window import BoothWindow


class CountingStylizer:
    def __init__(self):
        self.calls = 0

    def __call__(self, frame):
        self.calls += 1
        return frame


class BoothTests(unittest.TestCase):
    def test_open_camera_uses_all_central_config(self):
        calls = {}

        class FakeCamera:
            def __init__(self, **kwargs):
                calls.update(kwargs)

            def start(self):
                return self

        with patch("app.core.camera.Camera", FakeCamera), \
             patch.object(main, "CAMERA_INDEX", 4), \
             patch.object(main, "CAMERA_BACKEND", "MSMF"), \
             patch.object(main, "CAMERA_W", 640), \
             patch.object(main, "CAMERA_H", 480):
            main.open_camera()
        self.assertEqual(calls, {"index": 4, "backend": "MSMF", "width": 640, "height": 480})

    def test_touch_buttons_and_outside_hit(self):
        self.assertEqual(BoothWindow.hit_test(100, 680), "photo")
        self.assertEqual(BoothWindow.hit_test(400, 680), "video")
        self.assertEqual(BoothWindow.hit_test(1200, 30), "exit")
        self.assertIsNone(BoothWindow.hit_test(600, 400))

    def test_recording_resamples_to_constant_fps_and_four_seconds(self):
        rec = Recording(10, seconds=4, fps=2)
        for tick in range(80):
            now = 10 + tick / 20
            rec.add(now, np.full((4, 4, 3), tick, np.uint8))
        self.assertTrue(rec.finished(14))
        frames = list(rec.frames())
        self.assertEqual(len(frames), 8)

    def test_recording_rejects_camera_stall(self):
        rec = Recording(0, seconds=4, fps=2)
        rec.add(0, np.zeros((4, 4, 3), np.uint8))
        rec.add(3, np.zeros((4, 4, 3), np.uint8))
        with self.assertRaisesRegex(ValueError, "stalled"):
            list(rec.frames())

    def test_photo_is_published_to_output(self):
        with tempfile.TemporaryDirectory() as folder:
            stylizer = CountingStylizer()
            processor = BoothProcessor(stylizer, folder)
            frame = np.full((12, 14, 3), 127, np.uint8)
            result = processor.process("photo", frame)
            self.assertTrue(result.is_file())
            self.assertEqual(result.parent, Path(folder))
            self.assertEqual(result.suffix, ".png")
            self.assertEqual(stylizer.calls, 1)
            self.assertEqual(list(Path(folder).iterdir()), [result])

    def test_composed_vts_photo_bypasses_stylizer(self):
        with tempfile.TemporaryDirectory() as folder:
            stylizer = CountingStylizer()
            frame = np.full((12, 14, 3), 193, np.uint8)
            result = BoothProcessor(stylizer, folder).process("photo", frame, composed=True)
            import cv2
            saved = cv2.imdecode(np.fromfile(result, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertTrue(np.array_equal(saved, frame))
            self.assertEqual(stylizer.calls, 0)

    def test_failed_photo_does_not_publish_partial_file(self):
        class Broken:
            def __call__(self, _frame):
                raise RuntimeError("inference failed")

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                BoothProcessor(Broken(), folder).process("photo", np.zeros((2, 2, 3), np.uint8))
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
