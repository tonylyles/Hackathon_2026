# channels_last_test.py — 测试 NHWC 内存格式对 Blackwell fp16 卷积的加速（验证后可删除）
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

torch.backends.cudnn.benchmark = True

from app.core.stylizer_anime import AnimeStylizer


def bench(stylizer, frame, n=30):
    for _ in range(8):
        stylizer(frame)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        stylizer(frame)
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / n * 1000


frame = np.random.randint(0, 255, (720, 1280, 3), np.uint8)

for size in [512, 384]:
    st = AnimeStylizer(device="cuda", size=size)
    st.model = st.model.to(memory_format=torch.channels_last)
    st._in = torch.empty((1, 3, size, size), dtype=torch.float16, device=st._in.device).to(memory_format=torch.channels_last)
    ms = bench(st, frame)
    print(f"channels_last fp16  size={size}  ->  {ms:7.1f} ms/帧  ({1000/ms:5.1f} FPS)")
    del st
    torch.cuda.empty_cache()
