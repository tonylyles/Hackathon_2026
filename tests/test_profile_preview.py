"""Synthetic preview profiler smoke tests; no hardware or GUI required."""
import unittest
from unittest.mock import patch

from scripts.profile_preview import benchmark


class PreviewProfileTests(unittest.TestCase):
    def test_report_stages_process_new_sequences_without_devices(self):
        with patch("cv2.VideoCapture", side_effect=AssertionError("opened camera")), \
                patch("cv2.imshow", side_effect=AssertionError("opened GUI")):
            report = benchmark(width=32, height=24, samples=1, warmup=0)
        self.assertEqual(report["input_size"], [32, 24])
        self.assertEqual(report["stages"]["full_internal_path"]["samples"], 1)
        self.assertIn("same_sequence_early_return", report["stages"])
        self.assertIn("ui_result", report["stages"])
        self.assertGreater(report["stages"]["new_sequence_composite"]["mean_ms"], 0)
        self.assertIn("no capture, display", report["scope"])


if __name__ == "__main__":
    unittest.main()
