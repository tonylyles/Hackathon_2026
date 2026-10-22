# brightness_probe.py — 双摄像头亮度采样诊断
# 用法：python scripts/brightness_probe.py
# 测试期间请把 iPhone 镜头对准亮处（台灯/窗户/你的脸），移动手机观察亮度变化
import cv2
import numpy as np


def sample(index, seconds=4):
    cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
    if not cap.isOpened():
        return None
    samples = []
    t0 = cv2.getTickCount()
    freq = cv2.getTickFrequency()
    while (cv2.getTickCount() - t0) / freq < seconds:
        ok, f = cap.read()
        if ok:
            samples.append(float(f.mean()))
    cap.release()
    return samples


for index in [0, 1]:
    s = sample(index)
    if s is None:
        print(f"index={index}: 打不开")
        continue
    if not s:
        print(f"index={index}: 5 秒内没有收到任何帧 ← 【断点在这里】")
        continue
    lo, hi = min(s), max(s)
    delta = hi - lo
    verdict = "画面在变化（正常取流中）" if delta > 5 else "画面几乎静止/全黑（镜头没看到东西，或流是黑的）"
    print(f"index={index}: {len(s)} 帧 | 亮度 {lo:.0f}~{hi:.0f}（变化 {delta:.0f}）| {verdict}")
