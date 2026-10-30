"""Regression checks for VTS-only startup and named capture fallback."""
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from app.core.vts_launcher import VTSLauncher
from app.core.vts_video import VTSVideoFeed
from app.ui.booth_window import BoothWindow


class VTSFallbackTests(unittest.TestCase):
    def test_named_fallback_publishes_and_closes(self):
        failed = MagicMock()
        failed.isOpened.return_value = False
        named = MagicMock()
        named.isOpened.return_value = True
        frame = np.full((4, 6, 3), 90, np.uint8)
        gate = threading.Event()

        def read():
            gate.wait(.01)
            return True, frame

        named.read.side_effect = read
        with patch('app.core.named_capture.NamedCapture', return_value=named):
            feed = VTSVideoFeed(capture_factory=lambda *_: failed, named_fallback=True).start()
            try:
                end = time.monotonic() + 2
                while feed.snapshot() is None and time.monotonic() < end:
                    time.sleep(.01)
                self.assertIsNotNone(feed.snapshot())
                np.testing.assert_array_equal(feed.snapshot().frame, frame)
            finally:
                # Do not use a mocked class in close's isinstance check.
                feed._stop.set()
                gate.set()
                feed._thread.join(1)
            self.assertFalse(feed._thread.is_alive())
            failed.release.assert_called_once()
            named.release.assert_called_once()

    def test_vts_window_needs_no_physical_camera(self):
        booth = BoothWindow(None, lambda image: image, vts_capture=True)
        try:
            self.assertFalse(booth._frame())
        finally:
            booth.executor.shutdown(wait=True)

    def test_vts_entry_does_not_open_physical_camera(self):
        from app.main import run_booth
        with patch('app.main.open_camera') as camera, \
                patch('app.main.get_stylizer') as stylizer, \
                patch('app.core.vts_client.VTSClient'), \
                patch('app.core.vts_controller.VTSController') as controller, \
                patch('app.core.vts_video.VTSVideoFeed') as feed, \
                patch('app.server.share.ShareServer'), \
                patch('app.ui.booth_window.BoothWindow') as window:
            controller.return_value.connect.return_value = {'connected': True}
            run_booth(vts_preview=True)
            camera.assert_not_called()
            stylizer.assert_not_called()
            self.assertIsNone(window.call_args.args[0])
            self.assertTrue(feed.call_args.kwargs['named_fallback'])
            self.assertTrue(window.call_args.kwargs['vts_capture'])
            self.assertIsNone(window.call_args.kwargs['vts_api_error'])
            feed.return_value.start.return_value.close.assert_called_once()

    def test_launcher_selects_vts_capture(self):
        launcher = (Path(__file__).resolve().parents[1] / '启动照相亭.bat').read_text(encoding='utf-8-sig')
        self.assertIn('-m app.main --booth --vts-preview %*', launcher)

    def test_api_failure_stays_in_vts_mode_and_exposes_error(self):
        from app.main import run_booth
        with patch('app.main.open_camera') as camera, \
                patch('app.main.get_stylizer') as stylizer, \
                patch('app.core.vts_client.VTSClient'), \
                patch('app.core.vts_controller.VTSController') as controller, \
                patch('app.core.vts_video.VTSVideoFeed'), \
                patch('app.server.share.ShareServer'), \
                patch('app.ui.booth_window.BoothWindow') as window:
            controller.return_value.connect.side_effect = ConnectionError('连接被拒绝')
            run_booth(vts_preview=True)
            camera.assert_not_called()
            stylizer.assert_not_called()
            self.assertTrue(window.call_args.kwargs['vts_capture'])
            self.assertIsNone(window.call_args.kwargs['vts_api_error'])
            self.assertIsNotNone(window.call_args.kwargs['vts_launcher'])
            controller.return_value.connect.assert_not_called()

    def test_api_inactive_stays_in_vts_mode(self):
        from app.main import run_booth
        with patch('app.main.open_camera') as camera, \
                patch('app.main.get_stylizer') as stylizer, \
                patch('app.core.vts_client.VTSClient'), \
                patch('app.core.vts_controller.VTSController') as controller, \
                patch('app.core.vts_video.VTSVideoFeed'), \
                patch('app.server.share.ShareServer'), \
                patch('app.ui.booth_window.BoothWindow') as window:
            controller.return_value.connect.return_value = {'connected': False}
            run_booth(vts_preview=True)
            camera.assert_not_called()
            stylizer.assert_not_called()
            self.assertTrue(window.call_args.kwargs['vts_capture'])
            self.assertIsNone(window.call_args.kwargs['vts_api_error'])
            controller.return_value.connect.assert_not_called()

    def test_launcher_detects_running_process_without_restarting(self):
        start = MagicMock()
        launcher = VTSLauncher(process_running=lambda: True, start=start)
        self.assertIn('已运行', launcher.ensure_started())
        start.assert_not_called()

    def test_launcher_attempts_once_and_avoids_uncertain_process_state(self):
        start = MagicMock()
        launcher = VTSLauncher(process_running=lambda: False, start=start)
        self.assertIn('已向 Steam 请求', launcher.ensure_started())
        self.assertIn('启动已尝试', launcher.ensure_started())
        start.assert_called_once_with('steam://rungameid/1325860')
        uncertain_start = MagicMock()
        uncertain = VTSLauncher(process_running=lambda: None, start=uncertain_start)
        self.assertIn('无法确认', uncertain.ensure_started())
        uncertain_start.assert_not_called()

    def test_connection_failure_launches_once_then_recovers_on_retry(self):

        start = MagicMock()
        launcher = VTSLauncher(process_running=lambda: False, start=start)
        controller = MagicMock()
        controller.connect.side_effect = [ConnectionError('尚未启动'),
                                          ConnectionError('正在启动'),
                                          {'connected': True}]
        booth = BoothWindow(None, lambda image: image, vts_controller=controller,
                            vts_capture=True, vts_launcher=launcher)
        try:
            with patch.object(booth.vts_executor, 'submit', side_effect=lambda fn: fn()):
                booth._request_vts_connection()
                self.assertFalse(booth.vts_api_connected)
                self.assertIn('等待', booth.vts_status)
                self.assertGreater(booth._vts_startup_deadline, time.monotonic())
                booth._request_vts_connection()
                start.assert_called_once_with('steam://rungameid/1325860')
                booth._request_vts_connection()
            self.assertTrue(booth.vts_api_connected)
            self.assertEqual(controller.connect.call_count, 3)
            self.assertEqual(start.call_count, 1)
            self.assertEqual(booth._vts_startup_deadline, 0)
        finally:
            booth.vts_executor.shutdown(wait=True)
            booth.executor.shutdown(wait=True)

    def test_manual_retry_button_requests_connection(self):
        booth = BoothWindow(None, lambda image: image, vts_controller=MagicMock(),
                            vts_capture=True, vts_api_error='VTS API 未连接')
        try:
            with patch.object(booth, '_request_vts_connection') as request:
                x0, y0, x1, y1 = booth.VTS_LAYOUT['retry']
                booth._mouse(4, (x0 + x1) // 2, (y0 + y1) // 2, 0, None)
                request.assert_called_once_with(retry=True)
        finally:
            booth.vts_executor.shutdown(wait=True)
            booth.executor.shutdown(wait=True)

    def test_api_failure_blocks_capture_even_with_stale_frame(self):
        feed = MagicMock()
        feed.error = None
        booth = BoothWindow(None, lambda image: image, avatar_feed=feed,
                            vts_controller=MagicMock(), vts_capture=True,
                            vts_api_error='VTS API 未连接：连接被拒绝')
        try:
            booth.composed_frame = np.full((4, 6, 3), 50, np.uint8)
            booth._update_composite()
            self.assertIsNone(booth.composed_frame)
            self.assertIn('连接被拒绝', booth.composite_error)
            booth._begin('photo')
            self.assertEqual(booth.state, 'ready')
            self.assertIn('连接被拒绝', booth.status)
            self.assertFalse(any(action == 'photo' for action, *_ in booth._vts_buttons()))
        finally:
            booth.executor.shutdown(wait=True)


if __name__ == '__main__':
    unittest.main()
