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
    max_voice_move: int = 7  # mirrors the linter's voice-move rule


def voice_pc_options(chord_pcs: tuple[int, ...], voices: int) -> tuple[tuple[int, ...], ...]:
    """Candidate pc multisets for the voices, in preference order.

    Expects root-first pcs (root, third, fifth, extensions...). Doubling
    offers root-doubled then fifth-doubled (never the third); dropping offers
    fifth-dropped then root-dropped — the bass layer already covers the root.
    Multiple options matter: a forced doubling can pin both instances of a pc
    to specific octaves and force a voice to leap; the alternative multiset
    gives the movement optimizer an escape.
    """
    if len(chord_pcs) == voices:
        return (tuple(chord_pcs),)
    options: list[tuple[int, ...]] = []
    if len(chord_pcs) < voices:
        for double_idx in (0, 2, 1):
            if double_idx >= len(chord_pcs):
                continue
            out = list(chord_pcs)
            while len(out) < voices:
                out.append(chord_pcs[double_idx])
            options.append(tuple(out))
    else:
        for drop_idx in (2, 0, 1):
            out = [pc for i, pc in enumerate(chord_pcs) if i != drop_idx]
            while len(out) > voices:
                out.pop()  # trim extensions beyond capacity (not reachable today)
            if len(out) == voices:
                options.append(tuple(out))
    return tuple(options[:2] if len(options) > 2 else options) or (tuple(chord_pcs[:voices]),)


def select_voice_pcs(chord_pcs: tuple[int, ...], voices: int) -> tuple[int, ...]:
    """The preferred pc multiset (first of voice_pc_options)."""
    return voice_pc_options(chord_pcs, voices)[0]


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
    # Minimizing the SUM can concentrate motion in one voice; per-voice
    # excess is penalized steeply so the optimizer honors the linter's cap.
    per_voice_excess = sum(
        max(0, abs(a - b) - cfg.max_voice_move) * 20.0 for a, b in zip(prev, candidate)
    )
    return movement + top_smoothness + per_voice_excess


def voice_chord(
    chord_pcs: tuple[int, ...],
    prev: tuple[int, ...] | None,
    cfg: VoicingConfig = VoicingConfig(),
) -> tuple[tuple[int, ...], float]:
    """Best voicing (ascending pitches) for root-first chord pcs, given the
    previous voicing. Searches all doubling/dropping options. Returns
    (voicing, cost)."""
    candidates: list[tuple[int, ...]] = []
    for voice_pcs in voice_pc_options(chord_pcs, cfg.voices):
        candidates.extend(candidate_voicings(voice_pcs, cfg))
    if not candidates:
        raise ValueError(f"no voicing of pcs {chord_pcs} fits in [{cfg.lo}, {cfg.hi}]")
    best = min(candidates, key=lambda c: voicing_cost(c, prev, cfg))
    return best, voicing_cost(best, prev, cfg)
