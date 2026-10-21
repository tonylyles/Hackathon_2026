# make_test_video.py — 生成一段合成测试视频（运动圆环），用于模式 B 验收（无需真人出镜）
# 用法：python scripts/make_test_video.py [输出路径，默认 test.mp4]
import sys
from pathlib import Path

import cv2
import numpy as np


def main(out="test.mp4", seconds=4, fps=24, size=(512, 512)):
    w, h = size
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not vw.isOpened():
        print("VideoWriter 打开失败（检查 mp4v 编码器）")
        return 1
    n = seconds * fps
    for i in range(n):
        t = i / n
        frame = np.full((h, w, 3), 24, np.uint8)
        # 移动渐变背景
        grad = np.linspace(0, 255, w, dtype=np.uint8)
        shift = int(t * w) % w
        frame[:, :, 0] = np.roll(grad, shift)
        # 弹跳圆环（模拟人物动作幅度）
        cx = int(w * (0.5 + 0.35 * np.sin(2 * np.pi * t * 2)))
        cy = int(h * (0.5 + 0.3 * np.cos(2 * np.pi * t * 3)))
        r = 60 + int(20 * np.sin(2 * np.pi * t * 5))
        cv2.circle(frame, (cx, cy), r, (80, 220, 255), -1)
        cv2.circle(frame, (cx, cy), r + 12, (255, 255, 255), 4)
        vw.write(frame)
    vw.release()
    p = Path(out).resolve()
    print(f"生成完成: {p}  ({seconds}s @ {fps}fps, {n} 帧)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "test.mp4"))
