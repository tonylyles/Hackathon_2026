"""Deterministic procedural BGR backdrops and optional user-owned image resources."""
from pathlib import Path

import cv2
import numpy as np


BUILTIN_BACKGROUNDS = ("builtin:aurora", "builtin:sunset")
_IMAGE_SUFFIXES = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


def background_label(name: str) -> str:
    """Return a friendly display name without changing the resource identifier."""
    if name in BUILTIN_BACKGROUNDS:
        return {"builtin:aurora": "极光", "builtin:sunset": "落日"}[name]
    if isinstance(name, str) and name.startswith("user:"):
        return Path(name[5:]).stem
    return name or "无背景"


def _size(size: tuple[int, int]) -> tuple[int, int]:
    if (not isinstance(size, (tuple, list)) or len(size) != 2
            or any(not isinstance(v, (int, np.integer)) or isinstance(v, (bool, np.bool_)) or v <= 0 for v in size)):
        raise ValueError("size must be (positive width, positive height)")
    return int(size[0]), int(size[1])


def generate_background(name: str, size: tuple[int, int]) -> np.ndarray:
    """Generate one of two built-ins as a fresh uint8 BGR array of (width, height)."""
    width, height = _size(size)
    if name not in BUILTIN_BACKGROUNDS:
        raise ValueError(f"unknown built-in background: {name}")
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u, v = (x + .5) / width, (y + .5) / height
    if name == "builtin:aurora":
        band = np.exp(-((u - .5 - .20 * np.sin(v * 7)) / .24) ** 2)
        glow = np.exp(-(((u - .75) / .35) ** 2 + ((v - .18) / .32) ** 2))
        b = 55 + 65 * (1 - v) + 45 * band
        g = 22 + 112 * band + 30 * glow
        r = 45 + 70 * v + 45 * glow
    else:
        sun = np.exp(-(((u - .73) / .20) ** 2 + ((v - .34) / .25) ** 2) * 2)
        horizon = np.clip((v - .60) * 2.5, 0, 1)
        b = 105 - 65 * v + 35 * horizon
        g = 60 + 66 * sun - 25 * horizon
        r = 100 + 110 * sun + 75 * v
    return np.clip(np.rint(np.stack(np.broadcast_arrays(b, g, r), axis=-1)), 0, 255).astype(np.uint8)


def list_backgrounds(user_dir: str | Path | None = None) -> tuple[str, ...]:
    """List built-ins followed by directly contained supported files, if any."""
    if user_dir is None:
        return BUILTIN_BACKGROUNDS
    directory = Path(user_dir)
    if not directory.is_dir():
        return BUILTIN_BACKGROUNDS
    files = (p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES)
    return BUILTIN_BACKGROUNDS + tuple(f"user:{name}" for name in sorted(files, key=lambda s: (s.casefold(), s)))


def _resource_path(name, user_dir):
    if not isinstance(name, str) or not name.startswith("user:") or user_dir is None:
        raise ValueError("unknown background resource")
    filename = name[5:]
    if not filename or filename in (".", "..") or Path(filename).name != filename or "/" in filename or "\\" in filename or Path(filename).suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("invalid background filename")
    directory = Path(user_dir).resolve()
    path = directory / filename
    if not path.is_file() or path.resolve().parent != directory:
        raise ValueError("background file is missing or outside user_dir")
    return path


def cover_image(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Fill the target with a centered, aspect-preserving crop of a BGR image."""
    width, height = _size(size)
    if image is None or image.ndim != 3 or image.shape[2] != 3 or not image.size:
        raise ValueError("image must be a nonempty BGR image")
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized_width = max(width, round(source_width * scale))
    resized_height = max(height, round(source_height * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=interpolation)
    left = (resized_width - width) // 2
    top = (resized_height - height) // 2
    return resized[top:top + height, left:left + width].copy()


def load_background(name: str, size: tuple[int, int], user_dir: str | Path | None = None) -> np.ndarray:
    """Return a BGR backdrop, centered-cropped without distorting user images.

    User images are read only from direct children of user_dir. Unicode paths
    work on Windows via imdecode rather than cv2.imread.
    """
    width, height = _size(size)
    if name in BUILTIN_BACKGROUNDS:
        return generate_background(name, (width, height))
    path = _resource_path(name, user_dir)
    try:
        data = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as exc:
        raise ValueError("cannot read background image") from exc
    if image is None or image.size == 0:
        raise ValueError("cannot decode background image")
    return cover_image(image, (width, height))
