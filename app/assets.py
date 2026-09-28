"""Import uploaded assets into a project (background, animal animations, audio)."""
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from . import chroma, ffmpeg_util as ff
from .models import AnimSet, KeyCfg

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma"}
MAX_SPRITE_H = 512
MAX_FRAMES = 360


def imread(path: Path, flags=cv2.IMREAD_UNCHANGED) -> np.ndarray:
    """cv2.imread that works with non-ASCII Windows paths."""
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, flags)
    if img is None:
        raise ValueError(f"Không đọc được ảnh: {path.name}")
    return img


def imwrite(path: Path, img: np.ndarray, params=None):
    """cv2.imwrite for non-ASCII paths; format from the file extension."""
    ok, buf = cv2.imencode(path.suffix or ".png", img, params or [])
    if not ok:
        raise ValueError(f"Không ghi được ảnh: {path}")
    path.write_bytes(buf.tobytes())


# ---------------------------------------------------------------- video decoding ----------
def read_video(path: Path, trim_start=0.0, trim_end=0.0, max_frames=MAX_FRAMES):
    """Decode with ffmpeg -> (list of BGRA uint8 frames, fps, has_alpha)."""
    info = ff.video_info(path)
    w, h, fps = info["width"], info["height"], info["fps"]
    alpha = info["alpha"] or info["codec"] in ("vp8", "vp9") and path.suffix.lower() == ".webm"
    args = [ff.ffmpeg(), "-v", "error"]
    if info["codec"] in ("vp8", "vp9"):
        args += ["-c:v", "libvpx-vp9" if info["codec"] == "vp9" else "libvpx"]
    if trim_start > 0:
        args += ["-ss", f"{trim_start:.3f}"]
    args += ["-i", str(path)]
    if trim_end > trim_start > 0 or (trim_end > 0 and trim_start == 0):
        args += ["-t", f"{trim_end - trim_start:.3f}"]
    args += ["-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
    r = ff.run(args)
    if r.returncode != 0:
        raise RuntimeError("Không giải mã được video: " + r.stderr.decode(errors="ignore")[-300:])
    n = len(r.stdout) // (w * h * 4)
    if n == 0:
        raise RuntimeError("Video không có frame nào")
    arr = np.frombuffer(r.stdout[: n * w * h * 4], np.uint8).reshape(n, h, w, 4)
    frames = [arr[i] for i in range(n)]
    has_alpha = bool(alpha and (arr[..., 3] < 250).any())
    return frames, fps, has_alpha


def read_source(path: Path, trim_start=0.0, trim_end=0.0):
    """Any supported upload -> (BGRA frames, fps, has_alpha)."""
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return read_video(path, trim_start, trim_end)
    if ext in IMAGE_EXT:
        img = imread(path)
        return [to_bgra(img)], 24.0, img.ndim == 3 and img.shape[2] == 4
    if ext == ".zip":
        frames = []
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if Path(n).suffix.lower() in IMAGE_EXT)
            for n in names[:MAX_FRAMES]:
                img = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    frames.append(to_bgra(img))
        if not frames:
            raise ValueError("File zip không có ảnh PNG/JPG")
        has_alpha = any((f[..., 3] < 250).any() for f in frames[:3])
        return frames, 24.0, has_alpha
    raise ValueError(f"Định dạng không hỗ trợ: {ext}")


def to_bgra(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


# ---------------------------------------------------------------- keying ---------------
def key_frames(frames: list[np.ndarray], has_alpha: bool, cfg: KeyCfg) -> list[np.ndarray]:
    if has_alpha or not cfg.enabled:
        return frames
    bgr = [f[..., :3] for f in frames]
    sample = bgr[:: max(1, len(bgr) // 8)]
    if not chroma.detect_backdrop(sample):
        return frames
    key = chroma.estimate_key(sample)
    with ThreadPoolExecutor(max_workers=8) as pool:   # OpenCV/numpy release the GIL
        return list(pool.map(lambda f: chroma.key_frame(np.ascontiguousarray(f), key, cfg), bgr))


_preview_cache: dict[tuple, tuple] = {}


def _preview_source(src: Path, trim_start: float, trim_end: float):
    """Middle frame + backdrop key of a clip, cached so dragging the key sliders is fast."""
    k = (str(src), src.stat().st_mtime, trim_start, trim_end)
    if k not in _preview_cache:
        frames, _, has_alpha = read_source(src, trim_start, trim_end)
        bgr = [np.ascontiguousarray(f[..., :3]) for f in frames[:: max(1, len(frames) // 8)]]
        key = None if has_alpha or not chroma.detect_backdrop(bgr) else chroma.estimate_key(bgr)
        if len(_preview_cache) > 4:
            _preview_cache.clear()
        _preview_cache[k] = (frames[len(frames) // 2], key)
    return _preview_cache[k]


def keyed_preview(src: Path, cfg: KeyCfg, trim_start=0.0, trim_end=0.0, width=640) -> bytes:
    """Checkerboard preview of the middle frame, as JPEG bytes."""
    mid, key = _preview_source(src, trim_start, trim_end)
    out = mid if key is None or not cfg.enabled else chroma.key_frame(np.ascontiguousarray(mid[..., :3]), key, cfg)
    prev = chroma.checker_preview(out)
    h, w = prev.shape[:2]
    prev = cv2.resize(prev, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", prev, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


# ---------------------------------------------------------------- loop / stabilise -----
def best_loop(frames: list[np.ndarray], min_len: int = 12) -> tuple[int, int]:
    """Pick (start, end) so that frame[end] looks most like frame[start]."""
    n = len(frames)
    if n < min_len * 2:
        return 0, n
    small = [cv2.resize(f, (64, int(64 * f.shape[0] / f.shape[1]))).astype(np.float32) for f in frames]
    best, pair = 1e18, (0, n)
    for s in range(0, max(1, n // 3), 2):
        for e in range(s + min_len, n):
            d = float(np.mean((small[s] - small[e]) ** 2))
            if d < best:
                best, pair = d, (s, e)
    return pair


def centroid_x(alpha: np.ndarray) -> float | None:
    cols = alpha.astype(np.float32).sum(axis=0)
    tot = cols.sum()
    if tot < 1:
        return None
    return float((cols * np.arange(len(cols))).sum() / tot)


def stabilize(frames: list[np.ndarray]) -> list[np.ndarray]:
    """Remove steady horizontal drift (clip where the animal slides across the frame)."""
    xs = [centroid_x(f[..., 3]) for f in frames]
    idx = [i for i, x in enumerate(xs) if x is not None]
    if len(idx) < 4:
        return frames
    slope, icpt = np.polyfit(idx, [xs[i] for i in idx], 1)
    if abs(slope) * len(frames) < frames[0].shape[1] * 0.04:
        return frames
    out = []
    for i, f in enumerate(frames):
        shift = -slope * (i - len(frames) / 2)
        m = np.float32([[1, 0, shift], [0, 1, 0]])
        out.append(cv2.warpAffine(f, m, (f.shape[1], f.shape[0]), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)))
    return out


# ---------------------------------------------------------------- import animation -----
def import_anim(src: Path, out_dir: Path, cfg: KeyCfg, anim: AnimSet) -> AnimSet:
    frames, fps, has_alpha = read_source(src, anim.trim_start, anim.trim_end)
    frames = key_frames(frames, has_alpha, cfg)
    if anim.stabilize and len(frames) > 4:
        frames = stabilize(frames)
    if anim.auto_loop and len(frames) > 24:
        s, e = best_loop(frames)
        frames = frames[s:e]

    # union bbox of all frames so the sprite anchor stays put
    union = np.zeros(frames[0].shape[:2], bool)
    for f in frames:
        union |= f[..., 3] > 12
    if not union.any():
        raise ValueError("Sau khi tách nền không còn gì. Hãy giảm 'tolerance' hoặc tắt tách nền.")
    ys, xs = np.nonzero(union)
    pad = 4
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, union.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, union.shape[1])
    crop_h = y1 - y0
    px_scale = min(1.0, MAX_SPRITE_H / crop_h)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    def save(item):
        i, f = item
        c = f[y0:y1, x0:x1]
        if px_scale < 1:
            c = cv2.resize(c, (max(1, round(c.shape[1] * px_scale)), max(1, round(c.shape[0] * px_scale))),
                           interpolation=cv2.INTER_AREA)
        imwrite(out_dir / f"{i + 1:04d}.png", c, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        return c.shape[:2]
    with ThreadPoolExecutor(max_workers=8) as pool:
        h, w = list(pool.map(save, enumerate(frames)))[-1]
    return anim.model_copy(update={"frames": len(frames), "fps": float(fps), "width": int(w),
                                   "height": int(h), "px_scale": float(px_scale)})


def load_frames(anim_dir: Path, n: int) -> list[np.ndarray]:
    return [imread(anim_dir / f"{i + 1:04d}.png") for i in range(n)]


def anim_thumb(anim_dir: Path, n: int) -> bytes:
    f = imread(anim_dir / f"{max(1, n // 2):04d}.png")
    prev = chroma.checker_preview(to_bgra(f), cell=10)
    ok, buf = cv2.imencode(".jpg", prev, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


# ---------------------------------------------------------------- background / audio ---
def import_background(src: Path, dst: Path) -> tuple[int, int]:
    ext = src.suffix.lower()
    if ext in VIDEO_EXT:
        frames, _, _ = read_video(src, max_frames=1)
        img = frames[0][..., :3]
    else:
        img = imread(src, cv2.IMREAD_COLOR)
    imwrite(dst, img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return img.shape[1], img.shape[0]


def fit_background(path: Path, width: int, height: int) -> np.ndarray:
    """Load and cover-crop the background to exactly width x height (BGR uint8)."""
    if path and path.is_file():
        img = imread(path, cv2.IMREAD_COLOR)
    else:
        img = placeholder_background(width, height)
    h, w = img.shape[:2]
    s = max(width / w, height / h)
    nw, nh = max(width, round(w * s)), max(height, round(h * s))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x, y = (nw - width) // 2, (nh - height) // 2
    return np.ascontiguousarray(img[y:y + height, x:x + width])


def placeholder_background(width: int, height: int) -> np.ndarray:
    """Plain wooden wall + floor, used when no background was uploaded."""
    rng = np.random.default_rng(1)
    img = np.zeros((height, width, 3), np.float32)
    wall = int(height * 0.62)
    xs = np.arange(width)[None, :]
    grain = (np.sin(xs / 7.0 + rng.normal(0, 1, (wall, 1)).cumsum(0) * 0.02) * 10)
    img[:wall] = np.array([45, 85, 140], np.float32) + grain[..., None]
    plank = max(40, width // 12)
    img[:wall, ::plank] *= 0.55
    img[wall:] = np.array([30, 55, 95], np.float32)
    img[wall:wall + max(3, height // 120)] = (20, 35, 60)
    return np.clip(img, 0, 255).astype(np.uint8)


def import_audio(src: Path, dst: Path) -> float:
    r = ff.run([ff.ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", "48000",
                "-c:a", "pcm_s16le", str(dst)])
    if r.returncode != 0:
        raise RuntimeError("Không đọc được audio: " + r.stderr.decode(errors="ignore")[-300:])
    return (dst.stat().st_size - 44) / (48000 * 4)


def read_wav(path: Path) -> np.ndarray:
    """16-bit stereo 48k WAV written by import_audio -> float32 (n, 2)."""
    import wave
    with wave.open(str(path), "rb") as w:
        data = w.readframes(w.getnframes())
        ch = w.getnchannels()
    a = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
    a = a.reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    return a[:, :2]
