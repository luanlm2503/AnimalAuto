import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import AnimSet, Animal, Area, Project, parse_duration  # noqa: E402
from app.sampler import Sampler  # noqa: E402
from app.timeline import SEG_MOVE, animal_bounds, area_for, build_timeline  # noqa: E402


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


def test_area_defaults_to_project_area_for_old_projects():
    p = Project.model_validate({"id": "t", "name": "t", "animals": [{"id": "a"}]})
    animal = p.animals[0]
    assert animal.area is None
    assert area_for(p, animal) == p.area
    animal.anims = make_project().animals[0].anims
    assert build_timeline(p, 3, 20).to_json() == build_timeline(
        p.model_copy(update={"animals": [animal.model_copy(update={"area": p.area.model_copy()})]}), 3, 20).to_json()
    assert build_timeline(p, 3, 20).tracks
    p.render.depth_scale = True
    sampler = Sampler(p, build_timeline(p, 3, 20))
    before = sampler.depth_scale(800)
    animal.area = Area(x=0.1, y=0.1, w=0.3, h=0.3)
    sampler = Sampler(p, build_timeline(p, 3, 20))
    assert sampler.depth_scale(800) == before


def test_new_animal_area_is_an_independent_copy():
    p = Project(id="t", name="t")
    a = Animal(id="a", area=p.area.model_copy(deep=True))
    a.area.x = 0.3
    assert p.area.x == 0.05
    assert area_for(p, a).x == 0.3
    assert Area.model_validate({"x": 0.9, "w": 0.1, "y": 0.5, "h": 0.4}).w == 0.1
    assert Animal(id="legacy").model_dump()["area"] is None


def test_animal_areas_are_independent():
    p = make_project(count=1, animals=2)
    p.area = Area(x=0.05, y=0.55, w=0.9, h=0.4)
    p.animals[0].area = Area(x=0.02, y=0.55, w=0.42, h=0.4)
    p.animals[1].area = Area(x=0.56, y=0.55, w=0.42, h=0.4)
    tl = build_timeline(p, 99, 300)
    sm = Sampler(p, tl)
    bounds = [animal_bounds(p, a, tl.ref_w, tl.ref_h, False) for a in p.animals]
    assert bounds[0].x1 < bounds[1].x0
    tracks = {(tr.animal, tr.instance): i for i, tr in enumerate(tl.tracks)}
    t, visible = 0.0, 0
    while t < 300:
        for st in sm.states(t):
            tr_idx = tracks[(st.animal, st.instance)]
            if sm._seg(tr_idx, t).offscreen:
                continue
            b = bounds[st.animal]
            assert b.x0 - 1 <= st.x <= b.x1 + 1, (t, st)
            assert b.y0 - 1 <= st.y <= b.y1 + 1, (t, st)
            visible += 1
        t += 0.37
    assert visible > 100


def test_project_area_changes_only_inherited_area():
    p = make_project(count=1, animals=2)
    p.animals[1].area = Area(x=0.6, y=0.2, w=0.3, h=0.3)
    b_inherited = animal_bounds(p, p.animals[0], 1920, 1080, False)
    b_own = animal_bounds(p, p.animals[1], 1920, 1080, False)
    p.area = Area(x=0.1, y=0.6, w=0.8, h=0.3)
    assert animal_bounds(p, p.animals[0], 1920, 1080, False).x0 != b_inherited.x0
    assert animal_bounds(p, p.animals[1], 1920, 1080, False).x0 == b_own.x0


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


def test_flight_is_deterministic_and_returns_to_ground():
    p = make_project(count=1)
    animal = p.animals[0]
    animal.flight.enabled = True
    animal.flight.altitude = [0.12, 0.28]
    animal.flight.legs = [1, 2]
    animal.behaviors = {"walk": 0, "run": 0, "idle": 0, "turn": 0, "hide": 0, "fly": 1}
    a = build_timeline(p, 17, 180)
    b = build_timeline(p, 17, 180)
    assert a.to_json() == b.to_json()
    moves = [s for s in a.tracks[0].segs if s.kind == SEG_MOVE]
    assert any(s.z1 > 0 for s in moves)
    assert any(s.z0 > 0 and s.z1 == 0 for s in moves)
    assert all(0 <= z <= 0.28 * a.ref_h for s in moves for z in (s.z0, s.z1))
    assert all(s.anim == animal.flight.anim for s in moves if s.z0 > 0 or s.z1 > 0)
    states = Sampler(p, a).states(next(s.t0 + (s.t1 - s.t0) * 0.5 for s in moves if s.z1 > s.z0))
    assert any(st.z > 0 for st in states)


def test_old_project_flight_defaults_disabled():
    p = Project.model_validate({"id": "old", "name": "old", "animals": [{"id": "bird"}]})
    assert not p.animals[0].flight.enabled
    assert p.animals[0].behaviors["fly"] == 0


def test_flight_config_is_bounded():
    p = Project.model_validate({"id": "t", "name": "t", "animals": [{"id": "bird", "flight": {
        "enabled": True, "anim": "not-a-slot", "speed": [-2, 900], "altitude": [-1, 3],
        "legs": [0, 99], "hover": 4, "wobble": 500, "wobble_hz": -1,
    }}]})
    f = p.animals[0].flight
    assert f.anim == "run"
    assert f.speed == [5, 900]
    assert f.altitude == [0, 0.9]
    assert f.legs == [1, 8]
    assert f.hover == 1 and f.wobble == 200 and f.wobble_hz == 0
