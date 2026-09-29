"""Generate temporary transparent animal illustrations and optionally update the demo project.

Generate and inspect assets first:
    python tools/update_demo_animals.py --assets-only
Apply them to the existing demo only when ready:
    python tools/update_demo_animals.py --apply
"""
import argparse
import json
import math
import os
import urllib.request
import uuid
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "demo_assets" / "illustrations"
API = f"http://127.0.0.1:{os.environ.get('ANIMALTV_PORT', '8765')}/api"
PROJECT_ID = "demo_th_th_bd83fd"
W, H, SS, FPS = 360, 260, 3, 24

# OpenCV colors are BGR(A); all art is antialiased on a transparent canvas.

def _pt(p):
    return tuple(int(round(v * SS)) for v in p)


def ell(img, center, axes, color, angle=0, thickness=-1):
    cv2.ellipse(img, _pt(center), (max(1, round(axes[0] * SS)), max(1, round(axes[1] * SS))),
                angle, 0, 360, color, thickness if thickness < 0 else max(1, round(thickness * SS)), cv2.LINE_AA)


def line(img, p0, p1, color, width=2):
    cv2.line(img, _pt(p0), _pt(p1), color, max(1, round(width * SS)), cv2.LINE_AA)


def poly(img, points, color, thickness=-1):
    pts = np.array([_pt(p) for p in points], np.int32)
    if thickness < 0:
        cv2.fillPoly(img, [pts], color, cv2.LINE_AA)
    else:
        cv2.polylines(img, [pts], True, color, max(1, round(thickness * SS)), cv2.LINE_AA)


def canvas():
    return np.zeros((H * SS, W * SS, 4), np.uint8)


def bird(img, ph, mode):
    cx, gy = 174, 166
    step = math.sin(ph * math.tau) if mode != "idle" else 0
    bob = math.sin(ph * math.tau) * 2 if mode == "idle" else abs(step) * 3
    # Tail and feet sit behind the plump body.
    poly(img, [(119, 155 + bob), (72, 143 + bob), (112, 174 + bob)], (48, 93, 167, 255))
    line(img, (162, 194 + bob), (157 + step * 4, 210), (34, 67, 110, 255), 4)
    line(img, (184, 194 + bob), (188 - step * 4, 210), (34, 67, 110, 255), 4)
    for fx in (151 + step * 4, 188 - step * 4):
        line(img, (fx - 6, 210), (fx + 7, 210), (35, 67, 108, 255), 3)
    ell(img, (164, 158 + bob), (59, 43), (63, 139, 222, 255), -8)
    ell(img, (175, 177 + bob), (39, 19), (188, 218, 245, 255), -6)
    # Broad animated wing, lifted on every other flap.
    wing = math.sin(ph * math.tau) if mode == "run" else math.sin(ph * math.tau) * 0.35
    ell(img, (165, 142 + bob - abs(wing) * 18), (31, max(14, 34 - abs(wing) * 14)),
        (91, 171, 241, 255), -22 + wing * 38)
    for j in range(3):
        line(img, (149 + j * 8, 140 + bob), (139 + j * 10, 125 + bob - abs(wing) * 12),
             (173, 211, 250, 220), 1.6)
    ell(img, (205, 126 + bob), (34, 32), (74, 151, 232, 255), -8)
    ell(img, (216, 117 + bob), (13, 14), (242, 248, 255, 255))
    ell(img, (220, 119 + bob), (5, 6), (29, 43, 62, 255))
    ell(img, (222, 117 + bob), (2, 2), (255, 255, 255, 255))
    poly(img, [(234, 132 + bob), (265, 142 + bob), (235, 148 + bob)], (41, 158, 249, 255))
    line(img, (192, 98 + bob), (202, 83 + bob), (38, 86, 141, 255), 2)
    ell(img, (203, 82 + bob), (3, 3), (254, 208, 95, 255))


def lizard(img, ph, mode):
    cx, gy = 176, 171
    speed = 2 if mode == "run" else 1 if mode == "walk" else 0.25
    phase = ph * math.tau * speed
    bob = abs(math.sin(phase)) * (3 if mode != "idle" else 0.7)
    # Curled tapering tail, drawn behind the torso.
    pts = [(130, 166 + bob), (111, 160 + bob), (91, 148 + bob), (74, 132 + bob),
           (57, 128 + bob + 4 * math.sin(phase)), (44, 138 + bob + 4 * math.sin(phase))]
    for i in range(len(pts) - 1):
        line(img, pts[i], pts[i + 1], (57, 133, 66, 255), max(3, 13 - i * 2))
    # Four articulated legs.
    for idx, x in enumerate((133, 195)):
        swing = math.sin(phase + idx * math.pi) * (8 if mode != "idle" else 1)
        for yoff in (-3, 1):
            hip = (x, 178 + bob + yoff)
            elbow = (x + (-10 if idx == 0 else 10) + swing, 190 + bob)
            foot = (elbow[0] + (10 if idx else -10), gy + 3)
            line(img, hip, elbow, (52, 116, 55, 255), 7)
            line(img, elbow, foot, (65, 145, 67, 255), 5)
            for claw in (-4, 0, 4):
                line(img, foot, (foot[0] + claw, foot[1] + 3), (45, 97, 52, 255), 1.4)
    ell(img, (166, 163 + bob), (57, 28), (76, 164, 72, 255), -3)
    ell(img, (169, 171 + bob), (37, 13), (131, 195, 92, 255), -2)
    # Scales and dorsal ridge add texture without chroma-key colors.
    for x in range(133, 202, 12):
        ell(img, (x, 150 + bob + ((x // 12) % 2) * 5), (3, 2), (39, 111, 56, 255))
    ell(img, (215, 151 + bob), (34, 25), (83, 174, 77, 255), -13)
    ell(img, (229, 144 + bob), (11, 9), (243, 203, 65, 255))
    ell(img, (232, 144 + bob), (3, 6), (24, 38, 26, 255))
    ell(img, (231, 141 + bob), (1.7, 2), (255, 255, 255, 255))
    line(img, (233, 163 + bob), (247, 168 + bob), (48, 105, 52, 255), 2)
    ell(img, (250, 169 + bob), (3, 2), (49, 105, 54, 255))


def butterfly(img, ph, mode):
    cx, cy = 180, 143 + (math.sin(ph * math.tau) * 2 if mode == "idle" else 0)
    flap = math.sin(ph * math.tau * (3.0 if mode == "run" else 1.0 if mode == "walk" else 0.5))
    spread = 0.38 + 0.62 * abs(flap)
    # Antennae and slender body.
    line(img, (179, 119), (170, 97), (54, 55, 83, 255), 2)
    line(img, (181, 119), (192, 96), (54, 55, 83, 255), 2)
    ell(img, (170, 96), (3, 3), (54, 55, 83, 255))
    ell(img, (192, 95), (3, 3), (54, 55, 83, 255))
    # Four patterned wings hinge around the thorax; opacity remains fully alpha-backed.
    for side in (-1, 1):
        upper = [(180, 134), (180 + side * 20 * spread, 85), (180 + side * 68 * spread, 72),
                 (180 + side * 79 * spread, 111), (180 + side * 35 * spread, 143)]
        lower = [(180, 145), (180 + side * 38 * spread, 138), (180 + side * 56 * spread, 168),
                 (180 + side * 33 * spread, 195), (180 + side * 9 * spread, 169)]
        poly(img, upper, (194, 110, 233, 230))
        poly(img, lower, (237, 157, 248, 230))
        poly(img, upper, (125, 67, 193, 255), 2)
        poly(img, lower, (125, 67, 193, 255), 2)
        ell(img, (180 + side * 49 * spread, 105), (9, 12), (247, 211, 102, 255))
        ell(img, (180 + side * 34 * spread, 165), (5, 7), (246, 204, 91, 255))
        line(img, (180, 145), (180 + side * 57 * spread, 90), (249, 211, 247, 190), 1.2)
        line(img, (180, 149), (180 + side * 44 * spread, 181), (255, 226, 251, 190), 1.2)
    ell(img, (180, 145), (8, 35), (60, 69, 107, 255), -2)
    ell(img, (180, 118), (10, 10), (70, 76, 117, 255))
    ell(img, (177, 115), (2, 2), (255, 255, 255, 255))


ANIMALS = {
    "chim": {"draw": bird, "size_pct": 8, "count": 1,
              "behaviors": {"walk": 18, "run": 0, "idle": 34, "turn": 3, "hide": 0, "fly": 45},
              "flight": {"enabled": True, "anim": "run", "speed": [260, 430], "altitude": [0.13, 0.32],
                         "legs": [1, 3], "hover": 0.05, "wobble": 2, "wobble_hz": 2.4}},
    "thằn lằn": {"draw": lizard, "size_pct": 8, "count": 1,
                 "behaviors": {"walk": 23, "run": 16, "idle": 52, "turn": 7, "hide": 2, "fly": 0},
                 "flight": {"enabled": False}},
    "bướm": {"draw": butterfly, "size_pct": 5, "count": 2,
              "behaviors": {"walk": 5, "run": 0, "idle": 35, "turn": 2, "hide": 0, "fly": 58},
              "flight": {"enabled": True, "anim": "run", "speed": [105, 175], "altitude": [0.07, 0.26],
                         "legs": [2, 4], "hover": 0.38, "wobble": 12, "wobble_hz": 3.2}},
}
MODES = ("idle", "walk", "run")


def _frame(spec, mode, phase):
    img = canvas()
    spec["draw"](img, phase, mode)
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)


def make_assets():
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = []
    for animal, spec in ANIMALS.items():
        for mode in MODES:
            frames = 48 if mode == "idle" else 24
            zf = OUT / f"{animal}_{mode}.zip"
            thumbs = []
            with zipfile.ZipFile(zf, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for i in range(frames):
                    phase = i / frames
                    img = _frame(spec, mode, phase)
                    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                    if not ok:
                        raise RuntimeError("Could not encode illustration PNG")
                    z.writestr(f"{i + 1:04d}.png", buf.tobytes())
                    if i in (0, frames // 4, frames // 2, 3 * frames // 4):
                        checker = np.full((H, W, 3), 232, np.uint8)
                        for y in range(0, H, 20):
                            for x in range(0, W, 20):
                                if ((x // 20) + (y // 20)) % 2:
                                    checker[y:y+20, x:x+20] = 205
                        a = img[..., 3:4].astype(np.float32) / 255
                        checker = (img[..., :3] * a + checker * (1 - a)).astype(np.uint8)
                        thumbs.append(cv2.resize(checker, (180, 130)))
            sheets.append((f"{animal} / {mode}", thumbs))
            spec.setdefault("files", {})[mode] = zf
    sheet = np.full((len(sheets) * 156, 746, 3), 246, np.uint8)
    for i, (label, thumbs) in enumerate(sheets):
        x = 5
        tile_y = i * 156
        ascii_label = label.encode("ascii", "replace").decode("ascii")
        cv2.putText(sheet, ascii_label, (x, tile_y + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (35, 39, 48), 1, cv2.LINE_AA)
        for j, thumb in enumerate(thumbs):
            sheet[tile_y + 22:tile_y + 152, x + j * 184:x + j * 184 + 180] = thumb
    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Could not encode contact sheet")
    (OUT / "contact_sheet.jpg").write_bytes(buf.tobytes())
    return OUT / "contact_sheet.jpg"


def api_call(method, path, data=None, file=None):
    headers, body = {}, None
    if file:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\n"
                f"Content-Type: application/zip\r\n\r\n").encode() + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, body, headers, method=method)
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read())


def apply_demo():
    project = api_call("GET", f"/projects/{PROJECT_ID}")
    animal_by_name = {a["name"]: a for a in project["animals"]}
    old_names = {"hamster", "bọ rùa"}
    for name, spec in ANIMALS.items():
        a = animal_by_name.get(name)
        if not a:
            project = api_call("POST", f"/projects/{PROJECT_ID}/animals", {"name": name})
            a = project["animals"][-1]
        aid = a["id"]
        for mode in MODES:
            api_call("POST", f"/projects/{PROJECT_ID}/animals/{aid}/anims/{mode}",
                     file=spec["files"][mode])
        project = api_call("GET", f"/projects/{PROJECT_ID}")
        a = next(x for x in project["animals"] if x["id"] == aid)
        a.update(size_pct=spec["size_pct"], count=spec["count"],
                 walk_speed=[35, 70] if name != "bướm" else [10, 25],
                 run_speed=[180, 300] if name == "chim" else [320, 560] if name == "thằn lằn" else [80, 140],
                 pause=[0.8, 3.5], behaviors=spec["behaviors"], flight=spec["flight"], sound_enabled=False,
                 area={"x": 0.04, "y": 0.56, "w": 0.92, "h": 0.40})
        api_call("PUT", f"/projects/{PROJECT_ID}", {"animals": project["animals"]})
        print(f"Updated {name}: idle/walk/run transparent illustrations installed")
    # Retire the replaced demo entries only after all three new animals are safely imported.
    project = api_call("GET", f"/projects/{PROJECT_ID}")
    for a in project["animals"]:
        if a["name"] in old_names:
            api_call("DELETE", f"/projects/{PROJECT_ID}/animals/{a['id']}")
            print(f"Removed {a['name']} from the demo (source uploads remain in src/)")
    final = api_call("GET", f"/projects/{PROJECT_ID}")
    print("Demo lineup:", ", ".join(a["name"] for a in final["animals"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--assets-only", action="store_true", help="generate illustrations and contact sheet only")
    mode.add_argument("--apply", action="store_true", help="update the existing demo project via the local app API")
    args = parser.parse_args()
    sheet = make_assets()
    print("Contact sheet generated.")
    if args.apply:
        apply_demo()


if __name__ == "__main__":
    main()
