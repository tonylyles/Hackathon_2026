# Naiwa - PhotoBooth 📸

> 2026 秋季 AI 黑客松参赛项目｜中期检查点与公开作品资料草案
> 当前方向：以 VTube Studio Live2D 角色为主角的互动大头贴展台。

**项目现状：**拍照展台、照片生成和局域网扫码取件已跑通；VTube Studio 手机面捕能驱动角色，桌面端 API 已开启。VTubeStudioCam 尚未被本项目成功读取，当前拍照/录像仍来自普通摄像头，因此“用 Live2D 角色画面生成并扫码取件”的完整体验仍待打通和验收。

## 官方提交节点

- **中期检查点：2026-10-24（周六）14:00 前。**在平台「我的队伍 → 检查点提交」提交进度报告，说明队伍进度、困难和后续计划。仅本队成员和赛务组可见，不公开。
- **公开作品资料：**在「我的队伍 → 参赛作品」完善展示信息，代码仓库地址必填。若作品能在线运行或展示，还需填写可运行链接；桌面展台目前没有公开在线演示链接，不编造链接。建议先提交半成品并持续更新。
- **作品资料截止：2026-10-30（周五）22:00。**截止前可随时修改。

## 中期检查点进度报告（可复制到平台）

**项目名称：** Naiwa - PhotoBooth / VTube Studio 互动大头贴展台

**队伍进度：** 已完成桌面拍照展台原型、拍摄结果保存和局域网二维码取件流程；已接入 VTube Studio API 状态/角色控制探索。VTube Studio 中的 Live2D 角色可由手机面捕驱动。项目已开启 VTube Studio 虚拟摄像头，但展台尚未成功读到该视频源。当前版本拍照和录像仍使用普通摄像头画面，尚未完成 VTS 角色画面进入作品及扫码交付的端到端验收。

**遇到的困难：** VTubeStudioCam 在当前 Windows/OpenCV 环境中的设备识别尚未解决。枚举结果为 index 0（DSHOW）可读实景，index 1（DSHOW）可打开但测试画面全黑，index 2、3 不可用；VTS 预览区因此提示无法打开虚拟摄像头。另需验证照片与录像成片的实际视觉效果、VTS 状态异常处理和现场稳定性。旧 AnimeGAN/PyTorch 风格化代码仍在仓库中，但它不是当前选定的 VTS 展台路线，也不应作为已完成的主要体验描述。

**后续计划：** 1) 查明并验证 VTubeStudioCam 的可用采集接口/设备编号与后端；2) 将 VTS 画面设为拍照和录像的实际输入，而不只是预览；3) 完成照片、短视频、局域网扫码下载的端到端实机测试；4) 排查无 VTS、无模型、相机黑屏和网络不可用时的提示与恢复；5) 录制真实演示并更新公开作品资料。若虚拟摄像头仍不可用，先评估受支持的替代输出方案，不把普通摄像头画面冒称为 Live2D 成片。

## 公开参赛作品资料草案

以下内容用于平台「我的队伍 → 参赛作品」，发布前请队伍核对人员、演示素材及最终功能状态。

- **作品名称：**Naiwa - PhotoBooth——VTube Studio 互动大头贴
- **作品简介：**面向活动展位的桌面互动大头贴原型。计划将 VTube Studio 中由面捕驱动的 Live2D 角色画面接入拍照/短视频流程，并通过局域网二维码交付作品。目前拍照展台与扫码取件已实现；VTubeStudioCam 接入拍摄和成片流程仍在联调，现阶段不宣称该完整体验已验收。
- **当前可展示内容：**交互式桌面展台、普通摄像头拍摄结果与扫码取件；VTube Studio 手机面捕驱动角色可单独展示。具体演示应如实注明当前 VTS 虚拟摄像头输入未打通。
- **代码仓库（必填）：**https://github.com/tonylyles/Hackathon_2026
- **可运行链接：**暂不适用/待部署。当前为本地 Windows 桌面应用，没有已验证的公开在线运行地址；不要把仓库地址填作运行链接。
- **部署形态：**Windows 桌面端 + VTube Studio；本地/局域网运行与取件服务。
- **技术说明：**Python、OpenCV 桌面展台、VTube Studio API/虚拟摄像头接入探索、局域网二维码取件。仓库还保留旧 AnimeGANv2/PyTorch 与视频处理路径；它们不代表当前 VTS 方案已完成，也不应宣传为核心成果。
- **AI 使用与素材：**Live2D 角色和模型素材须按各自授权条款使用；未经明确再分发许可的模型文件不随代码仓库公开。面捕、模型和演示素材的具体来源/授权需在最终公开前逐项核对。

## 准备 VTube Studio（虚拟形象模式必需）

VTube Studio 为第三方商业软件（Steam 免费），受其用户协议保护，**本仓库不分发其安装包**，请从官方渠道获取：

1. 安装 Steam：https://store.steampowered.com/about/
2. 在 Steam 安装 VTube Studio：https://store.steampowered.com/app/1325860/VTube_Studio/
3. 首次启动 VTube Studio 后，在其设置中开启「Public API（插件接口）」与虚拟摄像头（VTubeStudioCam），加载 Live2D 模型并连接手机面捕（iOS 需安装 VTube Studio 手机端）。
4. 展台启动时会自动通过 Steam 拉起 VTube Studio（见 `app/core/vts_launcher.py` 与 `steam_appid.txt`）；首次连接时需在 VTube Studio 内确认插件授权弹窗。

仓库同样不分发 Live2D 模型文件：演示所用模型请按权利人许可自行获取，授权不明的文件请勿提交到本仓库（详见 `docs/建模素材指引.md`）。

## 开发与试运行

VTube Studio 路线不使用 PyTorch 风格化推理；仓库仍保留旧 AnimeGANv2/PyTorch 真人摄像头模式。安装依赖后，双击 `启动照相亭.bat` 默认进入 **VTS 角色拍摄**（不会回退到真人摄像头或本地 torch）；也可以在终端启动：

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main --booth --vts-preview
```

首次启动若检测到 VTube Studio 未运行，展台会尝试通过 Steam 启动一次，并在后台重连 API；在展台内可点“重试连接”。自动启动需要本机安装 Steam 和 VTube Studio，首次插件授权仍需在 VTS 内确认。请在 VTube Studio 加载角色、连接面捕、启用插件 API 及虚拟摄像头。角色画面和 VTS API 未就绪时展台会显示状态并阻止拍摄；虚拟摄像头设备编号依机器而异，需检查 `app/config.py` 中 `VTS_CAMERA_INDEX` 和实际摄像头画面。**仅显式运行 `python -m app.main --booth` 才启动旧的真人摄像头动漫风格化模式。**自动化模拟测试不代表此机器的 VTS 设备与扫码取件已通过实机验收。

测试：

```powershell
python scripts/test_cameras.py
python -m unittest discover -s tests -v
```

`test_cameras.py` 会写入本机 `tmp/` 测试帧。请人工检查图像内容以确认设备身份；设备能打开不等于画面有效。

## 目录概览

- `app/main.py`：运行入口与模式分发
- `app/ui/booth_window.py`：拍照、录像、VTS 状态/预览及取件界面
- `app/core/vts_video.py`：VTube Studio 虚拟摄像头帧读取
- `app/server/`：局域网分享服务与二维码
- `项目说明.md`：官方提交节点、检查点进度报告和公开作品资料草案
- `docs/`：验收记录、素材与授权说明
- `refs/`：本机参考资料目录，不应使用 `git add .` 将未经授权的第三方内容加入公开提交

## 已知限制与验收边界

- 目前确认展台照片结果可生成并显示扫码取件页；不据此推断录像取件或 VTS 成片已通过实机完整验收。
- VTubeStudioCam 尚未读出有效帧；普通摄像头拍摄仍是现有作品输入。
- `mock` 是无模型流程/画面测试，不是 AI 风格化，也不代表 PyTorch/CUDA 推理已验收。
- 桌面应用没有公开在线演示链接；平台如要求可运行链接，应先部署并验证后再填写。
- `refs/` 不再被 Git 整体忽略；提交时只选择已审查授权且确需公开的文件，避免 `git add .`。
- 运行时生成的照片、录像、二维码和摄像头测试帧应留在本地，不提交到公开仓库。

---

仓库开发指南与项目状态以实际代码和实机验证为准；若本文件与演示版本不一致，应先更新作品资料中的状态说明。
