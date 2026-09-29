"""Local web app: python -m app.main  ->  http://localhost:8765"""
import math
import os
import secrets
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import assets, ffmpeg_util as ff, store
from .jobs import Job, JobQueue, progress_cb
from .models import ANIMS, Animal, AnimSet, KeyCfg, Project, parse_duration
from .render import default_workers, render, render_preview
from .timeline import build_timeline

PORT = int(os.environ.get("ANIMALTV_PORT", 8765))
WEB = store.ROOT / "web"
app = FastAPI(title="Animal TV Generator")
jobs = JobQueue()
store.PROJECTS.mkdir(parents=True, exist_ok=True)
store.OUTPUT.mkdir(parents=True, exist_ok=True)
_locks: dict[str, threading.Lock] = {}


def lock(pid: str) -> threading.Lock:
    return _locks.setdefault(pid, threading.Lock())


def get_project(pid: str) -> Project:
    try:
        return store.load_project(pid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Không tìm thấy project")


def get_animal(p: Project, aid: str) -> Animal:
    for a in p.animals:
        if a.id == aid:
            return a
    raise HTTPException(404, "Không tìm thấy con vật")


def save_upload(up: UploadFile, dst_dir: Path, allowed: set[str]) -> Path:
    ext = Path(up.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Định dạng {ext or '?'} không hỗ trợ. Cho phép: {', '.join(sorted(allowed))}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    stem = store.slug(Path(up.filename).stem, "file")
    dst = dst_dir / f"{stem}_{secrets.token_hex(2)}{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(up.file, f, 1 << 20)
    return dst


def rel(p: Project, path: Path) -> str:
    return path.relative_to(store.project_dir(p.id)).as_posix()


@app.exception_handler(ValueError)
async def value_error(_, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(RuntimeError)
async def runtime_error(_, e: RuntimeError):
    return JSONResponse({"detail": str(e)}, status_code=500)


# ------------------------------------------------------------------ system ---------------
@app.get("/api/system")
def system():
    try:
        ffmpeg = ff.ffmpeg()
        encoder = ff.resolve_encoder("auto")
    except RuntimeError as e:
        ffmpeg, encoder = str(e), None
    return {"ffmpeg": ffmpeg, "encoder": encoder, "workers": default_workers(),
            "cpu": os.cpu_count(), "output": str(store.OUTPUT)}


@app.post("/api/open-output")
def open_output():
    if os.name == "nt":
        subprocess.Popen(["explorer", str(store.OUTPUT)])
    return {"ok": True}


# ------------------------------------------------------------------ projects -------------
@app.get("/api/projects")
def projects():
    return store.list_projects()


@app.post("/api/projects")
def new_project(name: str = Body("Mouse TV", embed=True)):
    return store.create_project(name)


@app.get("/api/projects/{pid}")
def project(pid: str):
    return get_project(pid)


ANIM_UI_FIELDS = ("loop", "native_speed", "scale")


@app.put("/api/projects/{pid}")
def update_project(pid: str, data: dict = Body(...)):
    """Save settings from the UI. Asset fields (animal list, clips, sounds, background, ambience)
    are owned by the upload endpoints, so a stale autosave can never drop a fresh upload."""
    with lock(pid):
        cur = get_project(pid)
        ui = {a.get("id"): a for a in data.get("animals", []) if isinstance(a, dict)}
        animals = []
        for a in cur.animals:
            d = a.model_dump()
            u = ui.get(a.id)
            if u:
                d.update({k: v for k, v in u.items() if k not in ("id", "anims", "sounds")})
                for name, an in (u.get("anims") or {}).items():
                    if name in d["anims"] and isinstance(an, dict):
                        d["anims"][name].update({k: an[k] for k in ANIM_UI_FIELDS if k in an})
            animals.append(d)
        merged = cur.model_dump()
        merged.update({k: v for k, v in data.items() if k in ("name", "area", "ambience_volume", "render")})
        merged["animals"] = animals
        return store.save_project(Project.model_validate(merged))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    get_project(pid)
    shutil.rmtree(store.project_dir(pid), ignore_errors=True)
    return {"ok": True}


# ------------------------------------------------------------------ uploads --------------
@app.post("/api/projects/{pid}/background")
def upload_background(pid: str, file: UploadFile = File(...)):
    p = get_project(pid)
    d = store.project_dir(pid) / "src"
    src = save_upload(file, d, assets.IMAGE_EXT | assets.VIDEO_EXT)
    dst = store.project_dir(pid) / "assets" / f"background_{secrets.token_hex(2)}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    w, h = assets.import_background(src, dst)
    with lock(pid):
        p = get_project(pid)
        old = store.project_dir(pid) / p.background if p.background else None
        p.background = rel(p, dst)
        store.save_project(p)
    if old and old.is_file():
        old.unlink(missing_ok=True)
    return {"project": p, "width": w, "height": h}


@app.get("/api/projects/{pid}/background.jpg")
def background_image(pid: str):
    """Background as rendered (cover-cropped to the render aspect), or the placeholder."""
    import cv2
    p = get_project(pid)
    w = 1280
    h = round(w * p.render.height / p.render.width)
    img = assets.fit_background(store.project_dir(pid) / p.background if p.background else None, w, h)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/animals")
def add_animal(pid: str, name: str = Body("mouse", embed=True)):
    with lock(pid):
        p = get_project(pid)
        a = Animal(id=f"{store.slug(name, 'animal')}_{secrets.token_hex(2)}", name=name,
                   area=p.area.model_copy(deep=True))
        p.animals.append(a)
        return store.save_project(p)


@app.delete("/api/projects/{pid}/animals/{aid}")
def remove_animal(pid: str, aid: str):
    with lock(pid):
        p = get_project(pid)
        get_animal(p, aid)
        p.animals = [a for a in p.animals if a.id != aid]
        shutil.rmtree(store.project_dir(pid) / "animals" / aid, ignore_errors=True)
        return store.save_project(p)


def _check_anim(anim: str):
    if anim not in ANIMS:
        raise HTTPException(400, f"anim phải là một trong {ANIMS}")


@app.post("/api/projects/{pid}/animals/{aid}/anims/{anim}")
def upload_anim(pid: str, aid: str, anim: str, file: UploadFile | None = File(None),
                trim_start: float = Form(0.0), trim_end: float = Form(0.0),
                auto_loop: bool = Form(False), stabilize: bool = Form(True)):
    """Upload a clip (or re-import the existing one when no file is sent, e.g. after key changes)."""
    _check_anim(anim)
    p = get_project(pid)
    a = get_animal(p, aid)
    pdir = store.project_dir(pid)
    old = a.anims.get(anim, AnimSet())
    if file is not None and file.filename:
        src = save_upload(file, pdir / "src", assets.VIDEO_EXT | assets.IMAGE_EXT | {".zip"})
    elif old.src and (pdir / old.src).is_file():
        src = pdir / old.src
    else:
        raise HTTPException(400, "Chưa có file")
    cfg = old.model_copy(update={"src": rel(p, src), "trim_start": trim_start, "trim_end": trim_end,
                                 "auto_loop": auto_loop, "stabilize": stabilize})
    new = assets.import_anim(src, pdir / "animals" / aid / anim, a.key, cfg)
    new.key_used = a.key.model_dump()
    with lock(pid):
        p = get_project(pid)
        a = get_animal(p, aid)
        prev_src = a.anims.get(anim).src if a.anims.get(anim) else ""
        a.anims[anim] = new
        store.save_project(p)
    used = {x.src for an in p.animals for x in an.anims.values()}
    if prev_src and prev_src not in used:
        (pdir / prev_src).unlink(missing_ok=True)
    return p


@app.delete("/api/projects/{pid}/animals/{aid}/anims/{anim}")
def remove_anim(pid: str, aid: str, anim: str):
    _check_anim(anim)
    with lock(pid):
        p = get_project(pid)
        a = get_animal(p, aid)
        a.anims.pop(anim, None)
        shutil.rmtree(store.project_dir(pid) / "animals" / aid / anim, ignore_errors=True)
        return store.save_project(p)


@app.post("/api/projects/{pid}/animals/{aid}/anims/{anim}/key-preview")
def key_preview(pid: str, aid: str, anim: str, key: KeyCfg = Body(...),
                trim_start: float = Body(0.0), trim_end: float = Body(0.0)):
    _check_anim(anim)
    p = get_project(pid)
    a = get_animal(p, aid)
    an = a.anims.get(anim)
    if not an or not an.src:
        raise HTTPException(400, "Chưa upload clip")
    jpg = assets.keyed_preview(store.project_dir(pid) / an.src, key, trim_start, trim_end)
    return Response(jpg, media_type="image/jpeg")


@app.get("/api/projects/{pid}/animals/{aid}/anims/{anim}/thumb")
def anim_thumb(pid: str, aid: str, anim: str):
    _check_anim(anim)
    p = get_project(pid)
    an = get_animal(p, aid).anims.get(anim)
    if not an or an.frames <= 0:
        raise HTTPException(404, "Chưa có animation")
    return Response(assets.anim_thumb(store.project_dir(pid) / "animals" / aid / anim, an.frames),
                    media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/projects/{pid}/animals/{aid}/anims/{anim}/frame/{idx}")
def anim_frame(pid: str, aid: str, anim: str, idx: int):
    _check_anim(anim)
    p = get_project(pid)
    an = get_animal(p, aid).anims.get(anim)
    if not an or not (0 <= idx < an.frames):
        raise HTTPException(404, "Không có frame")
    return FileResponse(store.project_dir(pid) / "animals" / aid / anim / f"{idx + 1:04d}.png",
                        headers={"Cache-Control": "max-age=60"})


@app.get("/api/projects/{pid}/animals/{aid}/anims/{anim}/sheet")
def anim_sheet(pid: str, aid: str, anim: str, h: int = 200):
    """All frames of an animation as one PNG grid, for the live preview in the browser."""
    import cv2
    import numpy as np
    _check_anim(anim)
    p = get_project(pid)
    an = get_animal(p, aid).anims.get(anim)
    if not an or an.frames <= 0:
        raise HTTPException(404, "Chưa có animation")
    frames = assets.load_frames(store.project_dir(pid) / "animals" / aid / anim, an.frames)
    ch = max(1, min(h, an.height))
    cw = max(1, round(an.width * ch / max(an.height, 1)))
    cols = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / cols)
    sheet = np.zeros((rows * ch, cols * cw, 4), np.uint8)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = cv2.resize(assets.to_bgra(f), (cw, ch),
                                                                     interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", sheet, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    return Response(buf.tobytes(), media_type="image/png",
                    headers={"X-Cols": str(cols), "X-Cell-W": str(cw), "X-Cell-H": str(ch),
                             "X-Frames": str(len(frames)), "Cache-Control": "max-age=3600"})


@app.post("/api/projects/{pid}/live")
def live_timeline(pid: str, seconds: float = Body(120.0, embed=True), seed: int = Body(1, embed=True)):
    """Short timeline for the in-browser live preview (same engine as the real render)."""
    p = get_project(pid)
    tl = build_timeline(p, seed, min(max(seconds, 10.0), 600.0), p.render.width / p.render.height)
    r = lambda v, n=1: round(v, n)
    return {"ref": [tl.ref_w, tl.ref_h], "duration": tl.duration,
            "tracks": [{"animal": p.animals[t.animal].id,
                        "instance": t.instance,
                        "segs": [[r(s.t0, 3), r(s.t1, 3), s.kind, r(s.x0), r(s.y0), r(s.cx), r(s.cy),
                                  r(s.x1), r(s.y1), s.anim, s.face, r(s.accel, 3), r(s.phase0, 2),
                                  r(s.z0), r(s.z1), r(s.dist, 2)] for s in t.segs]} for t in tl.tracks],
            "sounds": [[r(e.t, 2), p.animals[e.animal].id, e.file, r(e.volume, 2)] for e in tl.sounds]}


@app.post("/api/projects/{pid}/animals/{aid}/sounds")
def upload_sounds(pid: str, aid: str, files: list[UploadFile] = File(...)):
    pdir = store.project_dir(pid)
    get_animal(get_project(pid), aid)
    added = []
    for up in files:
        src = save_upload(up, pdir / "src", assets.AUDIO_EXT)
        dst = pdir / "sounds" / f"{src.stem}.wav"
        dst.parent.mkdir(parents=True, exist_ok=True)
        assets.import_audio(src, dst)
        src.unlink(missing_ok=True)
        added.append(dst)
    with lock(pid):
        p = get_project(pid)
        a = get_animal(p, aid)
        a.sounds += [rel(p, d) for d in added]
        return store.save_project(p)


@app.delete("/api/projects/{pid}/animals/{aid}/sounds")
def remove_sound(pid: str, aid: str, file: str = Body(..., embed=True)):
    with lock(pid):
        p = get_project(pid)
        a = get_animal(p, aid)
        if file in a.sounds:
            a.sounds.remove(file)
            (store.project_dir(pid) / file).unlink(missing_ok=True)
        return store.save_project(p)


@app.post("/api/projects/{pid}/ambience")
def upload_ambience(pid: str, file: UploadFile = File(...)):
    pdir = store.project_dir(pid)
    get_project(pid)
    src = save_upload(file, pdir / "src", assets.AUDIO_EXT)
    dst = pdir / "sounds" / f"ambience_{src.stem}.wav"
    dst.parent.mkdir(parents=True, exist_ok=True)
    assets.import_audio(src, dst)
    src.unlink(missing_ok=True)
    with lock(pid):
        p = get_project(pid)
        if p.ambience:
            (pdir / p.ambience).unlink(missing_ok=True)
        p.ambience = rel(p, dst)
        return store.save_project(p)


@app.delete("/api/projects/{pid}/ambience")
def remove_ambience(pid: str):
    with lock(pid):
        p = get_project(pid)
        if p.ambience:
            (store.project_dir(pid) / p.ambience).unlink(missing_ok=True)
        p.ambience = ""
        return store.save_project(p)


# ------------------------------------------------------------------ rendering ------------
def _ready(p: Project):
    if not any(an.frames > 0 for a in p.animals if a.enabled for an in a.anims.values()):
        raise HTTPException(400, "Chưa có con vật nào đang bật và có clip. Hãy upload ít nhất 1 clip idle/walk/run.")


@app.post("/api/projects/{pid}/preview")
def preview(pid: str, seconds: float = Body(60.0, embed=True)):
    p = get_project(pid)
    _ready(p)
    seed = p.render.seed

    def run(job: Job):
        meta = render_preview(p, store.project_dir(pid), min(max(seconds, 5), 300), seed=seed,
                              progress=progress_cb(job), stop=job.stop)
        meta["folder"] = "preview"
        return meta
    return jobs.submit("preview", pid, f"Preview {int(seconds)}s — {p.name}", run).public()


def _submit_render(p: Project, seed):
    r = p.render
    dur = parse_duration(r.duration)
    if dur <= 0:
        raise HTTPException(400, "Thời lượng phải > 0")
    title = f"{p.name} · {r.duration} · {r.width}x{r.height}@{r.fps}"

    def run(job: Job):
        return render(p, store.project_dir(p.id), duration=dur, width=r.width, height=r.height, fps=r.fps,
                      seed=seed, chunk_seconds=r.chunk_seconds, progress=progress_cb(job), stop=job.stop)
    return jobs.submit("render", p.id, title, run).public()


@app.post("/api/projects/{pid}/render")
def render_video(pid: str):
    p = get_project(pid)
    _ready(p)
    return _submit_render(p, p.render.seed)


@app.post("/api/projects/{pid}/batch")
def batch(pid: str, count: int = Body(3, embed=True)):
    p = get_project(pid)
    _ready(p)
    if not 1 <= count <= 50:
        raise HTTPException(400, "Số video batch từ 1 đến 50")
    # every video gets its own random seed; names are assigned when each render starts
    return [_submit_render(p, None) for _ in range(count)]


@app.get("/api/jobs")
def list_jobs():
    return jobs.list()


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.jobs.get(jid)
    if not j:
        raise HTTPException(404, "Không có job")
    return j.public()


@app.delete("/api/jobs/{jid}")
def cancel_job(jid: str):
    j = jobs.cancel(jid)
    if not j:
        raise HTTPException(404, "Không có job")
    if j.status not in ("queued", "running"):
        jobs.remove(jid)
    return j.public()


@app.get("/api/outputs")
def outputs():
    import json
    out = []
    for f in sorted(store.OUTPUT.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        if f.name.endswith(".timeline.json"):
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mp4 = store.OUTPUT / m.get("file", "")
        if mp4.is_file():
            out.append({k: m.get(k) for k in ("file", "thumbnail", "seed", "duration", "width", "height",
                                              "fps", "render_seconds", "created")} |
                       {"size_mb": round(mp4.stat().st_size / 2 ** 20, 1)})
    return out[:100]


# ------------------------------------------------------------------ static ---------------
app.mount("/output", StaticFiles(directory=store.OUTPUT), name="output")
app.mount("/projects", StaticFiles(directory=store.PROJECTS), name="projects")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/web", StaticFiles(directory=WEB), name="web")


def main():
    import uvicorn
    if not os.environ.get("ANIMALTV_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
