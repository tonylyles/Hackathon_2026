# stylizer_mock.py — 纯流程验证用引擎：不依赖任何 AI 模型/GPU 权重
# 用 OpenCV 描边+调色模拟"风格化"，用于验收管线连通性（环境未就绪时全链路仍可跑）
import cv2


class MockStylizer:
    """接口与 AnimeStylizer 一致：frame_in(BGR) → frame_out(BGR)；另附 batch 处理入口"""
    model = None  # 标记：无 torch 模型，video_batch 走逐帧路径

    def __init__(self, device="cpu"):
        self.device = device

    def __call__(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        # 描边叠加在暖色调底上，观感上区分于原画
        tinted = cv2.addWeighted(frame_bgr, 0.55, edges, 0.45, 0)
        tinted[:, :, 0] = cv2.add(tinted[:, :, 0], 25)  # 加蓝调，视觉上像"风格化"
        return tinted
