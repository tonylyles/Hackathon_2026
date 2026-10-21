# realtime_window.py — 模式 A：实时风格化全屏窗口（OpenCV 实现，最简可靠）
# 按键：q 退出 | s 保存当前帧 | space 切换 原画/风格化
import time

import cv2

from app.config import REALTIME_TARGET_FPS
from app.core.camera import Camera, mirror


class RealtimeWindow:
    def __init__(self, camera: Camera, stylizer):
        self.camera = camera
        self.stylizer = stylizer
        self.fps = 0.0

    def run(self):
        show_styled = True
        last = time.perf_counter()
        while True:
            frame = self.camera.read()
            if frame is None:
                continue
            frame = mirror(frame)
            out = frame
            if show_styled:
                try:
                    out = self.stylizer(frame)
                except Exception as e:
                    cv2.putText(frame, f"stylizer error: {e}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    out = frame

            now = time.perf_counter()
            self.fps = 0.9 * self.fps + 0.1 * (1 / max(1e-6, now - last))
            last = now
            self._hud(out)

            cv2.namedWindow("AI PhotoBooth", cv2.WINDOW_NORMAL)
            cv2.setWindowProperty("AI PhotoBooth", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.imshow("AI PhotoBooth", out)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord(' '):
                show_styled = not show_styled
            elif key == ord('s'):
                p = f"output/snap_{int(time.time())}.png"
                cv2.imwrite(p, out)
                print("saved:", p)
        cv2.destroyAllWindows()

    def _hud(self, frame):
        fps_color = (0, 255, 0) if self.fps >= REALTIME_TARGET_FPS * 0.6 else (0, 165, 255)
        cv2.putText(frame, f"{self.fps:.0f} FPS", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, fps_color, 2)
        cv2.putText(frame, "SPACE: toggle  S: save  Q: quit", (10, frame.shape[0] - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
