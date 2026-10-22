# stylizer_anime.py — AnimeGANv2 实时风格化（GPU 管线优化版）
# 优化点：
#   1. cudnn.benchmark（输入尺寸固定，让 cuDNN 自动选最优卷积核）
#   2. 预处理/后处理全部在 GPU 完成（颜色转换、归一化、uint8 量化）
#      —— CPU↔GPU 每帧只剩两次小体积传输（720p uint8 进 / N² uint8 出）
#   3. fp16 + inference_mode
#   4. 实测基准（RTX 5070 Laptop, fp16）：256px=46ms(22FPS) 384px=126ms 512px=276ms
#      —— cuDNN sm_120 卷积内核不成熟，实时模式用 256px；等 TensorRT/新版再提
import cv2
import torch

from app.config import ANIMEGAN_WEIGHT, USE_HALF

torch.backends.cudnn.benchmark = True


class AnimeStylizer:
    def __init__(self, device="cuda", weight=ANIMEGAN_WEIGHT, size=256):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.half = self.device.type == "cuda" and USE_HALF
        self.size = size
        self.model = torch.hub.load(
            "bryandlee/animegan2-pytorch:main", "generator",
            pretrained=weight, device=str(self.device), trust_repo=True,
        )
        if self.half:
            self.model = self.model.half()
        self.model.eval()
        # 预分配 GPU 输入缓冲（固定尺寸，配合 cudnn.benchmark）
        dtype = torch.float16 if self.half else torch.float32
        self._in = torch.empty((1, 3, size, size), dtype=dtype, device=self.device)

    @torch.inference_mode()
    def __call__(self, frame_bgr):
        img = cv2.resize(frame_bgr, (self.size, self.size))          # CPU 上唯一重活（~1-2ms）
        t = torch.from_numpy(img).to(self._in.device, non_blocking=True)
        t = t.permute(2, 0, 1)[None]                                 # CHW
        t = t.to(self._in.dtype).div_(127.5).sub_(1)                 # 原地归一化，少两次分配
        out = self.model(t)[0]                                       # CHW RGB float（GPU）
        out = out.mul(0.5).add(0.5).mul_(255).clamp_(0, 255).byte()  # 量化（GPU）
        out = out.permute(1, 2, 0)[:, :, [2, 1, 0]]                  # RGB→BGR（GPU）
        return out.contiguous().cpu().numpy()                        # 单次回传
