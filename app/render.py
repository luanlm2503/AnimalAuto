"""Long video rendering: timeline -> parallel video chunks -> concat + one continuous audio track.

Video is split into chunks rendered by a process pool; each worker pipes raw BGR frames into
its own ffmpeg. Audio is mixed chunk by chunk in the main process and streamed into a single
AAC encoder, so there are no clicks at chunk boundaries. Finished chunks are kept in the work
directory, so re-running the same render (same project, seed and settings) resumes.
"""
import hashlib
import json
import math
import os
import pickle
import random
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import ffmpeg_util as ff
from .assets import imwrite
from .audio_mix import SR, AudioBank, events_for, mix_chunk
from .compositor import Compositor
from .models import Project, format_duration
from .sampler import Sampler
from .store import OUTPUT, slug
from .timeline import Timeline, build_timeline

ProgressCb = Callable[[dict], None]


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ worker side -----------
_ctx: dict = {}


def _load_ctx(work: str, pdir: str, width: int, height: int):
    if _ctx.get("key") != work:
        with open(os.path.join(work, "timeline.pkl"), "rb") as f:
            project, tl = pickle.load(f)
        _ctx.clear()
        _ctx.update(key=work, project=project, tl=tl,
                    comp=Compositor(project, Path(pdir), width, height, tl.ref_w))
    return _ctx["project"], _ctx["tl"], _ctx["comp"]


def _chunk_worker(job: dict) -> str:
    """Render frames [f0, f1) into chunk mp4. Runs in a pool process."""
    work, idx = job["work"], job["idx"]
    width, height, fps = job["width"], job["height"], job["fps"]
    project, tl, comp = _load_ctx(work, job["pdir"], width, height)
    sampler = Sampler(project, tl)
    final = os.path.join(work, f"chunk_{idx:04d}.mp4")
    tmp = os.path.join(work, f"chunk_{idx:04d}.part.mp4")
    prog = os.path.join(work, f"chunk_{idx:04d}.prog")
    cancel = os.path.join(work, "CANCEL")
    args = [ff.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            *ff.encoder_args(job["encoder"], job["crf"], fps), "-an", "-f", "mp4", tmp]
    proc = ff.popen(args, stdin=-1, stderr=-1)
    frame = np.empty((height, width, 3), np.uint8)
    try:
        for n, f in enumerate(range(job["f0"], job["f1"])):
            comp.render(sampler.states(f / fps), frame)
            proc.stdin.write(memoryview(frame).cast("B"))
            if n % 30 == 29:
                with open(prog, "w") as pf:
                    pf.write(str(n + 1))
                if os.path.exists(cancel):
                    raise Cancelled()
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg lỗi ở chunk {idx}: {err[-500:]}")
    except BaseException:
        proc.kill()
        proc.wait()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    os.replace(tmp, final)
    with open(prog, "w") as pf:
        pf.write(str(job["f1"] - job["f0"]))
    return final


# ------------------------------------------------------------------ main side -------------
def default_workers() -> int:
    return max(1, min(6, (os.cpu_count() or 4) // 2))


def next_output_name(project: Project) -> str:
    on = [a for a in project.animals if a.enabled] or project.animals
    animal = slug(on[0].name, "animal") if on else "scene"
    day = datetime.now().strftime("%Y%m%d")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    n = 1
    while (OUTPUT / f"CatTV_{animal}_{day}_{n:03d}.mp4").exists() or \
            (OUTPUT / f"CatTV_{animal}_{day}_{n:03d}.json").exists():
        n += 1
    return f"CatTV_{animal}_{day}_{n:03d}"


def _work_key(project: Project, seed, duration, width, height, fps, encoder, crf) -> str:
    blob = json.dumps([project.model_dump(mode="json"), seed, duration, width, height, fps, encoder, crf],
                      sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _render_audio(project: Project, pdir: Path, tl: Timeline, duration: float, out: Path,
                  stop: threading.Event, step: float = 60.0):
    """Mix and encode the full soundtrack as one AAC stream (never all in RAM)."""
    if out.exists():
        return
    bank = AudioBank(pdir)
    tmp = out.with_suffix(".part.m4a")
    proc = ff.popen([ff.ffmpeg(), "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2",
                     "-i", "-", "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(tmp)],
                    stdin=-1, stderr=-1)
    try:
        total = int(round(duration * SR))
        pos = 0
        while pos < total:
            if stop.is_set():
                raise Cancelled()
            n = min(int(step * SR), total - pos)
            t0, t1 = pos / SR, (pos + n) / SR
            buf = mix_chunk(bank, t0, t1, events_for(tl.sounds, t0, t1), project.ambience,
                            project.ambience_volume)
            proc.stdin.write((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes())
            pos += n
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg lỗi khi encode audio: " + err[-500:])
    except BaseException:
        proc.kill()
        proc.wait()
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)


def _thumbnail(project: Project, pdir: Path, tl: Timeline, width: int, height: int, out: Path):
    """Frame with the most animals visible, from the first few minutes."""
    sampler = Sampler(project, tl)
    horizon = min(tl.duration, 600.0)
    best_t, best_n = 0.0, -1
    for i in range(40):
        t = horizon * (i + 0.5) / 40
        n = len(sampler.states(t))
        if n > best_n:
            best_t, best_n = t, n
    sampler = Sampler(project, tl)
    comp = Compositor(project, pdir, width, height, tl.ref_w)
    img = comp.render(sampler.states(best_t))
    if width > 1280:
        img = cv2.resize(img, (1280, round(height * 1280 / width)), interpolation=cv2.INTER_AREA)
    imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def render(project: Project, pdir: Path, **kw) -> dict:
    """Render a full video. Returns metadata dict (also written next to the video).

    With a fixed seed, finished chunks survive a cancel/crash and the next identical render
    resumes from them. With a random seed nothing can resume, so the work dir is removed."""
    state: dict = {}
    try:
        return _render(project, pdir, state=state, **kw)
    except BaseException:
        if kw.get("seed") is None and state.get("work"):
            time.sleep(0.5)   # let worker ffmpeg processes release their files
            shutil.rmtree(state["work"], ignore_errors=True)
        raise


def _render(project: Project, pdir: Path, *, state: dict, duration: float, width: int, height: int, fps: int,
           seed: Optional[int] = None, out_name: Optional[str] = None, out_dir: Path = OUTPUT,
           chunk_seconds: float = 300.0, workers: Optional[int] = None,
           progress: Optional[ProgressCb] = None, stop: Optional[threading.Event] = None,
           keep_work: bool = False, write_timeline: bool = True) -> dict:
    stop = stop or threading.Event()
    report = progress or (lambda d: None)
    started = time.time()
    if not any(a.frames > 0 for an in project.animals for a in an.anims.values()):
        raise ValueError("Chưa có con vật nào có animation. Hãy upload ít nhất 1 clip idle/walk/run.")
    if seed is None:
        seed = random.randrange(1, 2 ** 31)
    width, height, fps = int(width) // 2 * 2, int(height) // 2 * 2, int(fps)
    encoder = ff.resolve_encoder(project.render.encoder)
    crf = project.render.crf
    out_name = out_name or next_output_name(project)
    out_dir.mkdir(parents=True, exist_ok=True)

    work = OUTPUT / ".work" / _work_key(project, seed, duration, width, height, fps, encoder, crf)
    work.mkdir(parents=True, exist_ok=True)
    state["work"] = work
    (work / "CANCEL").unlink(missing_ok=True)

    report({"stage": "timeline", "done": 0, "total": 1})
    tl = build_timeline(project, seed, duration, width / height)
    with open(work / "timeline.pkl", "wb") as f:
        pickle.dump((project, tl), f)

    total_frames = int(round(duration * fps))
    # short videos: smaller chunks so every worker has something to do
    nw = workers or default_workers()
    chunk_seconds = min(chunk_seconds, max(20.0, math.ceil(duration / nw)))
    per = max(1, int(round(chunk_seconds * fps)))
    jobs = [{"work": str(work), "pdir": str(pdir), "idx": i, "f0": f0, "f1": min(f0 + per, total_frames),
             "width": width, "height": height, "fps": fps, "encoder": encoder, "crf": crf}
            for i, f0 in enumerate(range(0, total_frames, per))]
    todo = [j for j in jobs if not (work / f"chunk_{j['idx']:04d}.mp4").exists()]
    resumed = len(jobs) - len(todo)

    audio_path = work / "audio.m4a"
    audio_err: list[BaseException] = []

    def audio_job():
        try:
            _render_audio(project, pdir, tl, total_frames / fps, audio_path, stop)
        except BaseException as e:  # noqa: BLE001 - reported below
            audio_err.append(e)
    audio_thread = threading.Thread(target=audio_job, daemon=True)
    audio_thread.start()

    def frames_done() -> int:
        n = 0
        for j in jobs:
            if (work / f"chunk_{j['idx']:04d}.mp4").exists():
                n += j["f1"] - j["f0"]
                continue
            try:
                n += int((work / f"chunk_{j['idx']:04d}.prog").read_text() or 0)
            except (OSError, ValueError):
                pass
        return n

    t_render = time.time()
    base_done = frames_done()
    nworkers = max(1, min(workers or default_workers(), len(todo) or 1))
    if todo:
        with ProcessPoolExecutor(max_workers=nworkers) as pool:
            pending = {pool.submit(_chunk_worker, j) for j in todo}
            try:
                while pending:
                    finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        fut.result()
                    if stop.is_set():
                        raise Cancelled()
                    done = frames_done()
                    el = time.time() - t_render
                    speed = (done - base_done) / el if el > 0.5 else 0.0
                    eta = (total_frames - done) / speed if speed > 0 else None
                    report({"stage": "video", "done": done, "total": total_frames, "fps": round(speed, 1),
                            "eta": eta, "workers": nworkers, "chunks": len(jobs), "resumed": resumed})
            except BaseException:
                (work / "CANCEL").touch()
                for fut in pending:
                    fut.cancel()
                raise

    report({"stage": "audio", "done": total_frames, "total": total_frames})
    audio_thread.join()
    if audio_err:
        raise audio_err[0]
    if stop.is_set():
        raise Cancelled()

    report({"stage": "concat", "done": total_frames, "total": total_frames})
    lst = work / "concat.txt"
    lst.write_text("".join(f"file 'chunk_{j['idx']:04d}.mp4'\n" for j in jobs), encoding="utf-8")
    out_mp4 = out_dir / f"{out_name}.mp4"
    tmp_mp4 = out_dir / f"{out_name}.part.mp4"
    r = ff.run([ff.ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-i", str(audio_path), "-map", "0:v", "-map", "1:a", "-c", "copy",
                "-movflags", "+faststart", str(tmp_mp4)])
    if r.returncode != 0:
        tmp_mp4.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg lỗi khi ghép: " + r.stderr.decode(errors="ignore")[-500:])
    os.replace(tmp_mp4, out_mp4)

    report({"stage": "thumbnail", "done": total_frames, "total": total_frames})
    thumb = out_dir / f"{out_name}.jpg"
    _thumbnail(project, pdir, tl, width, height, thumb)
    if write_timeline:
        (out_dir / f"{out_name}.timeline.json").write_text(json.dumps(tl.to_json()), encoding="utf-8")

    elapsed = time.time() - started
    meta = {
        "file": out_mp4.name, "thumbnail": thumb.name, "seed": seed,
        "duration": format_duration(total_frames / fps), "duration_seconds": total_frames / fps,
        "width": width, "height": height, "fps": fps, "encoder": encoder, "crf": crf,
        "chunks": len(jobs), "resumed_chunks": resumed, "workers": nworkers,
        "render_seconds": round(elapsed, 1),
        "render_speed_x": round(total_frames / fps / elapsed, 2) if elapsed else None,
        "created": datetime.now().isoformat(timespec="seconds"),
        "sound_events": len(tl.sounds), "segments": sum(len(t.segs) for t in tl.tracks),
        "project": project.model_dump(mode="json"),
    }
    (out_dir / f"{out_name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    report({"stage": "done", "done": total_frames, "total": total_frames})
    return meta


def preview_size(width: int, height: int, max_h: int = 720) -> tuple[int, int]:
    if height <= max_h:
        return width, height
    return int(round(width * max_h / height / 2)) * 2, max_h


def render_preview(project: Project, pdir: Path, seconds: float = 60.0, seed: Optional[int] = None,
                   progress: Optional[ProgressCb] = None, stop: Optional[threading.Event] = None) -> dict:
    r = project.render
    w, h = preview_size(r.width, r.height)
    fps = min(r.fps, 30)
    pv = OUTPUT / "preview"
    # unique name: the browser may still hold the previous preview open (Windows file lock)
    for old in pv.glob(f"preview_{project.id}_*"):
        try:
            old.unlink()
        except OSError:
            pass
    return render(project, pdir, duration=seconds, width=w, height=h, fps=fps, seed=seed,
                  out_name=f"preview_{project.id}_{int(time.time())}", out_dir=pv,
                  chunk_seconds=math.ceil(seconds / default_workers()), progress=progress, stop=stop,
                  write_timeline=False)
