# fps_probe.py — 测摄像头实际出帧率（5 秒采样）
# 用法：python scripts/fps_probe.py [index]
import sys
import time

import cv2

index = int(sys.argv[1]) if len(sys.argv) > 1 else 0

for backend_name, backend in [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]:
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        print(f"{backend_name}: 打不开")
        continue
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)
    time.sleep(0.5)
    n, t0 = 0, time.perf_counter()
    last_brightness = -1
    while time.perf_counter() - t0 < 5.0:
        ok, f = cap.read()
        if not ok:
            continue
        n += 1
        import numpy as np
        last_brightness = float(f.mean())
    dt = time.perf_counter() - t0
    cap.release()
    print(f"{backend_name}: {n/dt:5.1f} FPS  （5 秒 {n} 帧，最后帧平均亮度 {last_brightness:.0f}/255）")
