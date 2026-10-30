"""A no-keyboard photo booth with live preview, capture, and QR sharing."""
import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.config import (BACKGROUND_DIR, CAMERA_BACKEND, CAMERA_INDEX, OUTPUT_DIR,
                        RECORD_FPS, RECORD_SECONDS, VTS_FRAME_MAX_AGE,
                        VTS_RETRY_INTERVAL_SECONDS, VTS_STARTUP_TIMEOUT_SECONDS)
from app.core.booth import BoothProcessor, Recording
from app.core.camera import mirror
from app.core.preview_worker import PreviewWorker
from app.core.chroma import BackgroundCatalog, ChromaRejected, blend_scene, compose_avatar
from app.core.vts_client import VTSAPIError
from app.core.image_io import read_image
from app.ui.camera_layout import compose_camera, scaled_rect
from app.server.qr import item_url, lan_ip, make_qr


@lru_cache(maxsize=256)
def _vts_text_mask(text, width, height, size, center):
    """Cache glyph coverage, not pixels from the changing video underneath."""
    image = Image.new("L", (width, height))
    draw, font = ImageDraw.Draw(image), _font(size)
    line_height = size + 7
    max_lines = max(1, height // line_height)
    lines, line = [], ""
    text = str(text)
    truncated = len(text) > 1000
    for char in text[:1000]:
        if char == "\n" or draw.textlength(line + char, font=font) > width - 4:
            lines.append(line)
            line = "" if char == "\n" else char
            if len(lines) == max_lines:
                truncated = True
                break
        else:
            line += char
    if len(lines) < max_lines:
        lines.append(line)
    if truncated:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width - 4:
            last = last[:-1]
        lines[-1] = last + "…"
    top = max(0, (height - len(lines) * line_height) // 2) if center else 0
    for index, line in enumerate(lines):
        left = max(0, int((width - draw.textlength(line, font=font)) / 2)) if center else 0
        draw.text((left, top + index * line_height), line, font=font, fill=255)
    return image


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
    MAIN_PREVIEW = (28, 76, 928, 596)
    RAW_INSET = (946, 119, 1254, 338)
    VTS_LAYOUT = {
        "preview": (32, 104, 824, 592),
        "scene": (850, 104, 1248, 575),
        "random_background": (870, 458, 1228, 497),
        "photo": (74, 624, 340, 688),
        "video": (360, 624, 660, 688),
        "hotkeys": (850, 616, 1248, 676),
        "models": (1028, 72, 1248, 104),
        "retry": (850, 72, 1018, 104),
        "model_dialog": (240, 110, 1040, 608),
        "model_refresh": (665, 127, 820, 171),
        "model_close": (842, 127, 1015, 171),
        "model_previous": (370, 535, 510, 580),
        "model_next": (760, 535, 900, 580),
        "source_virtual": (65, 565, 255, 608),
        "source_camera": (265, 565, 455, 608),
        "opacity_less": (875, 535, 935, 575),
        "opacity_more": (1165, 535, 1225, 575),
        "camera_retry": (870, 403, 1228, 447),
    }
    VTS_COLORS = {
        "background": (17, 15, 13), "panel": (28, 25, 22),
        "panel_alt": (39, 34, 30), "line": (67, 59, 52),
        "text": (246, 242, 235), "muted": (173, 166, 157),
        "cyan": (221, 157, 62), "violet": (191, 104, 184),
        "green": (119, 196, 129), "red": (92, 93, 220),
        "scene_base": (44, 35, 30),
    }

    def __init__(self, camera, stylizer, port=8000, show_styled=True,
                 record_seconds=RECORD_SECONDS, record_fps=RECORD_FPS,
                 share_ready=None, output_dir=OUTPUT_DIR, processor=None,
                 avatar_feed=None, vts_controller=None, vts_capture=None,
                 background_catalog=None, vts_api_error=None, vts_launcher=None,
                 camera_opener=None, camera_stylizer=None):
        self.camera, self.stylizer = camera, stylizer
        self.camera_opener, self.camera_stylizer = camera_opener, camera_stylizer
        self.source = "vts" if vts_capture else "camera"
        self.capture_source = None
        self.background_opacity = 1.0
        self.capture_opacity = 1.0
        self.camera_error = None
        self.camera_sequence = 0
        self.camera_captured_at = 0.0
        self._camera_executor = ThreadPoolExecutor(max_workers=1) if vts_capture and camera_opener else None
        self._camera_future = None
        self._camera_closed = False
        self._camera_processor = None
        self._camera_style_future = None
        self._camera_style_error = None
        self._camera_style_executor = ThreadPoolExecutor(max_workers=1) if vts_capture and camera_stylizer else None
        self.avatar_feed, self.vts_controller = avatar_feed, vts_controller
        self.vts_launcher = vts_launcher
        self.vts_executor = ThreadPoolExecutor(max_workers=1) if vts_controller else None
        self._vts_connecting = False
        self._vts_startup_deadline = 0.0
        self.vts_capture = False if vts_capture is None else vts_capture
        self._custom_background_catalog = background_catalog is not None
        self.backgrounds = background_catalog if background_catalog is not None else BackgroundCatalog(BACKGROUND_DIR)
        self._vts_base = None
        self._vts_base_scale = None
        self._display_scale = (1.0, 1.0)
        self._vts_action_pending = False
        self._last_render_key = None
        self._vts_images = {}
        self.background_index = 0
        self.capture_background = None
        self.composed_frame = None
        self.composed_sequence = -1
        self.last_recorded_sequence = -1
        self.last_composite_at = 0.0
        self.composite_source_sequence = -1
        self._composite_resource = None
        self.composite_error = "等待 VTS 虚拟摄像头画面" if self.vts_capture else None
        self.camera_frame = None
        self.avatar_frame = None
        self.avatar_status = "奶蛙画面等待连接" if avatar_feed else None
        self.vts_status = vts_api_error or ("正在启动 VTube Studio…" if vts_launcher else
                                            "VTS 未连接" if vts_controller else None)
        self.vts_api_connected = not vts_api_error and not vts_launcher
        self._vts_checking = False
        self._vts_next_check = 0.0
        self.vts_model_id = ""
        self.vts_model_name = ""
        self.vts_models = []
        self.vts_models_open = False
        self.vts_model_page = 0
        self.vts_model_message = ""
        self.vts_model_busy = False
        self.vts_model_loading = None
        self.vts_model_wait_frame = None
        self.vts_model_retry_count = 0
        self.vts_model_next_load = 0.0
        self.vts_model_error = None
        self._vts_generation = 0
        self.vts_hotkeys = []
        self.vts_hotkey_items = []
        self.port, self.show_styled = port, show_styled
        self.inference_lock = threading.Lock()
        self.preview_worker = (PreviewWorker(stylizer, self.inference_lock)
                               if camera is not None and show_styled and not self.vts_capture else None)
        self.raw_sequence = 0
        self.raw_captured_at = 0.0
        self.styled_captured_at = 0.0
        self.styled_inference_ms = 0.0
        self.styled_sequence = 0
        self._inference_error = None
        self.record_seconds, self.record_fps = record_seconds, record_fps
        self.share_ready = share_ready or (lambda: True)
        self.output_dir = Path(output_dir)
        self.qr_dir = self.output_dir / ".booth_qr"
        self.processor = processor or BoothProcessor(stylizer, output_dir,
                                                    stylizer_lock=self.inference_lock)
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

    def _request_vts_connection(self, retry=False):
        if not self.vts_controller or self._vts_connecting or self.vts_executor is None:
            return
        if retry:
            self._vts_startup_deadline = 0.0
        self._vts_connecting = True
        self.vts_api_connected = False
        self.composed_frame = None
        self._vts_next_check = time.monotonic() + VTS_RETRY_INTERVAL_SECONDS

        def connect():
            try:
                state = self.vts_controller.connect()
                if not state.get("connected"):
                    raise RuntimeError("请在 VTube Studio 设置中启用插件 API")
            except Exception as exc:
                detail = f"VTS API 未连接：{str(exc)[:70]}"
                if self.vts_launcher and not self.vts_launcher.launch_attempted:
                    launch_message = self.vts_launcher.ensure_started()
                    if self.vts_launcher.launch_attempted:
                        self._vts_startup_deadline = time.monotonic() + VTS_STARTUP_TIMEOUT_SECONDS
                    self.vts_status = launch_message
                if self._vts_startup_deadline:
                    if time.monotonic() < self._vts_startup_deadline:
                        self.vts_status = "等待 VTube Studio 启动及 API 授权…"
                    else:
                        self._vts_startup_deadline = 0.0
                        self.vts_status = detail + "；请检查 Steam、VTS 插件 API，再点重试连接"
                elif not self.vts_launcher or self.vts_launcher.launch_attempted:
                    self.vts_status = detail + "；请检查 VTS 插件 API 并重试"
                self.composite_error = self.vts_status
            else:
                self.vts_api_connected = True
                self._vts_startup_deadline = 0.0
                self.vts_status = "VTS 已连接，正在等待角色与虚拟摄像头画面"
                self._vts_next_check = 0.0
            finally:
                self._vts_connecting = False

        self.vts_executor.submit(connect)

    def _sync_background_catalog(self):
        """Use only the selected character's flat image directory."""
        if self._custom_background_catalog:
            return
        folder = next((name for name in ("奶蛙", "牛来") if name in (self.vts_model_name or "")), None)
        directory = BACKGROUND_DIR / folder if folder else BACKGROUND_DIR
        if self.backgrounds.user_dir == directory:
            return
        self.backgrounds = BackgroundCatalog(directory)
        self.background_index = 0
        self.composed_frame = None
        self.composed_sequence = -1
        self.composite_source_sequence = -1
        self._composite_resource = None

    def _open_vts_models(self):
        if self.state != "ready" or not self.vts_controller or not self.vts_api_connected or self.vts_model_loading:
            return
        self.vts_models_open = True
        self.composed_frame = None
        if not self.vts_models:
            self._refresh_vts_models()

    def _refresh_vts_models(self):
        if (not self.vts_controller or not self.vts_api_connected or self.vts_model_busy
                or self.vts_model_loading or self.vts_model_wait_frame is not None):
            return
        self.vts_model_busy = True
        self.composed_frame = None
        self.vts_model_message = "正在读取角色列表…"
        recovering = bool(self.vts_model_error)

        def refresh():
            try:
                models = self.vts_controller.models()
                if recovering:
                    status = self.vts_controller.status()
                    if not status.get("connected"):
                        raise RuntimeError("VTS API 未连接")
                    hotkeys = self.vts_controller.hotkeys()[:4] if status.get("model_loaded") else []
                self.vts_models = models
                self.vts_model_page = min(self.vts_model_page, max(0, (len(models) - 1) // 6))
                self.vts_model_message = "" if models else "VTube Studio 尚无可用角色"
                if recovering:
                    self.vts_model_id = status.get("model_id", "") if status.get("model_loaded") else ""
                    self.vts_model_name = status.get("model_name", "") if status.get("model_loaded") else ""
                    self._sync_background_catalog()
                    self.vts_api_connected = True
                    self.vts_hotkey_items = hotkeys
                    self.vts_hotkeys = [item.get("name") for item in hotkeys if item.get("name")]
                    self.vts_model_wait_frame = None
                    self.vts_model_error = None
                    self.composite_error = None
                    self.composite_source_sequence = -1
                    self.vts_status = (f"VTS 已连接 · {status.get('model_name') or '模型已加载'}"
                                       if status.get("model_loaded") else "VTS 已连接 · 尚未加载模型")
            except Exception as exc:
                self.vts_model_message = f"读取角色失败：{str(exc)[:70]}"
                if recovering:
                    self.vts_model_error = self.vts_model_message
                    self.composite_error = self.vts_model_message
            finally:
                self.vts_model_busy = False

        if self.vts_executor:
            self.vts_executor.submit(refresh)
        else:
            threading.Thread(target=refresh, name="vts-models", daemon=True).start()

    def _load_vts_model(self, model_id):
        if (self.state != "ready" or not self.vts_controller or self.vts_model_busy
                or self.vts_model_loading or self.vts_model_wait_frame is not None
                or self.vts_model_error or not model_id or model_id == self.vts_model_id
                or model_id not in {item["model_id"] for item in self.vts_models}):
            return
        remaining = self.vts_model_next_load - time.monotonic()
        if remaining > 0:
            self.vts_model_message = f"请等待 {remaining:.1f} 秒后切换角色"
            return
        self.vts_model_next_load = time.monotonic() + 2
        self._vts_generation += 1
        self._vts_next_check = time.monotonic() + 3
        self.vts_model_loading = model_id
        self.vts_model_error = None
        self.vts_model_message = "正在切换角色…"
        self.vts_model_wait_frame = None
        self.vts_hotkey_items = []
        self.vts_hotkeys = []
        self.composed_frame = None
        self.composite_source_sequence = -1
        self.composite_error = "正在切换角色，请等待新画面"
        old_sequence = self.avatar_feed.snapshot(max_age=VTS_FRAME_MAX_AGE) if self.avatar_feed else None
        old_sequence = old_sequence.sequence if old_sequence else self.composed_sequence

        def load():
            try:
                response = None
                for attempt in range(5):
                    try:
                        response = self.vts_controller.load_model(model_id)
                        break
                    except VTSAPIError as exc:
                        if str(exc.error_id) != "154" or attempt == 4:
                            raise
                        self.vts_model_message = f"VTS 正在切换角色，重试中…（{attempt + 1}/4）"
                        time.sleep(1.0)
                if response is None:
                    raise RuntimeError("VTS 未返回角色切换结果")
                if response.get("modelID") != model_id:
                    raise RuntimeError("VTS 加载响应的角色 ID 与所选角色不一致")
                deadline = time.monotonic() + 10
                while True:
                    status = self.vts_controller.status()
                    if not status.get("connected"):
                        raise RuntimeError("VTS API 已断开，角色未确认")
                    if status.get("model_loaded") and status.get("model_id") == model_id:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("VTS 未确认目标角色，请检查 VTS 是否仍显示旧角色")
                    time.sleep(min(0.25, remaining))
                hotkeys = self.vts_controller.hotkeys()[:4]
                confirmed_at = time.monotonic()
                self.vts_model_id = model_id
                self.vts_model_name = status.get("model_name", "")
                self._sync_background_catalog()
                self.vts_api_connected = True
                self.vts_status = f"VTS 已连接 · {status['model_name']}"
                self.vts_model_error = None
                self.vts_model_retry_count = 0
                self.vts_model_wait_frame = (old_sequence, confirmed_at)
                self.vts_model_message = "等待新角色画面…"
                self.composite_error = "正在等待新角色画面"
                self.vts_hotkey_items = hotkeys
                self.vts_hotkeys = [item.get("name") for item in hotkeys if item.get("name")]
                self.vts_models_open = False
            except Exception as exc:
                self.vts_model_error = f"角色切换失败：{str(exc)[:70]}"
                self.vts_model_message = self.vts_model_error
                self.composite_error = self.vts_model_error
                self.vts_model_wait_frame = None
                self._vts_next_check = 0
            finally:
                self.vts_model_loading = None

        if self.vts_executor:
            self.vts_executor.submit(load)
        else:
            threading.Thread(target=load, name="vts-model-load", daemon=True).start()

    def _trigger_vts_hotkey(self, hotkey):
        if self.vts_model_loading or self.vts_model_wait_frame is not None or self.vts_model_error:
            return
        try:
            self.vts_controller.trigger(hotkey)
        except Exception as exc:
            self.vts_status = f"VTS 热键触发失败：{str(exc)[:40]}"

    @staticmethod
    def _inside(x, y, rect):
        x0, y0, x1, y1 = rect
        return x0 <= x < x1 and y0 <= y < y1

    def _vts_buttons(self):
        """One source of geometry and labels for painting and pointer input."""
        buttons = [("exit", self.EXIT[1], "退出")]
        if self.vts_capture and not self.vts_models_open:
            buttons.append(("retry", self.VTS_LAYOUT["retry"], "重试连接"))
        if self.vts_controller and self.vts_api_connected and not self.vts_models_open:
            buttons.append(("models", self.VTS_LAYOUT["models"], "选择角色"))
        if self.state != "ready":
            return buttons
        if self.vts_controller and self.vts_api_connected:
            if self.vts_models_open:
                if not self.vts_model_loading:
                    buttons.append(("model_close", self.VTS_LAYOUT["model_close"], "返回"))
                if not self.vts_model_busy and not self.vts_model_loading:
                    buttons.append(("model_refresh", self.VTS_LAYOUT["model_refresh"], "刷新列表"))
                    start = self.vts_model_page * 6
                    if not self.vts_model_error:
                        for index, item in enumerate(self.vts_models[start:start + 6]):
                            if item["model_id"] != self.vts_model_id and self.vts_model_wait_frame is None:
                                buttons.append(("model:" + item["model_id"],
                                                (283, 186 + index * 55, 990, 233 + index * 55),
                                                item["model_name"]))
                    if self.vts_model_page:
                        buttons.append(("model_previous", self.VTS_LAYOUT["model_previous"], "上一页"))
                    if start + 6 < len(self.vts_models):
                        buttons.append(("model_next", self.VTS_LAYOUT["model_next"], "下一页"))
                return buttons
        if (self.vts_model_loading or self.vts_model_wait_frame is not None
                or self.vts_model_error or self.vts_models_open or self.vts_model_busy):
            return buttons
        buttons.extend([
            ("source_virtual", self.VTS_LAYOUT["source_virtual"], "虚拟角色"),
            ("source_camera", self.VTS_LAYOUT["source_camera"], "真人 HD"),
        ])
        if self.source == "camera":
            if self.camera_error:
                buttons.append(("camera_retry", self.VTS_LAYOUT["camera_retry"], "重试 HD 摄像头"))
            if (self.camera_frame is not None and self.camera_since is not None
                    and time.monotonic() - self.camera_since <= 2 and self._camera_processor is not None
                    and (not self.show_styled or self.preview_worker is not None)):
                buttons.extend([
                    ("photo", self.VTS_LAYOUT["photo"], "拍照  /  S"),
                    ("video", self.VTS_LAYOUT["video"], f"录像 {self.record_seconds:g} 秒  /  V"),
                ])
            return buttons
        buttons.extend([
            ("opacity_less", self.VTS_LAYOUT["opacity_less"], "－"),
            ("opacity_more", self.VTS_LAYOUT["opacity_more"], "＋"),
        ])
        if self.camera_error:
            buttons.append(("camera_retry", self.VTS_LAYOUT["camera_retry"], "重试 HD 摄像头"))
        if self.backgrounds.items:
            buttons.append(("random_background", self.VTS_LAYOUT["random_background"], "随机背景"))
        if self.composed_frame is not None and self.composed_frame.size and self.vts_api_connected:
            buttons.extend([
                ("photo", self.VTS_LAYOUT["photo"], "拍照  /  S"),
                ("video", self.VTS_LAYOUT["video"], f"录像 {self.record_seconds:g} 秒  /  V"),
            ])
        if self.vts_controller and self.vts_api_connected:
            x0, y0, x1, y1 = self.VTS_LAYOUT["hotkeys"]
            width = (x1 - x0 - 3 * 8) // 4
            for index, item in enumerate(self.vts_hotkey_items[:4]):
                if item.get("hotkeyID"):
                    left = x0 + index * (width + 8)
                    buttons.append(("hotkey:" + item["hotkeyID"],
                                    (left, y0, left + width, y1),
                                    item.get("name") or "动作"))
        return buttons

    def _mouse(self, event, x, y, flags, _param):
        if event != cv2.EVENT_LBUTTONUP:
            return
        sx, sy = self._display_scale
        x, y = round(x / sx), round(y / sy)
        if self.vts_capture:
            for action, rect, _label in self._vts_buttons():
                if not self._inside(x, y, rect):
                    continue
                if action == "exit":
                    self.state = "exit"
                elif action == "retry":
                    self._request_vts_connection(retry=True)
                elif action == "source_virtual":
                    self._select_source("vts")
                elif action == "source_camera":
                    self._select_source("camera")
                elif action == "camera_retry":
                    self._request_camera(retry=True)
                elif action == "opacity_less":
                    self._set_opacity(-1)
                elif action == "opacity_more":
                    self._set_opacity(1)
                elif action == "models":
                    self._open_vts_models()
                elif action == "random_background":
                    self._randomize_background()
                elif action == "model_close":
                    self.vts_models_open = False
                elif action == "model_refresh":
                    self._refresh_vts_models()
                elif action == "model_previous":
                    self.vts_model_page -= 1
                elif action == "model_next":
                    self.vts_model_page += 1
                elif action.startswith("model:"):
                    self._load_vts_model(action[6:])
                elif action in ("photo", "video"):
                    self._begin(action)
                elif action.startswith("hotkey:"):
                    if self.vts_executor:
                        self.vts_executor.submit(self._trigger_vts_hotkey, action[7:])
                return
            if (self.state in ("result", "error") and
                    not self._inside(x, y, self.VTS_LAYOUT["models"]) and
                    not self._inside(x, y, self.VTS_LAYOUT["retry"])):
                self._reset()
            return
        action = self.hit_test(x, y)
        hotkeys = self.VTS_LAYOUT["hotkeys"]
        if self.vts_controller and self._inside(x, y, hotkeys):
            index = (x - hotkeys[0]) // 88
            if index < len(self.vts_hotkey_items):
                hotkey_id = self.vts_hotkey_items[index].get("hotkeyID")
                if hotkey_id and self.vts_executor:
                    self.vts_executor.submit(self._trigger_vts_hotkey, hotkey_id)
            return
        if action == "photo":
            self._begin("photo")
        elif action == "video":
            self._begin("video")
        elif action == "exit":
            self.state = "exit"

    def _reset(self):
        self.state = "ready"
        if self.preview_worker:
            self.preview_worker.set_enabled(not self.vts_capture or self.source == "camera")
        self.status = "站到画面中央，然后选择拍照或录像"
        self.result_path, self.qr_path = None, None
        self._vts_images.clear()
        self.current, self.recording = None, None
        self.capture_background = None
        self.capture_source = None
        if self.vts_capture:
            self._update_vts_preview()
        self.last_recorded_sequence = -1
        self.progress = (0, 0)
        self.error = None

    def _choose_background(self, index):
        if (not self.vts_capture or self.source != "vts" or self.state != "ready" or self.vts_models_open
                or self.vts_model_loading or self.vts_model_busy
                or self.vts_model_wait_frame is not None or self.vts_model_error):
            return
        items = self.backgrounds.items
        if not 0 <= index < len(items):
            return
        self.background_index = index
        self.composed_frame = None
        self.composed_sequence = -1
        self.composite_source_sequence = -1
        self._composite_resource = None
        self._update_vts_preview()

    def _randomize_background(self):
        if (not self.vts_capture or self.source != "vts" or self.state != "ready"
                or self.vts_models_open or self.vts_model_loading or self.vts_model_busy
                or self.vts_model_wait_frame is not None or self.vts_model_error):
            return
        items = self.backgrounds.items
        if not items:
            self.composite_error = "没有可用背景"
            return
        if len(items) == 1:
            self.status = "当前只有一张背景"
            return
        current = self.background_index % len(items)
        index = random.randrange(len(items) - 1)
        self._choose_background(index + (index >= current))

    def _begin(self, kind):
        if self.state != "ready" or (self.vts_capture and (
                self.vts_models_open or (self.source == "vts" and (
                    self.vts_model_busy or self.vts_model_loading
                    or self.vts_model_wait_frame is not None or self.vts_model_error)))):
            return
        if self.vts_capture and self.source == "vts":
            self._update_vts_preview()
            if self.composed_frame is None or not self.vts_api_connected:
                self.status = self.composite_error or self.vts_status or "VTS 画面未就绪"
                return
            items = self.backgrounds.items
            if not items:
                self.status = "没有可用背景"
                return
            self.capture_background = items[self.background_index]
            self.capture_opacity = self._effective_opacity()
            self.last_recorded_sequence = self.composed_sequence
            self.composite_source_sequence = -1
        elif self.vts_capture:
            if self.camera_frame is None or self.camera_since is None or time.monotonic() - self.camera_since > 2:
                self.status = self.camera_error or "等待 HD 摄像头画面"
                return
            if self._camera_processor is None or (self.show_styled and self.preview_worker is None):
                self.status = self._camera_style_error or "正在初始化动漫引擎…"
                return
            self.last_recorded_sequence = self.camera_sequence
        elif self.last_frame is None:
            return
        self.capture_source = self.source
        self.current = kind
        self.state = "countdown"
        if self.preview_worker:
            self.preview_worker.set_enabled(False)
        self.deadline = time.monotonic() + 3
        self.status = "准备好！"

    def _poll_future(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            self.result_path = future.result()
            self._vts_images.clear()
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

        if self.vts_capture and self.capture_source == "vts":
            self.future = self.executor.submit(self.processor.process, kind, payload, progress, composed=True)
        elif self.vts_capture and self.capture_source == "camera":
            self.future = self.executor.submit(self._camera_processor.process, kind, payload, progress)
        else:
            self.future = self.executor.submit(self.processor.process, kind, payload, progress)

    def _vts_video_inset(self, frame, now):
        """Add the live HD view to a recorded VTS frame without changing the preview."""
        canvas = frame.copy()
        height, width = canvas.shape[:2]
        margin = max(4, round(width * .025))
        inset_width = min(round(width * .28), width - 2 * margin)
        label_height = max(14, round(height * .04))
        inset_height = min(round(inset_width * 9 / 16), height - 2 * margin - label_height)
        x0, y0 = width - margin - inset_width, margin
        x1, y1 = x0 + inset_width, y0 + label_height + inset_height
        cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (28, 25, 22), -1)
        cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (245, 245, 245), max(1, round(width / 640)))
        self._vts_text(canvas, "真人 HD", (x0 + 4, y0, x1 - 4, y0 + label_height),
                       max(12, round(label_height * .7)), (245, 245, 245))
        live = (self.camera_frame is not None and self.camera_since is not None
                and 0 <= now - self.camera_since <= 2)
        picture = (x0 + 3, y0 + label_height + 2, x1 - 3, y1 - 3)
        if not live or not self._vts_fit(canvas, self.camera_frame, picture):
            self._vts_text(canvas, "HD 未连接", picture,
                           max(12, round(label_height * .7)), (245, 245, 245), True)
        return canvas

    def _record_vts_frame(self, now):
        frame = (self.composed_frame if self.composed_sequence != self.last_recorded_sequence
                 else None)
        self._handle_recording(now, self._vts_video_inset(frame, now) if frame is not None else None)

    def _handle_recording(self, now, frame):
        if self.recording is None:
            return
        self.recording.add(now, frame) if frame is not None else None
        if self.vts_capture and self.capture_source == "vts":
            self.last_recorded_sequence = self.composed_sequence
        elif self.vts_capture and self.capture_source == "camera":
            self.last_recorded_sequence = self.camera_sequence
        elapsed = now - self.recording.started
        self.status = f"正在录像 {min(elapsed, self.record_seconds):.1f} / {self.record_seconds:.0f} 秒"
        if self.recording.finished(now):
            recording, self.recording = self.recording, None
            self._publish("video", RecordingSource(recording))

    def _request_camera(self, retry=False):
        if not self._camera_executor or self._camera_closed or self.camera is not None or self._camera_future:
            return
        if self.camera_error and not retry:
            return
        self.camera_error = None
        self._camera_future = self._camera_executor.submit(self.camera_opener)

    def _poll_camera(self, now):
        if self._camera_future and self._camera_future.done():
            future, self._camera_future = self._camera_future, None
            try:
                camera = future.result()
            except Exception as exc:
                self.camera_error = f"HD 摄像头不可用：{str(exc)[:60]}；虚拟拍摄仍可使用场景背景"
            else:
                if self._camera_closed:
                    camera.stop()
                else:
                    self.camera = camera
                    self.camera_frame = None
                    self.camera_since = now
                    self.camera_error = None
        if (self.vts_capture and self.camera is not None and self.camera_since is not None
                and now - self.camera_since > 2):
            self.camera.stop()
            self.camera = None
            self.camera_frame = None
            self.camera_error = "HD 摄像头画面中断；虚拟拍摄仍可使用场景背景"
            self.last_frame = self.last_styled = None
            self._composite_resource = None

    def _effective_opacity(self):
        return (self.capture_opacity if self.state in ("countdown", "recording")
                and self.capture_source == "vts" else self.background_opacity)

    def _set_opacity(self, direction):
        if self.state != "ready" or self.source != "vts" or self.vts_models_open:
            return
        self.background_opacity = min(1.0, max(0.0, round(self.background_opacity * 10 + direction) / 10))
        self._composite_resource = None

    def _start_camera_style(self):
        if not self.camera_stylizer or self._camera_style_future or self._camera_processor:
            return
        self._camera_style_error = None
        self._camera_style_future = self._camera_style_executor.submit(self.camera_stylizer)

    def _poll_camera_style(self):
        if not self._camera_style_future or not self._camera_style_future.done():
            return
        future, self._camera_style_future = self._camera_style_future, None
        try:
            stylizer = future.result()
            self._camera_processor = BoothProcessor(stylizer, self.output_dir,
                                                     stylizer_lock=self.inference_lock)
            if self.show_styled:
                self.preview_worker = PreviewWorker(stylizer, self.inference_lock).start()
                self.preview_worker.set_enabled(self.source == "camera")
        except Exception as exc:
            self._camera_style_error = f"动漫引擎初始化失败：{str(exc)[:65]}"

    def _select_source(self, source):
        if not self.vts_capture or self.state != "ready" or self.vts_models_open:
            return
        if source == "camera":
            self._request_camera(retry=True)
            self._start_camera_style()
        if source != self.source:
            self.source = source
            self.last_frame = self.last_styled = None
            self.styled_sequence = 0
            if self.preview_worker:
                self.preview_worker.set_enabled(source == "camera")

    def _frame(self):
        if self.camera is None:
            return False
        snapshot = self.camera.snapshot(only_new=True) if hasattr(self.camera, "snapshot") else None
        raw = snapshot.frame if snapshot is not None else (
            None if hasattr(self.camera, "snapshot") else self.camera.read(only_new=True))
        if raw is not None:
            captured_at = snapshot.timestamp if snapshot is not None else time.monotonic()
            self.camera_since = time.monotonic()
            self.camera_frame = mirror(raw)
            if self.vts_capture:
                self.camera_sequence = snapshot.sequence if snapshot is not None else self.camera_sequence + 1
                self.camera_captured_at = captured_at
                if self.source == "vts":
                    return True
            self.last_frame = self.camera_frame
            self.raw_sequence = snapshot.sequence if snapshot is not None else self.raw_sequence + 1
            self.raw_captured_at = captured_at
            if self.preview_worker and self.state == "ready":
                self.preview_worker.submit(self.last_frame, captured_at)
            elif not self.show_styled:
                self.last_styled = self.last_frame
        if self.preview_worker:
            result, error = self.preview_worker.snapshot()
            self._inference_error = error
            if result is not None and result.sequence > self.styled_sequence:
                self.last_styled = result.frame
                self.styled_sequence = result.sequence
                self.styled_captured_at = result.captured_at
                self.styled_inference_ms = result.inference_ms
        return raw is not None

    @staticmethod
    def _vts_text(canvas, text, rect, size, color, center=False):
        """Overlay cached glyph coverage on the current BGR pixels."""
        x0, y0, x1, y1 = rect
        mask = _vts_text_mask(str(text), x1 - x0, y1 - y0, size, center)
        roi = canvas[y0:y1, x0:x1]
        tint = Image.new("RGB", mask.size, (color[2], color[1], color[0]))
        image = Image.composite(tint, Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)), mask)
        roi[:] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _vts_fit(canvas, image, rect, interpolation=cv2.INTER_AREA):
        """Contain the entire image, centered; never crop or mutate the source."""
        if image is None or not image.size or image.ndim != 3:
            return False
        x0, y0, x1, y1 = rect
        height, width = image.shape[:2]
        scale = min((x1 - x0) / width, (y1 - y0) / height)
        w, h = max(1, int(width * scale)), max(1, int(height * scale))
        left, top = x0 + (x1 - x0 - w) // 2, y0 + (y1 - y0 - h) // 2
        chosen_interpolation = (cv2.INTER_LINEAR if scale > 1 and interpolation == cv2.INTER_AREA
                                else interpolation)
        canvas[top:top + h, left:left + w] = cv2.resize(image, (w, h),
                                                         interpolation=chosen_interpolation)
        return True

    def _vts_base_canvas(self):
        scale = self._display_scale
        if self._vts_base is None or self._vts_base_scale != scale:
            colors = self.VTS_COLORS
            sx, sy = scale
            base = np.full((round(self.HEIGHT * sy), round(self.WIDTH * sx), 3),
                           colors["background"], np.uint8)
            def rect(values):
                return scaled_rect(values, scale)
            def box(values, color, thickness=-1):
                x0, y0, x1, y1 = rect(values)
                cv2.rectangle(base, (x0, y0), (x1, y1), color, thickness)
            box((0, 0, self.WIDTH, 72), colors["panel"])
            cv2.line(base, rect((28, 70, 1252, 70))[:2],
                     rect((28, 70, 1252, 70))[2:], colors["line"], max(1, round(min(scale))))
            box((28, 20, 32, 54), colors["cyan"])
            self._vts_text(base, "奶蛙的虚拟照相馆", rect((42, 16, 420, 54)),
                           round(28 * min(scale)), colors["text"])
            for panel in (self.VTS_LAYOUT["preview"], self.VTS_LAYOUT["scene"]):
                x0, y0, x1, y1 = rect(panel)
                base[y0:y1, x0:x1] = colors["panel"]
                cv2.rectangle(base, (x0, y0), (x1 - 1, y1 - 1), colors["line"],
                              max(1, round(min(scale))))
            self._vts_base = base
            self._vts_base_scale = scale
        return self._vts_base.copy()

    def _vts_image(self, path):
        """Cache only decoded images; retry failed reads and detect replaced files."""
        try:
            stat = path.stat()
        except FileNotFoundError:
            return read_image(path)
        version = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        if version not in self._vts_images:
            image = read_image(path)
            if len(self._vts_images) >= 4:
                self._vts_images.pop(next(iter(self._vts_images)))
            self._vts_images[version] = image
        return self._vts_images[version]

    def _compose_vts(self, frame):
        colors, layout = self.VTS_COLORS, self.VTS_LAYOUT
        canvas = self._vts_base_canvas()
        scale = self._display_scale
        def scaled(values):
            return scaled_rect(values, scale)
        def point(x, y):
            return round(x * scale[0]), round(y * scale[1])
        def stroke(thickness=1):
            return max(1, round(thickness * min(scale)))
        def box(values, color, thickness=-1):
            x0, y0, x1, y1 = scaled(values)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), colors[color],
                          stroke(thickness) if thickness > 0 else thickness)
        def fit(image, area, interpolation=cv2.INTER_AREA):
            return self._vts_fit(canvas, image, scaled(area), interpolation)

        def panel(area, color="panel", outline="line"):
            x0, y0, x1, y1 = scaled(area)
            canvas[y0:y1, x0:x1] = colors[color]
            cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), colors[outline], stroke())

        def text(value, area, size=20, color="text", center=False):
            self._vts_text(canvas, value, scaled(area), round(size * min(scale)),
                           colors[color], center)

        # Fixed title and panels already exist in the copied base.
        status = {"ready": "画面就绪" if self.composed_frame is not None else "等待虚拟画面",
                  "countdown": "准备拍摄", "recording": "正在录像", "processing": "正在生成作品",
                  "result": "作品已完成", "error": "本次拍摄未完成"}.get(self.state, "")
        status_color = "red" if self.state == "error" else "green"
        panel((538, 16, 800, 58), "panel_alt")
        x0, y0 = point(559, 37)
        cv2.circle(canvas, (x0, y0), stroke(5), colors[status_color], -1)
        text(status, (577, 23, 790, 53), 19, status_color)
        text(self.vts_status or "VTS 虚拟摄像头 · 角色合成预览", (32, 74, 815, 100), 16, "muted")
        result = self.state in ("result", "error")
        if result:
            if self.state == "result":
                displayed = False
                if self.result_path and self.result_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    try:
                        displayed = fit(self._vts_image(self.result_path), layout["preview"])
                    except (OSError, ValueError, cv2.error):
                        pass
                if not displayed:
                    video = self.result_path and self.result_path.suffix.lower() == ".mp4"
                    text("视频已保存" if video else "作品预览不可用",
                         (80, 275, 776, 325), 32, center=True)
                    text("扫码下载后播放" if video else "可从本机作品目录查看",
                         (80, 337, 776, 375), 21, "muted", True)
            else:
                text("拍摄未完成", (65, 165, 790, 215), 32, "red")
                text(self.error or self.status, (65, 240, 790, 470), 24)
                text("检查虚拟摄像头和背景后再试一次", (65, 510, 790, 555), 21, "muted")
            text("扫码领取作品" if self.state == "result" else "分享不可用",
                 (875, 127, 1225, 170), 26)
            qr_ok = False
            if self.state == "result" and self.qr_path:
                try:
                    qr = self._vts_image(self.qr_path)
                    panel((944, 190, 1154, 400), "text")
                    qr_ok = fit(qr, (954, 200, 1144, 390), cv2.INTER_NEAREST)
                except (OSError, ValueError, cv2.error):
                    pass
            if qr_ok:
                text("手机与本机连接同一网络", (875, 423, 1225, 467), 20, "muted", True)
            else:
                text("二维码暂不可用" if self.state == "result" else "未生成可分享作品",
                     (875, 245, 1225, 325), 23, "muted", True)
                text("作品已保存在本机" if self.state == "result" else "返回后重新拍摄",
                     (875, 345, 1225, 420), 20, "muted", True)
            if self.result_path and self.state == "result":
                text(self.result_path.name, (875, 480, 1225, 552), 18, "muted")
            text(self.status, (32, 616, 1248, 670), 20)
            text("点击屏幕或按空格返回   /   Esc 退出", (32, 681, 1248, 710), 17, "muted")
        else:
            # Only a valid composed VTS frame can be displayed, never a camera fallback.
            panel(layout["preview"], "panel")
            panel(layout["scene"], "panel")
            available = (self.composed_frame is not None and self.composed_frame.size > 0
                         and self.vts_api_connected)
            if self.source == "camera":
                available = (self.camera_frame is not None and self.camera_since is not None
                             and time.monotonic() - self.camera_since <= 2
                             and self._camera_processor is not None
                             and (not self.show_styled or self.preview_worker is not None))
                camera_preview = (self.last_styled if self.show_styled and self.last_styled is not None
                                  else self.camera_frame if not self.show_styled else None)
                if not fit(camera_preview, layout["preview"]):
                    text("等待 HD 摄像头画面", (75, 268, 780, 320), 30, center=True)
                elif self.camera_frame is not None:
                    fit(self.camera_frame, (586, 407, 800, 559))
                    text("真人原画", (589, 530, 796, 560), 17)
                message = self.camera_error or self._camera_style_error or (
                    "正在初始化动漫引擎…" if self._camera_style_future else None)
                if message:
                    text(message, (70, 325, 780, 399), 19, "muted", True)
            elif not available or not fit(frame, layout["preview"]):
                text("等待虚拟角色画面", (75, 268, 780, 320), 30, center=True)
                message = (self.vts_status if self.vts_controller and not self.vts_api_connected
                           else self.composite_error)
                text(message or "请开启 VTS 虚拟摄像头与绿幕背景",
                     (75, 342, 780, 435), 21, "muted", True)
            if self.source == "vts":
                text("HD 摄像头预览", (875, 123, 1228, 165), 26)
                if not fit(self.camera_frame, (874, 179, 1224, 393)):
                    text("等待 HD 摄像头画面", (875, 245, 1225, 335), 20, "muted", True)
                if self.camera_error:
                    text(self.camera_error, (875, 310, 1225, 393), 16, "muted", True)
                box((875, 508, 913, 530), "scene_base")
                box((875, 508, 913, 530), "line", 1)
                text(f"背景不透明度 {round(self.background_opacity * 100)}% · 纯色底板",
                     (920, 502, 1228, 533), 16, "muted", True)
            else:
                text("真人 HD · 动漫主画面", (870, 540, 1230, 577), 18, "muted", True)
            if self.state == "ready":
                if not available:
                    for action, label in (("photo", "拍照 / 等待画面"), ("video", "录像 / 等待画面")):
                        panel(layout[action], "panel_alt")
                        text(label, layout[action], 22, "muted", True)
                if not any(action.startswith("hotkey:") for action, _, _ in self._vts_buttons()) and self.source == "vts":
                    text("角色动作尚未就绪", layout["hotkeys"], 20, "muted", True)
                text((self.camera_error or self._camera_style_error or self.status) if self.source == "camera"
                     else (self.composite_error or self.status),
                     (32, 694, 1248, 720), 16, "muted")
            else:
                text("拍摄期间场景和动作已锁定", (870, 500, 1230, 554), 19, "muted", True)
                if self.state == "countdown":
                    panel((338, 249, 518, 436), "panel_alt")
                    text(str(max(1, math.ceil(self.deadline - time.monotonic()))),
                         (338, 253, 518, 389), 96, center=True)
                    text("准备拍摄", (340, 390, 516, 428), 22, center=True)
                    text("保持姿势，马上开始", (74, 635, 800, 682), 26)
                elif self.state == "recording":
                    cv2.circle(canvas, point(88, 652), stroke(9), colors["red"], -1)
                    text(self.status, (115, 630, 810, 681), 26, "red")
                elif self.state == "processing":
                    text(self.status, (74, 617, 810, 655), 24)
                    done, total = self.progress
                    text(f"{done} / {total}" if total else "请稍候，正在保存作品",
                         (850, 630, 1248, 673), 20, "muted")
                    panel((74, 672, 810, 682), "panel_alt")
                    if total > 0:
                        right = 74 + int(736 * max(0, min(1, done / total)))
                        if right > 74:
                            panel((74, 672, right, 682), "violet")
        if self.vts_models_open and self.state == "ready":
            panel(layout["model_dialog"], "panel", "violet")
            cv2.line(canvas, point(275, 178), point(1005, 178), colors["line"], stroke())
            text("选择 VTube Studio 角色", (275, 125, 645, 173), 29)
            start = self.vts_model_page * 6
            for index, item in enumerate(self.vts_models[start:start + 6]):
                rect = (283, 186 + index * 55, 990, 233 + index * 55)
                active = item["model_id"] == self.vts_model_id
                panel(rect, "green" if active else "panel_alt")
                label = item["model_name"] + ("  ·  当前使用" if active else "")
                text(label, rect, 20, "background" if active else "text", True)
            count = len(self.vts_models)
            text(f"第 {self.vts_model_page + 1} / {max(1, (count + 5) // 6)} 页 · 共 {count} 个角色",
                 (530, 535, 755, 580), 16, "muted", True)
            text(self.vts_model_message or "选择角色，切换时暂停拍摄",
                 (285, 585, 985, 609), 16, "muted", True)
        for action, rect, label in self._vts_buttons():
            color = "cyan" if action == "photo" else "violet" if action == "video" else "panel_alt"
            if (action == "source_virtual" and self.source == "vts"
                    or action == "source_camera" and self.source == "camera"):
                color = "green"
            panel(rect, color, color if color in ("cyan", "violet", "green") else "line")
            x0, y0, x1, y1 = rect
            if action in ("photo", "video"):
                cv2.line(canvas, point(x0 + 14, y0 + 9), point(x1 - 14, y0 + 9),
                         colors["text"], stroke())
            text(label, (x0 + 8, y0 + 4, x1 - 8, y1 - 4),
                 23 if action in ("photo", "video") else 18,
                 "background" if action in ("photo", "video") else "text", True)
        return canvas

    def _compose(self, frame):
        if self.vts_capture:
            return self._compose_vts(frame)
        return compose_camera(self, frame)

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

    def _update_composite(self):
        if not self.avatar_feed:
            self.composed_frame = None
            self.composite_error = "VTS 虚拟摄像头未就绪"
            return
        if self.vts_controller and not self.vts_api_connected:
            self.composed_frame = None
            self.composite_error = self.vts_status or "VTS API 未连接"
            return
        if (self.vts_model_loading or self.vts_model_wait_frame is not None
                or self.vts_model_error or self.vts_models_open or self.vts_model_busy):
            return
        snapshot = self.avatar_feed.snapshot(max_age=VTS_FRAME_MAX_AGE)
        if snapshot is None:
            self.composed_frame = None
            self.composite_error = getattr(self.avatar_feed, "error", None) or "VTS 画面过期，请确认虚拟摄像头"
            return
        items = self.backgrounds.items
        if not items:
            self.composed_frame = None
            self.composite_error = "没有可用背景"
            return
        name = self.capture_background or items[self.background_index % len(items)]
        try:
            version = (name, self.backgrounds.resource_version(name)) if hasattr(
                self.backgrounds, "resource_version") else (name, None)
            effective_opacity = self._effective_opacity()
            key = (version, effective_opacity, self._vts_generation)
            if (self.composed_frame is not None and snapshot.sequence == self.composite_source_sequence
                    and key == self._composite_resource):
                return
            height, width = snapshot.frame.shape[:2]
            background = self.backgrounds.get(name, (width, height))
            if effective_opacity < 1:
                base = np.full_like(background, self.VTS_COLORS["scene_base"])
                scene = blend_scene(base, background, effective_opacity)
            else:
                scene = background
            composed, _diagnostics = compose_avatar(snapshot.frame, scene)
        except ChromaRejected:
            self.composed_frame = None
            self.composite_error = "绿幕或角色区域异常，请检查 VTS 纯色背景"
            return
        except (ValueError, OSError, cv2.error) as exc:
            self.composed_frame = None
            self.composite_error = f"背景合成失败：{str(exc)[:60]}"
            return
        self.composed_frame = composed
        self.composed_sequence = snapshot.sequence
        self.composite_source_sequence = snapshot.sequence
        self._composite_resource = key
        self.last_composite_at = snapshot.timestamp
        self.composite_error = None

    def _update_vts_preview(self):
        if not self.vts_capture and self.avatar_feed is None and self.vts_controller is None:
            return
        if self.vts_model_wait_frame is not None and self.avatar_feed:
            snapshot = self.avatar_feed.snapshot(max_age=VTS_FRAME_MAX_AGE)
            sequence, started_at = self.vts_model_wait_frame
            if (not self.vts_model_error and snapshot and snapshot.sequence > sequence
                    and snapshot.timestamp > started_at):
                self.vts_model_wait_frame = None
                self.vts_model_error = None
                self.vts_model_message = ""
                self.composite_source_sequence = -1
                self.composite_error = None
            elif time.monotonic() - started_at > 12 and not self.vts_model_error:
                self.vts_model_error = "新角色画面未就绪，请检查 VTS 虚拟摄像头"
                self.vts_model_message = self.vts_model_error
                self.composite_error = self.vts_model_error
                self.composed_frame = None
        if self.avatar_feed:
            if self.vts_capture:
                self._update_composite()
            else:
                frame = self.avatar_feed.read()
                if frame is not None:
                    self.avatar_frame = frame
                    self.avatar_status = None
                elif getattr(self.avatar_feed, "error", None):
                    self.avatar_status = self.avatar_feed.error
        if (self.vts_capture and self.vts_controller and not self.vts_api_connected
                and not self._vts_connecting and time.monotonic() >= self._vts_next_check):
            self._request_vts_connection()
        if (self.vts_controller and self.vts_api_connected and not self._vts_connecting
                and not self._vts_checking and not self.vts_model_loading
                and self.vts_model_wait_frame is None and not self.vts_model_error
                and not self.vts_model_busy and time.monotonic() >= self._vts_next_check):
            self._vts_checking = True
            self._vts_next_check = time.monotonic() + VTS_RETRY_INTERVAL_SECONDS
            generation = self._vts_generation

            def check_status():
                hotkeys = []
                labels = []
                text = "VTS API 不可用"
                api_connected = False
                model_loaded = False
                status = {}
                try:
                    status = self.vts_controller.status()
                    api_connected = bool(status.get("connected"))
                    model_loaded = bool(status.get("model_loaded"))
                    if api_connected and model_loaded:
                        model_name = status.get("model_name") or "模型已加载"
                        text = f"VTS 已连接 · {model_name}"
                        hotkeys = self.vts_controller.hotkeys()
                        labels = [item.get("name") for item in hotkeys if item.get("name")]
                    elif api_connected:
                        text = "VTS 已连接 · 尚未加载模型（点击切换角色）"
                    else:
                        text = "VTS API 未连接"
                except Exception as exc:
                    text = f"VTS API 不可用：{str(exc)[:48]}"
                finally:
                    if not self.vts_model_loading and generation == self._vts_generation:
                        self.vts_status = text
                        self.vts_api_connected = api_connected
                        if not api_connected:
                            self._vts_next_check = 0.0
                            self.vts_models_open = False
                            self.composed_frame = None
                            self.composite_error = text
                        self.vts_model_id = status.get("model_id", "") if model_loaded else ""
                        if self.vts_capture:
                            self.vts_model_name = status.get("model_name", "") if model_loaded else ""
                            self._sync_background_catalog()
                        self.vts_hotkey_items = hotkeys[:4] if model_loaded else []
                        self.vts_hotkeys = labels[:4]
                    self._vts_checking = False

            if self.vts_executor:
                self.vts_executor.submit(check_status)
            else:
                threading.Thread(target=check_status, name="vts-status", daemon=True).start()

    def run(self):
        try:
            import ctypes
            import sys
            if sys.platform == "win32":
                user32 = ctypes.windll.user32
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except (AttributeError, OSError):
                    user32.SetProcessDPIAware()
                width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
                if width > 0 and height > 0:
                    self._display_scale = (width / self.WIDTH, height / self.HEIGHT)
        except (AttributeError, OSError):
            pass
        cv2.namedWindow("Naiwa - PhotoBooth", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("Naiwa - PhotoBooth", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        cv2.setMouseCallback("Naiwa - PhotoBooth", self._mouse)
        if self.vts_capture:
            self._request_camera()
        if self.preview_worker:
            self.preview_worker.start()
        try:
            while self.state != "exit":
                fresh = self._frame()
                now = time.monotonic()
                if self.vts_capture:
                    self._poll_camera_style()
                    self._poll_camera(now)
                self._update_vts_preview()
                if self.vts_capture:
                    self._poll_future()
                    if self.capture_source == "camera" and self.state in ("countdown", "recording"):
                        if (self.camera is None or self.camera_frame is None or self.camera_since is None
                                or now - self.camera_since > 2):
                            self.recording = None
                            self.state = "error"
                            self.status = self.camera_error or "HD 摄像头画面中断，本次拍摄已取消"
                            self.status_until = now + 8
                        elif self.state == "countdown" and now >= self.deadline:
                            if self.camera_sequence <= self.last_recorded_sequence:
                                self.status = "等待 HD 摄像头新画面"
                            elif self.current == "photo":
                                self.last_recorded_sequence = self.camera_sequence
                                self._publish("photo", self.camera_frame.copy())
                            else:
                                self.recording = Recording(now, self.record_seconds, self.record_fps)
                                self.last_recorded_sequence = self.camera_sequence
                                self.state = "recording"
                        if self.recording is not None:
                            fresh_camera = self.camera_frame if self.camera_sequence != self.last_recorded_sequence else None
                            self._handle_recording(now, fresh_camera)
                    elif self.capture_source == "vts":
                        if self.state in ("countdown", "recording") and (
                                self.composed_frame is None or not self.vts_api_connected):
                            self.recording = None
                            self.state = "error"
                            self.status = self.composite_error or "VTS 画面中断，本次拍摄已取消"
                            self.status_until = now + 8
                        elif self.state == "countdown" and now >= self.deadline:
                            if self.composed_sequence <= self.last_recorded_sequence:
                                self.status = "等待 VTS 新画面"
                            elif self.current == "photo":
                                self.last_recorded_sequence = self.composed_sequence
                                self._publish("photo", self.composed_frame.copy())
                            else:
                                self.recording = Recording(now, self.record_seconds, self.record_fps)
                                self.last_recorded_sequence = self.composed_sequence
                                self.state = "recording"
                        if self.recording is not None:
                            self._record_vts_frame(now)
                    display = self.composed_frame
                    if self.source == "camera":
                        display = (self.last_styled if self.show_styled and self.last_styled is not None
                                   else self.camera_frame if not self.show_styled else None)
                    if display is None:
                        items = self.backgrounds.items
                        name = self.capture_background or (items[self.background_index % len(items)] if items else None)
                        try:
                            display = self.backgrounds.get(name, (self.WIDTH, self.HEIGHT))
                        except (ValueError, OSError):
                            display = np.full((self.HEIGHT, self.WIDTH, 3), (32, 28, 38), np.uint8)
                    cv2.imshow("Naiwa - PhotoBooth", self._compose(display))
                else:
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
                        display = (self.last_styled if self.show_styled and self.last_styled is not None
                                   and self.state in ("ready", "countdown", "recording")
                                   else self.last_frame)
                        cv2.imshow("Naiwa - PhotoBooth", self._compose(display))
                    else:
                        preview = self.last_styled if self.show_styled and self.last_styled is not None else self.last_frame
                        if preview is not None:
                            cv2.imshow("Naiwa - PhotoBooth", self._compose(preview))
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
            self._camera_closed = True
            if self.camera:
                self.camera.stop()
                self.camera = None
            if self._camera_executor:
                self._camera_executor.shutdown(wait=True, cancel_futures=True)
                if self._camera_future and self._camera_future.done():
                    try:
                        camera = self._camera_future.result()
                        if camera is not None:
                            camera.stop()
                    except Exception:
                        pass
            if self._camera_style_executor:
                self._camera_style_executor.shutdown(wait=True, cancel_futures=True)
            if self.preview_worker:
                self.preview_worker.close()
            self.executor.shutdown(wait=True, cancel_futures=True)
            if self.vts_executor:
                self.vts_executor.shutdown(wait=True, cancel_futures=True)
            if self.avatar_feed:
                self.avatar_feed.close()
            if self.vts_controller:
                self.vts_controller.close()
            cv2.destroyAllWindows()


class RecordingSource:
    def __init__(self, recording):
        self.recording, self.fps = recording, recording.fps

    def frames(self):
        return self.recording.frames()
