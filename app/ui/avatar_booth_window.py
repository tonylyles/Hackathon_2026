"""Operator panel for connecting to VTube Studio and triggering model hotkeys."""
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor


class AvatarBoothWindow:
    WIDTH, HEIGHT = 960, 600

    def __init__(self, controller, target_model="奶蛙"):
        self.controller = controller
        self.target_model = target_model
        self.status = "尚未连接 VTube Studio"
        self.model_name = ""
        self.hotkeys = []
        self.error = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None

    def refresh(self):
        status = self.controller.connect()
        self.model_name = status["model_name"]
        if not status["model_loaded"]:
            self.status = "VTube Studio 已连接；请先在 VTS 中加载奶蛙模型"
            self.hotkeys = []
            return
        if self.target_model and self.target_model not in self.model_name:
            self.status = f"当前模型为「{self.model_name or '未知'}」；请在 VTS 中切换到奶蛙"
            self.hotkeys = []
            return
        self.hotkeys = self.controller.hotkeys()
        self.status = f"已连接：{self.model_name or '模型已加载'}"

    def _draw(self):
        canvas = np.zeros((self.HEIGHT, self.WIDTH, 3), dtype=np.uint8)
        canvas[:] = (28, 30, 38)
        cv2.putText(canvas, "NAIWA AVATAR BOOTH", (40, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (235, 235, 245), 2)
        cv2.putText(canvas, self.status[:90], (42, 112),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (110, 220, 160), 1)
        if self.error:
            cv2.putText(canvas, self.error[:100], (42, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, .55, (90, 100, 255), 1)
        cv2.putText(canvas, "R: connect / refresh     Q: quit", (42, 185),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, (180, 185, 195), 1)
        for i, key in enumerate(self.hotkeys[:8]):
            name = key.get("name", key.get("hotkeyID", "(unnamed)"))
            line = f"{i + 1}. {name}"
            if key.get("file"):
                line += f"  [{key['file']}]"
            cv2.putText(canvas, line[:100], (54, 245 + i * 42),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (230, 230, 235), 1)
        cv2.putText(canvas, "Press 1-8 to trigger a model hotkey", (42, 565),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, (180, 185, 195), 1)
        return canvas

    def _safe_refresh(self):
        if self.pending and not self.pending.done():
            return
        self.pending = self.executor.submit(self.refresh)

    def _poll_pending(self):
        if self.pending is None or not self.pending.done():
            return
        future, self.pending = self.pending, None
        try:
            future.result()
            self.error = None
        except Exception as exc:
            self.error = str(exc)
            self.status = "无法连接 VTube Studio；确认已启动并开启 API"

    def run(self):
        cv2.namedWindow("Naiwa Avatar Booth", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Naiwa Avatar Booth", self.WIDTH, self.HEIGHT)
        self._safe_refresh()
        try:
            while True:
                self._poll_pending()
                cv2.imshow("Naiwa Avatar Booth", self._draw())
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    self._safe_refresh()
                elif ord("1") <= key <= ord("8"):
                    index = key - ord("1")
                    if index < len(self.hotkeys) and not (self.pending and not self.pending.done()):
                        self.error = None
                        self.pending = self.executor.submit(
                            self.controller.trigger, self.hotkeys[index]["hotkeyID"])
        finally:
            if self.pending is not None:
                self.pending.cancel()
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.controller.close()
            cv2.destroyWindow("Naiwa Avatar Booth")
