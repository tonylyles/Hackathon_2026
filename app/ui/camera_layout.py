"""Composition for the camera-first booth; logical coordinates stay at 1280x720."""
import math
import time

import cv2
import numpy as np


MAIN_PREVIEW = (28, 76, 928, 596)
RAW_INSET = (946, 119, 1254, 338)


def scaled_rect(rect, scale):
    sx, sy = scale
    return tuple(round(value * (sx if index % 2 == 0 else sy))
                 for index, value in enumerate(rect))


def compose_camera(booth, frame):
    sx, sy = booth._display_scale
    canvas = np.full((round(booth.HEIGHT * sy), round(booth.WIDTH * sx), 3),
                     (28, 24, 20), np.uint8)

    def rect(values):
        return scaled_rect(values, (sx, sy))

    def text(value, area, size=24, color=(245, 241, 232), center=False):
        x0, y0, x1, y1 = rect(area)
        size = max(12, round(size * min(sx, sy)))
        if x1 > x0 and y1 > y0:
            booth._vts_text(canvas, value, (x0, y0, x1, y1), size, color, center)

    def button(spec, color):
        _, area, label = spec
        x0, y0, x1, y1 = rect(area)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, -1)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (235, 235, 240),
                      max(1, round(min(sx, sy))))
        text(label, area, 25, (255, 255, 255), True)

    main, inset = rect(MAIN_PREVIEW), rect(RAW_INSET)
    if frame is not None:
        booth._vts_fit(canvas, frame, main)
    if booth.state not in ("result", "error") and booth.last_frame is not None:
        booth._vts_fit(canvas, booth.last_frame, inset)
    cv2.rectangle(canvas, inset[:2], inset[2:], (225, 210, 170),
                  max(1, round(2 * min(sx, sy))))
    text("动漫画面" if booth.show_styled else "实时原画", (28, 27, 260, 66), 26)
    text("实时原画", (946, 72, 1100, 111), 24)

    if booth.show_styled and booth.state == "ready":
        age = time.monotonic() - booth.styled_captured_at if booth.styled_captured_at else None
        if booth._inference_error:
            status = "风格化异常：" + booth._inference_error[:20]
        elif age is None:
            status = "动漫生成中，主画面暂显示原画"
        elif age > 1:
            status = f"动漫画面更新中（延迟 {age:.1f} 秒）"
        else:
            status = f"动漫处理 {booth.styled_inference_ms:.0f} 毫秒"
        text(status, (946, 358, 1254, 440), 18, (220, 213, 202))
    if booth.state == "result" and booth.result_path:
        if booth.result_path.suffix.lower() == ".png":
            try:
                booth._vts_fit(canvas, booth._vts_image(booth.result_path), main)
            except (OSError, ValueError, cv2.error):
                pass
        if booth.qr_path:
            try:
                qr = booth._vts_image(booth.qr_path)
                booth._vts_fit(canvas, qr, rect((1050, 95, 1240, 285)), cv2.INTER_NEAREST)
                text("扫码下载", (1040, 292, 1245, 334), 23, center=True)
            except (OSError, ValueError, cv2.error):
                pass
    if booth.state == "countdown":
        remaining = max(1, math.ceil(booth.deadline - time.monotonic()))
        text(str(remaining), (330, 206, 620, 427), 144, (255, 255, 255), True)
    elif booth.state == "recording":
        text("● 正在录制", (945, 455, 1254, 503), 25, (102, 110, 239))
    elif booth.state == "processing":
        done, total = booth.progress
        if total:
            x0, y0, x1, y1 = rect((945, 542, 1245, 555))
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (90, 90, 100), -1)
            cv2.rectangle(canvas, (x0, y0),
                          (x0 + round((x1 - x0) * min(1, done / total)), y1),
                          (180, 85, 245), -1)
    x0, y0, x1, y1 = rect((0, 604, booth.WIDTH, booth.HEIGHT))
    cv2.rectangle(canvas, (x0, y0), (x1, y1), (18, 20, 34), -1)
    text(booth.status, (30, 607, 1220, 645), 24, (255, 255, 255))
    if booth.state == "ready":
        button(booth.PHOTO, (40, 170, 210))
        button(booth.VIDEO, (170, 85, 245))
    elif booth.state in ("result", "error"):
        text("点击屏幕或按空格返回", (40, 654, 700, 704), 24)
    button(booth.EXIT, (80, 80, 190))
    return canvas
