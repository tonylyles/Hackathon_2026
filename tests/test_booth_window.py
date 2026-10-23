"""Real-time touch UI tests using a fake camera and deterministic helpers."""
import unittest
from unittest.mock import patch

import numpy as np

from app.ui.booth_window import BoothWindow
from app.core.booth import Recording


class FakeCamera:
    def __init__(self, frame):
        self.frame = frame

    def read(self, only_new=False):
        return self.frame.copy()


class FakeProcessor:
    def process(self, kind, payload, progress):
        return kind, payload


class BoothWindowTests(unittest.TestCase):
    def test_mouse_capture_enters_countdown_and_publishes_photo(self):
        frame = np.full((24, 32, 3), 90, np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), show_styled=False)
        booth.last_frame = frame
        with patch("app.ui.booth_window.time.monotonic", return_value=100):
            booth._mouse(4, 100, 680, 0, None)
        self.assertEqual(booth.state, "countdown")
        self.assertEqual(booth.current, "photo")
        booth._reset()
        self.assertEqual(booth.state, "ready")
        booth.executor.shutdown(wait=True)

    def test_recording_shows_completed_progress_before_processing(self):
        frame = np.zeros((4, 4, 3), np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), show_styled=False,
                            record_seconds=1, record_fps=2)
        booth.state = "recording"
        booth.recording = Recording(5, 1, 2)
        booth.recording.add(5, frame)
        booth.recording.add(5.5, frame)
        booth._handle_recording(6, frame)
        self.assertEqual(booth.state, "processing")
        self.assertEqual(booth.future.result()[0], "video")
        booth.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
