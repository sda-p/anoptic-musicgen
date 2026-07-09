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

from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale


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
