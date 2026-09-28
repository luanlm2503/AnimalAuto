"""Audio for one chunk: looped ambience + scheduled animal sounds."""
import wave
from pathlib import Path

import numpy as np

from .assets import read_wav
from .timeline import SoundEvent

SR = 48000


class AudioBank:
    def __init__(self, pdir: Path):
        self.pdir = pdir
        self.cache: dict[str, np.ndarray] = {}

    def get(self, rel: str) -> np.ndarray | None:
        if rel not in self.cache:
            f = self.pdir / rel
            self.cache[rel] = read_wav(f) if f.is_file() else None
        return self.cache[rel]


def mix_chunk(bank: AudioBank, t0: float, t1: float, sounds: list[SoundEvent],
              ambience: str, ambience_volume: float) -> np.ndarray:
    n = int(round((t1 - t0) * SR))
    buf = np.zeros((n, 2), np.float32)
    if ambience:
        amb = bank.get(ambience)
        if amb is not None and len(amb):
            start = int(round(t0 * SR)) % len(amb)
            reps = (start + n) // len(amb) + 1
            buf += np.tile(amb, (reps, 1))[start:start + n] * ambience_volume
    for ev in sounds:
        clip = bank.get(ev.file)
        if clip is None:
            continue
        s = int(round((ev.t - t0) * SR))
        e = s + len(clip)
        if e <= 0 or s >= n:
            continue
        cs = max(0, -s)
        buf[max(s, 0):min(e, n)] += clip[cs:cs + min(e, n) - max(s, 0)] * ev.volume
    peak = np.abs(buf).max() if n else 0
    if peak > 0.95:
        buf = np.tanh(buf)  # soft clip
    return buf


def events_for(sounds: list[SoundEvent], t0: float, t1: float, max_len: float = 30.0) -> list[SoundEvent]:
    return [e for e in sounds if t0 - max_len <= e.t < t1]


def write_wav(path: Path, buf: np.ndarray):
    data = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
