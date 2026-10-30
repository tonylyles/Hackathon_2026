"""Create an offline AnimeGAN photo comparison without changing booth behavior."""
import sys
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ANIMEGAN_WEIGHT, USE_HALF
from app.core.image_io import read_image, write_image

ORIGINAL = ROOT / "output" / "photo_134bb35e95984b429310abc14571c302.png"
OLD_RESULT = ROOT / "output" / "photo_c020955bafc445598cad9d8d241122da.png"


def load_cached_stylizer():
    repo = Path(torch.hub.get_dir()) / "bryandlee_animegan2-pytorch_main"
    weight = Path(torch.hub.get_dir()) / "checkpoints" / f"{ANIMEGAN_WEIGHT}.pt"
    if not repo.is_dir() or not weight.is_file():
        raise FileNotFoundError("AnimeGAN 本地代码或权重不存在；本脚本不会联网下载。")

    original_load = torch.hub.load

    def local_load(_repository, model_name, **kwargs):
        return original_load(str(repo), model_name, source="local", **kwargs)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    with patch("torch.hub.load", side_effect=local_load):
        model = torch.hub.load(
            "bryandlee/animegan2-pytorch:main",
            "generator",
            pretrained=ANIMEGAN_WEIGHT,
            device=str(device),
            trust_repo=True,
        )
    half = device.type == "cuda" and USE_HALF
    if half:
        model = model.half()
    model.eval()
    return model, device, half


def stylize(model, device, half, image):
    height, width = image.shape[:2]
    # AnimeGAN's generator operates on dimensions divisible by 32. Pad rather
    # than crop or distort, then remove the padding after inference.
    padded_h = ((height + 31) // 32) * 32
    padded_w = ((width + 31) // 32) * 32
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = cv2.copyMakeBorder(
        rgb, 0, padded_h - height, 0, padded_w - width, cv2.BORDER_REFLECT_101
    )
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(device)
    dtype = torch.float16 if half else torch.float32
    tensor = tensor.to(dtype).div_(127.5).sub_(1)
    with torch.inference_mode():
        result = model(tensor)[0]
    result = result[:, :height, :width].float().add(1).mul(127.5).clamp_(0, 255)
    result = result.byte().permute(1, 2, 0).cpu().numpy()
    return cv2.cvtColor(result, cv2.COLOR_RGB2BGR)


def fit_height(image, height):
    width = max(1, round(image.shape[1] * height / image.shape[0]))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA if height < image.shape[0] else cv2.INTER_CUBIC)


def make_comparison(original, old, corrected, output):
    panel_h = 540
    panels = []
    for label, image in (("Original", original), ("Previous 256x256", old), ("Corrected RGB / aspect ratio", corrected)):
        resized = fit_height(image, panel_h)
        header = np.full((54, resized.shape[1], 3), (36, 40, 48), dtype=np.uint8)
        cv2.putText(header, label, (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (245, 245, 245), 2, cv2.LINE_AA)
        panels.append(np.vstack((header, resized)))
    gap = np.full((panel_h + 54, 18, 3), (18, 20, 24), dtype=np.uint8)
    canvas = panels[0]
    for panel in panels[1:]:
        canvas = np.hstack((canvas, gap, panel))
    write_image(output, canvas)


def main():
    for path in (ORIGINAL, OLD_RESULT):
        if not path.is_file():
            raise FileNotFoundError(path)
    original = read_image(ORIGINAL)
    old = read_image(OLD_RESULT)
    model, device, half = load_cached_stylizer()
    started = time.perf_counter()
    corrected = stylize(model, device, half, original)
    elapsed = time.perf_counter() - started

    stamp = time.strftime("%Y%m%d_%H%M%S")
    output = ROOT / "output" / f"photo_corrected_{stamp}.png"
    comparison = ROOT / "output" / f"photo_comparison_{stamp}.png"
    write_image(output, corrected)
    make_comparison(original, old, corrected, comparison)

    reopened = read_image(output)
    assert reopened.shape == original.shape, (reopened.shape, original.shape)
    assert cv2.imread(str(ORIGINAL)).shape == original.shape
    print(f"Original: {ORIGINAL} {original.shape[1]}x{original.shape[0]}")
    print(f"Previous: {OLD_RESULT} {old.shape[1]}x{old.shape[0]}")
    print(f"Corrected: {output} {reopened.shape[1]}x{reopened.shape[0]}")
    print(f"Comparison: {comparison}")
    print(f"Inference: {elapsed:.2f}s on {device}; no file overwritten")


if __name__ == "__main__":
    main()
