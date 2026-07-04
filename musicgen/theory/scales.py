"""Diatonic modes on the EMS brightness axis (PLANS.md §5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

_IONIAN = (0, 2, 4, 5, 7, 9, 11)

# Conventional key spellings (Eb, not D#; F# kept sharp) for Scale.name.
# Event-level spelling stays sharps-only — see pitch.pitch_name's TODO.
TONIC_NAMES = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")

MODE_OFFSETS = {
    "ionian": 0,
    "dorian": 1,
    "phrygian": 2,
    "lydian": 3,
    "mixolydian": 4,
    "aeolian": 5,
    "locrian": 6,
}

# Usable modes, bright to dark. Locrian is deliberately absent (PLANS.md §2);
# the control layer (M3) must only select from these.
BRIGHTNESS = {
    "lydian": 3,
    "ionian": 2,
    "mixolydian": 1,
    "dorian": 0,
    "aeolian": -1,
    "phrygian": -2,
}


def mode_intervals(mode: str) -> tuple[int, ...]:
    """Ascending semitone offsets from the tonic for a diatonic mode."""
    k = MODE_OFFSETS[mode]
    root = _IONIAN[k]
    return tuple((_IONIAN[(k + i) % 7] - root) % 12 for i in range(7))


@dataclass(frozen=True)
class Scale:
    tonic: int  # pitch class 0..11
    mode: str = "ionian"

    def __post_init__(self) -> None:
        if self.mode not in MODE_OFFSETS:
            raise ValueError(f"unknown mode {self.mode!r}")
        if not 0 <= self.tonic <= 11:
            raise ValueError(f"tonic must be a pitch class 0..11, got {self.tonic}")

    @cached_property
    def intervals(self) -> tuple[int, ...]:
        return mode_intervals(self.mode)

    @cached_property
    def pcs(self) -> tuple[int, ...]:
        """Pitch classes, ascending from the tonic."""
        return tuple((self.tonic + iv) % 12 for iv in self.intervals)

    def contains(self, midi: int) -> bool:
        return midi % 12 in self.pcs

    def degree_of(self, midi: int) -> int | None:
        """1-based scale degree of a pitch, or None if chromatic."""
        pc = midi % 12
        for i, p in enumerate(self.pcs):
            if p == pc:
                return i + 1
        return None

    def pitch_at(self, degree: int, octave: int) -> int:
        """MIDI pitch of a 1-based degree; `octave` is the tonic's octave
        (C-ionian pitch_at(1, 4) == 60). Degrees past 7 wrap upward, so
        stacking thirds as (d, d+2, d+4) works across the octave break."""
        if degree < 1:
            raise ValueError("degree is 1-based")
        step, oct_up = (degree - 1) % 7, (degree - 1) // 7
        return (octave + 1 + oct_up) * 12 + self.tonic + self.intervals[step]

    @property
    def name(self) -> str:
        return f"{TONIC_NAMES[self.tonic]} {self.mode}"


def snap_to_scale(scale: Scale, pitch: int) -> int:
    """Nearest scale tone (upward preference on ties)."""
    for delta in (0, 1, -1, 2, -2):
        if scale.contains(pitch + delta):
            return pitch + delta
    return pitch


def diatonic_shift(scale: Scale, pitch: int, steps: int) -> int:
    """Walk N scale steps from a pitch (snapped to the scale first)."""
    p = snap_to_scale(scale, pitch)
    direction = 1 if steps > 0 else -1
    for _ in range(abs(steps)):
        q = p + direction
        while not scale.contains(q):
            q += direction
        p = q
    return p
