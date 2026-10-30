# test_cameras.py — 枚举本机所有可用摄像头，逐个截一帧存图
# 用法：先打开 Camo Studio（iPhone 已连接），然后 .venv\Scripts\python.exe scripts\test_cameras.py
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.camera import frame_is_black

OUT = Path(__file__).resolve().parent.parent / "tmp"
BACKENDS = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]
OK, NG = "[OK]", "[NG]"


def probe(index, backend_name, backend):
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, frame = False, None
    for _ in range(30):  # 最多等 3 秒取得有内容的画面
        ok, frame = cap.read()
        if ok and not frame_is_black(frame):
            break
        time.sleep(0.1)
    cap.release()
    return (True, frame) if ok and not frame_is_black(frame) else (False, None)


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
            else:
                print(f"{NG} index={index} [{bname}] 无有效画面（可能只有黑帧）")
    print("\n===== 结果 =====")
    for index, bname, w, h, p in found:
        print(f"index={index} [{bname}] {w}x{h}  截图: {p}")
    print("把截图发出来确认哪个是 Camo(iPhone)，哪个是笔记本内置。")


if __name__ == "__main__":
    sys.exit(main())
