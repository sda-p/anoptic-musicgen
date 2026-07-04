"""Diatonic modes on the EMS brightness axis (PLANS.md §5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from musicgen.theory.pitch import PC_SHARP

_IONIAN = (0, 2, 4, 5, 7, 9, 11)

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
        return f"{PC_SHARP[self.tonic]} {self.mode}"
