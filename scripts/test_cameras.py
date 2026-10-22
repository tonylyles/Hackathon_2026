# test_cameras.py — 枚举本机所有可用摄像头，逐个截一帧存图
# 用法：先打开 Camo Studio（iPhone 已连接），然后 .venv\Scripts\python.exe scripts\test_cameras.py
import sys
import time
from pathlib import Path

import cv2

OUT = Path(__file__).resolve().parent.parent / "tmp"
BACKENDS = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]
OK, NG = "[OK]", "[NG]"


def probe(index, backend_name, backend):
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, frame = False, None
    for _ in range(30):  # 最多等 3 秒出帧
        ok, frame = cap.read()
        if ok:
            break
        time.sleep(0.1)
    cap.release()
    return (ok, frame) if ok else (False, None)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    found = []
    for index in range(4):
        for bname, backend in BACKENDS:
            ok, frame = probe(index, bname, backend)
            if ok:
                h, w = frame.shape[:2]
                p = OUT / f"cam{index}_{bname}.png"
                cv2.imwrite(str(p), frame)
                found.append((index, bname, w, h, p))
                print(f"{OK} 摄像头 index={index} [{bname}]  {w}x{h}  -> {p.name}")
                break  # 该编号一个后端能用就行
        else:
            print(f"{NG} index={index} 不可用")
    print("\n===== 结果 =====")
    for index, bname, w, h, p in found:
        print(f"index={index} [{bname}] {w}x{h}  截图: {p}")
    print("把截图发出来确认哪个是 Camo(iPhone)，哪个是笔记本内置。")


if __name__ == "__main__":
    sys.exit(main())
