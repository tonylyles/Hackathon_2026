"""The preview worker skips queued frames and never blocks camera polling."""
import threading
import time
import unittest

import numpy as np

from app.core.preview_worker import PreviewWorker


class PreviewWorkerTests(unittest.TestCase):
    def test_only_newest_pending_frame_runs(self):
        started = threading.Event()
        release = threading.Event()
        completed = []

        def stylize(frame):
            value = int(frame[0, 0, 0])
            completed.append(value)
            if value == 1:
                started.set()
                self.assertTrue(release.wait(2))
            return frame + 10

        worker = PreviewWorker(stylize).start()
        try:
            worker.submit(np.full((2, 2, 3), 1, np.uint8))
            self.assertTrue(started.wait(2))
            worker.submit(np.full((2, 2, 3), 2, np.uint8))
            worker.submit(np.full((2, 2, 3), 3, np.uint8))
            self.assertEqual(worker.dropped, 1)
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result, error = worker.snapshot()
                if result is not None and result.sequence == 3:
                    break
                time.sleep(.005)
            self.assertIsNone(error)
            self.assertEqual(completed, [1, 3])
            self.assertEqual(result.sequence, 3)
            self.assertEqual(int(result.frame[0, 0, 0]), 13)
        finally:
            release.set()
            worker.close()

    def test_disabling_clears_pending_but_preserves_last_result(self):
        gate = threading.Event()
        started = threading.Event()

        def stylize(frame):
            started.set()
            gate.wait(2)
            return frame

        worker = PreviewWorker(stylize).start()
        try:
            worker.submit(np.ones((2, 2, 3), np.uint8))
            self.assertTrue(started.wait(2))
            worker.submit(np.full((2, 2, 3), 2, np.uint8))
            worker.set_enabled(False)
            gate.set()
            time.sleep(.02)
            self.assertIsNone(worker.snapshot()[0])
            worker.set_enabled(True)
            worker.submit(np.full((2, 2, 3), 3, np.uint8))
            deadline = time.monotonic() + 2
            while worker.snapshot()[0] is None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(worker.snapshot()[0].sequence, 3)
        finally:
            gate.set()
            worker.close()

    def test_previous_generation_cannot_replace_new_preview_after_reset(self):
        started = threading.Event()
        release = threading.Event()

        def stylize(frame):
            if int(frame[0, 0, 0]) == 1:
                started.set()
                release.wait(2)
            return frame

        worker = PreviewWorker(stylize).start()
        try:
            worker.submit(np.ones((2, 2, 3), np.uint8))
            self.assertTrue(started.wait(2))
            worker.set_enabled(False)
            worker.set_enabled(True)
            release.set()
            time.sleep(.02)
            self.assertIsNone(worker.snapshot()[0])
            worker.submit(np.full((2, 2, 3), 2, np.uint8))
            deadline = time.monotonic() + 2
            while worker.snapshot()[0] is None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(int(worker.snapshot()[0].frame[0, 0, 0]), 2)
        finally:
            release.set()
            worker.close()


if __name__ == "__main__":
    unittest.main()
