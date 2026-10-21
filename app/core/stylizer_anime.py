# stylizer_anime.py — AnimeGANv2 实时风格化（模式 A 核心）
# 首次运行会通过 torch.hub 从 GitHub 下载权重（约几十 MB），之后走本地缓存
import cv2
import torch

from app.config import ANIMEGAN_WEIGHT, STYLE_SIZE, USE_HALF


class AnimeStylizer:
    def __init__(self, device="cuda", weight=ANIMEGAN_WEIGHT, size=STYLE_SIZE):
        self.device = device if torch.cuda.is_available() else "cpu"
        self.size = size
        self.model = torch.hub.load(
            "bryandlee/animegan2-pytorch:main", weight, device=self.device,
            trust_repo=True,
        )
        if self.device == "cuda" and USE_HALF:
            self.model = self.model.half()
        self.model.eval()

    @torch.inference_mode()
    def __call__(self, frame_bgr):
        """输入 BGR 帧，输出风格化 BGR 帧"""
        img = cv2.cvtColor(cv2.resize(frame_bgr, (self.size, self.size)), cv2.COLOR_BGR2RGB)
        t = torch.from_numpy(img).to(self.device).float().permute(2, 0, 1)[None] / 127.5 - 1
        if self.device == "cuda" and USE_HALF:
            t = t.half()
        out = self.model(t)[0].permute(1, 2, 0).float().cpu().numpy()
        out = ((out + 1) * 127.5).clip(0, 255).astype("uint8")
        return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
