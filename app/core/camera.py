# camera.py — 摄像头采集线程（独立线程持续取流，主循环永远拿到最新帧，避免缓冲堆积造成延迟）
import threading
import time
from dataclasses import dataclass
import cv2
import numpy as np


def frame_is_black(frame, threshold=5):
    """Reject empty/dark virtual-camera frames without mistaking a read for video."""
    if frame is None or frame.size == 0 or frame.ndim != 3:
        return True
    sample = frame[::max(1, frame.shape[0] // 80), ::max(1, frame.shape[1] // 80)]
    return np.count_nonzero(np.max(sample, axis=2) > threshold) < sample.shape[0] * sample.shape[1] * .005


@dataclass(frozen=True)
class CameraSnapshot:
    frame: object
    sequence: int
    timestamp: float


class Camera:
    def __init__(self, index=0, width=1920, height=1080, backend="MSMF"):
        b = cv2.CAP_MSMF if backend == "MSMF" else cv2.CAP_DSHOW
        self.cap = cv2.VideoCapture(index, b)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.actual_size = None
        self._lock = threading.Lock()
        self._frame = None
        self._timestamp = 0.0
        self._sequence = 0
        self._last_read_sequence = -1
        self._last_visible_at = time.monotonic()
        self._black_frame_seen = False
        self._running = False
        self._thread = None
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"摄像头 {index} ({backend}) 打开失败")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                # Avoid a tight loop (and a flood of OpenCV warnings) when a device is offline.
                time.sleep(0.1)
                continue
            if frame_is_black(frame):
                # A virtual camera can remain open while outputting black frames.
                # Give a briefly covered lens time to recover before dropping the preview.
                with self._lock:
                    self._black_frame_seen = True
                    if time.monotonic() - self._last_visible_at > 2:
                        self._frame = None
                time.sleep(0.05)
                continue
            with self._lock:
                size = (frame.shape[1], frame.shape[0])
                if size != self.actual_size:
                    print(f"HD 摄像头实际采集尺寸：{size[0]}x{size[1]}")
                    self.actual_size = size
                self._last_visible_at = time.monotonic()
                self._black_frame_seen = False
                self._frame = frame
                self._timestamp = time.monotonic()
                self._sequence += 1

    def snapshot(self, only_new=False):
        with self._lock:
            if self._frame is None or (only_new and self._sequence == self._last_read_sequence):
                return None
            self._last_read_sequence = self._sequence
            return CameraSnapshot(self._frame.copy(), self._sequence, self._timestamp)

    @property
    def black_frame_seen(self):
        with self._lock:
            return self._black_frame_seen

    def read(self, only_new=False):
        snapshot = self.snapshot(only_new=only_new)
        return snapshot.frame if snapshot is not None else None

    def stop(self):
        self._running = False
        self.cap.release()


def mirror(frame):
    """镜像翻转（自拍习惯）"""
    return cv2.flip(frame, 1)
