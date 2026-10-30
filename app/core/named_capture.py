"""Bounded named DirectShow capture through FFmpeg (Windows)."""
import queue
import subprocess
import threading

import numpy as np


class NamedCapture:
    def __init__(self, name="VTubeStudioCam", timeout=4.0, width=1280, height=720):
        self.width, self.height = width, height
        self.timeout = timeout
        self.frames = queue.Queue(maxsize=1)
        self.stopped = threading.Event()
        self.process = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "dshow",
             "-rtbufsize", "32M", "-video_size", f"{width}x{height}", "-framerate", "30",
             "-i", f"video={name}", "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.worker = threading.Thread(target=self._pump, daemon=True)
        self.worker.start()

    def isOpened(self):
        return not self.stopped.is_set() and self.process.poll() is None

    def _pump(self):
        size = self.width * self.height * 3
        try:
            while not self.stopped.is_set():
                data = bytearray()
                while len(data) < size and not self.stopped.is_set():
                    chunk = self.process.stdout.read(size - len(data))
                    if not chunk:
                        return
                    data.extend(chunk)
                if len(data) != size:
                    return
                frame = np.frombuffer(data, np.uint8).reshape(self.height, self.width, 3).copy()
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(frame)
                except queue.Full:
                    pass
        except (OSError, ValueError):
            pass

    def read(self):
        if self.stopped.is_set():
            return False, None
        try:
            frame = self.frames.get(timeout=self.timeout)
            return not self.stopped.is_set(), frame
        except queue.Empty:
            return False, None

    def release(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        try:
            self.frames.put_nowait(None)
        except queue.Full:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.worker.join(timeout=1)
        if not self.worker.is_alive():
            self.process.stdout.close()
