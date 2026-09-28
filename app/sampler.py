"""Timeline -> per-frame animal states."""
import bisect
import math
from dataclasses import dataclass

from .models import AnimSet, Project
from .timeline import (DEPTH_MAX, DEPTH_MIN, SEG_HIDDEN, SEG_IDLE, SEG_MOVE, SEG_TURN, Seg,
                       Timeline, bezier, sprite_ref_box, trap_pos)


@dataclass(slots=True)
class State:
    animal: int
    instance: int
    x: float           # feet point, reference px
    y: float
    face: int          # +1 right / -1 left
    anim: str
    frame: int
    scale: float       # depth scale factor
    squash: float      # 1.0 normally, <1 while turning (horizontal squash)


def resolve_anim(anims: dict[str, AnimSet], want: str) -> str | None:
    order = {"idle": ("idle", "walk", "run"), "walk": ("walk", "run", "idle"),
             "run": ("run", "walk", "idle")}[want]
    for name in order:
        a = anims.get(name)
        if a and a.frames > 0:
            return name
    return None


def frame_index(a: AnimSet, phase: float) -> int:
    """phase is measured in source frames (may be huge); maps to a looping index."""
    n = a.frames
    if n <= 1:
        return 0
    p = int(math.floor(phase))
    if a.loop == "pingpong":
        period = 2 * (n - 1)
        p %= period
        return p if p < n else period - p
    return p % n


class Sampler:
    def __init__(self, project: Project, timeline: Timeline):
        self.p = project
        self.tl = timeline
        self.starts = [[s.t0 for s in tr.segs] for tr in timeline.tracks]
        self.cursor = [0] * len(timeline.tracks)
        self.ref_w = {}
        for ai, animal in enumerate(project.animals):
            self.ref_w[ai] = sprite_ref_box(animal, timeline.ref_w)[0]
        ar = project.area
        self.depth = project.render.depth_scale
        self.y_top = ar.y * timeline.ref_h
        self.y_bot = (ar.y + ar.h) * timeline.ref_h

    def _seg(self, ti: int, t: float) -> Seg | None:
        segs = self.tl.tracks[ti].segs
        i = self.cursor[ti]
        if not (i < len(segs) and segs[i].t0 <= t < segs[i].t1):
            i = max(0, bisect.bisect_right(self.starts[ti], t) - 1)
            self.cursor[ti] = i
        return segs[i] if segs else None

    def depth_scale(self, y: float) -> float:
        if not self.depth or self.y_bot <= self.y_top:
            return 1.0
        f = min(max((y - self.y_top) / (self.y_bot - self.y_top), 0.0), 1.0)
        return DEPTH_MIN + (DEPTH_MAX - DEPTH_MIN) * f

    def states(self, t: float) -> list[State]:
        out = []
        for ti, tr in enumerate(self.tl.tracks):
            s = self._seg(ti, t)
            if s is None or s.kind == SEG_HIDDEN:
                continue
            animal = self.p.animals[tr.animal]
            dur = max(s.t1 - s.t0, 1e-6)
            u = min(max((t - s.t0) / dur, 0.0), 1.0)
            squash = 1.0
            face = s.face
            if s.kind == SEG_MOVE:
                frac = trap_pos(u, s.accel)
                x, y = bezier(s.x0, s.y0, s.cx, s.cy, s.x1, s.y1, frac)
                want = s.anim
            else:
                x, y = s.x0, s.y0
                want = "idle"
                if s.kind == SEG_TURN:
                    squash = max(0.15, abs(math.cos(math.pi * u)))
                    if u >= 0.5:
                        face = -s.face
            name = resolve_anim(animal.anims, want)
            if name is None:
                continue
            a = animal.anims[name]
            scale = self.depth_scale(y)
            elapsed = t - s.t0
            if s.kind == SEG_MOVE and a.native_speed > 0 and name != "idle":
                # advance the gait with the distance travelled so feet do not slide
                sprite_scale = self.ref_w[tr.animal] * scale * a.scale / max(a.width / a.px_scale, 1)
                ref_speed = a.native_speed * sprite_scale
                phase = s.phase0 + frac * s.dist / max(ref_speed, 1e-3) * a.fps
            else:
                phase = s.phase0 * a.fps + elapsed * a.fps
            out.append(State(tr.animal, tr.instance, x, y, face, name, frame_index(a, phase),
                             scale, squash))
        out.sort(key=lambda st: st.y)
        return out
