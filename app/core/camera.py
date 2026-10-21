# camera.py — 摄像头采集线程（独立线程持续取流，主循环永远拿到最新帧，避免缓冲堆积造成延迟）
import threading
import cv2


class Camera:
    def __init__(self, index=0, width=1280, height=720):
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # Windows 用 DSHOW 启动更快
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        if not self.cap.isOpened():
            raise RuntimeError(f"摄像头 {index} 打开失败")

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                continue
            with self._lock:
                self._frame = frame

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._running = False
        self.cap.release()


def mirror(frame):
    """镜像翻转（自拍习惯）"""
    return cv2.flip(frame, 1)
