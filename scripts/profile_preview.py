"""Device-free preview microbenchmark; timings are NOT end-to-end latency."""
import argparse
import cProfile
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import PIL

from app.core.chroma import BackgroundCatalog, compose_avatar
from app.core.vts_video import VideoSnapshot
from app.ui.booth_window import BoothWindow


def measure(fn, warmup, samples):
    for _ in range(warmup):
        fn()
    times = []
    start = time.perf_counter()
    for _ in range(samples):
        before = time.perf_counter_ns()
        fn()
        times.append((time.perf_counter_ns() - before) / 1e6)
    wall = time.perf_counter() - start
    return dict(samples=samples, mean_ms=float(np.mean(times)),
                p50_ms=float(np.percentile(times, 50)),
                p95_ms=float(np.percentile(times, 95)),
                p99_ms=float(np.percentile(times, 99)), wall_seconds=wall,
                internal_iterations_per_second=samples / wall)


def benchmark(width=1280, height=720, samples=30, warmup=3):
    if min(width, height, samples) <= 0 or warmup < 0:
        raise ValueError('positive dimensions/samples and nonnegative warmup required')
    frame = np.full((height, width, 3), (0, 255, 0), np.uint8)
    frame[height // 4:3 * height // 4, width // 4:3 * width // 4] = (50, 80, 210)

    class Feed:
        sequence = 0
        error = None

        def snapshot(self, max_age=1):
            return VideoSnapshot(frame.copy(), self.sequence, time.monotonic())

    feed = Feed()
    catalog = BackgroundCatalog()
    booth = BoothWindow(None, lambda image: image, avatar_feed=feed,
                        vts_capture=True, background_catalog=catalog)
    background = catalog.get('builtin:aurora', (width, height))

    def new_frame():
        feed.sequence += 1
        booth._update_composite()

    def full_path():
        new_frame()
        booth._compose_vts(frame)

    try:
        results = {}
        results['background_cold'] = measure(
            lambda: BackgroundCatalog().get('builtin:aurora', (width, height)), 0, samples)
        results['background_warm'] = measure(
            lambda: catalog.get('builtin:aurora', (width, height)), warmup, samples)
        results['chroma'] = measure(lambda: compose_avatar(frame, background), warmup, samples)
        results['new_sequence_composite'] = measure(new_frame, warmup, samples)
        results['same_sequence_early_return'] = measure(booth._update_composite, warmup, samples)
        for state in ('ready', 'countdown', 'recording', 'processing', 'result', 'error'):
            booth.state = state
            booth.deadline = time.monotonic() + 3600
            if state == 'result':
                booth.result_path, booth.qr_path = Path('synthetic-result.png'), Path('synthetic-qr.png')
                artwork = np.full((400, 200, 3), (25, 70, 210), np.uint8)
                qr = np.full((190, 190, 3), 255, np.uint8)
                with patch.object(booth, '_vts_image', side_effect=lambda path: (
                        qr if path == booth.qr_path else artwork)):
                    results['ui_result'] = measure(lambda: booth._compose_vts(frame), warmup, samples)
                booth.result_path, booth.qr_path = None, None
            else:
                results['ui_' + state] = measure(lambda: booth._compose_vts(frame), warmup, samples)
        booth.state = 'ready'
        results['full_internal_path'] = measure(full_path, warmup, samples)
        return dict(scope='synthetic internal processing; no capture, display or end-to-end latency',
                    input_size=[width, height], ui_size=[booth.WIDTH, booth.HEIGHT],
                    warmup=warmup, environment=dict(python=platform.python_version(),
                    opencv=cv2.__version__, numpy=np.__version__, pillow=PIL.__version__),
                    stages=results)
    finally:
        booth.executor.shutdown(wait=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--json', type=Path, help='optional JSON report path')
    parser.add_argument('--cprofile', type=Path, help='optional cProfile stats path')
    args = parser.parse_args()
    if min(args.width, args.height, args.samples) <= 0 or args.warmup < 0:
        parser.error('positive dimensions/samples and nonnegative warmup required')
    profiler = cProfile.Profile() if args.cprofile else None
    if profiler:
        profiler.enable()
    report = benchmark(args.width, args.height, args.samples, args.warmup)
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(args.cprofile))
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(output + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
