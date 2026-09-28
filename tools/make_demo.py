"""Create a demo project with procedurally drawn animals (green-screen clips like Veo),
squeak sounds, ambience and a background, then upload them through the running tool.

    python tools/make_demo.py        (the tool must be running: run.bat)
"""
import io
import json
import math
import subprocess
import sys
import urllib.request
import uuid
import wave
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import ffmpeg_util as ff  # noqa: E402

API = "http://127.0.0.1:8765/api"
OUT = ROOT / "tools" / "demo_assets"
W, H, FPS = 640, 480, 24
SS = 3  # supersampling for smooth edges


# ------------------------------------------------------------------ drawing ------------
def backdrop(w, h):
    """Veo-like green screen: uneven green, darker bottom, soft floor shadow."""
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    g = 180 - 35 * y - 15 * (x - 0.5) ** 2
    img = np.zeros((h, w, 3), np.float32)
    img[..., 0] = 95 - 20 * y   # B
    img[..., 1] = g             # G
    img[..., 2] = 55 - 10 * y   # R
    return img


def ell(img, c, axes, ang, col):
    cv2.ellipse(img, (int(c[0] * SS), int(c[1] * SS)), (max(1, int(axes[0] * SS)), max(1, int(axes[1] * SS))),
                ang, 0, 360, col, -1, cv2.LINE_AA)


def line(img, p, q, col, t):
    cv2.line(img, (int(p[0] * SS), int(p[1] * SS)), (int(q[0] * SS), int(q[1] * SS)), col, max(1, int(t * SS)),
             cv2.LINE_AA)


def poly(img, pts, col, t):
    p = np.array([[int(a * SS), int(b * SS)] for a, b in pts], np.int32)
    cv2.polylines(img, [p], False, col, max(1, int(t * SS)), cv2.LINE_AA)


def mouse(img, ph, mode, spec):
    """Side view facing right; ph = animation phase 0..1."""
    body, dark, pink = spec["body"], spec["dark"], spec["pink"]
    cx, gy = 300, 330
    s = spec["size"]
    amp = {"idle": 0, "walk": 1, "run": 1.8}[mode]
    bob = math.sin(ph * 4 * math.pi) * 3 * amp if mode != "idle" else math.sin(ph * 2 * math.pi) * 1.5
    stretch = 1 + (0.08 * math.sin(ph * 2 * math.pi) if mode == "run" else 0)
    by = gy - 38 * s + bob
    # tail
    if spec["tail"]:
        sway = math.sin(ph * 2 * math.pi + 1) * (10 if mode == "idle" else 6)
        pts = [(cx - 60 * s * stretch + 0, by + 8 * s)]
        for i in range(1, 12):
            k = i / 11
            pts.append((cx - 60 * s * stretch - 110 * s * k, by + 8 * s + 25 * s * k * k - sway * math.sin(k * 3)))
        poly(img, pts, pink, 4 * s)
    # legs (far side darker)
    for side, colr in ((0.5, dark), (0, body)):
        for j, lx in enumerate((-38, 34)):
            a = math.sin((ph + side + j * 0.5) * 2 * math.pi) * 0.6 * amp
            hip = (cx + lx * s * stretch, by + 18 * s)
            foot = (hip[0] + math.sin(a) * 26 * s, gy - max(0, math.cos(a * 2)) * 0 - (abs(math.sin(a)) * 6 * amp))
            line(img, hip, foot, colr, 9 * s)
            ell(img, (foot[0] + 5 * s, gy - 2), (8 * s, 4 * s), 0, pink)
    # body
    ell(img, (cx, by), (72 * s * stretch, 40 * s), -4 if mode == "run" else 0, body)
    ell(img, (cx + 5, by + 14 * s), (50 * s * stretch, 20 * s), 0, spec["belly"])
    # head
    look = math.sin(ph * 2 * math.pi) * 8 if mode == "idle" else 0
    hx, hy = cx + 72 * s * stretch, by - 12 * s + look * 0.3
    ell(img, (hx, hy), (38 * s, 28 * s), -15 + look, body)
    ell(img, (hx + 36 * s, hy + 6 * s), (9 * s, 7 * s), 0, pink)               # nose
    ell(img, (hx + 10 * s, hy - 6 * s), (6 * s, 6 * s), 0, (20, 20, 20))       # eye
    ell(img, (hx + 12 * s, hy - 8 * s), (2 * s, 2 * s), 0, (240, 240, 240))
    ell(img, (hx - 14 * s, hy - 30 * s), (spec["ear"] * s, spec["ear"] * s), 0, body)     # ear
    ell(img, (hx - 14 * s, hy - 30 * s), (spec["ear"] * 0.62 * s, spec["ear"] * 0.62 * s), 0, pink)
    for d in (-6, 0, 6):                                                         # whiskers
        line(img, (hx + 32 * s, hy + 6 * s), (hx + 62 * s, hy + 6 * s + d * 1.6), (230, 230, 230), 1.2)


def ladybug(img, ph, mode, spec):
    cx, gy = 320, 320
    amp = {"idle": 0.2, "walk": 1, "run": 2}[mode]
    by = gy - 55
    for k in range(3):
        for sgn in (-1, 1):
            a = math.sin((ph * 2 + k * 0.33 + (sgn > 0) * 0.5) * 2 * math.pi) * 14 * amp
            x0 = cx - 40 + k * 40
            line(img, (x0, by + 20), (x0 + a + sgn * 6, gy - 2), (25, 25, 25), 5)
    ell(img, (cx + 82, by + 8), (30, 26), 0, (30, 30, 30))                      # head
    ell(img, (cx + 92, by), (7, 7), 0, (235, 235, 235))
    ang = math.sin(ph * 2 * math.pi) * 10 if mode == "idle" else 0
    line(img, (cx + 100, by - 12), (cx + 130, by - 45 + ang), (25, 25, 25), 3)   # antenna
    ell(img, (cx, by), (82, 58), 0, (30, 40, 215))                              # shell (BGR red)
    line(img, (cx - 80, by), (cx + 80, by), (20, 20, 20), 3)
    for dx, dy, r in ((-40, -25, 13), (10, -30, 11), (45, -12, 10), (-15, 22, 12), (35, 25, 9), (-60, 8, 9)):
        ell(img, (cx + dx, by + dy), (r, r), 0, (25, 25, 25))
    ell(img, (cx - 20, by - 35), (22, 8), -10, (120, 140, 250))                 # highlight


ANIMALS = [
    {"name": "chuột xám", "draw": mouse, "size_pct": 7, "count": 2, "freq": 3200,
     "spec": {"body": (150, 150, 158), "dark": (110, 110, 118), "belly": (200, 200, 205),
              "pink": (170, 160, 235), "ear": 22, "size": 1.0, "tail": True}},
    {"name": "hamster", "draw": mouse, "size_pct": 6, "count": 1, "freq": 2400,
     "spec": {"body": (70, 150, 225), "dark": (50, 115, 185), "belly": (215, 235, 245),
              "pink": (170, 160, 235), "ear": 15, "size": 0.95, "tail": False}},
    {"name": "bọ rùa", "draw": ladybug, "size_pct": 4, "count": 1, "freq": 5200,
     "spec": {}},
]
CLIPS = {"idle": (2.0, 1), "walk": (1.0, 1), "run": (0.5, 1)}   # seconds per cycle, cycles


def render_clip(animal, mode, dst: Path):
    period, cycles = CLIPS[mode]
    n = int(round(period * cycles * FPS)) * (2 if mode != "idle" else 1)
    bd = backdrop(W * SS, H * SS)
    proc = subprocess.Popen([ff.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16",
                             "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    for i in range(n):
        ph = (i / (period * FPS)) % 1.0
        img = bd.copy()
        # soft cast shadow on the "floor", like Veo clips
        sh = np.zeros(img.shape[:2], np.float32)
        cv2.ellipse(sh, (330 * SS, 330 * SS), (120 * SS, 12 * SS), 0, 0, 360, 1.0, -1)
        sh = cv2.GaussianBlur(sh, (0, 0), 8 * SS)
        img *= (1 - 0.35 * sh)[..., None]
        animal["draw"](img, ph, mode, animal["spec"])
        frame = cv2.resize(np.clip(img, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()


# ------------------------------------------------------------------ audio / bg ---------
def write_wav(path: Path, mono: np.ndarray, sr=48000):
    a = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())


def squeak(path: Path, f0: float, n_chirps: int, seed: int, sr=48000):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_chirps):
        d = rng.uniform(0.07, 0.16)
        t = np.arange(int(sr * d)) / sr
        f = f0 * (1 + rng.uniform(-0.1, 0.1)) * (1 + 0.35 * np.sin(np.pi * t / d))
        ph = 2 * np.pi * np.cumsum(f) / sr
        env = np.sin(np.pi * t / d) ** 2
        out.append(0.6 * env * (np.sin(ph) + 0.25 * np.sin(2 * ph)))
        out.append(np.zeros(int(sr * rng.uniform(0.04, 0.12))))
    write_wav(path, np.concatenate(out))


def ambience(path: Path, secs=20, sr=48000):
    rng = np.random.default_rng(7)
    n = sr * secs
    x = rng.normal(0, 1, n)
    b = np.cumsum(x)                               # brown-ish room tone
    b -= np.convolve(b, np.ones(4801) / 4801, "same")
    b /= np.abs(b).max()
    tick = np.zeros(n)
    for k in range(secs):                          # quiet clock tick each second
        i = k * sr
        m = min(600, n - i)
        tick[i:i + m] = np.sin(2 * np.pi * 1800 * np.arange(m) / sr) * np.exp(-np.arange(m) / 90)
    fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (sr * 0.5))  # loops seamlessly
    write_wav(path, (0.35 * b + 0.15 * tick) * fade)


def background(path: Path, w=1920, h=1080):
    rng = np.random.default_rng(3)
    img = np.zeros((h, w, 3), np.float32)
    wall = int(h * 0.58)
    xs = np.arange(w)[None, :]
    grain = np.sin(xs / 9.0 + rng.normal(0, 1, (wall, 1)).cumsum(0) * 0.015) * 9
    img[:wall] = np.array([150, 190, 215], np.float32) + grain[..., None]          # cream wall
    img[wall - 60:wall] = (60, 90, 130)                                             # baseboard
    img[wall - 64:wall - 58] = (40, 65, 100)
    fy = np.arange(h - wall)[:, None]
    img[wall:] = np.array([45, 90, 150], np.float32) + (fy / (h - wall) * 30)[..., None]   # wood floor
    for x in range(0, w, 160):
        img[wall:, x:x + 3] *= 0.6
    cv2.ellipse(img, (380, wall - 2), (70, 95), 0, 180, 360, (20, 20, 25), -1, cv2.LINE_AA)   # mouse hole
    cv2.ellipse(img, (380, wall - 2), (70, 95), 0, 180, 360, (40, 60, 90), 6, cv2.LINE_AA)
    cv2.rectangle(img, (1300, 180), (1640, 420), (70, 110, 150), 14)                # picture frame
    cv2.rectangle(img, (1314, 194), (1626, 406), (190, 170, 120), -1)
    cv2.circle(img, (1560, 250), 30, (120, 220, 250), -1, cv2.LINE_AA)
    vign = 1 - 0.25 * (((np.arange(w) / w - 0.5) ** 2)[None, :] + ((np.arange(h) / h - 0.5) ** 2)[:, None])
    img *= vign[..., None]
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8))


# ------------------------------------------------------------------ API ----------------
def call(method, url, data=None, files=None, fields=None):
    headers = {}
    body = None
    if files is not None:
        bnd = uuid.uuid4().hex
        buf = io.BytesIO()
        for k, v in (fields or {}).items():
            buf.write(f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, p in files:
            buf.write(f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{p.name}\"\r\n"
                      f"Content-Type: application/octet-stream\r\n\r\n".encode())
            buf.write(p.read_bytes())
            buf.write(b"\r\n")
        buf.write(f"--{bnd}--\r\n".encode())
        body = buf.getvalue()
        headers["Content-Type"] = f"multipart/form-data; boundary={bnd}"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + url, body, headers, method=method)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("drawing clips...")
    for i, a in enumerate(ANIMALS):
        a["files"] = {}
        for mode in CLIPS:
            p = OUT / f"animal{i}_{mode}.mp4"
            render_clip(a, mode, p)
            a["files"][mode] = p
        a["sounds"] = []
        for k in range(3):
            p = OUT / f"animal{i}_squeak{k + 1}.wav"
            squeak(p, a["freq"], 1 + k, seed=i * 10 + k)
            a["sounds"].append(p)
    ambience(OUT / "ambience_room.wav")
    background(OUT / "background_room.png")

    print("uploading...")
    p = call("POST", "/projects", {"name": "Demo - thú thử"})
    pid = p["id"]
    call("POST", f"/projects/{pid}/background", files=[("file", OUT / "background_room.png")])
    call("POST", f"/projects/{pid}/ambience", files=[("file", OUT / "ambience_room.wav")])
    for a in ANIMALS:
        p = call("POST", f"/projects/{pid}/animals", {"name": a["name"]})
        aid = p["animals"][-1]["id"]
        for mode, f in a["files"].items():
            call("POST", f"/projects/{pid}/animals/{aid}/anims/{mode}", files=[("file", f)],
                 fields={"trim_start": 0, "trim_end": 0, "auto_loop": "false", "stabilize": "true"})
            print(f"  {a['name']} {mode} ok")
        call("POST", f"/projects/{pid}/animals/{aid}/sounds", files=[("files", s) for s in a["sounds"]])
        cur = call("GET", f"/projects/{pid}")
        for an in cur["animals"]:
            if an["id"] == aid:
                an.update(size_pct=a["size_pct"], count=a["count"])
                if a["draw"] is ladybug:
                    an.update(walk_speed=[30, 60], run_speed=[90, 150], behaviors={"walk": 50, "run": 10, "idle": 30, "turn": 10, "hide": 0})
                an["key"]["shadow"] = 25
        call("PUT", f"/projects/{pid}", {"animals": cur["animals"], "area": {"x": 0.04, "y": 0.6, "w": 0.92, "h": 0.36},
                                         "render": {**cur["render"], "duration": "00:10:00", "seed": 42}})
    # key settings changed (shadow) -> re-import with the new key
    cur = call("GET", f"/projects/{pid}")
    for an in cur["animals"]:
        for mode in an["anims"]:
            call("POST", f"/projects/{pid}/animals/{an['id']}/anims/{mode}",
                 fields={"trim_start": 0, "trim_end": 0, "auto_loop": "false", "stabilize": "true"}, files=[])
    print("project:", pid)


if __name__ == "__main__":
    main()
