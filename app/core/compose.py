# compose.py — ffmpeg 合成：帧序列 + BGM → MP4（模式 B 最后一步）
# 依赖系统 ffmpeg 在 PATH 中
import subprocess
from pathlib import Path


def frames_to_video(frames_dir: Path, out_path: Path, fps=24, bgm_path=None, width=512, height=512):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y",
           "-framerate", str(fps),
           "-i", str(frames_dir / "styled_%05d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30"]
    if bgm_path and Path(bgm_path).exists():
        cmd += ["-i", str(bgm_path), "-shortest", "-c:a", "aac", "-b:a", "128k"]
    cmd.append(str(out_path))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 合成失败:\n{r.stderr[-800:]}")
    return out_path


def probe_duration(path):
    r = subprocess.run(["ffmpeg", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        return None
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + s
