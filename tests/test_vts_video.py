"""VTS capture validity and recovery tests using fake devices."""
import threading
import unittest

import numpy as np

from app.core.vts_video import VTSVideoFeed


class Capture:
    def __init__(self, frames, opened=True):
        self.frames = iter(frames)
        self.opened = opened
        self.released = False
        self.last = None

    def isOpened(self):
        return self.opened

    def read(self):
        item = next(self.frames, self.last)
        if isinstance(item, Exception):
            raise item
        if item is None:
            return False, None
        self.last = item
        return True, item.copy()

    def release(self):
        self.released = True


class VTSVideoTests(unittest.TestCase):
    def wait_for(self, condition):
        event = threading.Event()
        for _ in range(100):
            if condition():
                return
            event.wait(.01)
        self.fail("condition was not reached")

    def test_fresh_snapshot_is_copied_and_stale_frame_is_rejected(self):
        now = [10.0]
        frame = np.full((4, 5, 3), 25, np.uint8)
        cap = Capture([frame])
        feed = VTSVideoFeed(capture_factory=lambda *_: cap, clock=lambda: now[0], retry_seconds=10)
        feed.start()
        self.wait_for(lambda: feed.frame is not None)
        snap = feed.snapshot(.5)
        self.assertIsNotNone(snap)
        self.assertGreaterEqual(snap.sequence, 1)
        snap.frame[:] = 200
        self.assertEqual(int(feed.snapshot(.5).frame[0, 0, 0]), 25)
        now[0] += 2
        self.assertIsNone(feed.snapshot(.5))
        feed.close()
        self.assertTrue(cap.released)

    def test_open_failure_clears_frame_and_retries(self):
        calls = []
        frame = np.full((3, 4, 3), 50, np.uint8)
        caps = [Capture([], opened=False), Capture([frame])]

        def factory(*_):
            cap = caps[min(len(calls), 1)]
            calls.append(cap)
            return cap

        feed = VTSVideoFeed(capture_factory=factory, retry_seconds=.01)
        feed.start()
        self.wait_for(lambda: feed.snapshot() is not None)
        self.assertGreaterEqual(len(calls), 2)
        feed.close()
        self.assertTrue(all(cap.released for cap in calls))


if __name__ == "__main__":
    unittest.main()
