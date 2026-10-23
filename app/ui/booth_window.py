"""A no-keyboard photo booth with live preview, capture, and QR sharing."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.config import CAMERA_BACKEND, CAMERA_INDEX, OUTPUT_DIR, RECORD_FPS, RECORD_SECONDS
from app.core.booth import BoothProcessor, Recording
from app.core.camera import mirror
from app.core.image_io import read_image
from app.server.qr import item_url, lan_ip, make_qr


@lru_cache(maxsize=8)
def _font(size):
    candidates = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class BoothWindow:
    WIDTH, HEIGHT = 1280, 720
    PHOTO = ("photo", (68, 650, 360, 704), "拍照")
    VIDEO = ("video", (390, 650, 720, 704), "录制 4 秒")
    EXIT = ("exit", (1120, 12, 1260, 56), "退出")

    def __init__(self, camera, stylizer, port=8000, show_styled=True,
                 record_seconds=RECORD_SECONDS, record_fps=RECORD_FPS,
                 share_ready=None, output_dir=OUTPUT_DIR, processor=None):
        self.camera, self.stylizer = camera, stylizer
        self.port, self.show_styled = port, show_styled
        self.record_seconds, self.record_fps = record_seconds, record_fps
        self.share_ready = share_ready or (lambda: True)
        self.output_dir = Path(output_dir)
        self.qr_dir = self.output_dir / ".booth_qr"
        self.processor = processor or BoothProcessor(stylizer, output_dir)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.current = None
        self.recording = None
        self.state = "ready"
        self.status = "站到画面中央，然后选择拍照或录像"
        self.status_until = 0
        self.progress = (0, 0)
        self.last_frame = None
        self.last_styled = None
        self.qr_path = None
        self.result_path = None
        self.error = None
        self.camera_since = None

    @classmethod
    def hit_test(cls, x, y):
        for action in (cls.PHOTO, cls.VIDEO, cls.EXIT):
            _, (x0, y0, x1, y1), _ = action
            if x0 <= x <= x1 and y0 <= y <= y1:
                return action[0]
        return None

    def _mouse(self, event, x, y, flags, _param):
        if event != cv2.EVENT_LBUTTONUP:
            return
        if self.state in ("result", "error"):
            self._reset()
            return
        action = self.hit_test(x, y)
        if action == "photo":
            self._begin("photo")
        elif action == "video":
            self._begin("video")
        elif action == "exit":
            self.state = "exit"

    def _reset(self):
        self.state = "ready"
        self.status = "站到画面中央，然后选择拍照或录像"
        self.result_path, self.qr_path = None, None
        self.current, self.recording = None, None
        self.progress = (0, 0)
        self.error = None

    def _begin(self, kind):
        if self.state != "ready" or self.last_frame is None:
            return
        self.current = kind
        self.state = "countdown"
        self.deadline = time.monotonic() + 3
        self.status = "准备好！"

    def _poll_future(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            self.result_path = future.result()
            self.state = "result"
            self.status = "作品已完成。扫码下载，点击屏幕返回"
            try:
                self.qr_path = self._make_qr(self.result_path)
            except Exception as exc:
                self.status = f"作品已保存；扫码不可用：{exc}。点击返回"
        except Exception as exc:
            self.state = "error"
            self.error = str(exc)
            self.status = f"处理失败：{self.error[:100]}"
            self.status_until = time.monotonic() + 8

    def _make_qr(self, path):
        if not self.share_ready():
            raise RuntimeError("分享服务未启动")
        ip = lan_ip()
        if ip == "127.0.0.1":
            raise RuntimeError("未找到局域网地址；作品已保存到 output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.qr_dir.mkdir(parents=True, exist_ok=True)
        qr = self.qr_dir / f"{path.stem}.png"
        make_qr(item_url(ip, self.port, path.name), str(qr))
        return qr

    def _publish(self, kind, payload):
        self.state = "processing"
        self.status = "正在生成作品，请稍候…"

        def progress(done, total):
            self.progress = (done, total)

        self.future = self.executor.submit(self.processor.process, kind, payload, progress)

    def _handle_recording(self, now, frame):
        if self.recording is None:
            return
        self.recording.add(now, frame) if frame is not None else None
        elapsed = now - self.recording.started
        self.status = f"正在录像 {min(elapsed, self.record_seconds):.1f} / {self.record_seconds:.0f} 秒"
        if self.recording.finished(now):
            recording, self.recording = self.recording, None
            self._publish("video", RecordingSource(recording))

    def _frame(self):
        raw = self.camera.read(only_new=True)
        if raw is not None:
            self.camera_since = time.monotonic()
            self.last_frame = mirror(raw)
            if self.show_styled and self.state in ("ready", "countdown"):
                try:
                    self.last_styled = self.stylizer(self.last_frame)
                    self.error = None
                except Exception as exc:
                    self.error = str(exc)
                    self.last_styled = self.last_frame
            elif not self.show_styled:
                self.last_styled = self.last_frame
        return raw is not None

    def _compose(self, frame):
        canvas = cv2.resize(frame, (self.WIDTH, self.HEIGHT), interpolation=cv2.INTER_CUBIC)
        if self.state == "result" and self.result_path:
            try:
                if self.result_path.suffix.lower() == ".png":
                    art = read_image(self.result_path)
                    h = 470
                    art = cv2.resize(art, (int(art.shape[1] * h / art.shape[0]), h))
                    canvas[:h, :min(art.shape[1], 650)] = art[:, :650]
            except Exception:
                pass
            if self.qr_path and self.qr_path.exists():
                qr = read_image(self.qr_path)
                qr = cv2.resize(qr, (190, 190), interpolation=cv2.INTER_NEAREST)
                canvas[95:285, 1050:1240] = qr
                self._text(canvas, "扫码下载", 1050, 315, 25, (255, 255, 255))
            self._text(canvas, self.result_path.name[:34], 35, 520, 23, (255, 255, 255))
        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, 610), (self.WIDTH, self.HEIGHT), (18, 20, 34), -1)
        cv2.addWeighted(overlay, .88, canvas, .12, 0, canvas)
        if self.state == "ready":
            self._button(canvas, self.PHOTO, (40, 170, 210))
            self._button(canvas, self.VIDEO, (170, 85, 245))
            self._button(canvas, self.EXIT, (80, 80, 190))
            self._text(canvas, self.status, 40, 640, 26, (255, 255, 255))
        elif self.state == "countdown":
            value = max(1, math.ceil(self.deadline - time.monotonic()))
            self._text(canvas, str(value), 0, 170, 130, (255, 255, 255), center=True)
            self._text(canvas, "准备拍摄", 0, 245, 40, (255, 255, 255), center=True)
        elif self.state == "recording":
            self._text(canvas, "● REC", 45, 660, 32, (60, 80, 255))
            self._text(canvas, self.status, 220, 660, 28, (255, 255, 255))
        elif self.state == "processing":
            self._text(canvas, self.status, 42, 660, 26, (255, 255, 255))
            done, total = self.progress
            if total:
                cv2.rectangle(canvas, (600, 675), (1180, 690), (90, 90, 100), -1)
                cv2.rectangle(canvas, (600, 675), (600 + int(580 * done / total), 690), (180, 85, 245), -1)
        elif self.state in ("result", "error"):
            self._text(canvas, self.status, 40, 660, 24, (255, 255, 255))
            self._text(canvas, "点击屏幕或按空格返回", 40, 700, 19, (200, 210, 220))
        return canvas

    @staticmethod
    def _text(canvas, text, x, y, size, color, center=False):
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        draw = ImageDraw.Draw(image)
        font = _font(size)
        if center:
            x = (canvas.shape[1] - draw.textbbox((0, 0), text, font=font)[2]) // 2
        draw.text((x, y - size), text, font=font, fill=(color[2], color[1], color[0]))
        canvas[:] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    def _button(self, canvas, spec, color):
        _, (x0, y0, x1, y1), label = spec
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, -1)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (235, 235, 240), 1)
        self._text(canvas, label, x0 + 18, y0 + 43, 25, (255, 255, 255))

    def run(self):
        cv2.namedWindow("AI PhotoBooth", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("AI PhotoBooth", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        cv2.setMouseCallback("AI PhotoBooth", self._mouse)
        try:
            while self.state != "exit":
                fresh = self._frame()
                now = time.monotonic()
                if self.camera_since is None:
                    self.camera_since = now
                if now - self.camera_since > 2 and self.state not in ("processing", "result", "error"):
                    self.recording = None
                    self.state = "error"
                    self.status = f"摄像头 {CAMERA_INDEX} ({CAMERA_BACKEND}) 已断开"
                    self.status_until = now + 8
                self._poll_future()
                if self.last_frame is not None:
                    if self.state == "countdown" and now >= self.deadline:
                        if self.current == "photo" and fresh:
                            self._publish("photo", self.last_frame.copy())
                        elif self.current == "video" and fresh:
                            self.recording = Recording(now, self.record_seconds, self.record_fps)
                            self.state = "recording"
                    if self.recording is not None:
                        self._handle_recording(now, self.last_frame if fresh else None)
                    if self.state == "recording":
                        display = self.last_frame
                    elif self.show_styled and self.last_styled is not None:
                        display = self.last_styled
                    else:
                        display = self.last_frame
                    if self.state == "result" and self.result_path and self.result_path.suffix.lower() == ".png":
                        display = read_image(self.result_path)
                    cv2.imshow("AI PhotoBooth", self._compose(display))
                else:
                    preview = self.last_styled if self.show_styled and self.last_styled is not None else self.last_frame
                    if preview is not None:
                        cv2.imshow("AI PhotoBooth", self._compose(preview))
                key = cv2.pollKey() & 0xFF
                if key in (ord('q'), 27):
                    self.state = "exit"
                elif key == ord('s'):
                    self._begin("photo")
                elif key == ord('v'):
                    self._begin("video")
                elif key in (ord(' '), 13):
                    if self.state in ("result", "error"):
                        self._reset()
                    elif self.state == "ready":
                        self._begin("photo")
                if self.state == "error" and time.monotonic() >= self.status_until:
                    self._reset()
                if not fresh:
                    time.sleep(.002)
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)
            cv2.destroyAllWindows()


class RecordingSource:
    def __init__(self, recording):
        self.recording, self.fps = recording, recording.fps

    def frames(self):
        return self.recording.frames()
