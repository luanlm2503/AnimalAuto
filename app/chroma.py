"""Chroma key tuned for AI-generated clips (Veo etc.).

Such clips rarely have a clean #00FF00 backdrop: the green drifts, darkens towards a
corner and there is often a floor with a soft cast shadow. So the key colour is
estimated from the frame border, and the matte uses a chroma distance in YCrCb
(brightness independent) plus an optional "shadow" term that also removes dull,
darker backdrop tones.
"""
import cv2
import numpy as np

from .models import KeyCfg


def estimate_key(frames: list[np.ndarray], band: float = 0.04) -> np.ndarray:
    """Median chroma/luma of the frame borders (BGR uint8 frames) -> array([cr, cb, y])."""
    samples = []
    for f in frames:
        h, w = f.shape[:2]
        b = max(2, int(min(h, w) * band))
        ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
        for part in (ycc[:b], ycc[:, :b], ycc[:, -b:]):
            samples.append(part.reshape(-1, 3)[::7])
    s = np.concatenate(samples)
    med = np.median(s, axis=0)
    return np.array([med[1], med[2], med[0]], np.float32)


def detect_backdrop(frames: list[np.ndarray]) -> bool:
    """True when the frame border is a saturated green or blue screen."""
    key = estimate_key(frames)
    cr, cb = key[:2] - 128.0
    return float(np.hypot(cr, cb)) > 18.0


def matte(frame: np.ndarray, key: np.ndarray, cfg: KeyCfg) -> np.ndarray:
    """Returns alpha float32 0..1 (1 = keep)."""
    ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    d_cr = ycc[..., 1] - key[0]
    d_cb = ycc[..., 2] - key[1]
    dist = np.sqrt(d_cr * d_cr + d_cb * d_cb)
    if cfg.shadow > 0:
        # project onto the key's chroma direction: backdrop in shadow keeps the hue but
        # loses saturation; subject colours usually point elsewhere.
        kv = key[:2] - 128.0
        kn = kv / max(float(np.linalg.norm(kv)), 1e-3)
        cr, cb = ycc[..., 1] - 128.0, ycc[..., 2] - 128.0
        along = cr * kn[0] + cb * kn[1]
        across = np.abs(-cr * kn[1] + cb * kn[0])
        darker = ycc[..., 0] < key[2] * 1.08 + 4.0     # shadows/floor are never brighter than the screen
        shadowy = darker & (along > 4.0) & (across < cfg.shadow * 0.6 + 4.0)
        dist = np.where(shadowy, np.minimum(dist, cfg.tolerance), dist)
    soft = max(cfg.softness, 0.5)
    a = np.clip((dist - cfg.tolerance) / soft, 0.0, 1.0)
    return a.astype(np.float32)


def clean_alpha(alpha: np.ndarray, keep_largest: bool) -> np.ndarray:
    hard = (alpha > 0.5).astype(np.uint8)
    hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if keep_largest and hard.any():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
        if n > 2:
            areas = stats[1:, cv2.CC_STAT_AREA]
            biggest = areas.max()
            keep = np.zeros(n, np.uint8)
            keep[1:] = areas >= biggest * 0.08   # keep big parts (e.g. a detached tail)
            hard = keep[labels]
    # soft edge limited to the cleaned region grown by 2px
    region = cv2.dilate(hard, np.ones((5, 5), np.uint8)).astype(np.float32)
    a = alpha * region
    return cv2.GaussianBlur(a, (3, 3), 0)


def despill(frame: np.ndarray, key: np.ndarray, amount: float) -> np.ndarray:
    """Reduce the backdrop colour cast on the subject (green or blue screens)."""
    if amount <= 0:
        return frame
    f = frame.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    # key colour in RGB space: decide whether it is a green or blue screen
    cr, cb = float(key[0]) - 128, float(key[1]) - 128
    if cb > abs(cr):          # blue screen
        limit = np.maximum(g, r)
        b2 = b - np.clip(b - limit, 0, None) * amount
        f[..., 0] = b2
    else:                     # green screen
        limit = (r + b) / 2 if amount < 0.99 else np.maximum(r, b)
        limit = np.maximum(limit, np.maximum(r, b) * (1 - amount) + limit * amount)
        excess = np.clip(g - limit, 0, None)
        f[..., 1] = g - excess * amount
    return np.clip(f, 0, 255).astype(np.uint8)


def key_frame(frame: np.ndarray, key: np.ndarray, cfg: KeyCfg) -> np.ndarray:
    """BGR uint8 -> BGRA uint8 with background removed."""
    a = clean_alpha(matte(frame, key, cfg), cfg.keep_largest)
    rgb = despill(frame, key, cfg.despill)
    return np.dstack([rgb, (a * 255 + 0.5).astype(np.uint8)])


def checker_preview(bgra: np.ndarray, cell: int = 16) -> np.ndarray:
    h, w = bgra.shape[:2]
    yy, xx = np.indices((h, w))
    chk = np.where(((yy // cell + xx // cell) % 2) == 0, 205, 150).astype(np.float32)
    a = bgra[..., 3:4].astype(np.float32) / 255
    out = bgra[..., :3].astype(np.float32) * a + chk[..., None] * (1 - a)
    return out.astype(np.uint8)
