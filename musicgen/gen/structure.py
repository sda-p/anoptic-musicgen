"""Phrase clock, cadence slots, and the within-phrase tension micro-arc
(PLANS.md §5.6): tension rises toward the pre-cadence bar and settles at the
cadence, giving local shape even under static levers.
"""

from __future__ import annotations

from dataclasses import dataclass

ARCS = {
    4: (0.90, 1.00, 1.20, 0.75),
    8: (0.85, 0.90, 1.00, 1.05, 1.10, 1.20, 1.30, 0.75),
}


@dataclass(frozen=True)
class PhrasePos:
    phrase: int  # 0-based phrase index
    pos: int     # 0-based bar within the phrase
    bars: int    # phrase length in bars

    @property
    def slot(self) -> str:
        if self.pos == self.bars - 1:
            return "cadence"
        if self.pos == self.bars - 2:
            return "pre-cadence"
        if self.pos == 0:
            return "open"
        return "free"


def phrase_position(bar: int, phrase_bars: int = 8) -> PhrasePos:
    return PhrasePos(phrase=bar // phrase_bars, pos=bar % phrase_bars, bars=phrase_bars)


def effective_tension(base: float, pos: PhrasePos) -> float:
    arc = ARCS.get(pos.bars)
    factor = arc[pos.pos] if arc else 1.0
    return max(0.0, min(1.0, base * factor))


HYPER_PROFILE = (1.0, 0.4, 0.7, 0.4)  # bar weights within the 4-bar group (B3)


def hyper_weight(pos: int, bars: int) -> float:
    """Hypermetric weight of a bar within its phrase (REFINEMENT_PLAN B3):
    bars group in fours the way beats group in bars — bar 1 strong, bar 3
    secondary. In phrases of 8+ the mid-phrase downbeat is the second-
    strongest (which is why the M15 signature slot at bars//2 already felt
    right). Consumers: bar-level dynamics, the mid-phrase fill/crash, and the
    slow-harmonic-rhythm hold placement."""
    weight = HYPER_PROFILE[pos % 4]
    if bars >= 8 and pos == bars // 2:
        weight = 0.85
    return weight
