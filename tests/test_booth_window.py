"""Real-time touch UI tests using a fake camera and deterministic helpers."""
import unittest
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app.ui.booth_window import BoothWindow
from app.core.booth import Recording
from app.core.chroma import BackgroundCatalog


class FakeCamera:
    def __init__(self, frame):
        self.frame = frame

    def read(self, only_new=False):
        return self.frame.copy()


class FakeProcessor:
    def process(self, kind, payload, progress, *, composed=False):
        return kind, payload


class BoothWindowTests(unittest.TestCase):
    def test_avatar_feed_is_display_only_and_closed_on_exit(self):
        camera_frame = np.full((12, 16, 3), 30, np.uint8)
        avatar_frame = np.full((8, 8, 3), 220, np.uint8)

        class Feed:
            error = None

            def __init__(self):
                self.closed = False

            def read(self):
                return avatar_frame.copy()

            def close(self):
                self.closed = True

        feed = Feed()
        processor = FakeProcessor()
        booth = BoothWindow(FakeCamera(camera_frame), lambda image: image,
                            processor=processor, show_styled=False, avatar_feed=feed)
        booth._frame()
        booth._update_vts_preview()
        self.assertTrue(np.array_equal(booth.last_frame, camera_frame))
        self.assertTrue(np.array_equal(booth.avatar_frame, avatar_frame))
        booth._publish("photo", booth.last_frame.copy())
        kind, payload = booth.future.result()
        self.assertEqual(kind, "photo")
        self.assertTrue(np.array_equal(payload, camera_frame))
        booth.avatar_feed.close()
        self.assertTrue(feed.closed)
        booth.executor.shutdown(wait=True)

    def test_vts_feed_releases_unavailable_capture(self):
        from app.core.vts_video import VTSVideoFeed

        class Capture:
            def __init__(self):
                self.released = False

            def isOpened(self):
                return False

            def release(self):
                self.released = True

        capture = Capture()
        feed = VTSVideoFeed(capture_factory=lambda *_args: capture).start()
        self.assertIsNone(feed.capture)
        self.assertIn("无法打开", feed.error)
        self.assertTrue(capture.released)

    def test_vts_status_error_clears_hotkeys_without_thread_failure(self):
        class Controller:
            def status(self):
                raise RuntimeError("VTS offline")

        booth = BoothWindow(FakeCamera(np.zeros((2, 2, 3), np.uint8)), lambda image: image,
                            vts_controller=Controller(), show_styled=False)
        booth.vts_hotkey_items = [{"hotkeyID": "old"}]
        booth.vts_hotkeys = ["旧热键"]
        booth._update_vts_preview()
        deadline = time.monotonic() + 1
        while booth._vts_checking and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("VTS API 不可用", booth.vts_status)
        self.assertEqual(booth.vts_hotkey_items, [])
        self.assertEqual(booth.vts_hotkeys, [])
        booth.executor.shutdown(wait=True)

    def test_result_layout_keeps_qr_visible_over_avatar_feed(self):
        from pathlib import Path

        frame = np.zeros((12, 16, 3), np.uint8)
        qr = np.full((10, 10, 3), 255, np.uint8)
        class Feed:
            error = None
            def read(self):
                return np.full((8, 8, 3), 220, np.uint8)
            def close(self):
                pass

        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            avatar_feed=Feed(), show_styled=False)
        booth.state = "result"
        booth.result_path = Path("capture.mp4")
        booth.qr_path = Path("qr.png")
        with patch("app.ui.booth_window.read_image", return_value=qr), patch.object(Path, "exists", return_value=True):
            composed = booth._compose(frame)
        self.assertGreater(int(composed[95:285, 1050:1240].mean()), 240)
        booth.executor.shutdown(wait=True)

    def test_camera_preview_uses_latest_raw_inset_without_waiting_for_inference(self):
        import threading
        started, release = threading.Event(), threading.Event()
        current = np.full((90, 160, 3), 20, np.uint8)
        camera = FakeCamera(current)

        def stylize(frame):
            started.set()
            release.wait(2)
            return np.full_like(frame, 180)

        booth = BoothWindow(camera, stylize, processor=FakeProcessor())
        booth.preview_worker.start()
        try:
            self.assertTrue(booth._frame())
            self.assertTrue(started.wait(2))
            camera.frame = np.full_like(current, 80)
            self.assertTrue(booth._frame())
            self.assertEqual(int(booth.last_frame[0, 0, 0]), 80)
            preview = booth._compose(booth.last_frame)
            self.assertEqual(int(preview[200, 1000, 0]), 80)
            self.assertIsNone(booth.last_styled)
            release.set()
            deadline = time.monotonic() + 2
            while booth.last_styled is None and time.monotonic() < deadline:
                booth._frame()
                time.sleep(.005)
            self.assertIsNotNone(booth.last_styled)
            self.assertEqual(int(booth.last_styled[0, 0, 0]), 180)
        finally:
            release.set()
            booth.preview_worker.close()
            booth.executor.shutdown(wait=True)

    def test_high_resolution_canvas_keeps_buttons_clickable(self):
        frame = np.full((180, 320, 3), 66, np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), show_styled=False)
        try:
            booth.last_frame = frame
            booth._display_scale = (1.5, 1.5)
            canvas = booth._compose(frame)
            self.assertEqual(canvas.shape, (1080, 1920, 3))
            with patch.object(booth, "_begin") as begin:
                booth._mouse(4, 150, 1020, 0, None)
                begin.assert_called_once_with("photo")
        finally:
            booth.executor.shutdown(wait=True)

    def test_camera_capture_uses_raw_frame_not_inset_or_old_style(self):
        frame = np.full((24, 32, 3), 44, np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor())
        try:
            booth.last_frame = frame
            booth.last_styled = np.full_like(frame, 200)
            booth._publish("photo", booth.last_frame.copy())
            np.testing.assert_array_equal(booth.future.result()[1], frame)
        finally:
            booth.executor.shutdown(wait=True)

    def test_vts_composite_is_capture_source_and_background_changes(self):
        green = np.full((18, 22, 3), (0, 255, 0), np.uint8)
        green[3:15, 6:16] = (30, 40, 210)
        camera_frame = np.full_like(green, 7)

        class Feed:
            error = None
            sequence = 0
            def snapshot(self, max_age=1):
                from app.core.vts_video import VideoSnapshot
                self.sequence += 1
                return VideoSnapshot(green.copy(), self.sequence, time.monotonic())

        class Catalog:
            items = ("bg:a", "bg:b")
            def get(self, name, size):
                width, height = size
                color = (20, 50, 200) if name == "bg:a" else (200, 40, 20)
                return np.full((height, width, 3), color, np.uint8)

        booth = BoothWindow(FakeCamera(camera_frame), lambda image: image,
                            processor=FakeProcessor(), avatar_feed=Feed(),
                            background_catalog=Catalog(), vts_capture=True, show_styled=False)
        booth._frame()
        booth._update_vts_preview()
        self.assertIsNone(booth.last_frame)
        self.assertTrue(np.array_equal(booth.composed_frame[0, 0], [20, 50, 200]))
        with patch("app.ui.booth_window.random.randrange", return_value=0):
            booth._randomize_background()
        self.assertTrue(np.array_equal(booth.composed_frame[0, 0], [200, 40, 20]))
        booth._begin("photo")
        self.assertEqual(booth.capture_background, "bg:b")
        booth.executor.shutdown(wait=True)

    def test_vts_capture_is_disabled_without_composite(self):
        class Feed:
            error = "打不开 VTS 设备"
            def snapshot(self, max_age=1): return None
        booth = BoothWindow(FakeCamera(np.zeros((6, 6, 3), np.uint8)), lambda image: image,
                            processor=FakeProcessor(), avatar_feed=Feed(), vts_capture=True)
        booth._begin("photo")
        self.assertEqual(booth.state, "ready")
        self.assertIn("VTS", booth.status)
        booth.executor.shutdown(wait=True)

    def test_mouse_capture_enters_countdown_and_publishes_photo(self):
        frame = np.full((24, 32, 3), 90, np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), show_styled=False)
        booth.last_frame = frame
        with patch("app.ui.booth_window.time.monotonic", return_value=100):
            booth._mouse(4, 100, 680, 0, None)
        self.assertEqual(booth.state, "countdown")
        self.assertEqual(booth.current, "photo")
        booth._reset()
        self.assertEqual(booth.state, "ready")
        booth.executor.shutdown(wait=True)

    def test_recording_shows_completed_progress_before_processing(self):
        frame = np.zeros((4, 4, 3), np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), show_styled=False,
                            record_seconds=1, record_fps=2)
        booth.state = "recording"
        booth.recording = Recording(5, 1, 2)
        booth.recording.add(5, frame)
        booth.recording.add(5.5, frame)
        booth._handle_recording(6, frame)
        self.assertEqual(booth.state, "processing")
        self.assertEqual(booth.future.result()[0], "video")
        booth.executor.shutdown(wait=True)


class VTSLayoutTests(unittest.TestCase):
    def make_booth(self):
        class Catalog:
            items = ("builtin:aurora", "user:" + "长背景名称" * 50)

            def get(self, name, size):
                return np.full((size[1], size[0], 3), (60, 70, 80), np.uint8)

        frame = np.full((180, 320, 3), (10, 100, 200), np.uint8)
        booth = BoothWindow(FakeCamera(frame), lambda image: image,
                            processor=FakeProcessor(), vts_capture=True,
                            background_catalog=Catalog())
        self.addCleanup(booth.executor.shutdown, wait=True)
        booth.composed_frame = frame
        booth.composite_error = None
        booth.deadline = time.monotonic() + 3
        return booth

    def click(self, booth, rect):
        x0, y0, x1, y1 = rect
        booth._mouse(4, (x0 + x1) // 2, (y0 + y1) // 2, 0, None)

    def test_vts_high_resolution_canvas_and_exit_click(self):
        booth = self.make_booth()
        booth._display_scale = (2.0, 1600 / 720)
        canvas = booth._compose(booth.composed_frame)
        self.assertEqual(canvas.shape, (1600, 2560, 3))
        exit_rect = next(rect for action, rect, _ in booth._vts_buttons() if action == "exit")
        x0, y0, x1, y1 = exit_rect
        booth._mouse(4, round((x0 + x1) * booth._display_scale[0] / 2),
                     round((y0 + y1) * booth._display_scale[1] / 2), 0, None)
        self.assertEqual(booth.state, "exit")

    def test_recorded_vts_video_adds_live_hd_inset_without_changing_photo(self):
        booth = self.make_booth()
        original = booth.composed_frame.copy()
        hd = np.full((90, 160, 3), (7, 218, 41), np.uint8)
        booth.camera_frame = hd.copy()
        booth.camera_since = 10.0
        booth.capture_source = "vts"
        booth.state = "recording"
        booth.recording = Recording(10.0, seconds=2, fps=10)
        booth.composed_sequence = 1
        booth.last_recorded_sequence = 0

        booth._record_vts_frame(10.1)
        self.assertEqual(len(booth.recording.samples), 1)
        recorded = booth.recording.samples[0][1]
        self.assertEqual(recorded.shape, original.shape)
        np.testing.assert_array_equal(recorded[3, 3], original[3, 3])
        np.testing.assert_array_equal(recorded[48, 275], hd[45, 80])
        np.testing.assert_array_equal(booth.composed_frame, original)
        np.testing.assert_array_equal(booth.camera_frame, hd)
        self.assertFalse(np.array_equal(booth._compose_vts(original), recorded))
        booth._record_vts_frame(10.2)
        self.assertEqual(len(booth.recording.samples), 1)
        booth.composed_sequence += 1
        booth._record_vts_frame(10.8)
        booth.composed_sequence += 1
        booth._record_vts_frame(11.5)
        booth._handle_recording(12.1, None)
        kind, source = booth.future.result()
        self.assertEqual(kind, "video")
        np.testing.assert_array_equal(next(source.frames()), recorded)
        booth._publish("photo", booth.composed_frame.copy())
        self.assertEqual(booth.future.result()[1].shape, original.shape)
        np.testing.assert_array_equal(booth.future.result()[1], original)

    def test_recorded_vts_video_uses_placeholder_when_hd_is_stale_and_recovers(self):
        booth = self.make_booth()
        original = booth.composed_frame.copy()
        booth.camera_frame = np.full((90, 160, 3), (7, 218, 41), np.uint8)
        booth.camera_since = 1.0
        booth.capture_source = "vts"
        booth.state = "recording"
        booth.recording = Recording(10.0, seconds=2, fps=10)
        booth.composed_sequence = 1
        booth.last_recorded_sequence = 0

        booth._record_vts_frame(10.1)
        placeholder = booth.recording.samples[0][1]
        self.assertFalse(np.any(np.all(placeholder == (7, 218, 41), axis=2)))
        self.assertFalse(np.array_equal(placeholder, original))
        booth.camera_frame = None
        booth.camera_since = None
        booth.composed_sequence += 1
        booth._record_vts_frame(10.2)
        np.testing.assert_array_equal(booth.recording.samples[1][1], placeholder)
        booth.camera_frame = np.full((90, 160, 3), (2, 200, 90), np.uint8)
        booth.camera_since = 10.3
        booth.composed_sequence += 1
        booth._record_vts_frame(10.3)
        np.testing.assert_array_equal(booth.recording.samples[2][1][48, 275], (2, 200, 90))
        np.testing.assert_array_equal(booth.composed_frame, original)

    def test_vts_video_inset_is_not_added_to_hd_only_recording(self):
        booth = self.make_booth()
        frame = np.full((180, 320, 3), (1, 2, 3), np.uint8)
        booth.capture_source = "camera"
        booth.recording = Recording(10, seconds=2, fps=10)
        booth._handle_recording(10.1, frame)
        np.testing.assert_array_equal(booth.recording.samples[0][1], frame)

    def test_states_and_aspect_ratios_do_not_mutate_inputs(self):
        booth = self.make_booth()
        for shape in ((90, 160, 3), (160, 90, 3), (100, 100, 3), (1, 400, 3)):
            frame = np.full(shape, (7, 19, 231), np.uint8)
            original = frame.copy()
            booth.composed_frame = frame
            for state in ("ready", "countdown", "recording", "processing", "result", "error"):
                with self.subTest(shape=shape, state=state):
                    booth.state = state
                    booth.progress = (20, 10)  # A late callback cannot overflow the bar.
                    canvas = booth._compose(frame)
                    self.assertEqual(canvas.shape, (720, 1280, 3))
                    self.assertEqual(canvas.dtype, np.uint8)
                    np.testing.assert_array_equal(frame, original)

    def test_text_mask_cache_uses_current_pixels_and_bounds_growth(self):
        from app.ui.booth_window import _vts_text_mask
        _vts_text_mask.cache_clear()
        rect = (0, 0, 150, 60)
        dark = np.zeros((60, 150, 3), np.uint8)
        light = np.full_like(dark, 100)
        BoothWindow._vts_text(dark, "文字", rect, 25, (255, 255, 255))
        BoothWindow._vts_text(light, "文字", rect, 25, (255, 255, 255))
        self.assertEqual(_vts_text_mask.cache_info().hits, 1)
        self.assertEqual(int(dark[0, 0, 0]), 0)
        self.assertEqual(int(light[0, 0, 0]), 100)
        self.assertFalse(np.array_equal(dark, light))
        for n in range(260):
            _vts_text_mask(str(n), 150, 60, 25, False)
        self.assertLessEqual(_vts_text_mask.cache_info().currsize, 256)

    def test_vts_theme_keeps_control_geometry_and_does_not_mutate_preview(self):
        booth = self.make_booth()
        source = booth.composed_frame.copy()
        booth.vts_api_connected = True
        canvas = booth._compose_vts(source)
        self.assertEqual(canvas.shape, (720, 1280, 3))
        np.testing.assert_array_equal(booth.composed_frame, source)
        np.testing.assert_array_equal(canvas[110, 32], booth.VTS_COLORS["line"])
        for action in ("photo", "video", "random_background", "source_virtual"):
            rect = booth.VTS_LAYOUT[action]
            self.assertIn(action, [item[0] for item in booth._vts_buttons()])
            x0, y0, x1, y1 = rect
            self.assertTrue(booth._inside((x0 + x1) // 2, (y0 + y1) // 2, rect))
            self.assertFalse(np.array_equal(canvas[(y0 + y1) // 2, (x0 + x1) // 2],
                                            booth.VTS_COLORS["background"]))

    def test_fixed_canvas_is_copied_and_status_repaints(self):
        booth = self.make_booth()
        base = booth._vts_base_canvas()
        base[:] = 255
        self.assertFalse(np.array_equal(base, booth._vts_base_canvas()))
        booth.state = "ready"
        first = booth._compose_vts(booth.composed_frame)
        booth.state = "error"
        booth.error = "场景出错"
        second = booth._compose_vts(booth.composed_frame)
        self.assertFalse(np.array_equal(first, second))

    def test_result_image_cache_invalidates_on_replacement(self):
        import tempfile
        from pathlib import Path
        import cv2
        booth = self.make_booth()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "art.png"
            def save(color):
                cv2.imencode(".png", np.full((16, 16, 3), color, np.uint8))[1].tofile(path)
            save((10, 20, 30))
            with patch("app.ui.booth_window.read_image", wraps=__import__(
                    "app.core.image_io", fromlist=["read_image"]).read_image) as reader:
                first = booth._vts_image(path)
                self.assertIs(first, booth._vts_image(path))
                self.assertEqual(reader.call_count, 1)
                previous_mtime = path.stat().st_mtime_ns
                save((70, 80, 90))
                import os
                os.utime(path, ns=(previous_mtime + 1_000_000_000,
                                   previous_mtime + 1_000_000_000))
                second = booth._vts_image(path)
                self.assertEqual(reader.call_count, 2)
                self.assertFalse(np.array_equal(first, second))

    def test_background_file_replacement_recomposes_same_sequence(self):
        import tempfile
        from pathlib import Path
        import cv2
        from app.core.chroma import BackgroundCatalog
        from app.core.vts_video import VideoSnapshot

        green = np.full((24, 32, 3), (0, 255, 0), np.uint8)
        green[6:18, 8:24] = (50, 80, 210)

        class Feed:
            error = None
            def snapshot(self, max_age=1):
                return VideoSnapshot(green.copy(), 1, time.monotonic())

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.png"
            def save(color):
                cv2.imencode(".png", np.full((24, 32, 3), color, np.uint8))[1].tofile(path)
            save((10, 20, 30))
            booth = BoothWindow(None, lambda image: image, avatar_feed=Feed(),
                                vts_capture=True, background_catalog=BackgroundCatalog(temp))
            self.addCleanup(booth.executor.shutdown, wait=True)
            booth.background_index = 2
            booth._update_composite()
            first = booth.composed_frame.copy()
            booth._update_composite()
            np.testing.assert_array_equal(first, booth.composed_frame)
            save((100, 120, 180))
            booth._update_composite()
            self.assertEqual(booth.composed_sequence, 1)
            self.assertFalse(np.array_equal(first, booth.composed_frame))

    def test_preview_is_contained_and_centered(self):
        booth = self.make_booth()
        frame = np.full((400, 200, 3), (7, 19, 231), np.uint8)
        booth.composed_frame = frame
        canvas = booth._compose(frame)
        mask = np.all(canvas == (7, 19, 231), axis=2)
        ys, xs = np.where(mask)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (306, 549, 104, 591))
        self.assertEqual((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1), 0.5)

    def test_hd_camera_preview_is_separate_from_vts_composition(self):
        green = np.full((18, 22, 3), (0, 255, 0), np.uint8)
        green[3:15, 6:16] = (30, 40, 210)

        class Feed:
            error = None
            def snapshot(self, max_age=1):
                return SimpleNamespace(frame=green.copy(), sequence=1, timestamp=time.monotonic())

        class Catalog:
            items = ("builtin:aurora", "builtin:sunset")
            def get(self, name, size):
                return np.full((size[1], size[0], 3), (200, 40, 20), np.uint8)

        booth = BoothWindow(None, lambda image: image, avatar_feed=Feed(),
                            vts_capture=True, background_catalog=Catalog())
        self.addCleanup(booth.executor.shutdown, wait=True)
        booth.camera_frame = np.full_like(green, (230, 150, 90))
        booth.camera_since = time.monotonic()
        booth.background_opacity = 0.5
        booth._update_composite()
        self.assertIsNotNone(booth.composed_frame)
        expected = np.rint(np.array(booth.VTS_COLORS["scene_base"]) * 0.5
                            + np.array((200, 40, 20)) * 0.5).astype(np.uint8)
        np.testing.assert_array_equal(booth.composed_frame[0, 0], expected)
        np.testing.assert_array_equal(booth.composed_frame[6, 10], green[6, 10])
        first = booth.composed_frame.copy()
        booth.camera_frame[:] = (1, 2, 3)
        booth.camera_sequence += 1
        booth._update_composite()
        np.testing.assert_array_equal(booth.composed_frame, first)
        self.assertNotIn("camera_retry", [action for action, _, _ in booth._vts_buttons()])
        booth.camera_error = "HD 摄像头不可用"
        self.assertIn("camera_retry", [action for action, _, _ in booth._vts_buttons()])
        booth.camera_frame = None
        booth.camera_since = None
        booth._update_composite()
        np.testing.assert_array_equal(booth.composed_frame, first)
        self.assertEqual(booth._effective_opacity(), 0.5)

    def test_random_background_changes_composed_capture(self):
        green = np.full((18, 22, 3), (0, 255, 0), np.uint8)
        green[3:15, 6:16] = (30, 40, 210)

        class Feed:
            error = None
            def snapshot(self, max_age=1):
                return SimpleNamespace(frame=green.copy(), sequence=1, timestamp=time.monotonic())

        class Catalog:
            items = ("builtin:aurora", "builtin:sunset") + tuple(
                f"user:背景{i}.jpg" for i in range(8))
            def get(self, name, size):
                color = (20, 50, 200) if name == "user:背景7.jpg" else (200, 40, 20)
                return np.full((size[1], size[0], 3), color, np.uint8)

        booth = BoothWindow(None, lambda image: image, processor=FakeProcessor(),
                            avatar_feed=Feed(), vts_capture=True, show_styled=False,
                            background_catalog=Catalog())
        self.addCleanup(booth.executor.shutdown, wait=True)
        booth._update_composite()
        self.assertIn("random_background", [action for action, _, _ in booth._vts_buttons()])
        with patch("app.ui.booth_window.random.randrange", return_value=8):
            self.click(booth, booth.VTS_LAYOUT["random_background"])
        self.assertEqual(booth.background_index, 9)
        np.testing.assert_array_equal(booth.composed_frame[0, 0], [20, 50, 200])
        booth._begin("photo")
        self.assertEqual(booth.capture_background, "user:背景7.jpg")
        self.assertEqual(booth.state, "countdown")
        with patch.object(booth, "_randomize_background") as randomize:
            self.click(booth, booth.VTS_LAYOUT["random_background"])
            randomize.assert_not_called()
        self.assertEqual(booth.capture_background, "user:背景7.jpg")

    def test_random_background_does_not_repeat_current_image(self):
        booth = self.make_booth()
        booth.background_index = 1
        with patch("app.ui.booth_window.random.randrange", return_value=0):
            self.click(booth, booth.VTS_LAYOUT["random_background"])
        self.assertEqual(booth.background_index, 0)
        self.assertEqual(len(booth.backgrounds.items), 2)

    def test_character_background_catalog_switches_without_cross_character_images(self):
        from app.config import BACKGROUND_DIR
        booth = self.make_booth()
        booth._custom_background_catalog = False
        booth.backgrounds = BackgroundCatalog(BACKGROUND_DIR)
        booth.vts_model_name = "奶蛙"
        booth._sync_background_catalog()
        self.assertEqual(booth.backgrounds.user_dir, BACKGROUND_DIR / "奶蛙")
        self.assertIn("user:最后的晚餐.jpg", booth.backgrounds.items)
        self.assertNotIn("user:IMG_8324.jpg", booth.backgrounds.items)
        booth.background_index = 4
        booth.vts_model_name = "牛来"
        booth._sync_background_catalog()
        self.assertEqual(booth.backgrounds.user_dir, BACKGROUND_DIR / "牛来")
        self.assertNotIn("user:最后的晚餐.jpg", booth.backgrounds.items)
        self.assertEqual(booth.background_index, 0)

    def test_visible_button_centers_and_blank_space(self):
        booth = self.make_booth()
        with patch.object(booth, "_begin") as begin, patch.object(booth, "_randomize_background") as randomize:
            for action in ("photo", "video", "random_background"):
                self.click(booth, booth.VTS_LAYOUT[action])
            self.assertEqual([call.args[0] for call in begin.call_args_list], ["photo", "video"])
            randomize.assert_called_once_with()
            begin.reset_mock()
            randomize.reset_mock()
            # Old capture rectangles and gaps must not remain invisible controls.
            for x, y in ((100, 700), (700, 680), (350, 650), (1053, 520), (400, 300)):
                booth._mouse(4, x, y, 0, None)
            begin.assert_not_called()
            randomize.assert_not_called()
            for state in ("countdown", "recording", "processing"):
                booth.state = state
                self.click(booth, booth.VTS_LAYOUT["photo"])
                self.click(booth, booth.VTS_LAYOUT["random_background"])
            begin.assert_not_called()
            randomize.assert_not_called()
        for state in ("ready", "countdown", "recording", "processing", "result", "error"):
            booth.state = state
            self.click(booth, booth.EXIT[1])
            self.assertEqual(booth.state, "exit")

    def test_hotkey_labels_ids_and_hit_geometry_share_specs(self):
        booth = self.make_booth()
        booth.vts_controller = object()
        booth.vts_hotkey_items = [{"hotkeyID": "a", "name": "挥手"},
                                  {"hotkeyID": "b"}, {"name": "不可用"},
                                  {"hotkeyID": "d", "name": "很长的动作名称" * 20}]
        booth.vts_hotkeys = ["故意不同的旧标签"]
        booth.vts_api_connected = True
        booth.vts_executor = MagicMock()
        specs = [s for s in booth._vts_buttons() if s[0].startswith("hotkey:")]
        self.assertEqual([s[2] for s in specs[:2]], ["挥手", "动作"])
        with patch.object(booth.vts_executor, "submit") as submit:
            for action, rect, _ in specs:
                self.click(booth, rect)
                self.assertEqual(submit.call_args.args, (booth._trigger_vts_hotkey, action[7:]))
            self.assertEqual(submit.call_count, 3)
            submit.reset_mock()
            booth._mouse(4, specs[0][1][2] + 2, 640, 0, None)
            booth._mouse(4, 1060, 640, 0, None)  # Slot with no usable id.
            submit.assert_not_called()
        with patch.object(booth, "_vts_text", wraps=booth._vts_text) as paint:
            booth._compose(booth.composed_frame)
        painted = [call.args[1] for call in paint.call_args_list]
        for _, _, label in specs:
            self.assertIn(label, painted)

    def test_empty_vts_never_displays_camera_fallback_and_disables_capture(self):
        booth = self.make_booth()
        real = np.full((180, 320, 3), (1, 2, 253), np.uint8)
        booth.camera_frame = real
        for empty in (None, np.empty((0, 0, 3), np.uint8)):
            booth.composed_frame = empty
            for passed in (None, real, np.empty((0, 0, 3), np.uint8)):
                canvas = booth._compose(passed)
                self.assertFalse(np.any(np.all(canvas[104:592, 74:810] == (1, 2, 253), axis=2)))
                self.assertTrue(np.any(np.all(canvas[179:393, 874:1224] == (1, 2, 253), axis=2)))
            with patch.object(booth, "_begin") as begin:
                self.click(booth, booth.VTS_LAYOUT["photo"])
                self.click(booth, booth.VTS_LAYOUT["video"])
                begin.assert_not_called()

    def test_result_image_and_qr_are_separate_and_video_has_placeholder(self):
        from pathlib import Path
        booth = self.make_booth()
        booth.state = "result"
        booth.result_path, booth.qr_path = Path("art.png"), Path("qr.png")
        art = np.full((400, 200, 3), (7, 19, 231), np.uint8)
        qr = np.full((19, 19, 3), 255, np.uint8)
        with patch("app.ui.booth_window.read_image", side_effect=lambda path: qr if path == booth.qr_path else art):
            canvas = booth._compose(booth.composed_frame)
        np.testing.assert_array_equal(canvas[200:390, 954:1144], 255)
        np.testing.assert_array_equal(canvas[104:592, 306:550], art[0, 0] * np.ones((488, 244, 3), np.uint8))
        booth.result_path = Path("clip.mp4")
        with patch("app.ui.booth_window.read_image", return_value=qr), \
                patch.object(booth, "_vts_text", wraps=booth._vts_text) as paint:
            canvas = booth._compose(booth.composed_frame)
        self.assertIn("视频已保存", [call.args[1] for call in paint.call_args_list])
        np.testing.assert_array_equal(canvas[200:390, 954:1144], 255)
        for state in ("result", "error"):
            booth.state = state
            with patch("app.ui.booth_window.read_image", side_effect=OSError("missing")), \
                    patch.object(booth, "_vts_text", wraps=booth._vts_text) as paint:
                booth._compose(booth.composed_frame)
            expected = "二维码暂不可用" if state == "result" else "未生成可分享作品"
            self.assertIn(expected, [call.args[1] for call in paint.call_args_list])
            self.click(booth, booth.VTS_LAYOUT["preview"])
            self.assertEqual(booth.state, "ready")

    def test_long_text_is_clipped_to_its_rectangle(self):
        booth = self.make_booth()
        canvas = np.zeros((120, 240, 3), np.uint8)
        booth._vts_text(canvas, "长错误\n" * 10000, (20, 20, 120, 90), 20, (255, 255, 255))
        self.assertGreater(canvas[20:90, 20:120].sum(), 0)
        canvas[20:90, 20:120] = 0
        self.assertEqual(canvas.sum(), 0)
        booth.state = "error"
        booth.error = booth.status = "设备错误很长" * 1000
        booth.vts_status = "连接错误" * 1000
        canvas = booth._compose(booth.composed_frame)
        np.testing.assert_array_equal(canvas[104:592, 825:849],
                                      np.full((488, 24, 3), booth.VTS_COLORS["background"], np.uint8))

    def test_model_list_pagination_and_switch_blocks_old_capture(self):
        booth = self.make_booth()
        class Controller:
            def models(self):
                return [{"model_id": str(i), "model_name": f"角色 {i}"} for i in range(8)]
            def load_model(self, model_id):
                self.loaded = model_id
                return {"modelID": model_id}
            def hotkeys(self):
                return [{"name": "挥手", "hotkeyID": "wave"}]
            def status(self):
                return {"connected": True, "model_loaded": True, "model_id": "2", "model_name": "角色 2"}
        controller = Controller()
        booth.vts_controller = controller
        frame = booth.composed_frame
        with patch("app.ui.booth_window.threading.Thread") as worker:
            booth._open_vts_models()
            self.assertTrue(booth.vts_models_open)
            self.assertIsNone(booth.composed_frame)
            worker.call_args.kwargs["target"]()
            self.assertEqual(len(booth.vts_models), 8)
            self.assertIn("model_next", [item[0] for item in booth._vts_buttons()])
            self.click(booth, booth.VTS_LAYOUT["model_next"])
            self.assertEqual(booth.vts_model_page, 1)
            self.assertIn("model:7", [item[0] for item in booth._vts_buttons()])
            self.click(booth, booth.VTS_LAYOUT["model_previous"])
            booth.composed_frame = frame
            self.click(booth, (283, 296, 990, 343))
            self.assertEqual(booth.vts_model_loading, "2")
            self.assertIsNone(booth.composed_frame)
            self.assertFalse(any(item[0] == "photo" for item in booth._vts_buttons()))
            booth._begin("photo")
            self.assertEqual(booth.state, "ready")
            worker.call_args.kwargs["target"]()
        self.assertEqual(controller.loaded, "2")
        self.assertEqual(booth.vts_model_id, "2")
        self.assertFalse(booth.vts_models_open)
        self.assertIsNotNone(booth.vts_model_wait_frame)
        self.assertNotIn("model:1", [item[0] for item in booth._vts_buttons()])

    def test_model_switch_waits_for_delayed_api_confirmation(self):
        booth = self.make_booth()
        booth.vts_models = [{"model_id": "new", "model_name": "新角色"}]
        booth.vts_model_id = "old"
        booth.vts_models_open = True
        statuses = iter([
            {"connected": True, "model_loaded": True, "model_id": "old"},
            {"connected": True, "model_loaded": False, "model_id": ""},
            {"connected": True, "model_loaded": True, "model_id": "new", "model_name": "新角色"},
        ])
        class Controller:
            def load_model(self, model_id):
                self.loaded = model_id
                return {"modelID": model_id}
            def status(self):
                return next(statuses)
            def hotkeys(self):
                return [{"name": "挥手", "hotkeyID": "wave"}]
        booth.vts_controller = controller = Controller()
        with patch("app.ui.booth_window.threading.Thread") as worker, \
                patch("app.ui.booth_window.time.sleep") as sleep:
            booth._load_vts_model("new")
            self.assertFalse(any(action == "photo" for action, _, _ in booth._vts_buttons()))
            worker.call_args.kwargs["target"]()
        self.assertEqual(controller.loaded, "new")
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(booth.vts_model_id, "new")
        self.assertFalse(booth.vts_models_open)
        self.assertIsNotNone(booth.vts_model_wait_frame)
        self.assertEqual(booth.vts_hotkey_items[0]["hotkeyID"], "wave")

    def test_model_switch_rejects_missing_or_wrong_response_id(self):
        for response in ({}, {"modelID": "old"}):
            with self.subTest(response=response):
                booth = self.make_booth()
                booth.vts_models = [{"model_id": "new", "model_name": "新角色"}]
                class Controller:
                    def load_model(self, _model_id):
                        return response
                    def status(self):
                        raise AssertionError("响应 ID 不符时不能查询当前模型")
                booth.vts_controller = Controller()
                with patch("app.ui.booth_window.threading.Thread") as worker:
                    booth._load_vts_model("new")
                    worker.call_args.kwargs["target"]()
                self.assertIn("角色 ID", booth.vts_model_error)
                self.assertEqual(booth.composite_error, booth.vts_model_error)
                self.assertIsNone(booth.vts_model_wait_frame)
                self.assertEqual(booth.vts_model_id, "")
                self.assertGreater(booth.vts_model_next_load, time.monotonic())

    def test_old_model_frames_do_not_confirm_switch_and_timeout_blocks_capture(self):
        booth = self.make_booth()
        booth.vts_models = [{"model_id": "new", "model_name": "新角色"}]
        booth.vts_model_id = "old"
        class Feed:
            error = None
            def snapshot(self, max_age=1):
                return SimpleNamespace(sequence=10, timestamp=1003,
                                       frame=np.ones((2, 2, 3), np.uint8))
        booth.avatar_feed = Feed()
        class Controller:
            def load_model(self, model_id):
                return {"modelID": model_id}
            def status(self):
                return {"connected": True, "model_loaded": True, "model_id": "old"}
        booth.vts_controller = Controller()
        clock = [1000.0]
        def advance(seconds):
            clock[0] += seconds
        with patch("app.ui.booth_window.threading.Thread") as worker, \
                patch("app.ui.booth_window.time.monotonic", side_effect=lambda: clock[0]), \
                patch("app.ui.booth_window.time.sleep", side_effect=advance):
            booth._load_vts_model("new")
            worker.call_args.kwargs["target"]()
        self.assertIsNone(booth.vts_model_wait_frame)
        self.assertEqual(booth.vts_model_id, "old")
        self.assertIn("VTS 未确认目标角色", booth.vts_model_error)
        self.assertEqual(booth.composite_error, booth.vts_model_error)
        self.assertFalse(any(action == "photo" for action, _, _ in booth._vts_buttons()))
        booth._begin("photo")
        self.assertEqual(booth.state, "ready")

    def test_confirmed_model_composes_after_new_frame_without_popup(self):
        booth = self.make_booth()
        booth.vts_models = [{"model_id": "new", "model_name": "新角色"}]
        booth.vts_models_open = True
        booth.vts_model_id = "old"
        class Controller:
            def load_model(self, model_id):
                return {"modelID": model_id}
            def status(self):
                return {"connected": True, "model_loaded": True, "model_id": "new", "model_name": "新角色"}
            def hotkeys(self):
                return []
        booth.vts_controller = Controller()
        class Feed:
            error = None
            def __init__(self):
                green = np.full((24, 32, 3), (0, 255, 0), np.uint8)
                green[6:18, 8:24] = (50, 80, 210)
                self.current = SimpleNamespace(sequence=7, timestamp=100, frame=green)
            def snapshot(self, max_age=1):
                return self.current
        feed = Feed()
        booth.avatar_feed = feed
        with patch("app.ui.booth_window.threading.Thread") as worker, \
                patch("app.ui.booth_window.time.monotonic", return_value=100):
            booth._load_vts_model("new")
            worker.call_args.kwargs["target"]()
        self.assertFalse(booth.vts_models_open)
        self.assertIsNotNone(booth.vts_model_wait_frame)
        feed.current = SimpleNamespace(sequence=8, timestamp=100.01,
                                       frame=feed.current.frame)
        with patch("app.ui.booth_window.time.monotonic", return_value=100.01), \
                patch.object(booth, "_update_composite", wraps=booth._update_composite) as composite:
            booth._update_vts_preview()
        self.assertIsNone(booth.vts_model_wait_frame)
        composite.assert_called_once()
        self.assertIsNotNone(booth.composed_frame)
        self.assertIn("photo", [action for action, _, _ in booth._vts_buttons()])

    def test_model_switch_waits_for_later_frame_and_timeout_blocks_capture(self):
        booth = self.make_booth()
        booth.vts_controller = object()
        now = time.monotonic()
        stale = SimpleNamespace(sequence=8, timestamp=now - 0.01,
                                frame=np.ones((2, 2, 3), np.uint8))
        class Feed:
            error = None
            def snapshot(self, max_age=1):
                return self.current
        feed = Feed()
        feed.current = stale
        booth.avatar_feed = feed
        booth.vts_model_wait_frame = (7, now)
        booth._update_vts_preview()
        self.assertIsNotNone(booth.vts_model_wait_frame)
        feed.current = SimpleNamespace(sequence=9, timestamp=now + 3,
                                       frame=np.ones((2, 2, 3), np.uint8))
        with patch("app.ui.booth_window.time.monotonic", return_value=now + 3):
            booth._update_vts_preview()
        self.assertIsNone(booth.vts_model_wait_frame)
        booth.vts_model_wait_frame = (9, now - 13)
        booth.composed_frame = np.ones((2, 2, 3), np.uint8)
        feed.current = None
        booth._update_vts_preview()
        self.assertIsNone(booth.composed_frame)
        self.assertIsNotNone(booth.vts_model_error)
        booth._begin("photo")
        self.assertEqual(booth.state, "ready")

    def test_failed_model_load_requires_explicit_refresh(self):
        booth = self.make_booth()
        class Controller:
            def models(self):
                return [{"model_id": "new", "model_name": "新角色"}]
            def load_model(self, model_id):
                raise RuntimeError("模型不可用")
            def status(self):
                return {"connected": True, "model_loaded": True, "model_id": "old", "model_name": "旧角色"}
            def hotkeys(self):
                return []
        booth.vts_controller = Controller()
        booth.vts_models = booth.vts_controller.models()
        with patch("app.ui.booth_window.threading.Thread") as worker:
            booth._load_vts_model("new")
            worker.call_args.kwargs["target"]()
            self.assertIn("模型不可用", booth.vts_model_error)
            self.assertEqual(booth.state, "ready")
            self.assertFalse(any(action == "photo" for action, _, _ in booth._vts_buttons()))
            booth.composed_frame = np.ones((2, 2, 3), np.uint8)
            booth._begin("photo")
            self.assertEqual(booth.state, "ready")
            booth._refresh_vts_models()
            worker.call_args.kwargs["target"]()
        self.assertIsNone(booth.vts_model_error)
        self.assertIsNone(booth.vts_model_wait_frame)
        self.assertIsNone(booth.composed_frame)
        self.assertEqual(booth.vts_model_id, "old")
        self.assertIsNone(booth.composite_error)
        booth._open_vts_models()
        self.assertIn("model:new", [item[0] for item in booth._vts_buttons()])
        with patch("app.ui.booth_window.threading.Thread") as worker:
            booth._load_vts_model("new")
            self.assertIsNone(booth.vts_model_loading)
            self.assertIn("请等待", booth.vts_model_message)
            worker.assert_not_called()

    def test_failed_refresh_keeps_model_capture_locked(self):
        booth = self.make_booth()
        booth.vts_model_error = "角色切换失败"
        booth.vts_models = [{"model_id": "new", "model_name": "新角色"}]
        class Controller:
            def models(self):
                return [{"model_id": "new", "model_name": "新角色"}]
            def status(self):
                raise RuntimeError("无法查询 VTS 状态")
        booth.vts_controller = Controller()
        with patch("app.ui.booth_window.threading.Thread") as worker:
            booth._refresh_vts_models()
            worker.call_args.kwargs["target"]()
        self.assertIn("无法查询 VTS 状态", booth.vts_model_error)
        self.assertEqual(booth.vts_model_error, booth.composite_error)
        self.assertIsNone(booth.vts_model_wait_frame)
        self.assertFalse(any(action == "photo" for action, _, _ in booth._vts_buttons()))


if __name__ == "__main__":
    unittest.main()
