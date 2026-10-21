"""Bounded camera/UI smoke check; closes after 8 seconds. No AI model.

python -m scripts.check_realtime [--no-style]
The mock run requests one snapshot through the same S-key handler.
"""
import argparse
import json
import time
from unittest.mock import patch

import cv2

from app.config import OUTPUT_DIR
from app.main import run_realtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-style", action="store_true")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)
    original_wait = cv2.waitKey
    original_show = cv2.imshow
    start = None
    frames = 0
    saved = False
    just_displayed = False

    def show(name, frame):
        nonlocal start, frames, just_displayed
        if start is None:
            start = time.perf_counter()
        frames += 1
        just_displayed = True
        original_show(name, frame)

    def key(delay):
        nonlocal saved, just_displayed
        actual = original_wait(delay)
        elapsed = time.perf_counter() - start if start is not None else 0
        if elapsed >= 8:
            return ord("q")
        shown = just_displayed
        just_displayed = False
        if elapsed >= 3 and not args.no_style and not saved and shown:
            saved = True
            return ord("s")
        return actual

    try:
        with patch.object(cv2, "imshow", show), patch.object(cv2, "waitKey", key):
            run_realtime(args.no_style, engine="mock")
    finally:
        cv2.destroyAllWindows()
    elapsed = time.perf_counter() - start if start is not None else 0
    result = {"mode": "raw" if args.no_style else "mock", "displayed_frames": frames,
              "seconds": round(elapsed, 3),
              "display_loop_fps": round(frames / elapsed, 2) if elapsed else 0,
              "snapshot_requested": saved,
              "note": "Distinct captured frames displayed per second; not end-to-end latency; no AI."}
    path = OUTPUT_DIR / ("check_raw.json" if args.no_style else "check_mock.json")
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
