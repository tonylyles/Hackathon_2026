# check_env.py — 环境自检（第一个要跑的脚本）
# 用法：py -3 scripts/check_env.py
import importlib
import platform
import shutil
import subprocess
import sys

OK, WARN, FAIL = "[OK]", "[WARN]", "[FAIL]"
results = []


def check(name, cond, detail="", level=None):
    icon = (OK if cond else FAIL) if level is None else level
    results.append((icon, name, detail))


print(f"Python: {platform.python_version()}  ({sys.executable})")
check("Python ≥ 3.10", sys.version_info >= (3, 10))

# torch / CUDA
try:
    import torch
    check("torch 版本", True, torch.__version__)
    cuda_ok = torch.cuda.is_available()
    check("CUDA 可用", cuda_ok)
    if cuda_ok:
        props = torch.cuda.get_device_properties(0)
        vram = props.total_memory / 1024**3
        check("GPU", True, f"{props.name} · {vram:.1f}GB")
        check("显存 ≥ 8GB", vram >= 7.5, f"{vram:.1f}GB")
        # Blackwell 架构检查：sm_120 需要 torch ≥ 2.7 + cu128
        major, minor = torch.cuda.get_device_capability(0)
        sm = f"sm_{major}{minor}"
        if major >= 12:
            ver_ok = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2]) >= (2, 7)
            check("Blackwell 架构需要 torch≥2.7+cu128", ver_ok, f"{sm} / torch {torch.__version__}")
        # 实测一次 GPU 前向
        try:
            t = torch.randn(1, 3, 512, 512, device="cuda").half()
            conv = torch.nn.Conv2d(3, 16, 3, padding=1).cuda().half()
            import time
            torch.cuda.synchronize(); t0 = time.perf_counter()
            for _ in range(10):
                conv(t)
            torch.cuda.synchronize()
            ms = (time.perf_counter() - t0) / 10 * 1000
            check("GPU 前向实测", True, f"{ms:.1f} ms/帧 (512px conv)")
        except Exception as e:
            check("GPU 前向实测", False, str(e)[:120])
except ImportError:
    check("torch 未安装", False, "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128")

# 其他依赖
for mod, pkg, tip in [
    ("cv2", "opencv-python", ""), ("fastapi", "fastapi", ""), ("qrcode", "qrcode[pil]", ""),
    ("yaml", "PyYAML", ""), ("websocket", "websocket-client", "VTube Studio API 用"),
    ("rembg", "rembg", "（可选，缺省跳过抠图）"),
    ("diffusers", "diffusers", "（可选，SD 生成用）"),
]:
    try:
        importlib.import_module(mod)
        check(pkg, True, tip)
    except ImportError:
        check(pkg, False, f"pip install {pkg}  {tip}", level=WARN if "可选" in tip else FAIL)

# ffmpeg
ff = shutil.which("ffmpeg")
check("ffmpeg 在 PATH", ff is not None, ff or "模式 B 合成必需，winget install ffmpeg")

# 摄像头
try:
    import cv2
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    ok = cap.isOpened()
    if ok:
        ok, _ = cap.read()
    cap.release()
    check("摄像头可读", ok)
except Exception as e:
    check("摄像头可读", False, str(e)[:80])

print("\n===== 环境自检结果 =====")
for icon, name, detail in results:
    print(f"{icon} {name}  {detail}")
bad = sum(1 for r in results if r[0] == FAIL)
print(f"\n{len(results) - bad}/{len(results)} 通过" + (f"，{bad} 项未通过" if bad else "，环境就绪"))
sys.exit(1 if bad else 0)
