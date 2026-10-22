# matrix_capture.py — 遍历 编号×后端 组合，保存每组的真实画面
# 用法：python scripts/matrix_capture.py  （保持 Camo Studio 开启）
import cv2

OUT = "tmp"

for index in [0, 1, 2]:
    for bname, backend in [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW)]:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            print(f"index={index} [{bname}]: 打不开")
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        ok, frame = False, None
        import time
        for _ in range(30):
            ok, frame = cap.read()
            if ok:
                break
            time.sleep(0.1)
        cap.release()
        if not ok:
            print(f"index={index} [{bname}]: 无帧")
            continue
        p = f"{OUT}/matrix_i{index}_{bname}.png"
        ok2, enc = cv2.imencode(".png", frame)
        if ok2:
            enc.tofile(p)
            import numpy as np
            print(f"index={index} [{bname}]: {frame.shape[1]}x{frame.shape[0]} 亮度 {frame.mean():.0f} -> {p}")
        else:
            print(f"index={index} [{bname}]: 保存失败")
