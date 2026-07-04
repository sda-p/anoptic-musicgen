"""Voice-led chord voicings by minimum-movement search (PLANS.md §5.3).

Candidates are strictly ascending pitch tuples realizing the chord's pc
multiset inside a register window; the winner minimizes total semitone
movement from the previous voicing (plus a mild top-voice smoothness term).
No randomness — voicing is a pure function of (chord, previous voicing).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class VoicingConfig:
    voices: int = 4
    lo: int = 52  # E3
    hi: int = 79  # G5
    max_adjacent_gap: int = 12
    center: float = 64.0


def select_voice_pcs(chord_pcs: tuple[int, ...], voices: int) -> tuple[int, ...]:
    """Choose the pc multiset the voices take.

    Expects root-first pcs (root, third, fifth, extensions...). Doubling
    prefers root then fifth, never the third; dropping prefers the fifth then
    the root — the bass layer already covers the root.
    """
    out = list(chord_pcs)
    double_order = (0, 2, 1)
    i = 0
    while len(out) < voices:
        idx = double_order[i % len(double_order)]
        if idx < len(chord_pcs):
            out.append(chord_pcs[idx])
        i += 1
    if len(out) > voices:
        for idx in (2, 0):  # drop fifth, then root
            if len(out) > voices and idx < len(chord_pcs):
                out.remove(chord_pcs[idx])
    return tuple(out[:voices])


def _octave_options(pc: int, cfg: VoicingConfig) -> list[int]:
    first = cfg.lo + (pc - cfg.lo) % 12
    return list(range(first, cfg.hi + 1, 12))


def candidate_voicings(voice_pcs: tuple[int, ...], cfg: VoicingConfig) -> list[tuple[int, ...]]:
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[int, ...]] = []
    for combo in product(*[_octave_options(pc, cfg) for pc in voice_pcs]):
        voicing = tuple(sorted(combo))
        if voicing in seen:
            continue
        seen.add(voicing)
        if any(b <= a for a, b in zip(voicing, voicing[1:])):  # unison doubling
            continue
        if any(b - a > cfg.max_adjacent_gap for a, b in zip(voicing, voicing[1:])):
            continue
        out.append(voicing)
    return out


def voicing_cost(candidate: tuple[int, ...], prev: tuple[int, ...] | None, cfg: VoicingConfig) -> float:
    if prev is None or len(prev) != len(candidate):
        centering = abs(sum(candidate) / len(candidate) - cfg.center)
        return centering + 0.1 * (candidate[-1] - candidate[0])
    movement = sum(abs(a - b) for a, b in zip(prev, candidate))
    top_smoothness = max(0, abs(candidate[-1] - prev[-1]) - 2) * 0.5
    return movement + top_smoothness


def voice_chord(
    chord_pcs: tuple[int, ...],
    prev: tuple[int, ...] | None,
    cfg: VoicingConfig = VoicingConfig(),
) -> tuple[tuple[int, ...], float]:
    """Best voicing (ascending pitches) for root-first chord pcs, given the
    previous voicing. Returns (voicing, cost)."""
    voice_pcs = select_voice_pcs(chord_pcs, cfg.voices)
    candidates = candidate_voicings(voice_pcs, cfg)
    if not candidates:
        raise ValueError(f"no voicing of pcs {voice_pcs} fits in [{cfg.lo}, {cfg.hi}]")
    best = min(candidates, key=lambda c: voicing_cost(c, prev, cfg))
    return best, voicing_cost(best, prev, cfg)
