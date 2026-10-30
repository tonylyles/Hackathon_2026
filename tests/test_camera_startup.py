"""Camera startup and disconnected-device behavior without physical hardware."""
import threading
import unittest
from unittest.mock import patch

import app.core.camera as camera_module
import app.main as main
import numpy as np


class FakeCapture:
    def __init__(self, opened=True, good=False):
        self.opened = opened
        self.good = good
        self.released = False
        self.reads = 0

    def isOpened(self):
        return self.opened

    def set(self, *_args):
        return True

    def read(self):
        self.reads += 1
        if self.good:
            return True, None
        return False, None

    def release(self):
        self.released = True


class CameraStartupTests(unittest.TestCase):
    def test_failed_open_releases_device(self):
        capture = FakeCapture(opened=False)
        with patch.object(camera_module.cv2, "VideoCapture", return_value=capture):
            with self.assertRaisesRegex(RuntimeError, r"摄像头 1 \(DSHOW\) 打开失败"):
                camera_module.Camera(index=1, backend="DSHOW")
        self.assertTrue(capture.released)

    def test_failed_reads_wait_before_retry(self):
        capture = FakeCapture()
        camera = camera_module.Camera.__new__(camera_module.Camera)
        camera.cap = capture
        camera._running = True
        slept = threading.Event()

        def stop_on_sleep(delay):
            self.assertEqual(delay, 0.1)
            camera._running = False
            slept.set()

        with patch.object(camera_module.time, "sleep", side_effect=stop_on_sleep):
            camera._loop()
        self.assertTrue(slept.is_set())
        self.assertEqual(capture.reads, 1)
    def test_black_frames_are_rejected(self):
        self.assertTrue(camera_module.frame_is_black(np.zeros((720, 1280, 3), np.uint8)))
        visible = np.full((480, 640, 3), 120, np.uint8)
        self.assertFalse(camera_module.frame_is_black(visible))

    def test_wait_for_frame_skips_black_then_returns_visible(self):
        class FakeCamera:
            def __init__(self):
                self.frames = iter((np.zeros((4, 4, 3), np.uint8),
                                    np.full((4, 4, 3), 200, np.uint8)))

            def read(self, only_new=False):
                self.test_only_new = only_new
                return next(self.frames)

        camera = FakeCamera()
        with patch.object(main.time, "sleep"):
            result = main.wait_for_frame(camera)
        self.assertEqual(int(result.mean()), 200)
        self.assertTrue(camera.test_only_new)

    def test_wait_for_frame_reports_persistent_black_frames(self):
        class FakeCamera:
            black_frame_seen = True

            def read(self, only_new=False):
                return None

        with patch.object(main.time, "monotonic", side_effect=(0, 11)):
            with self.assertRaisesRegex(RuntimeError, "持续黑帧"):
                main.wait_for_frame(FakeCamera())

    def test_black_frames_expire_from_camera_snapshot(self):
        capture = FakeCapture()
        black = np.zeros((4, 4, 3), np.uint8)
        capture.read = lambda: (True, black)
        camera = camera_module.Camera.__new__(camera_module.Camera)
        camera.cap = capture
        camera._running = True
        camera._frame = np.full((4, 4, 3), 200, np.uint8)
        camera._last_visible_at = 0
        camera._black_frame_seen = False
        camera._lock = threading.Lock()

        def stop_on_sleep(_delay):
            camera._running = False

        with patch.object(camera_module.time, "sleep", side_effect=stop_on_sleep):
            camera._loop()
        self.assertIsNone(camera._frame)
        self.assertTrue(camera.black_frame_seen)


if __name__ == "__main__":
    unittest.main()
