"""Random behaviour engine: seed -> per-animal movement segments + sound events.

All coordinates are in reference pixels of a frame REF_W wide (height follows the
render aspect ratio). (x, y) is the animal's feet point (bottom centre of the sprite).
The result depends only on (project, seed, duration, aspect), so every render worker
can rebuild the identical timeline on its own.
"""
import heapq
import math
import random
from dataclasses import dataclass, field

from .models import Animal, Project

REF_W = 1920.0
SEG_MOVE, SEG_IDLE, SEG_TURN, SEG_HIDDEN = "move", "idle", "turn", "hidden"
DEPTH_MIN, DEPTH_MAX = 0.75, 1.25


@dataclass(slots=True)
class Seg:
    t0: float
    t1: float
    kind: str
    x0: float
    y0: float
    cx: float
    cy: float
    x1: float
    y1: float
    anim: str
    face: int          # +1 facing right, -1 facing left (turn: face at the start)
    accel: float = 0.0
    dist: float = 0.0
    phase0: float = 0.0
    offscreen: bool = False

    def to_list(self):
        return [round(self.t0, 3), round(self.t1, 3), self.kind, round(self.x0, 1), round(self.y0, 1),
                round(self.cx, 1), round(self.cy, 1), round(self.x1, 1), round(self.y1, 1),
                self.anim, self.face, self.offscreen]


@dataclass(slots=True)
class SoundEvent:
    t: float
    animal: int        # index into project.animals
    instance: int
    file: str
    volume: float


@dataclass
class Track:
    animal: int
    instance: int
    segs: list[Seg] = field(default_factory=list)


@dataclass
class Timeline:
    duration: float
    ref_w: float
    ref_h: float
    tracks: list[Track]
    sounds: list[SoundEvent]

    def to_json(self) -> dict:
        return {"duration": self.duration, "ref": [self.ref_w, self.ref_h],
                "tracks": [{"animal": t.animal, "instance": t.instance,
                            "segments": [s.to_list() for s in t.segs]} for t in self.tracks],
                "sounds": [[round(e.t, 3), e.animal, e.instance, e.file, round(e.volume, 3)]
                           for e in self.sounds]}


def sprite_ref_box(animal: Animal, ref_w: float = REF_W) -> tuple[float, float]:
    """Largest sprite (width, height) of an animal in reference px."""
    anims = [a for a in animal.anims.values() if a.frames > 0 and a.width > 0]
    base_w = animal.size_pct / 100.0 * ref_w
    if not anims:
        return base_w, base_w * 0.6
    ref = animal.anims.get("idle") or anims[0]
    if ref.frames <= 0:
        ref = anims[0]
    s = base_w / (ref.width / ref.px_scale)
    w = max(a.width / a.px_scale * s * a.scale for a in anims)
    h = max(a.height / a.px_scale * s * a.scale for a in anims)
    return w, h


def trap_pos(s: float, a: float) -> float:
    """Distance fraction at time fraction s for a trapezoid speed profile (ramp fraction a)."""
    if a <= 0:
        return s
    s = min(max(s, 0.0), 1.0)
    vmax = 1.0 / (1.0 - a)
    if s < a:
        return 0.5 * vmax * s * s / a
    if s > 1.0 - a:
        r = 1.0 - s
        return 1.0 - 0.5 * vmax * r * r / a
    return 0.5 * vmax * a + vmax * (s - a)


def bezier(x0, y0, cx, cy, x1, y1, u):
    v = 1.0 - u
    return (v * v * x0 + 2 * v * u * cx + u * u * x1,
            v * v * y0 + 2 * v * u * cy + u * u * y1)


def bezier_len(x0, y0, cx, cy, x1, y1, n=12):
    total, px, py = 0.0, x0, y0
    for i in range(1, n + 1):
        qx, qy = bezier(x0, y0, cx, cy, x1, y1, i / n)
        total += math.hypot(qx - px, qy - py)
        px, py = qx, qy
    return total


class Bounds:
    def __init__(self, x0, y0, x1, y1):
        if x1 < x0:
            x0 = x1 = (x0 + x1) / 2
        if y1 < y0:
            y0 = y1 = (y0 + y1) / 2
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def clamp(self, x, y):
        return min(max(x, self.x0), self.x1), min(max(y, self.y0), self.y1)

    def random(self, rng):
        return rng.uniform(self.x0, self.x1), rng.uniform(self.y0, self.y1)

    @property
    def w(self):
        return self.x1 - self.x0


def animal_bounds(project: Project, animal: Animal, ref_w: float, ref_h: float, depth: bool) -> Bounds:
    sw, sh = sprite_ref_box(animal, ref_w)
    if depth:
        sw, sh = sw * DEPTH_MAX, sh * DEPTH_MAX
    ar = project.area
    half = sw / 2 + 2
    return Bounds(max(ar.x * ref_w, 0) + half, max(ar.y * ref_h, sh + 2),
                  min((ar.x + ar.w) * ref_w, ref_w) - half, min((ar.y + ar.h) * ref_h, ref_h - 2))


class _Walker:
    def __init__(self, ai, k, animal, bounds, ref_w, rng):
        self.ai, self.k, self.animal, self.b, self.ref_w, self.rng = ai, k, animal, bounds, ref_w, rng
        self.track = Track(ai, k)
        self.t = 0.0
        self.x, self.y = 0.0, 0.0
        self.face = 1
        self.sw = sprite_ref_box(animal, ref_w)[0] * DEPTH_MAX
        w = animal.behaviors
        self.choices = [(k_, max(float(w.get(k_, 0)), 0.0)) for k_ in ("walk", "run", "idle", "turn", "hide")]
        if sum(v for _, v in self.choices) <= 0:
            self.choices = [("walk", 1.0), ("idle", 1.0)]

    # -- helpers -------------------------------------------------------------------------
    def _pick(self):
        r = self.rng.uniform(0, sum(v for _, v in self.choices))
        for name, v in self.choices:
            r -= v
            if r <= 0:
                return name
        return self.choices[-1][0]

    def _pause(self, mult=1.0):
        lo, hi = self.animal.pause
        return max(0.05, self.rng.uniform(min(lo, hi), max(lo, hi)) * mult)

    def _speed(self, kind):
        lo, hi = self.animal.run_speed if kind == "run" else self.animal.walk_speed
        return max(5.0, self.rng.uniform(min(lo, hi), max(lo, hi)))

    def add(self, seg: Seg):
        self.track.segs.append(seg)
        self.t = seg.t1
        self.x, self.y = seg.x1, seg.y1

    def idle(self, dur, anim="idle"):
        self.add(Seg(self.t, self.t + dur, SEG_IDLE, self.x, self.y, self.x, self.y, self.x, self.y,
                     anim, self.face, phase0=self.rng.uniform(0, 1000)))

    def turn(self):
        dur = self.rng.uniform(0.25, 0.6)
        self.add(Seg(self.t, self.t + dur, SEG_TURN, self.x, self.y, self.x, self.y, self.x, self.y,
                     "idle", self.face, phase0=self.rng.uniform(0, 1000)))
        self.face = -self.face

    def move(self, x1, y1, kind, offscreen=False):
        x0, y0 = self.x, self.y
        d = math.hypot(x1 - x0, y1 - y0)
        if d < 3:
            self.idle(self._pause(0.5))
            return
        # gentle curve: control point pushed sideways from the midpoint
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        off = self.rng.uniform(-0.3, 0.3) * d
        nx, ny = -(y1 - y0) / d, (x1 - x0) / d
        cx, cy = mx + nx * off, my + ny * off
        if not offscreen:
            cx, cy = self.b.clamp(cx, cy)
        else:
            cy = min(max(cy, self.b.y0), self.b.y1)
        length = bezier_len(x0, y0, cx, cy, x1, y1)
        speed = self._speed(kind)
        accel = self.rng.uniform(0.08, 0.16) if kind == "run" else self.rng.uniform(0.15, 0.28)
        dur = length / (speed * (1 - accel))
        if abs(x1 - x0) > 4:
            self.face = 1 if x1 > x0 else -1
        self.add(Seg(self.t, self.t + dur, SEG_MOVE, x0, y0, cx, cy, x1, y1, kind, self.face,
                     accel, length, self.rng.uniform(0, 1000), offscreen))

    def destination(self, dmin, dmax, others, side=0):
        best, best_score = None, -1e18
        rng = self.rng
        for _ in range(8):
            if dmax >= 1e8:
                x, y = self.b.random(rng)
            else:
                # mostly horizontal headings, like a small animal scurrying along the floor
                ang = rng.gauss(0, 0.55) + (math.pi if rng.random() < 0.5 else 0.0)
                if side and math.cos(ang) * side < 0:
                    ang = math.pi - ang
                dist = rng.uniform(dmin, dmax)
                x, y = self.b.clamp(self.x + math.cos(ang) * dist, self.y + math.sin(ang) * dist * 0.6)
            score = math.sqrt(min(((x - ox) ** 2 + (y - oy) ** 2 for ox, oy in others), default=0.0))
            score = min(score, self.ref_w * 0.25) + self.rng.uniform(0, self.ref_w * 0.08)
            if score > best_score:
                best, best_score = (x, y), score
        return best

    # -- behaviours ----------------------------------------------------------------------
    def step(self, others):
        """Append one behaviour (one or more segments)."""
        if self.track.segs and self.track.segs[-1].kind == SEG_HIDDEN:
            return self._enter(others)
        b = self._pick()
        W = self.b.w
        if b == "walk":
            dest = self.destination(W * 0.08, W * 0.45, others)
            self.move(*dest, "walk")
            if self.rng.random() < 0.55:
                self.idle(self._pause())
        elif b == "run":
            for i in range(1 + (self.rng.random() < 0.5) + (self.rng.random() < 0.25)):
                dest = self.destination(W * 0.12, W * 0.7, others)
                self.move(*dest, "run")
                self.idle(self.rng.uniform(0.15, 0.7) if i == 0 else self._pause())
        elif b == "idle":
            self.idle(self._pause(self.rng.uniform(1.0, 2.5)))
        elif b == "turn":
            self.turn()
            if self.rng.random() < 0.6:
                dest = self.destination(W * 0.05, W * 0.35, others, side=self.face)
                self.move(*dest, "walk")
            else:
                self.idle(self._pause())
        elif b == "hide":
            edge_x = -self.sw if self.x < (self.b.x0 + self.b.x1) / 2 else self.ref_w + self.sw
            self.move(edge_x, self.y + self.rng.uniform(-40, 40), "run", offscreen=True)
            self.y = min(max(self.y, self.b.y0), self.b.y1)
            dur = self._pause(self.rng.uniform(2.0, 5.0))
            self.add(Seg(self.t, self.t + dur, SEG_HIDDEN, self.x, self.y, self.x, self.y,
                         self.x, self.y, "idle", self.face, offscreen=True))

    def _enter(self, others):
        left = self.rng.random() < 0.5
        self.x = -self.sw if left else self.ref_w + self.sw
        self.y = self.rng.uniform(self.b.y0, self.b.y1)
        dest = self.destination(0, 1e9, others, side=1 if left else -1)
        self.move(dest[0], dest[1], "run" if self.rng.random() < 0.6 else "walk", offscreen=True)
        self.idle(self._pause())


def build_timeline(project: Project, seed: int, duration: float, aspect: float = 16 / 9) -> Timeline:
    ref_w, ref_h = REF_W, REF_W / aspect
    depth = project.render.depth_scale
    walkers: list[_Walker] = []
    for ai, animal in enumerate(project.animals):
        if not animal.enabled or not any(a.frames > 0 for a in animal.anims.values()):
            continue
        b = animal_bounds(project, animal, ref_w, ref_h, depth)
        for k in range(max(1, animal.count)):
            walkers.append(_Walker(ai, k, animal, b, ref_w, random.Random(f"{seed}:{ai}:{k}")))

    # spread the start positions
    placed = []
    for w in walkers:
        best = max((w.b.random(w.rng) for _ in range(12)),
                   key=lambda p: min((math.hypot(p[0] - q[0], p[1] - q[1]) for q in placed), default=0))
        w.x, w.y = best
        w.face = 1 if w.rng.random() < 0.5 else -1
        placed.append(best)
        w.idle(w.rng.uniform(0.3, 2.5))

    heap = [(w.t, i) for i, w in enumerate(walkers)]
    heapq.heapify(heap)
    while heap:
        _, i = heapq.heappop(heap)
        w = walkers[i]
        others = [(o.x, o.y) for j, o in enumerate(walkers) if j != i]
        w.step(others)
        if w.t < duration:
            heapq.heappush(heap, (w.t, i))

    sounds: list[SoundEvent] = []
    for ai, animal in enumerate(project.animals):
        if not (animal.enabled and animal.sound_enabled and animal.sounds):
            continue
        rng = random.Random(f"{seed}:sound:{ai}")
        lo, hi = sorted(animal.sound_interval)
        vlo, vhi = sorted(animal.sound_volume)
        t = rng.uniform(0.5, max(1.0, hi / 2))
        while t < duration:
            sounds.append(SoundEvent(t, ai, rng.randrange(max(1, animal.count)),
                                     rng.choice(animal.sounds), rng.uniform(vlo, vhi)))
            t += rng.uniform(max(0.5, lo), max(0.5, hi))
    sounds.sort(key=lambda e: e.t)
    return Timeline(duration, ref_w, ref_h, [w.track for w in walkers], sounds)
