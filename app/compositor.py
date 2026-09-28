"""Frame compositing: background + soft shadows + animal sprites (numpy, BGR uint8)."""
from pathlib import Path

import cv2
import numpy as np

from .assets import fit_background, load_frames, to_bgra
from .models import Project
from .sampler import State


class SpriteBank:
    """Animal frames scaled once to the output size; per-state variants (flip, depth scale,
    turn squash) are premultiplied and cached, bounded by CACHE_BYTES."""
    CACHE_BYTES = 384 * 2 ** 20

    def __init__(self, project: Project, pdir: Path, out_w: int, ref_w: float):
        self.k = out_w / ref_w
        self.base: dict[tuple[int, str], list[np.ndarray]] = {}
        self.cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
        self.cache_bytes = 0
        self.src_face: dict[int, int] = {}
        for ai, animal in enumerate(project.animals):
            self.src_face[ai] = -1 if animal.facing == "left" else 1
            anims = [a for a in animal.anims.values() if a.frames > 0]
            if not anims:
                continue
            ref = animal.anims.get("idle") if animal.anims.get("idle") and animal.anims["idle"].frames else anims[0]
            # reference px per source px, shared by every anim of one animal (same as sprite_ref_box)
            unit = animal.size_pct / 100 * ref_w / (ref.width / ref.px_scale)
            for name, a in animal.anims.items():
                if a.frames <= 0:
                    continue
                s = unit / a.px_scale * a.scale * self.k
                self.base[(ai, name)] = [_resize(to_bgra(f), s, s)
                                         for f in load_frames(pdir / "animals" / animal.id / name, a.frames)]

    def get(self, st: State) -> tuple[np.ndarray, np.ndarray]:
        """Returns (premultiplied BGR float32, alpha float32 HxWx1)."""
        flip = st.face != self.src_face[st.animal]
        sc = round(st.scale * 50) / 50
        sq = round(st.squash * 20) / 20
        key = (st.animal, st.anim, st.frame, flip, sc, sq)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        img = self.base[(st.animal, st.anim)][st.frame]
        if sc != 1.0 or sq != 1.0:
            img = _resize(img, sc * sq, sc)
        if flip:
            img = img[:, ::-1]
        a = img[..., 3:4].astype(np.float32) * (1 / 255.0)
        pre = img[..., :3].astype(np.float32) * a
        size = pre.nbytes + a.nbytes
        if self.cache_bytes + size > self.CACHE_BYTES:
            self.cache.clear()
            self.cache_bytes = 0
        self.cache[key] = (pre, a)
        self.cache_bytes += size
        return pre, a


def _resize(img: np.ndarray, sx: float, sy: float) -> np.ndarray:
    h, w = img.shape[:2]
    nw, nh = max(1, round(w * sx)), max(1, round(h * sy))
    if (nw, nh) == (w, h):
        return img
    interp = cv2.INTER_AREA if sx * sy < 1 else cv2.INTER_LINEAR
    return cv2.resize(img, (nw, nh), interpolation=interp)


class Compositor:
    def __init__(self, project: Project, pdir: Path, width: int, height: int, ref_w: float):
        self.p = project
        self.w, self.h = width, height
        self.k = width / ref_w
        bg_path = pdir / project.background if project.background else None
        self.bg = fit_background(bg_path, width, height)
        self.sprites = SpriteBank(project, pdir, width, ref_w)
        self.shadow = project.render.shadow
        self.shadow_op = project.render.shadow_opacity
        self._shadow_cache: dict[tuple[int, int], np.ndarray] = {}

    def _shadow(self, sw: int, sh: int) -> np.ndarray:
        key = (sw, sh)
        m = self._shadow_cache.get(key)
        if m is None:
            pad = max(4, sh)
            m = np.zeros((sh + 2 * pad, sw + 2 * pad), np.float32)
            cv2.ellipse(m, (m.shape[1] // 2, m.shape[0] // 2), (max(1, sw // 2), max(1, sh // 2)),
                        0, 0, 360, 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), max(1.0, sh * 0.45))
            m = m[..., None]
            self._shadow_cache[key] = m
        return m

    @staticmethod
    def _clip(x0, y0, w, h, W, H):
        cx0, cy0 = max(x0, 0), max(y0, 0)
        cx1, cy1 = min(x0 + w, W), min(y0 + h, H)
        if cx0 >= cx1 or cy0 >= cy1:
            return None
        return cx0, cy0, cx1, cy1, cx0 - x0, cy0 - y0

    def render(self, states: list[State], out: np.ndarray | None = None) -> np.ndarray:
        frame = out if out is not None else np.empty_like(self.bg)
        np.copyto(frame, self.bg)
        W, H = self.w, self.h
        for st in states:
            pre, a = self.sprites.get(st)
            sh, sw = a.shape[:2]
            fx, fy = st.x * self.k, st.y * self.k
            x0 = int(round(fx - sw / 2))
            y0 = int(round(fy - sh))
            if self.shadow and self.shadow_op > 0:
                shw = max(4, int(sw * 0.8))
                shh = max(3, int(sh * 0.14))
                m = self._shadow(shw, shh)
                mx0 = int(round(fx - m.shape[1] / 2))
                my0 = int(round(fy - m.shape[0] / 2 - shh * 0.1))
                c = self._clip(mx0, my0, m.shape[1], m.shape[0], W, H)
                if c:
                    cx0, cy0, cx1, cy1, ox, oy = c
                    reg = frame[cy0:cy1, cx0:cx1]
                    mm = m[oy:oy + cy1 - cy0, ox:ox + cx1 - cx0]
                    reg[:] = (reg * (1.0 - mm * self.shadow_op)).astype(np.uint8)
            c = self._clip(x0, y0, sw, sh, W, H)
            if not c:
                continue
            cx0, cy0, cx1, cy1, ox, oy = c
            reg = frame[cy0:cy1, cx0:cx1]
            pp = pre[oy:oy + cy1 - cy0, ox:ox + cx1 - cx0]
            aa = a[oy:oy + cy1 - cy0, ox:ox + cx1 - cx0]
            reg[:] = (pp + reg * (1.0 - aa) + 0.5).astype(np.uint8)
        return frame
