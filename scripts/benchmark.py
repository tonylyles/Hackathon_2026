# benchmark.py — 风格化引擎基准测试（无窗口，合成帧喂入）
# 用法：.venv\Scripts\python.exe -X utf8 scripts\benchmark.py [帧数，默认120]
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

from app.config import DEVICE
from app.core.stylizer_anime import AnimeStylizer


def main(n=120):
    print(f"device={DEVICE}")
    st = AnimeStylizer(device=DEVICE)
    frame = np.random.randint(0, 255, (720, 1280, 3), np.uint8)

    # 预热 10 帧（cudnn.benchmark 选核）
    for _ in range(10):
        st(frame)
    if st.device.type == "cuda":
        torch.cuda.synchronize()

    t0 = time.perf_counter()
    for _ in range(n):
        st(frame)
    if st.device.type == "cuda":
        torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / n * 1000

    print(f"平均 {dt:.1f} ms/帧  →  {1000/dt:.0f} FPS  （{n} 帧 @ {st.size}px, half={st.half}）")
    if st.device.type == "cuda":
        print(f"显存峰值: {torch.cuda.max_memory_allocated()/1024**2:.0f} MB")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
