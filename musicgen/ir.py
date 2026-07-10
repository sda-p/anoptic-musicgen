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

LAYER_NAMES = ("pad", "bass", "melody", "counter", "arp", "perc")


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

    @property
    def slots(self) -> int:
        """Grid slots per bar (16 in 4/4, 12 in 3/4 and 6/8)."""
        return round(self.bar_quarters / GRID)

    def slot_of(self, start: float) -> int:
        """Grid slot within the bar for a beat position."""
        return round((start - self.bar_of(start) * self.bar_quarters) / GRID)

    @property
    def is_compound(self) -> bool:
        """Compound meters (6/8, 9/8, 12/8) group in threes: the felt pulse
        is the dotted unit, not the notated denominator beat."""
        return self.numerator >= 6 and self.numerator % 3 == 0

    @property
    def pulses(self) -> int:
        """Felt beats per bar (4/4 -> 4, 3/4 -> 3, 6/8 -> 2, 12/8 -> 4)."""
        return self.numerator // 3 if self.is_compound else self.numerator

    @property
    def pulse_quarters(self) -> float:
        """Quarter-note length of one felt beat (1.0 in x/4, 1.5 in 6/8)."""
        return self.bar_quarters / self.pulses

    @property
    def pulse_slots(self) -> int:
        """Grid slots per felt beat (4 in x/4, 6 in 6/8)."""
        return round(self.pulse_quarters / GRID)

    def metric_weights(self) -> tuple[float, ...]:
        """Accent hierarchy per grid slot (PLANS.md §5.4): downbeat 4.0,
        mid-bar pulse 3.5, other pulses 3.0, 8ths 2.0, 16ths 1.0. Pulses are
        felt beats, so 6/8 accents its two dotted quarters, not six 8ths."""
        eighth = max(1, round(0.5 / GRID))
        out = []
        for s in range(self.slots):
            if s == 0:
                out.append(4.0)
            elif s % self.pulse_slots == 0:
                pulse = s // self.pulse_slots
                is_mid = self.pulses % 2 == 0 and pulse == self.pulses // 2
                out.append(3.5 if is_mid else 3.0)
            elif s % eighth == 0:
                out.append(2.0)
            else:
                out.append(1.0)
        return tuple(out)

    def strong_slots(self) -> tuple[int, ...]:
        """Slots carrying beat-level weight (chord-tone rules key off these)."""
        return tuple(s for s, w in enumerate(self.metric_weights()) if w >= 3.0)


TIE_VALUES = ("", "out", "in", "both")


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
    # --- tie flag (REFINEMENT_PLAN D1): "out" continues into the next
    # same-layer same-pitch event whose start meets this end; "in" continues
    # from one; "both" is an interior segment. A CHAIN of tied halves is one
    # musical note that happens to cross barlines — each half stays grid- and
    # bar-legal (the M8 invariant survives), and merge_ties() recovers the
    # logical note for consumers that need it (MIDI, the melodic-line lints).
    tie: str = ""

    def __post_init__(self) -> None:
        if self.layer not in LAYER_NAMES:
            raise ValueError(f"unknown layer {self.layer!r}")
        if not 0 <= self.pitch <= 127:
            raise ValueError(f"pitch {self.pitch} out of MIDI range")
        if not 1 <= self.velocity <= 127:
            raise ValueError(f"velocity {self.velocity} out of range 1..127")
        if self.start < 0 or self.dur <= 0:
            raise ValueError(f"bad timing: start={self.start} dur={self.dur}")
        if self.tie not in TIE_VALUES:
            raise ValueError(f"tie must be one of {TIE_VALUES}, got {self.tie!r}")

    @property
    def end(self) -> float:
        return self.start + self.dur


def merge_ties(events) -> list["NoteEvent"]:
    """Collapse tie chains into logical notes: a chain — consecutive
    same-layer same-pitch events whose ends meet the next start, flagged
    out → (both …) → in — becomes one note with the head's start, velocity,
    and annotations and the summed duration. Untied events pass through
    UNCOPIED and in their given order (byte-identity for tie-free input);
    an orphan "out" (a tie into a rest or an unhosted bar) dissolves into a
    plain note, an orphan "in" passes through as struck (the linter flags
    it). Input is expected in chronological emission order per layer, which
    is how the conductor emits."""
    from dataclasses import replace as _replace

    out: list[NoteEvent] = []
    open_chains: dict[tuple[str, int], NoteEvent] = {}
    for ev in events:
        key = (ev.layer, ev.pitch)
        if ev.tie in ("in", "both"):
            head = open_chains.get(key)
            if head is not None and abs(head.end - ev.start) < 1e-9:
                head.dur = round(head.dur + ev.dur, 10)
                if ev.tie == "in":
                    del open_chains[key]  # the chain closed
                continue
        if ev.tie in ("out", "both"):
            head = _replace(ev, tie="")
            open_chains[key] = head
            out.append(head)
        else:
            out.append(ev)
    return out


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
    modulation: str = ""      # key-change annotation ("pivot ≡ ii of G ionian", ...)
    obligation: str = ""      # M14 harmonic obligation (§5.8): "" | "tonicize:N" — a secondary
    #                           dominant that verify._lint_obligations checks resolves to degree N
    phrase_pos: int = 0       # 0-based bar position within the phrase (REFINEMENT_PLAN A1:
    phrase_bars: int = 8      # phrase-aware modifiers like Perform read these)
    # D3 intra-bar harmonic timeline: (beat offset within the bar, Chord)
    # pairs; empty = one chord per bar (the `chord` field is always the
    # downbeat alias). The prototype populates it only for the compressed
    # cadential 6/4 (I64 -> V inside the pre-cadence bar); harmonic layers
    # and the segment-aware lint rules consume it via chord_at().
    chords: tuple = ()
    phrase_apex: int = -1     # bar-in-phrase of the planned melodic apex (-1 = unplanned; A4 —
    #                           Perform's hairpin crests here instead of at a fixed position)
    form: str = ""            # phrase-form annotation (B2): "" | "antecedent" | "consequent" —
    #                           verify.lint_periods re-derives the question/answer contract from it

    def chord_at(self, beat_offset: float):
        """The chord in force at a beat offset within the bar (D3): the last
        timeline entry at or before the offset, else the downbeat chord."""
        current = self.chord
        for off, ch in self.chords:
            if off <= beat_offset + 1e-9:
                current = ch
        return current


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
    texture: str = ""  # Tier-2 texture state (REFINEMENT_PLAN C4): "" (no texture
    #                    system — pre-C4 behavior) | "monophonic" | "homophonic" |
    #                    "doubled" | "imitative" | "counter". Phrase-quantized by
    #                    the conductor's rotation; verify.lint_texture checks the
    #                    claim each value makes about the sounding events.
    # (layer, patch) pairs, energy-tiered by the mapper. Patch names are
    # semantic; midi_io maps them to GM programs, synth/patches to voice
    # variants. Defaults are the calm tier (the original fixed sounds).
    instruments: tuple[tuple[str, str], ...] = (
        ("pad", "warm"), ("bass", "round"), ("melody", "soft"), ("arp", "pluck"))
    # --- DSP tier (consumed by the synth backend; inert on the MIDI path) ---
    filter_cutoff: float = 2500.0  # Hz, master brightness for subtractive voices
    reverb_send: float = 0.20      # 0..1 global send scale
    delay_send: float = 0.10       # 0..1 global send scale
    drive: float = 0.15            # 0..1 master saturation amount
    stereo_width: float = 0.70     # pad width 0..1+
