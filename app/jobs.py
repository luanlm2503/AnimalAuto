"""In-process job queue: renders run one at a time on a background thread
(each render already uses all CPU cores through its own process pool)."""
import itertools
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from .render import Cancelled


@dataclass
class Job:
    id: str
    kind: str                     # preview | render
    project: str
    title: str
    fn: Callable = field(repr=False, default=None)
    status: str = "queued"        # queued | running | done | error | cancelled
    stage: str = ""
    done: int = 0
    total: int = 0
    fps: float = 0.0
    eta: float | None = None
    result: dict | None = None
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        r = self.result or {}
        return {"id": self.id, "kind": self.kind, "project": self.project, "title": self.title,
                "status": self.status, "stage": self.stage, "done": self.done, "total": self.total,
                "progress": round(self.done / self.total, 4) if self.total else 0.0,
                "fps": self.fps, "eta": self.eta, "error": self.error,
                "elapsed": round((self.finished or time.time()) - self.started, 1) if self.started else 0,
                "file": r.get("file"), "thumbnail": r.get("thumbnail"), "seed": r.get("seed"),
                "folder": r.get("folder"), "created": self.created}


class JobQueue:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[Job] = queue.Queue()
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="render-jobs").start()

    def submit(self, kind: str, project: str, title: str, fn: Callable[[Job], dict]) -> Job:
        job = Job(id=f"j{next(self.ids)}", kind=kind, project=project, title=title, fn=fn)
        with self.lock:
            self.jobs[job.id] = job
        self.q.put(job)
        return job

    def cancel(self, jid: str) -> Job | None:
        job = self.jobs.get(jid)
        if job and job.status in ("queued", "running"):
            job.stop.set()
            if job.status == "queued":
                job.status = "cancelled"
        return job

    def remove(self, jid: str):
        with self.lock:
            job = self.jobs.get(jid)
            if job and job.status not in ("queued", "running"):
                del self.jobs[jid]

    def list(self) -> list[dict]:
        return [j.public() for j in sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)]

    def _loop(self):
        while True:
            job = self.q.get()
            if job.status == "cancelled" or job.stop.is_set():
                job.status = "cancelled"
                continue
            job.status, job.started = "running", time.time()
            try:
                job.result = job.fn(job)
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except Exception as e:  # noqa: BLE001 - surfaced to the UI
                traceback.print_exc()
                job.status, job.error = "error", str(e) or e.__class__.__name__
            finally:
                job.finished = time.time()
                job.eta = None


def progress_cb(job: Job):
    def cb(d: dict):
        job.stage = d.get("stage", job.stage)
        job.done, job.total = d.get("done", job.done), d.get("total", job.total)
        if "fps" in d:
            job.fps = d["fps"]
        job.eta = d.get("eta")
    return cb
