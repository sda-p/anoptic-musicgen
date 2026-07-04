"""Pitch classes, MIDI numbers, and note-name spelling."""

from __future__ import annotations

import re

PC_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
PC_FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

_BASE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NAME_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def pitch_class(midi: int) -> int:
    return midi % 12


def octave_of(midi: int) -> int:
    return midi // 12 - 1  # MIDI 60 == C4


def pitch_name(midi: int, prefer_flats: bool = False) -> str:
    # TODO(M1): spell relative to the active key (F# in D major, not Gb).
    names = PC_FLAT if prefer_flats else PC_SHARP
    return f"{names[midi % 12]}{octave_of(midi)}"


def name_to_midi(name: str) -> int:
    m = _NAME_RE.match(name.strip())
    if not m:
        raise ValueError(f"bad note name {name!r}")
    letter, accidental, octave = m.groups()
    pc = _BASE_PC[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental]
    midi = (int(octave) + 1) * 12 + pc
    if not 0 <= midi <= 127:
        raise ValueError(f"{name!r} is out of MIDI range")
    return midi
