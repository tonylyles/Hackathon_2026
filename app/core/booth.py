"""Timed capture and atomic publication, independent of the display/camera hardware."""
import math
import threading
import tempfile
import uuid
from pathlib import Path

from app.config import OUTPUT_DIR, RECORD_FPS, ROOT
from app.core.compose import frames_to_video
from app.core.image_io import write_image
from app.core.video_batch import stylize_frames


class Recording:
    def __init__(self, started, seconds=4, fps=24):
        if seconds <= 0 or fps <= 0:
            raise ValueError("Recording duration and FPS must be positive")
        self.started, self.seconds, self.fps = started, seconds, fps
        self.samples = []

    def add(self, now, frame):
        elapsed = now - self.started
        if not 0 <= elapsed < self.seconds:
            return
        # Bound memory even when the camera produces more than the target FPS.
        slot = int(elapsed * self.fps)
        if not self.samples or slot > int(self.samples[-1][0] * self.fps):
            self.samples.append((elapsed, frame.copy()))

    def finished(self, now):
        return now - self.started >= self.seconds

    def frames(self):
        if not self.samples or self.samples[0][0] > 0.5:
            raise ValueError("Camera did not supply the start of the recording")
        times = [t for t, _ in self.samples] + [self.seconds]
        if max(b - a for a, b in zip(times, times[1:])) > 0.75:
            raise ValueError("Camera stalled during recording; please reconnect and retry")
        # Constant-frame-rate resampling keeps wall-clock duration at low source FPS.
        index = 0
        for tick in range(math.ceil(self.seconds * self.fps)):
            t = tick / self.fps
            while index + 1 < len(self.samples) and self.samples[index + 1][0] <= t:
                index += 1
            yield self.samples[index][1]


class BoothProcessor:
    def __init__(self, stylizer, output_dir=OUTPUT_DIR, stylizer_lock=None):
        self.stylizer = stylizer
        self.stylizer_lock = stylizer_lock or threading.Lock()
        self.output_dir = Path(output_dir)

    def process(self, kind, source, progress=lambda done, total: None, *, composed=False):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        name = f"{kind}_{uuid.uuid4().hex}"
        suffix = ".png" if kind == "photo" else ".mp4"
        target = self.output_dir / (name + suffix)
        # Nothing becomes visible to the sharing API until the complete file exists.
        with tempfile.TemporaryDirectory(prefix="booth_", dir=scratch) as folder:
            job = Path(folder)
            if kind == "photo":
                if composed:
                    image = source
                else:
                    with self.stylizer_lock:
                        image = self.stylizer(source)
                pending = job / (name + suffix)
                write_image(pending, image)
                progress(1, 1)
            elif kind == "video":
                if composed:
                    styled_dir = job / "styled"
                    styled_dir.mkdir()
                    frames = list(source.frames())
                    if not frames:
                        raise ValueError("No VTS frames were recorded")
                    for i, frame in enumerate(frames):
                        write_image(styled_dir / f"styled_{i:05d}.png", frame)
                        progress(i + 1, len(frames))
                else:
                    raw = job / "raw"
                    raw.mkdir()
                    paths = []
                    for i, frame in enumerate(source.frames()):
                        path = raw / f"frame_{i:05d}.png"
                        write_image(path, frame)
                        paths.append(path)
                    if not paths:
                        raise ValueError("No camera frames were recorded")
                    styled_dir = job / "styled"
                    total = len(paths)

                    def report(done, _total):
                        progress(done, total)

                    with self.stylizer_lock:
                        stylize_frames(paths, self.stylizer, styled_dir, progress=report)
                pending = job / (name + suffix)
                frames_to_video(styled_dir, pending, fps=source.fps)
            else:
                raise ValueError(f"Unknown capture kind: {kind}")
            pending.replace(target)
        return target
