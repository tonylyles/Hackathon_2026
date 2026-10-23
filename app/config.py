# config.py — 全局配置（路径 / 摄像头 / 风格预设）
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"          # 生成的作品（图片/视频）
FRAME_DIR = ROOT / "assets" / "frames"
BGM_DIR = ROOT / "assets" / "bgm"

CAMERA_INDEX = 1          # Camo 手机摄像头（已通过 MSMF 实拍确认）
CAMERA_BACKEND = "MSMF"  # MSMF | DSHOW；Camo 在 MSMF 下输出有效画面
CAMERA_W, CAMERA_H = 1280, 720

# VTube Studio public WebSocket API (enable in VTS settings).
VTS_API_URL = "ws://localhost:8001"
VTS_PLUGIN_NAME = "Naiwa Booth"
VTS_PLUGIN_DEVELOPER = "AI PhotoBooth"
VTS_TIMEOUT_SECONDS = 8

# 推理设置
DEVICE = "cuda"            # cuda | cpu
STYLE_SIZE = 512           # 离线模式 B / SD 精修的推理分辨率
REALTIME_SIZE = 256        # 模式 A 实时推理分辨率（实测 256px fp16 ≈ 22 FPS；512 ≈ 4 FPS）
                           # ↑ cuDNN 对 Blackwell(sm_120) 的卷积内核尚不成熟，等 TensorRT/新版本再上 512
REALTIME_TARGET_FPS = 30
USE_HALF = True            # fp16
SHARPEN = True             # 显示前锐化（补偿 256px 放大的模糊感）
DISPLAY_W, DISPLAY_H = 1280, 720

# 模式 B
RECORD_SECONDS = 4
RECORD_FPS = 24

# 风格预设：name -> (animegan权重名 | SD prompt, negative)
# animegan: face_paint_512_v2 / celeba_distill 两个官方权重
ANIMEGAN_WEIGHT = "face_paint_512_v2"

SD_MODEL_ID = "stabilityai/sd-turbo"   # SDXL-Turbo 换成 stabilityai/sdxl-turbo

STYLES = {
    "anime": {
        "engine": "animegan",
        "prompt": "anime style, makoto shinkai, vibrant colors, detailed background",
        "negative": "lowres, bad anatomy, extra fingers, watermark",
    },
    "cyberpunk": {
        "engine": "sd",
        "prompt": "cyberpunk portrait, neon lights, rain, blade runner style, cinematic, highly detailed",
        "negative": "lowres, deformed face, extra fingers, watermark, text",
    },
    "ghibli": {
        "engine": "sd",
        "prompt": "ghibli anime style portrait, soft lighting, painterly, warm colors",
        "negative": "lowres, deformed face, watermark, text",
    },
    "figurine": {
        "engine": "sd",
        "prompt": "chibi figurine of the person, collectible toy, product photo, studio lighting",
        "negative": "lowres, deformed, watermark, text",
    },
}
