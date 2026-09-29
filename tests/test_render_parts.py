import numpy as np

from app.audio_mix import SR, mix_chunk
from app.compositor import Compositor, SpriteBank
from app.models import Project
from app.sampler import State
from app.timeline import SoundEvent


class FakeBank:
    def __init__(self, clips):
        self.clips = clips

    def get(self, rel):
        return self.clips.get(rel)


def test_mix_length_and_spill_over():
    beep = np.full((SR, 2), 0.5, np.float32)          # 1 s clip
    bank = FakeBank({"a.wav": beep, "amb.wav": np.full((SR // 3, 2), 0.1, np.float32)})
    ev = [SoundEvent(9.5, 0, 0, "a.wav", 1.0)]         # starts 0.5 s before the chunk
    buf = mix_chunk(bank, 10.0, 12.0, ev, "amb.wav", 1.0)
    assert buf.shape == (2 * SR, 2)
    assert np.allclose(buf[: SR // 2 - 10], 0.6, atol=1e-4)     # tail of the event + ambience
    assert np.allclose(buf[SR // 2 + 10:], 0.1, atol=1e-4)      # ambience only


def test_mix_soft_clips():
    loud = np.full((SR, 2), 0.9, np.float32)
    bank = FakeBank({"a.wav": loud})
    ev = [SoundEvent(0.0, 0, 0, "a.wav", 1.0), SoundEvent(0.0, 0, 1, "a.wav", 1.0)]
    buf = mix_chunk(bank, 0.0, 1.0, ev, "", 0.0)
    assert buf.max() <= 1.0


def test_compositor_alpha(tmp_path):
    p = Project(id="t", name="t")
    p.render.shadow = False
    comp = Compositor(p, tmp_path, 200, 100, 200.0)
    comp.bg[:] = (0, 0, 255)
    sprite = np.zeros((10, 20, 4), np.uint8)
    sprite[..., 1] = 255
    sprite[:, :10, 3] = 255        # left half opaque green
    sprite[:, 10:, 3] = 128        # right half 50 %
    comp.sprites.base[(0, "idle")] = [sprite]
    comp.sprites.src_face[0] = 1
    out = comp.render([State(0, 0, 100.0, 50.0, 1, "idle", 0, 1.0, 1.0)])
    assert tuple(out[45, 92]) == (0, 255, 0)
    b, g, r = out[45, 105]
    assert abs(int(g) - 128) <= 2 and abs(int(r) - 127) <= 2
    assert tuple(out[10, 10]) == (0, 0, 255)
    # facing left mirrors the sprite
    out = comp.render([State(0, 0, 100.0, 50.0, -1, "idle", 0, 1.0, 1.0)])
    assert tuple(out[45, 107]) == (0, 255, 0)
    # partly off-screen must not crash
    comp.render([State(0, 0, 2.0, 5.0, 1, "idle", 0, 1.0, 1.0)])
    comp.render([State(0, 0, 500.0, 500.0, 1, "idle", 0, 1.0, 1.0)])


def test_compositor_offsets_airborne_sprite_but_keeps_shadow_grounded(tmp_path):
    p = Project(id="t", name="t")
    p.render.shadow = False
    comp = Compositor(p, tmp_path, 200, 100, 200.0)
    comp.bg[:] = (0, 0, 0)
    sprite = np.zeros((10, 20, 4), np.uint8)
    sprite[..., 2] = 255
    sprite[..., 3] = 255
    comp.sprites.base[(0, "idle")] = [sprite]
    comp.sprites.src_face[0] = 1
    ground = comp.render([State(0, 0, 100, 50, 1, "idle", 0, 1, 1, 0)])
    airborne = comp.render([State(0, 0, 100, 50, 1, "idle", 0, 1, 1, 20)])
    assert tuple(ground[45, 100]) == (0, 0, 255)
    assert tuple(airborne[25, 100]) == (0, 0, 255)
    assert tuple(airborne[45, 100]) == (0, 0, 0)


def test_airborne_shadow_fades_with_altitude(tmp_path):
    p = Project(id="t", name="t")
    p.render.shadow = True
    p.render.shadow_opacity = 0.8
    comp = Compositor(p, tmp_path, 200, 100, 200.0)
    comp.bg[:] = (255, 255, 255)
    sprite = np.zeros((10, 20, 4), np.uint8)
    sprite[..., 2] = 255
    sprite[..., 3] = 255
    comp.sprites.base[(0, "idle")] = [sprite]
    comp.sprites.src_face[0] = 1
    ground = comp.render([State(0, 0, 100, 50, 1, "idle", 0, 1, 1, 0)])
    airborne = comp.render([State(0, 0, 100, 50, 1, "idle", 0, 1, 1, 100)])
    assert ground[50, 100, 0] < airborne[50, 100, 0] < 255
    assert airborne[50, 100, 0] > ground[50, 100, 0]
    assert airborne[50, 100, 0] < 255

