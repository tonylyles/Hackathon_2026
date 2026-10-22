# debug_stylize.py — 从摄像头取一帧，分别用 fp16/fp32 风格化并保存对比图
# 用法：python scripts/debug_stylize.py  （测试时请对着摄像头，画面里有你的脸）
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import torch

from app.core.camera import Camera, mirror

OUT = Path("tmp")


def grab(camera_index=1):
    cap = cv2.VideoCapture(camera_index, cv2.CAP_MSMF)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    time.sleep(1.0)
    frame = None
    for _ in range(30):
        ok, f = cap.read()
        if ok:
            frame = f
    cap.release()
    return frame


import time  # noqa: E402

print("从摄像头抓帧（请对着镜头）...")
frame = mirror(grab(1))
assert frame is not None, "没有输入帧"
cv2.imwrite(str(OUT / "input.png"), frame)

import app.config as cfg  # noqa: E402

for half in [True, False]:
    cfg.USE_HALF = half
    import importlib
    import app.core.stylizer_anime as sa
    importlib.reload(sa)
    st = sa.AnimeStylizer(device="cuda", size=512)
    for _ in range(5):
        st(frame)  # 预热
    out = st(frame)
    tag = "fp16" if half else "fp32"
    cv2.imwrite(str(OUT / f"styled_{tag}.png"), out)
    print(f"{tag}: 输出均值 {out.mean():.1f}（正常应 40~200）")
print("已保存 tmp/input.png, tmp/styled_fp16.png, tmp/styled_fp32.png")
