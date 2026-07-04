"""Core intermediate representation: theory-annotated events and context types.

All times are in quarter-note beats from piece start (MIDI-natural: ticks =
beats * PPQ). Pre-modifier events align to GRID; only modifiers (M4) may move
events off-grid. MIDI is the *output* format — inspection and linting operate
on this IR, which carries the theory annotations MIDI cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale

GRID = 0.25  # 16th-note grid, in quarter-note beats

LAYER_NAMES = ("pad", "bass", "melody", "arp", "perc")


@dataclass(frozen=True)
class Meter:
    numerator: int = 4
    denominator: int = 4

    @property
    def bar_quarters(self) -> float:
        """Bar length in quarter-note beats (4/4 -> 4.0, 6/8 -> 3.0)."""
        return self.numerator * 4.0 / self.denominator

    def bar_of(self, start: float) -> int:
        """0-based bar index containing a beat position."""
        return int(start // self.bar_quarters)

    def beat_in_bar(self, start: float) -> float:
        """1-based musician-style beat position within the bar."""
        return start - self.bar_of(start) * self.bar_quarters + 1.0


@dataclass
class NoteEvent:
    start: float  # absolute quarter-note beats from piece start
    dur: float    # musical duration in beats (pre-articulation)
    pitch: int
    velocity: int
    layer: str
    # --- annotations (inspection & linting only, no acoustic effect) ---
    degree: int | None = None  # 1..7 within the bar's scale
    chord: str = ""            # roman-numeral symbol in context, e.g. "V7"
    role: str = ""             # "chord-tone" | "passing" | "root" | "approach" | ...

    def __post_init__(self) -> None:
        if self.layer not in LAYER_NAMES:
            raise ValueError(f"unknown layer {self.layer!r}")
        if not 0 <= self.pitch <= 127:
            raise ValueError(f"pitch {self.pitch} out of MIDI range")
        if not 1 <= self.velocity <= 127:
            raise ValueError(f"velocity {self.velocity} out of range 1..127")
        if self.start < 0 or self.dur <= 0:
            raise ValueError(f"bad timing: start={self.start} dur={self.dur}")

    @property
    def end(self) -> float:
        return self.start + self.dur


@dataclass
class HarmonicContext:
    """Per-bar harmonic state handed from the conductor to generators.

    chord_pcs is bass-first: chord_pcs[0] is the sounding bass pitch class
    (respecting inversion); the linter's bass-root rule relies on this.
    """

    bar: int  # 0-based
    scale: Scale
    chord: Chord | None = None
    chord_sym: str = ""
    chord_pcs: tuple[int, ...] = ()
    next_chord: Chord | None = None
    next_chord_sym: str = ""
    tension: float = 0.0
    cadence_slot: str = ""    # "" | "pre-cadence" | "cadence"
    cadence_policy: str = ""  # "" | "authentic" | "half" | "deceptive"


@dataclass
class MusicalParams:
    """Tier-2 musical parameters (PLANS.md §6.2).

    M0 consumes only tempo_bpm; M1/M2 read the rest from static config
    literals; the affect mapper that derives them arrives in M3.
    """

    tempo_bpm: float = 100.0
    note_density: float = 0.5
    roughness: float = 0.0
    articulation: float = 0.9    # gate ratio: staccato 0.45 .. legato 1.05
    velocity_center: int = 80
    accent_depth: int = 12
    register_center: int = 72    # melody center (C5)
    layers: tuple[str, ...] = ("pad", "bass")
    harmonic_rhythm: float = 1.0  # chords per bar
    dissonance_budget: float = 0.0
    cadence_policy: str = "authentic"
