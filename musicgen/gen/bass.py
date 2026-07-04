"""Bass lines: root anchoring with density-tiered patterns and approach tones
into the next chord (PLANS.md §5.3).

Tiers by note_density: sustained roots -> root + approach -> root/fifth/approach.
Root instances are chosen nearest the previous bar's root so the line moves
smoothly; approach tones may be diatonic neighbors or the chromatic tone below
the target (role "approach" licenses them with the linter).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.scales import Scale


@dataclass(frozen=True)
class BassConfig:
    lo: int = 28  # E1
    hi: int = 50  # D3
    velocity_offset: int = 8
    approach_beats: float = 1.0


def _nearest_instance(pc: int, near: int, lo: int, hi: int) -> int:
    candidates = range(lo + (pc - lo) % 12, hi + 1, 12)
    return min(candidates, key=lambda p: (abs(p - near), p))


def _approach_options(target: int, scale: Scale) -> list[tuple[int, str, float]]:
    """(pitch, kind, weight) candidates approaching a target root."""
    below = max(p for p in range(target - 3, target) if scale.contains(p))
    above = min(p for p in range(target + 1, target + 4) if scale.contains(p))
    options = [(below, "diatonic-below", 0.40), (above, "diatonic-above", 0.30)]
    chromatic = target - 1
    if chromatic != below:
        options.append((chromatic, "chromatic-below", 0.30))
    return options


def generate_bass(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    prev_root: int | None,
    next_bass_pc: int | None,
    cfg: BassConfig,
    rng: random.Random,
) -> tuple[list[NoteEvent], int, str]:
    """One bar of bass. Returns (events, this bar's root pitch, trace)."""
    bar_len = meter.bar_quarters
    start = ctx.bar * bar_len
    root_pc = ctx.chord_pcs[0]
    near = prev_root if prev_root is not None else (cfg.lo + cfg.hi) // 2
    root = _nearest_instance(root_pc, near, cfg.lo, cfg.hi)
    velocity = max(1, min(127, params.velocity_center + cfg.velocity_offset))

    def note(t: float, d: float, p: int, role: str) -> NoteEvent:
        return NoteEvent(t, d, p, velocity, "bass",
                         degree=ctx.scale.degree_of(p), chord=ctx.chord_sym, role=role)

    approach: NoteEvent | None = None
    trace_bits = [f"root {root}"]
    wants_approach = (
        params.note_density >= 0.35
        and next_bass_pc is not None
        and next_bass_pc != root_pc
        and bar_len >= 2.0
    )
    if wants_approach:
        target = _nearest_instance(next_bass_pc, root, cfg.lo, cfg.hi)
        options = [(p, k, w) for p, k, w in _approach_options(target, ctx.scale) if cfg.lo <= p <= cfg.hi]
        if options:
            pitches, kinds, weights = zip(*options)
            i = rng.choices(range(len(options)), weights=weights)[0]
            approach = note(start + bar_len - cfg.approach_beats, cfg.approach_beats, pitches[i], "approach")
            trace_bits.append(f"approach {kinds[i]} {pitches[i]} -> target {target}")

    # Root/fifth split lands on a pulse (half-bar in 4/4 and 6/8, beat 2 in
    # 3/4) so the fifth reinforces the meter instead of an offbeat.
    split = meter.pulse_quarters * max(1, meter.pulses // 2)
    events: list[NoteEvent] = []
    if params.note_density < 0.35 or approach is None:
        events.append(note(start, bar_len, root, "root"))
    elif params.note_density < 0.65 or bar_len - split - cfg.approach_beats <= 0:
        events.append(note(start, bar_len - cfg.approach_beats, root, "root"))
    else:
        fifth_pc = ctx.chord_pcs[2] if len(ctx.chord_pcs) >= 3 else root_pc
        fifth = _nearest_instance(fifth_pc, root, cfg.lo, cfg.hi)
        events.append(note(start, split, root, "root"))
        events.append(note(start + split, bar_len - split - cfg.approach_beats, fifth, "chord-tone"))
        trace_bits.append(f"fifth {fifth}")
    if approach is not None:
        events.append(approach)
    return events, root, "bass: " + ", ".join(trace_bits)
