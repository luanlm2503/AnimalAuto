"""Project configuration models (saved as projects/<id>/project.json)."""
from typing import Optional

from pydantic import BaseModel, Field, model_validator

ANIMS = ("idle", "walk", "run")


class Area(BaseModel):
    """Walkable area for the animal's feet, as fractions of the frame."""
    x: float = 0.05
    y: float = 0.55
    w: float = 0.90
    h: float = 0.40


class KeyCfg(BaseModel):
    """Chroma-key settings used when importing clips with a green/blue backdrop."""
    enabled: bool = True
    tolerance: float = 22.0      # chroma distance (0..~120) fully removed
    softness: float = 14.0       # transition width after tolerance
    shadow: float = 0.0          # 0 = off; higher removes darker/duller backdrop tones (floor, cast shadow)
    despill: float = 0.8         # 0..1 removes green tint from edges and fur
    keep_largest: bool = True    # drop specks not attached to the animal


class AnimSet(BaseModel):
    """One imported animation (idle / walk / run) stored as a PNG sequence."""
    src: str = ""                # uploaded original, relative to the project dir
    frames: int = 0
    fps: float = 24.0
    width: int = 0               # stored sprite size in px
    height: int = 0
    px_scale: float = 1.0        # stored px / source px (keeps anims of one animal at the same scale)
    loop: str = "loop"           # loop | pingpong
    native_speed: float = 0.0    # sprite px/s the clip "walks" at; 0 = follow the speed range
    scale: float = 1.0           # extra size factor relative to the animal size
    trim_start: float = 0.0
    trim_end: float = 0.0        # 0 = until the end
    auto_loop: bool = False
    stabilize: bool = True       # cancel steady drift when the clip's animal slides across its frame
    key_used: Optional[dict] = None   # key settings this import was made with (UI shows "not applied yet")


class FlightCfg(BaseModel):
    """Optional flight behaviour; altitude and speed are relative to the frame."""
    enabled: bool = False
    anim: str = "run"             # existing animation slot used for flapping
    speed: list[float] = Field(default_factory=lambda: [250.0, 450.0])
    altitude: list[float] = Field(default_factory=lambda: [0.12, 0.32])  # fraction of frame height
    legs: list[int] = Field(default_factory=lambda: [1, 3])
    hover: float = 0.0             # probability of a brief mid-flight hover
    wobble: float = 0.0            # vertical flutter in reference pixels
    wobble_hz: float = 2.0

    @model_validator(mode="after")
    def normalize(self):
        self.speed = [max(5.0, float(v)) for v in self.speed[:2]]
        self.altitude = [min(max(0.0, float(v)), 0.9) for v in self.altitude[:2]]
        self.legs = [min(max(1, int(v)), 8) for v in self.legs[:2]]
        for field, default in (("speed", [250.0, 450.0]), ("altitude", [0.12, 0.32]), ("legs", [1, 3])):
            values = getattr(self, field)
            if not values:
                setattr(self, field, default)
            elif len(values) == 1:
                values.append(values[0])
        self.hover = min(max(float(self.hover), 0.0), 1.0)
        self.wobble = min(max(float(self.wobble), 0.0), 200.0)
        self.wobble_hz = min(max(float(self.wobble_hz), 0.0), 20.0)
        if self.anim not in ANIMS:
            self.anim = "run"
        return self


class Animal(BaseModel):
    id: str
    name: str = "mouse"
    enabled: bool = True         # off = kept in the project but left out of videos
    count: int = 1
    area: Optional[Area] = None  # None = use the project-wide walkable area
    flight: FlightCfg = Field(default_factory=FlightCfg)
    size_pct: float = 7.0        # sprite width as % of the frame width
    facing: str = "right"        # direction the source clip faces
    anims: dict[str, AnimSet] = Field(default_factory=dict)
    key: KeyCfg = Field(default_factory=KeyCfg)
    walk_speed: list[float] = Field(default_factory=lambda: [60.0, 120.0])    # px/s at 1920 wide
    run_speed: list[float] = Field(default_factory=lambda: [250.0, 450.0])
    pause: list[float] = Field(default_factory=lambda: [0.4, 3.0])
    behaviors: dict[str, float] = Field(
        default_factory=lambda: {"walk": 30, "run": 30, "idle": 25, "turn": 8, "hide": 7, "fly": 0})
    sounds: list[str] = Field(default_factory=list)
    sound_enabled: bool = True
    sound_interval: list[float] = Field(default_factory=lambda: [6.0, 25.0])
    sound_volume: list[float] = Field(default_factory=lambda: [0.4, 0.8])


class RenderCfg(BaseModel):
    duration: str = "01:00:00"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    seed: Optional[int] = None
    shadow: bool = True
    shadow_opacity: float = 0.35
    depth_scale: bool = False
    encoder: str = "auto"        # auto | libx264 | h264_nvenc
    crf: int = 20
    chunk_seconds: int = 300


class Project(BaseModel):
    id: str
    name: str
    background: str = ""
    area: Area = Field(default_factory=Area)
    animals: list[Animal] = Field(default_factory=list)
    ambience: str = ""
    ambience_volume: float = 0.25
    render: RenderCfg = Field(default_factory=RenderCfg)


def parse_duration(text: str) -> float:
    """'08:00:00' / '45:00' / '90' (seconds) -> seconds."""
    parts = [float(p) for p in str(text).strip().split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    if secs <= 0:
        raise ValueError(f"invalid duration: {text!r}")
    return secs


def format_duration(secs: float) -> str:
    s = int(round(secs))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
