"""Pure BGR green-screen compositing for VTS frames (no device or file IO)."""
from collections import OrderedDict
from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class ChromaSettings:
    """Green excess is G - max(B, R), on the 0..255 channel scale."""

    min_green: int = 80
    threshold: float = 40.0
    edge: float = 20.0
    min_foreground_ratio: float = 0.01
    max_foreground_ratio: float = 0.90

    def __post_init__(self):
        if not isinstance(self.min_green, (int, np.integer)) or isinstance(self.min_green, (bool, np.bool_)) or not 0 <= self.min_green <= 255:
            raise ValueError("min_green must be an integer between 0 and 255")
        for name in ("threshold", "edge", "min_foreground_ratio", "max_foreground_ratio"):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if not 0 <= self.threshold <= 255 or not 0 <= self.edge <= 255:
            raise ValueError("threshold and edge must be between 0 and 255")
        if not 0 <= self.min_foreground_ratio < self.max_foreground_ratio <= 1:
            raise ValueError("foreground ratio limits must satisfy 0 <= min < max <= 1")


@dataclass(frozen=True)
class ChromaDiagnostics:
    foreground_ratio: float  # mean opacity, including antialiased edges
    keyed_ratio: float       # fraction of fully replaced pixels
    edge_ratio: float        # fraction of partially transparent pixels


class ChromaRejected(ValueError):
    """A frame whose foreground coverage falls outside the configured limits."""

    def __init__(self, diagnostics: ChromaDiagnostics):
        self.diagnostics = diagnostics
        super().__init__(f"abnormal foreground ratio: {diagnostics.foreground_ratio:.4f}")


def _check_frame(frame: np.ndarray, name: str) -> None:
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 or not all(frame.shape[:2]):
        raise ValueError(f"{name} must be a nonempty HxWx3 uint8 BGR array")


def blend_scene(base_bgr: np.ndarray, background_bgr: np.ndarray, opacity: float) -> np.ndarray:
    """Place a translucent background over a base layer without changing either source."""
    _check_frame(base_bgr, "base_bgr")
    _check_frame(background_bgr, "background_bgr")
    if base_bgr.shape != background_bgr.shape:
        raise ValueError("base_bgr and background_bgr must have identical dimensions")
    if (isinstance(opacity, (bool, np.bool_)) or not isinstance(opacity, (int, float, np.integer, np.floating))
            or not math.isfinite(opacity) or not 0 <= opacity <= 1):
        raise ValueError("opacity must be between 0 and 1")
    if opacity == 0:
        return base_bgr.copy()
    if opacity == 1:
        return background_bgr.copy()
    blended = base_bgr.astype(np.float32) * (1 - opacity) + background_bgr.astype(np.float32) * opacity
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)


def composite_chroma(vts_bgr: np.ndarray, background_bgr: np.ndarray,
                     settings: ChromaSettings = ChromaSettings()) -> tuple[np.ndarray, ChromaDiagnostics]:
    """Replace green pixels and return (new BGR frame, diagnostics).

    Threshold marks the beginning of the transition. Edge is its width; zero
    creates a hard key. Both images must have the same dimensions. Frames with
    implausible foreground coverage raise ChromaRejected (carrying diagnostics).
    Inputs are never modified.
    """
    _check_frame(vts_bgr, "vts_bgr")
    _check_frame(background_bgr, "background_bgr")
    if vts_bgr.shape != background_bgr.shape:
        raise ValueError("vts_bgr and background_bgr must have identical dimensions")
    if not isinstance(settings, ChromaSettings):
        raise ValueError("settings must be ChromaSettings")

    blue, green, red = cv2.split(vts_bgr)
    excess = green.astype(np.int16) - cv2.max(blue, red).astype(np.int16)
    eligible = green >= settings.min_green
    if settings.edge == 0:
        transparency = (eligible & (excess >= settings.threshold)).astype(np.float32)
    else:
        t = np.clip((excess.astype(np.float32) - settings.threshold) / settings.edge, 0, 1)
        transparency = np.where(eligible, t * t * (3 - 2 * t), 0)
    opacity = 1 - transparency
    keyed = transparency == 1
    edges = (transparency > 0) & (transparency < 1)
    diagnostics = ChromaDiagnostics(
        foreground_ratio=float(opacity.mean()),
        keyed_ratio=float(np.mean(keyed)),
        edge_ratio=float(np.mean(edges)),
    )
    if not settings.min_foreground_ratio <= diagnostics.foreground_ratio <= settings.max_foreground_ratio:
        raise ChromaRejected(diagnostics)
    result = vts_bgr.copy()
    cv2.copyTo(background_bgr, keyed.astype(np.uint8), result)
    if np.any(edges):
        weight = transparency[edges, None]
        blended = (vts_bgr[edges].astype(np.float32) * (1 - weight)
                   + background_bgr[edges].astype(np.float32) * weight)
        result[edges] = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    return result, diagnostics


def compose_avatar(vts_bgr: np.ndarray, background_bgr: np.ndarray,
                   settings: ChromaSettings = ChromaSettings()) -> tuple[np.ndarray, ChromaDiagnostics]:
    """Public UI entry point; see composite_chroma for validation and diagnostics."""
    return composite_chroma(vts_bgr, background_bgr, settings)


class BackgroundCatalog:
    """List backgrounds and cache bounded rendered images without sharing mutable arrays."""

    MAX_CACHE_BYTES = 48 * 1024 * 1024
    MAX_CACHE_ITEMS = 8

    def __init__(self, user_dir=None):
        self.user_dir = user_dir
        self._cache = OrderedDict()
        self._cache_bytes = 0

    @property
    def items(self) -> tuple[str, ...]:
        from app.core.backgrounds import list_backgrounds
        return list_backgrounds(self.user_dir)

    def clear_cache(self):
        self._cache.clear()
        self._cache_bytes = 0

    def resource_version(self, name):
        from pathlib import Path
        from app.core.backgrounds import BUILTIN_BACKGROUNDS, _resource_path
        if name in BUILTIN_BACKGROUNDS:
            return None
        path = _resource_path(name, self.user_dir)
        try:
            stat = path.stat()
        except OSError as exc:
            raise ValueError("background file is missing or outside user_dir") from exc
        return (str(Path(self.user_dir).resolve()), stat.st_mtime_ns, stat.st_size)

    def get(self, name: str, size: tuple[int, int]) -> np.ndarray:
        from app.core.backgrounds import _size, load_background

        size = _size(size)
        version = self.resource_version(name)
        key = (name, size, version)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].copy()
        image = load_background(name, size, self.user_dir)
        if image.nbytes <= self.MAX_CACHE_BYTES:
            # Discard old versions of the same resource and size on replacement.
            for old in list(self._cache):
                if old[:2] == key[:2] and old != key:
                    self._cache_bytes -= self._cache.pop(old).nbytes
            while self._cache and (len(self._cache) >= self.MAX_CACHE_ITEMS
                                   or self._cache_bytes + image.nbytes > self.MAX_CACHE_BYTES):
                _, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= evicted.nbytes
            self._cache[key] = image
            self._cache_bytes += image.nbytes
        return image.copy()
