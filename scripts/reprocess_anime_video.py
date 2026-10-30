"""Reprocess the matching Camo recording with corrected AnimeGAN color and aspect ratio."""
import sys
import time
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.compose import frames_to_video, probe_duration
from app.core.image_io import read_image, write_image
from scripts.compare_anime_photo import load_cached_stylizer, stylize

SOURCE = ROOT / "output" / "video_a4ff871358bf48b1a6c4c2b984db088b.mp4"


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    model, device, half = load_cached_stylizer()
    cap = cv2.VideoCapture(str(SOURCE))
    if not cap.isOpened():
        raise ValueError(f"无法打开原画视频: {SOURCE}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output = ROOT / "output" / f"video_corrected_{stamp}.mp4"
    preview = ROOT / "output" / f"video_corrected_preview_{stamp}.png"
    scratch_root = ROOT / "tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed = 0
    started = time.perf_counter()

    try:
        with tempfile.TemporaryDirectory(prefix="anime_video_", dir=scratch_root) as folder:
            frames_dir = Path(folder)
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                result = stylize(model, device, half, frame)
                if result.shape != frame.shape:
                    raise ValueError(f"帧尺寸改变: {frame.shape} -> {result.shape}")
                write_image(frames_dir / f"styled_{processed:05d}.png", result)
                if processed == 0:
                    write_image(preview, result)
                processed += 1
                if processed % 16 == 0 or processed == expected:
                    print(f"AI video progress: {processed}/{expected}", flush=True)
            if processed == 0:
                raise ValueError("原画视频中没有可解码帧")
            frames_to_video(frames_dir, output, fps=fps)
    finally:
        cap.release()

    check = cv2.VideoCapture(str(output))
    decoded = 0
    first = last = None
    try:
        while True:
            ok, frame = check.read()
            if not ok:
                break
            if first is None:
                first = frame.copy()
            last = frame
            decoded += 1
        output_fps = check.get(cv2.CAP_PROP_FPS)
        output_size = (int(check.get(cv2.CAP_PROP_FRAME_WIDTH)), int(check.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        check.release()

    duration = probe_duration(output)
    assert decoded > 0 and output_size == (width, height), (decoded, output_size, width, height)
    assert abs(decoded - processed) <= 1, (decoded, processed)
    assert duration is not None and abs(duration - processed / fps) < 0.15, duration
    difference = float(cv2.absdiff(first, last).mean()) if decoded > 1 else 0.0
    print(f"Source: {SOURCE} {width}x{height}, {fps:.3f} fps, {expected} frames")
    print(f"Corrected: {output} {output_size[0]}x{output_size[1]}, {output_fps:.3f} fps")
    print(f"Decoded: {decoded} frames, {duration:.3f}s; first-last difference {difference:.3f}")
    print(f"Preview: {preview}")
    print(f"Processing: {time.perf_counter() - started:.2f}s on {device}; no source files overwritten")


if __name__ == "__main__":
    main()
