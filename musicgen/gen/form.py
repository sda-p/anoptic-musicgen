"""Phrase-level form planning (REFINEMENT_PLAN B2: antecedent–consequent
periods). D2's elastic PhraseClock (codetta / extension / elision) grows here.

The antecedent–consequent period — two phrases opening identically, the first
ending on a half cadence, the second answering with an authentic one — is the
strongest "a mind composed this" signal in tonal music, and this codebase had
most of the machinery already: per-phrase cadence policies, a per-phrase motif
cache, cadence rationing. The planner is dumb state; the commitment logic lives
in the conductor (it needs affect, dramaturg, and modulation context). Cadence
precedence, documented once here and implemented in MusicEngine._policy:

    modulation > override > dramaturg > period planner > cycle / mapper

The dramaturg outranking the planner is the musical truth: while withholding,
a consequent's promised PAC becomes another deception and the period rolls
forward — and a dramaturg spend landing on a consequent is the maximal arrival
(PAC + cadential 6/4 + the M15 cadence-fused statement + brightening at once).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicgen.gen.structure import PhrasePos
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale


@dataclass
class Segment:
    """One scheduled phrase (D2): where it starts, how long it runs, and what
    it is. An "elision" segment starts ON the previous segment's cadence bar
    (the one bar serving as both resolution and opening)."""

    start: int
    bars: int
    kind: str = ""  # "" | "codetta" | "extension" | "elision"


@dataclass
class PhraseClock:
    """The scheduled phrase clock (REFINEMENT_PLAN D2). Everything was 4 or 8
    bars because phrase position was a pure div/mod; this replaces the
    arithmetic with a SCHEDULE — a list of committed segments, extrapolated
    with the default length beyond the frontier — so the dramaturg and the
    planner can author codettas (a 2-bar tonic afterglow appended to a big
    payoff), extensions (the pre-dominant stretched while withholding), and
    elisions (the next phrase starting ON the cadence bar). With nothing
    scheduled, position() reproduces structure.phrase_position exactly —
    byte-identical, which is the regression anchor.

    Commitments only ever touch the frontier (the first unscheduled phrase),
    and every deviation is decided at a phrase's first bar — at least two
    bars before any bar whose slot it changes, safely outside the one-bar
    chord lookahead."""

    phrase_bars: int = 8
    segments: list[Segment] = field(default_factory=list)

    def _frontier(self) -> int:
        """The bar where extrapolation begins (after the last segment)."""
        if not self.segments:
            return 0
        last = self.segments[-1]
        return last.start + last.bars

    def position(self, bar: int) -> PhrasePos:
        # later segments win a shared bar: an elision's opening downbeat
        # belongs to the NEW phrase (the old one's cadence is an annotation)
        for idx in range(len(self.segments) - 1, -1, -1):
            seg = self.segments[idx]
            if seg.start <= bar < seg.start + seg.bars:
                return PhrasePos(phrase=idx, pos=bar - seg.start, bars=seg.bars,
                                 kind=seg.kind)
        base = self._frontier()
        if bar < base:  # inside no segment but before the frontier (unreachable
            #             with contiguous commitments; defensive)
            return PhrasePos(phrase=bar // self.phrase_bars,
                             pos=bar % self.phrase_bars, bars=self.phrase_bars)
        n = len(self.segments) + (bar - base) // self.phrase_bars
        return PhrasePos(phrase=n, pos=(bar - base) % self.phrase_bars,
                         bars=self.phrase_bars)

    def materialize_through(self, phrase: int) -> None:
        """Fill default segments up to and including `phrase` — observably a
        no-op (defaults match extrapolation), but it moves the frontier so a
        deviation can be appended right after."""
        while len(self.segments) <= phrase:
            self.segments.append(Segment(self._frontier(), self.phrase_bars))

    def schedule(self, phrase: int, bars: int, kind: str = "",
                 overlap: int = 0) -> Segment:
        """Commit phrase `phrase` (which must be the frontier) with an
        explicit length/kind; `overlap` starts it that many bars INSIDE the
        previous segment (elision = 1)."""
        self.materialize_through(phrase - 1)
        assert len(self.segments) == phrase, "only the frontier is schedulable"
        seg = Segment(self._frontier() - overlap, bars, kind)
        self.segments.append(seg)
        return seg


@dataclass
class PeriodPlanner:
    """B2 sequential state — lives in ConductorState, deterministic like every
    other cache (a pure function of seed, affect trajectory, and bar). Roles
    are committed pairwise at even phrase boundaries; the antecedent's opening
    (chord, scale, melody realization) is recorded when its first bar sounds so
    the consequent can answer with the same question."""

    periods: dict[int, str] = field(default_factory=dict)  # phrase -> "antecedent" | "consequent"
    opening_chord: dict[int, Chord] = field(default_factory=dict)   # antecedent -> bar-0 chord
    opening_scale: dict[int, Scale] = field(default_factory=dict)   # antecedent -> bar-0 scale
    opening_melody: dict[int, tuple[tuple[int, int, int], ...]] = field(default_factory=dict)
    #                              antecedent -> bar-0 melody as (slot, dur_slots, pitch)

    def role(self, phrase: int) -> str:
        return self.periods.get(phrase, "")

    def commit(self, phrase: int) -> None:
        self.periods[phrase] = "antecedent"
        self.periods[phrase + 1] = "consequent"
