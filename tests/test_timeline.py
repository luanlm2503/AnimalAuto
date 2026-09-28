import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import AnimSet, Animal, Project, parse_duration  # noqa: E402
from app.sampler import Sampler  # noqa: E402
from app.timeline import SEG_MOVE, animal_bounds, build_timeline  # noqa: E402


def make_project(count=2, animals=1):
    p = Project(id="t", name="t")
    for i in range(animals):
        p.animals.append(Animal(id=f"a{i}", count=count, anims={
            "idle": AnimSet(frames=10, width=300, height=200, fps=24),
            "walk": AnimSet(frames=12, width=320, height=200, fps=24),
        }))
    return p


def test_parse_duration():
    assert parse_duration("08:00:00") == 8 * 3600
    assert parse_duration("45:00") == 2700
    assert parse_duration("90") == 90


def test_deterministic_and_seed_varies():
    p = make_project()
    a = build_timeline(p, 123, 600).to_json()
    b = build_timeline(p, 123, 600).to_json()
    c = build_timeline(p, 124, 600).to_json()
    assert a == b
    assert a != c


def test_covers_duration():
    p = make_project(count=3, animals=2)
    tl = build_timeline(p, 7, 3600)
    assert len(tl.tracks) == 6
    for tr in tl.tracks:
        assert tr.segs[0].t0 == 0
        assert tr.segs[-1].t1 >= 3600
        for s0, s1 in zip(tr.segs, tr.segs[1:]):
            assert abs(s0.t1 - s1.t0) < 1e-6


def test_stays_in_bounds():
    p = make_project(count=3)
    tl = build_timeline(p, 99, 3600)
    b = animal_bounds(p, p.animals[0], tl.ref_w, tl.ref_h, False)
    sm = Sampler(p, tl)
    t, visible = 0.0, 0
    while t < 3600:
        for st in sm.states(t):
            tr = next(x for x in tl.tracks if x.instance == st.instance)
            seg = sm._seg(tl.tracks.index(tr), t)
            if seg.offscreen:
                continue
            visible += 1
            assert b.x0 - 1 <= st.x <= b.x1 + 1, (t, st)
            assert b.y0 - 1 <= st.y <= b.y1 + 1, (t, st)
        t += 0.37
    assert visible > 10000


def test_moves_and_pauses():
    tl = build_timeline(make_project(count=1), 5, 600)
    kinds = {s.kind for s in tl.tracks[0].segs}
    assert SEG_MOVE in kinds and "idle" in kinds
    faces = {s.face for s in tl.tracks[0].segs}
    assert faces == {1, -1}
