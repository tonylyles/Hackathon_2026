# 交接说明 HANDOVER — Naiwa - PhotoBooth 项目全状态

> 交接对象：接手后续开发的 AI（Opus 5.5）/开发者
> 交接时间：2026-10-22 晚
> **读完本文即可接手，无需任何历史对话记录。**
> ⚠️ 本文档由前一个 AI（GLM/CodeBuddy）撰写，其中"已验证/未验证"标注经过严谨核实，可信。

---

## 一、项目是什么

**2026 秋季 AI 黑客松**（华南师大 AI 创新协会）参赛作品：**实时"二次元之镜"展台装置**。

- 路人站在摄像头前 → 大屏实时显示"动画风格的自己"（30FPS）
- 录制 4 秒动作 → 约 1 分钟生成动漫风短视频 → 扫二维码带走
- 展示评审 **10/31**，作品提交 **10/30 22:00**（代码仓库 + ≤3min 演示视频 + 说明文档 + AI 使用声明）
- 评分：完成度 30% · 技术难度 25% · 创新 20% · 协作 15% · 宣发 10%

**团队**：2 人（用户 + 队友）。用户负责推理管线（本文档作者），队友负责应用工程。

---

## 二、机器与环境（重要，全部实测）

| 项 | 值 |
|---|---|
| 开发机 | i9-14900HX + **RTX 5070 Laptop 8GB**（Blackwell 架构 sm_120）+ 32GB RAM |
| 活动工程目录 | **`C:\Users\ZhuanZ1\AI-PhotoBooth`**（纯英文路径，Git 仓库在此） |
| venv | `C:\Users\ZhuanZ1\AI-PhotoBooth\.venv`（Python 3.14） |
| Python 包 | torch **2.11.0+cu128**（CUDA 可用，已验证识别 5070）、opencv-python 5.0.0、numpy 2.5.4、fastapi/uvicorn/qrcode/PyYAML、httpx（测试用）、pygrabber+comtypes（设备名枚举） |
| ffmpeg | 9.0.2 已装，**注意：新开终端才有 PATH，旧终端需手动刷新** `$env:Path=[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User")` |
| 电源计划 | 已切高性能 |
| 废弃目录 | `D:\全栈开发\AI大头贴`（旧副本，中文路径，**别用**）；`D:\音游`（只读，无关） |
| 参考仓库镜像 | `refs/` 下 8 个（animegan2-pytorch、StreamDiffusion/V2、Practical-RIFE、Open-LLM-VTuber、photobooth-app、LivePortrait、lora-scripts），已 gitignore |

### ⚠️ 本机器的已确认硬件/系统坑（每个都实际踩过）

1. **RTX 5070 = Blackwell sm_120**：PyTorch 必须 ≥2.7 且 cu128 构建，装错报 `no kernel image available`。安装命令：`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128`
2. **中文路径会让 OpenCV/编译工具静默失败**：整个项目曾在 `D:\全栈开发\AI大头贴`，cv2.imwrite"成功"但文件写去乱码路径、Unity 的 bee 后端也崩——**所以工程已迁纯英文路径，别迁回去**
3. **控制台是 GBK 编码**：Python print ✅/emoji 会 `UnicodeEncodeError`，跑脚本一律加 `-X utf8`
4. **pip 进度条不写入重定向日志**：后台装包时看日志 Tail 永远是旧内容，要靠进程存活 + site-packages 目录变化判断

---

## 三、运行方式

```powershell
cd C:\Users\ZhuanZ1\AI-PhotoBooth
.venv\Scripts\activate
python -X utf8 scripts\check_env.py        # 环境自检（应全绿）
python -m app.main --engine anime          # 模式 A：实时风格化全屏（q退出 s截图 space切换）
python -m app.main --engine mock           # 零依赖管线验证（无模型/GPU 也能跑）
python -m app.main --video test.mp4        # 模式 B：视频风格化+合成（可用 scripts/make_test_video.py 生成素材）
python -m app.main --serve                 # 取图服务（http://localhost:8000/api/items）
python -m unittest discover -s tests -v    # 回归测试（4 项，需 ffmpeg+httpx）
```

---

## 四、当前状态（截至交接，逐项注明"怎么验证的"）

### ✅ 已完成且验证

| 项 | 验证方式 |
|---|---|
| 模式 A 实时镜子跑通（AnimeGANv2 真引擎，256px fp16，**实测 30FPS**） | 屏幕截屏：全屏动画化画面 + FPS HUD（tmp/screen*.png） |
| 性能优化：10→30FPS | perf.log 相位计时器：wait_cam 27ms / stylize 20ms / show 0.1ms |
| 模式 B 管线（mock 引擎） | 队友验收 A1~A6 通过 + 回归测试 4/4 |
| 回归测试套件 `tests/test_pipeline.py` | 本机复测 4/4 OK（装 ffmpeg 后） |
| 中文路径图片 IO | `app/core/image_io.py`（imdecode/imencode+tofile 封装） |
| 摄像头帧去重（FPS 虚高修复） | `camera.py` 帧序号 + `read(only_new=True)` |

### 🔴 未解决（接手者第一优先级）

#### 问题 1：**Camo(iPhone) 虚拟摄像头 → OpenCV 拿到的是占位图，不是真实画面**

这是当前唯一的硬阻塞。详细症状：

- 设备：iPhone 16 Pro + **Camo Studio 2.9.3**（手机装 Camo App，USB 连接电脑）
- Camo Studio **自己的预览窗口完全正常**（明亮清晰的人脸）
- 但 OpenCV 打开 "Camo" 设备：
  - MSMF 后端：能开，~29fps，但画面是**灰色占位图**（纯灰底+摄像机图标+共享图标，亮度恒定 ~130，会随图标动画轻微波动 89~153——注意这曾骗过亮度探针）
  - DSHOW 后端：能开，30fps，但画面**全黑**（亮度 0）
- 占位图截图：`tmp/matrix_i1_MSMF.png`（看过就明白）
- 已排除：手机锁屏/黑屏（占位图在手机解锁、Camo App 前台时依然出现）；fp16 数值问题（fp32 同样）；编号混淆（用 pygrabber + 截图双重确认过）

**已尝试未解决**：关闭 Camo Studio 后再开 OpenCV → index=1 设备直接消失（虚拟设备随 Studio 注册）

**下一步选项（按推荐顺序）**：
1. **换 Iriun Webcam**（免费，iOS+Windows，USB/WiFi）——与 OpenCV 兼容性口碑最好，预计 10 分钟切换。装完跑 `scripts/matrix_capture.py` 即可验证
2. 换 **DroidCam**（同级别备选）
3. 深入 Camo：查 Camo Studio 设置里是否有"虚拟摄像头分辨率/格式"选项；或抓 Camo 虚拟驱动的协商格式（Microsoft Pro apparat？）——费时，不推荐
4. 兜底：模式 A 用**笔记本内置摄像头**（`CAMERA_INDEX=0`，实测亮光下 27.8fps 可用，画质一般），iPhone 只用于模式 B 原生录像（不需要虚拟摄像头）

**验证时务必注意**：
- 摄像头画面**亮度探针会骗人**（灰色占位图均值 ~130 也会"变化"）——必须**看保存的截图**或用 `scripts/debug_stylize.py` 生成风格化结果人眼确认
- 历史教训：前一个 AI 曾两次把"暗色漩涡噪声"误判为"成功跑通"——**判定成功必须人眼看截图**

#### 问题 2：**内置摄像头（index=0 "HD Camera"）暗光下只有 ~10fps**

- 原因：暗光自动曝光拉长单帧 → 出帧率降到 10fps。亮光下实测 27.8fps（MSMF）
- 现场对策：补光灯（还没买）。代码无需改

#### 问题 3：**风格化分辨率 256px 导致画面糊**

- 实测矩阵（`scripts/conv_experiment.py`、`scripts/channels_last_test.py` 可复跑）：
  - fp16: 512px=276ms(4fps) 384px=126ms 256px=**46ms(22fps)**
  - fp32 更慢；channels_last 无改善（cuDNN 对 Blackwell sm_120 卷积内核不成熟）
- 当前策略：实时用 256px + 显示端锐化补偿（`config.py SHARPEN=True`，unsharp mask）
- **画质真正升级路线**：StreamDiffusionV2（`refs/StreamDiffusionV2`，2026 新开源，宣称免 TensorRT 实时视频扩散）——未验证，值得 1 天专项
- TensorRT 路线（512px 实时）坑多，非必要不走

---

## 五、待办清单（按优先级）

| # | 任务 | 验收标准 | 预估 |
|---|---|---|---|
| P0 | 解决 iPhone 摄像头（见问题 1，推荐换 Iriun） | 镜子画面 = iPhone 拍到的明亮实时画面（人眼截图确认） | 0.5 天 |
| P0 | `booth_window.py` 拍照/录制交互：按钮/倒计时 → 静态大头贴（选风格）或 4 秒录制 → 走管线 → 作品落 output/ | 现场无键盘操作即可完整体验一轮 | 1~1.5 天 |
| P0 | 二维码接入主流程：作品生成后自动弹二维码（`app/server/qr.py` 已有生成函数，未接） | 作品生成后屏幕出二维码，手机扫码可下载 | 0.5 天 |
| P1 | 模式 B 用真引擎（anime）跑一遍（目前只 mock 验证过） | output/ 出真风格 MP4，人眼确认 | 0.5 天 |
| P1 | 崩溃守护（watchdog 自动重启）+ output/ 磁盘清理 | 连续 1 小时压力测试不挂 | 0.5 天 |
| P1 | 硬件采购确认：大屏/显示器、手机支架（显示器顶部夹式）、补光灯、HDMI 线、排插 | 到位 | — |
| P2 | 相框/Logo 叠加（assets/frames/） | 作品带活动 Logo | 0.5 天 |
| P2 | LivePortrait 试玩（refs/LivePortrait）：AI 立绘表情驱动 | demo 跑通 | 0.5 天 |
| P2 | StreamDiffusionV2 验证（画质升级） | 512px 实时 ≥15fps 或明确放弃 | 1 天 |
| P0(10/28) | 演示视频 ≤3min + 说明文档 + AI 使用声明 | 提交物三件套 | 1 天 |

---

## 六、架构速览

```
app/
├── main.py              入口：--engine anime|mock / --video / --serve / --no-style
├── config.py            唯一配置源（摄像头编号/后端/风格预设/路径）★改摄像头只动这里
├── core/
│   ├── camera.py            采集线程：只保留最新帧 + 帧序号（read(only_new=True) 防FPS虚高）
│   │                         backend 可配（实测 Camo 用 DSHOW、内置用 MSMF）
│   ├── stylizer_anime.py    AnimeGANv2（torch.hub 入口是 "generator"+pretrained=风格名！）
│   │                         GPU 管线：cudnn.benchmark+全GPU预处理+fp16+预分配缓冲
│   ├── stylizer_mock.py     零依赖描边引擎（纯流程验收用）
│   ├── stylizer_sd.py       SD 精修照（diffusers，未实测）
│   ├── video_batch.py       模式B：抽帧→batch=8推理→帧序列（风格化帧写独立 styled_dir！）
│   ├── compose.py           ffmpeg 合成（BGM -stream_loop 循环 + -map 显式选流）
│   └── image_io.py          中文路径安全的图片读写（imdecode/imencode+tofile）
├── ui/realtime_window.py    全屏窗口：HUD、快捷键、相位计时器（[perf] 日志）、锐化后处理
└── server/api.py + qr.py    FastAPI 取图 + 二维码生成（qr 未接主流程）
scripts/                     check_env / test_cameras / fps_probe / brightness_probe /
                             matrix_capture / debug_stylize / benchmark / make_test_video
                             / acceptance 相关 / conv_experiment(实验记录，可删)
tests/test_pipeline.py       回归 4 项（需 ffmpeg+httpx）
docs/                        队友任务/资源清单/建模素材指引/1021验收记录/方案核对
```

**两人接口契约**：推理侧只需交付 `AnimeStylizer(frame)→frame` 和 `stylize_frames(paths, out_dir)`；应用侧只依赖这两个签名 + `compose.frames_to_video()`。

---

## 七、关键性能数据（RTX 5070 Laptop 8GB，高性能电源，插电）

```
AnimeGANv2 fp16：256px=46ms(22fps)  384px=126ms(8fps)  512px=276ms(4fps)
  （fp32 更慢；channels_last 无改善——cuDNN sm_120 内核不成熟，这是库的问题）
实时运行 perf.log（256px）：wait_cam≈28ms（=摄像头30fps节拍，健康）
                          stylize≈20ms  show≈7ms（含放大+锐化）→ 30FPS
当前瓶颈：画面糊 = 256px 上采样（已加锐化补偿）+ 暗光（需补光）
```

---

## 八、Git / 协作

- 远程：`https://github.com/tonylyles/Hackathon_2026`（分支 main）
- 身份（本仓库局部）：tonylyles / 2734014177@qq.com
- ⚠️ **本地有一笔未推送提交**（`7649a43` 修复摄像头配置），当时 GitHub 连接抖动 push 失败——**网络恢复后先 `git push`**
- 队友分支 `codex/mock-acceptance-1021` 已合并
- 私人备忘 `命令速查.md` 已 gitignore（只在用户电脑上）

---

## 九、给接手 AI 的三条铁律

1. **判定成功必须人眼看截图**。FPS 日志、亮度探针都可能骗人（灰色占位图均值 130 会波动、暗色 GAN 噪声曾被误判为成功）。屏幕截图 → `read_file` 看。
2. **别把工程迁回中文路径**，别用非 ASCII 路径调 cv2/编译工具。
3. **每次改完跑 `python -m unittest discover -s tests -v`**（4 项全过才算没改坏）。

## 十、合规注意（比赛规则）

- AI 素材需在《AI 使用声明》中如实申报；模型权重本地运行合规
- **禁用游戏 rip 模型**；下载的角色模型要截图保存授权条款
- 摄像头画面全程本地处理不外传（可写进展位话术）
