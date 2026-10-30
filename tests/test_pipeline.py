"""Regression checks for real decoding/encoding, BGM and HTTP downloads.

Run: python -m unittest discover -s tests -v
Requires project dependencies, httpx, and ffmpeg on PATH. No camera/model needed.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.core.compose import frames_to_video, probe_duration
from app.core.stylizer_mock import MockStylizer
from app.core.video_batch import extract_frames, stylize_frames
from app.config import OUTPUT_DIR
from app.server.api import app


class PipelineTests(unittest.TestCase):
    def setUp(self):
        # Keep temporary files inside the workspace on restricted Windows setups.
        root = Path(__file__).resolve().parents[1] / "tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_frames(self, count=24):
        paths = []
        for index in range(count):
            image = np.full((64, 64, 3), 30, np.uint8)
            cv2.circle(image, (10 + index, 32), 8, (80, 220, 255), -1)
            path = self.root / f"source_{index:05d}.png"
            ok, encoded = cv2.imencode(".png", image)
            self.assertTrue(ok)
            encoded.tofile(path)
            paths.append(path)
        return stylize_frames(paths, MockStylizer(), self.root / "styled")

    def assert_playable(self, path, duration):
        cap = cv2.VideoCapture(str(path))
        self.assertTrue(cap.isOpened())
        decoded = 0
        try:
            while cap.read()[0]:
                decoded += 1
        finally:
            cap.release()
        self.assertGreater(decoded, 0)
        self.assertAlmostEqual(probe_duration(path), duration, delta=0.15)

    def test_mock_encoding_and_http_download(self):
        self.make_frames()
        out = OUTPUT_DIR / "acceptance_regression.mp4"
        try:
            frames_to_video(self.root / "styled", out, fps=24)
            self.assert_playable(out, 1)
            with TestClient(app) as client:
                listing = client.get("/api/items")
                self.assertEqual(listing.status_code, 200)
                self.assertTrue(any(x["name"] == out.name for x in listing.json()))
                for url in (f"/files/{out.name}", f"/api/download/{out.name}"):
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, out.read_bytes())
                for name in ("test.py", "../test_pipeline.py", "..\\test_pipeline.py"):
                    self.assertEqual(client.get(f"/api/download/{name}").status_code, 404)
        finally:
            out.unlink(missing_ok=True)

    def test_short_bgm_loops_without_truncating_video(self):
        self.make_frames(48)
        bgm = self.root / "short.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.25", str(bgm)],
                       check=True, capture_output=True)
        out = self.root / "with_audio.mp4"
        frames_to_video(self.root / "styled", out, fps=24, bgm_path=bgm)
        self.assert_playable(out, 2)
        metadata = subprocess.run(["ffmpeg", "-i", str(out)], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
        self.assertIn("Audio: aac", metadata.stderr)

    def test_fractional_fps_preserves_duration(self):
        self.make_frames(24)
        out = self.root / "fractional.mp4"
        frames_to_video(self.root / "styled", out, fps=24000 / 1001)
        self.assert_playable(out, 1.001)

    def test_missing_video_fails_before_processing(self):
        with self.assertRaisesRegex(ValueError, "无法打开"):
            extract_frames(str(self.root / "missing.mp4"), self.root / "in")


if __name__ == "__main__":
    unittest.main()
