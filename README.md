# FallBeats? No — AI PhotoBooth 📸✨

> 2026 秋季 AI 黑客松参赛项目（华南师大 AI 创新协会）
> 产品说明见 `项目说明.md`，本文件是**开发指南**。

## 快速开始

```powershell
# 1. 创建虚拟环境
py -3 -m venv .venv
.venv\Scripts\activate

# 2. 装 PyTorch（⚠️ 必须是 cu128 版本，RTX 5070 Blackwell 架构要求）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. 装其余依赖
pip install -r requirements.txt

# 4. 环境自检（所有 ✅ 再继续）
python scripts/check_env.py

# 5. 跑模式 A：实时风格化（首次自动下载权重）
python -m app.main

# 6. 验证摄像头原画（无风格化）
python -m app.main --no-style

# 7. 模式 B：对一段视频做风格化 + 合成 MP4（需 ffmpeg 在 PATH）
python -m app.main --video test.mp4

# 8. 取图服务（手机扫码下载）
python -m app.main --serve
```

## 目录结构

```
app/
├── main.py              入口（模式分发）
├── config.py            全局配置：摄像头/风格预设/路径
├── core/                核心管线（纯函数式，互相解耦）
│   ├── camera.py            摄像头采集线程（始终取最新帧）
│   ├── stylizer_anime.py    AnimeGANv2 实时风格化（模式 A）
│   ├── stylizer_sd.py       SD 生成精修照（扩展）
│   ├── video_batch.py       视频帧批处理（模式 B，文件进/帧序列出）
│   └── compose.py           ffmpeg 合成 MP4 + BGM
├── ui/
│   └── realtime_window.py   全屏窗口 + HUD（FPS/按键提示）
└── server/
    ├── api.py               FastAPI 取图服务
    └── qr.py                二维码生成
scripts/
├── check_env.py         环境自检（第一个跑的脚本）
output/                  生成作品（git 忽略）
```

## 分工接口契约

推理侧（甲）只需要交付：`stylize_frames(frame_paths, out_dir)` 与 `AnimeStylizer(frame)→frame`。
应用侧（乙）只依赖这两个接口 + `compose.frames_to_video()`，双方通过函数签名解耦，可完全并行。

## 已知坑

1. **RTX 5070 (Blackwell/sm_120)**：torch 必须 ≥2.7 且 cu128 构建，否则 `no kernel image available`
2. **xformers 不要装**：新架构用 PyTorch 自带 SDPA 即可
3. **8GB 显存跑 SDXL**：代码里已开 attention slicing + vae tiling + cpu offload 三件套
4. **ffmpeg**：`winget install ffmpeg` 后重开终端
