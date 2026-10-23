# AI PhotoBooth 📸✨

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

# 8. 交互式展台（拍照 / 4 秒风格化录像 / 扫码下载）
python -m app.main --booth --engine anime
# 无模型检查摄像头与交互窗口
python -m app.main --booth --engine mock

# 奶蛙 Live2D 控制台：先启动 VTube Studio、开启 API 并加载奶蛙模型
python -m app.main --avatar-booth
# 首次运行需在 VTube Studio 中批准插件授权；模型热键按 1-8 触发，R 刷新，Q 退出

# 9. 取图服务（单独启动时）
python -m app.main --serve
```

## 目录结构

```
app/
├── main.py              入口（模式分发）
├── config.py            全局配置：摄像头/风格预设/路径
├── core/                核心管线（纯函数式，互相解耦）
│   ├── camera.py            摄像头采集线程（始终取最新帧）
│   ├── booth.py              拍摄定时逻辑与作品安全落盘
│   ├── stylizer_anime.py    AnimeGANv2 实时风格化（模式 A）
│   ├── stylizer_sd.py       SD 生成精修照（扩展）
│   ├── video_batch.py       视频帧批处理（模式 B，文件进/帧序列出）
│   └── compose.py           ffmpeg 合成 MP4 + BGM
├── ui/
│   ├── booth_window.py       展台触屏拍照/录像/二维码
│   └── realtime_window.py   全屏预览 + HUD（FPS/按键提示）
└── server/
    ├── api.py               FastAPI 取图服务
    ├── share.py             展台嵌入式分享服务生命周期
    └── qr.py                二维码生成
scripts/
├── check_env.py         环境自检（第一个跑的脚本）
output/                  生成作品（git 忽略）
refs/                    8 个参考开源仓库的本地浅克隆（git 忽略，见下）
```

## 本地参考仓库（refs/，已 gitignore）

`git clone --depth 1` 镜像的开源参考项目，离线可查（约 260MB）：

| 本地路径 | 上游 | 用途 |
|---|---|---|
| refs/animegan2-pytorch | bryandlee/animegan2-pytorch | 模式 A 保底引擎 |
| refs/StreamDiffusion | cumulo-autumn/StreamDiffusion | 实时扩散管线 V1（TensorRT 路线） |
| refs/StreamDiffusionV2 | chenfengxu714/StreamDiffusionV2 | 实时视频扩散 V2（免 TensorRT） |
| refs/Practical-RIFE | hzwer/Practical-RIFE | 补帧时序平滑 |
| refs/Open-LLM-VTuber | Open-LLM-VTuber | 数字人全套（LLM+面捕+TTS） |
| refs/photobooth-app | photobooth-app/photobooth-app | 照相亭交互参考 |
| refs/LivePortrait | KwaiVGI/LivePortrait | 表情移植 |
| refs/lora-scripts | Akegarasu/lora-scripts | LoRA 训练整合包 |

重新镜像：`git clone --depth 1 --single-branch <上游URL> refs/<名称>`

## 分工接口契约

推理侧（甲）只需要交付：`stylize_frames(frame_paths, out_dir)` 与 `AnimeStylizer(frame)→frame`。
应用侧（乙）只依赖这两个接口 + `compose.frames_to_video()`，双方通过函数签名解耦，可完全并行。

## 已知坑

1. **RTX 5070 (Blackwell/sm_120)**：torch 必须 ≥2.7 且 cu128 构建，否则 `no kernel image available`
2. **xformers 不要装**：新架构用 PyTorch 自带 SDPA 即可
3. **8GB 显存跑 SDXL**：代码里已开 attention slicing + vae tiling + cpu offload 三件套
4. **ffmpeg**：`winget install ffmpeg` 后重开终端

## 模拟引擎验收（不下载 AI 权重）

`mock` 使用 OpenCV 描边，不代表 AI 画质或模型速度。模拟视频管线无需安装 torch；
完整环境自检仍会检查 torch/CUDA，不能将模拟管线通过视为 GPU 验收通过。

```powershell
python -m pip install -r requirements-dev.txt
# 若不安装系统 FFmpeg，可将开发依赖附带的可执行文件复制到虚拟环境：
python -c "import imageio_ffmpeg,shutil,sys; from pathlib import Path; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), Path(sys.executable).parent / 'ffmpeg.exe')"
# 请先激活 .venv，使 ffmpeg.exe 在 PATH 中
python scripts/make_test_video.py
python -m app.main --video test.mp4 --engine mock
python -m unittest discover -s tests -v
```

摄像头窗口的有界检查（各约 8 秒后关闭；mock 自动触发一次截图）：

```powershell
python -m scripts.check_realtime --no-style
python -m scripts.check_realtime
```

结果写入 `output/check_raw.json`、`output/check_mock.json`，截图也仅保存在本地。
实时窗口只处理新采集的帧，FPS 不再重复计算同一张画面；它仍不代表端到端延迟。
人工观察流畅度、拍摄延迟测量以及 Live2D 面捕验收需另外完成。
