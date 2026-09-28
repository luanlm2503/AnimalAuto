"""Locate ffmpeg/ffprobe and detect usable encoders."""
import glob
import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _candidates(exe: str):
    yield shutil.which(exe)
    yield str(ROOT / "bin" / f"{exe}.exe")
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        yield os.path.join(local, "Microsoft", "WinGet", "Links", f"{exe}.exe")
        yield from sorted(glob.glob(os.path.join(
            local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", f"{exe}.exe"),
            recursive=True), reverse=True)


@lru_cache(maxsize=None)
def find(exe: str) -> str:
    for c in _candidates(exe):
        if c and os.path.isfile(c):
            return c
    raise RuntimeError(f"Không tìm thấy {exe}. Cài bằng: winget install Gyan.FFmpeg "
                       f"hoặc chép {exe}.exe vào {ROOT / 'bin'}")


def ffmpeg() -> str:
    return find("ffmpeg")


def ffprobe() -> str:
    return find("ffprobe")


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    return subprocess.run(args, creationflags=NO_WINDOW, **kw)


def popen(args: list[str], **kw) -> subprocess.Popen:
    return subprocess.Popen(args, creationflags=NO_WINDOW, **kw)


def probe(path: str | Path) -> dict:
    r = run([ffprobe(), "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe lỗi: {r.stderr.decode(errors='ignore')[-400:]}")
    return json.loads(r.stdout)


def video_info(path: str | Path) -> dict:
    info = probe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise RuntimeError("File không có hình")
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "24/1").split("/")
    fps = float(num) / float(den) if float(den) else 24.0
    dur = float(v.get("duration") or info["format"].get("duration") or 0)
    alpha = v.get("tags", {}).get("alpha_mode") == "1" or "a" in v.get("pix_fmt", "")[:6]
    return {"width": int(v["width"]), "height": int(v["height"]), "fps": fps or 24.0,
            "duration": dur, "codec": v.get("codec_name", ""), "alpha": alpha}


@lru_cache(maxsize=None)
def nvenc_available() -> bool:
    try:
        r = run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
                 "-t", "1", "-c:v", "h264_nvenc", "-f", "null", "-"], timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def resolve_encoder(name: str) -> str:
    if name in ("auto", "h264_nvenc") and nvenc_available():
        return "h264_nvenc"
    return "libx264"


def encoder_args(encoder: str, crf: int, fps: int) -> list[str]:
    gop = str(int(fps) * 4)
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 3),
                "-b:v", "0", "-pix_fmt", "yuv420p", "-g", gop]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-g", gop, "-threads", "2"]
