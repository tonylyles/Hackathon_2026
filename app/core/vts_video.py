"""Capture fresh frames from the VTube Studio virtual webcam."""
from dataclasses import dataclass
import threading
import time

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoSnapshot:
    frame: np.ndarray
    sequence: int
    timestamp: float


class VTSVideoFeed:
    """Publish valid frame copies; retry unavailable devices in a worker thread."""

    def __init__(self, index=2, backend="DSHOW", capture_factory=cv2.VideoCapture,
                 clock=time.monotonic, retry_seconds=1.0, named_fallback=False,
                 width=1920, height=1080):
        self.named_fallback = named_fallback
        self.width, self.height = width, height
        self.actual_size = None
        self._resolution_fallback = False
        self.index, self.backend = index, backend
        self.capture_factory, self.clock = capture_factory, clock
        self.retry_seconds = retry_seconds
        self.capture = None
        self.frame = None
        self.error = "等待 VTube Studio 虚拟摄像头"
        self._timestamp = 0.0
        self._sequence = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        if not hasattr(cv2, f"CAP_{self.backend.upper()}"):
            raise ValueError(f"Unknown camera backend: {self.backend}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, name="vts-video", daemon=True)
        self._thread.start()
        return self

    def _invalidate(self, message):
        with self._lock:
            self.frame = None
            self.error = message

    def _read_loop(self):
        backend_id = getattr(cv2, f"CAP_{self.backend.upper()}")
        while not self._stop.is_set():
            capture = None
            try:
                capture = self.capture_factory(self.index, backend_id)
                if capture.isOpened() and hasattr(capture, "set"):
                    width, height = ((1280, 720) if self._resolution_fallback
                                     else (self.width, self.height))
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                if not capture.isOpened() and self.named_fallback:
                    capture.release()
                    from app.core.named_capture import NamedCapture
                    width, height = ((1280, 720) if self._resolution_fallback
                                     else (self.width, self.height))
                    capture = NamedCapture(width=width, height=height)
                self.capture = capture
                if not capture.isOpened():
                    self._invalidate(f"无法打开 VTube Studio 虚拟摄像头（编号 {self.index}，{self.backend}）")
                else:
                    failures = 0
                    while not self._stop.is_set():
                        ok, frame = capture.read()
                        if (ok and isinstance(frame, np.ndarray) and frame.dtype == np.uint8
                                and frame.ndim == 3 and frame.shape[2] == 3 and frame.shape[0] > 0
                                and frame.shape[1] > 0):
                            if self._stop.is_set():
                                break
                            if self.named_fallback and not np.any(frame):
                                self._invalidate("虚拟摄像头输出全黑，请检查 VTS 的虚拟摄像头开关及角色画面")
                                self._stop.wait(0.03)
                                continue
                            failures = 0
                            size = (frame.shape[1], frame.shape[0])
                            if size != self.actual_size:
                                print(f"VTS 虚拟摄像头实际采集尺寸：{size[0]}x{size[1]}")
                                self.actual_size = size
                            with self._lock:
                                self._sequence += 1
                                self.frame = frame.copy()
                                self._timestamp = self.clock()
                                self.error = None
                        else:
                            failures += 1
                            self._invalidate("VTube Studio 虚拟摄像头暂时没有画面")
                            if failures >= 3:
                                break
                            self._stop.wait(0.05)
            except Exception as exc:
                self._invalidate(f"VTube Studio 摄像头读取失败：{exc}")
            finally:
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass
                self.capture = None
            if not self._stop.is_set():
                self._stop.wait(self.retry_seconds)

    def snapshot(self, max_age=0.65):
        if (isinstance(max_age, (bool, np.bool_)) or not isinstance(max_age, (int, float))
                or max_age < 0):
            raise ValueError("max_age must be a nonnegative number")
        with self._lock:
            if (self.frame is None or self.error is not None
                    or self.clock() - self._timestamp > max_age):
                return None
            return VideoSnapshot(self.frame.copy(), self._sequence, self._timestamp)

    def read(self):
        snap = self.snapshot()
        return snap.frame if snap is not None else None

    def close(self):
        self._stop.set()
        from app.core.named_capture import NamedCapture
        capture = self.capture
        if isinstance(capture, NamedCapture):
            capture.release()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1)
        if not thread or not thread.is_alive():
            self._thread = None
        self._invalidate("VTube Studio 虚拟摄像头已停止")

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()
