# video_batch.py — 模式 B：对录制视频做逐帧批处理风格化
# 设计为"文件进、帧序列出"的纯函数接口，与录制/合成解耦（两人可并行开发）
import shutil
from pathlib import Path

import cv2
import torch

from app.config import STYLE_SIZE


def extract_frames(video_path: str, out_dir: Path, max_fps_downsample=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    step = 1
    if max_fps_downsample and fps > max_fps_downsample:
        step = max(1, round(fps / max_fps_downsample))
    paths, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            p = out_dir / f"frame_{len(paths):05d}.png"
            cv2.imwrite(str(p), frame)
            paths.append(p)
        i += 1
    cap.release()
    return paths, fps / step


@torch.inference_mode()
def stylize_frames(frame_paths, stylizer, out_dir: Path, progress=None):
    """批量风格化：有 torch 模型时打包 batch 一次前向；mock 引擎走逐帧路径"""
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    model = getattr(stylizer, "model", None)
    if model is None:  # mock 等纯 CPU 引擎：逐帧
        for i, p in enumerate(frame_paths):
            o = stylizer(cv2.imread(str(p)))
            po = out_dir / f"styled_{i:05d}.png"
            cv2.imwrite(str(po), o)
            outs.append(po)
            if progress:
                progress(i + 1, len(frame_paths))
        return outs
    batch = 8
    for s in range(0, len(frame_paths), batch):
        group = frame_paths[s:s + batch]
        tensors = []
        for p in group:
            img = cv2.cvtColor(cv2.resize(cv2.imread(str(p)), (STYLE_SIZE, STYLE_SIZE)), cv2.COLOR_BGR2RGB)
            tensors.append(torch.from_numpy(img).float().permute(2, 0, 1) / 127.5 - 1)
        t = torch.stack(tensors).to(next(model.parameters()).device)
        if t.dtype != next(model.parameters()).dtype:
            t = t.half()
        res = model(t)
        for j, o in enumerate(res):
            o = o.permute(1, 2, 0).float().cpu().numpy()
            o = ((o + 1) * 127.5).clip(0, 255).astype("uint8")
            p = out_dir / f"styled_{s + j:05d}.png"
            cv2.imwrite(str(p), cv2.cvtColor(o, cv2.COLOR_RGB2BGR))
            outs.append(p)
        if progress:
            progress(min(len(outs), len(frame_paths)), len(frame_paths))
    return outs


def cleanup(dir_path: Path):
    shutil.rmtree(dir_path, ignore_errors=True)
