# conv_experiment.py — 一次性实验：找出 Blackwell 上最快的卷积配置后可删除
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

torch.backends.cudnn.benchmark = True
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

from app.core.stylizer_anime import AnimeStylizer


def bench(stylizer, frame, n=30):
    for _ in range(8):  # 预热
        stylizer(frame)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        stylizer(frame)
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / n * 1000


frame = np.random.randint(0, 255, (720, 1280, 3), np.uint8)

print("== 配置矩阵（5070 Laptop 8GB）==")
for half in [True, False]:
    for size in [512, 384, 256]:
        st = AnimeStylizer(device="cuda", size=size)
        if half != st.half:
            st.model = st.model.float()
            st.half = False
            st._in = torch.empty((1, 3, size, size), dtype=torch.float32, device=st._in.device)
        ms = bench(st, frame)
        print(f"half={half!s:5}  size={size}  ->  {ms:7.1f} ms/帧  ({1000/ms:5.1f} FPS)")
        del st
        torch.cuda.empty_cache()
