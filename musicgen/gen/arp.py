"""Arpeggio layer: chord tones cycled above the pad (PLANS.md §5.6).

The traversal pattern (up / down / up-down) is fixed per phrase for
coherence; rate and skip probability follow note_density.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent

PATTERNS = ("up", "updown", "down")


@dataclass(frozen=True)
class ArpConfig:
    base_octave: int = 5      # pool starts at C5
    span_octaves: int = 2
    velocity_offset: int = -16


def make_skips(rng: random.Random, meter: Meter, density: float) -> frozenset[int]:
    """Per-phrase rest mask (REFINEMENT_PLAN A2): the arp's skip slots drawn once
    per phrase — like its traversal pattern — so the figuration is a held pattern
    the ear can track harmony through, not a fresh roll every bar."""
    step = 1 if density > 0.65 else 2
    skip_prob = max(0.0, 1.0 - density) * 0.35
    return frozenset(s for s in range(0, meter.slots, step)
                     if s != 0 and rng.random() < skip_prob)


def generate_arp(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    pattern: str,
    cfg: ArpConfig,
    rng: random.Random,
    skips: frozenset[int] | None = None,
) -> tuple[list[NoteEvent], str]:
    lo = (cfg.base_octave + 1) * 12
    hi = lo + cfg.span_octaves * 12
    pool = sorted(
        p
        for pc in set(ctx.chord_pcs)
        for p in range(lo + (pc - lo) % 12, hi + 1, 12)
    )
    if not pool:
        return [], "arp: empty pool"
    if pattern == "down":
        seq = list(reversed(pool))
    elif pattern == "updown":
        seq = pool + pool[-2:0:-1]
    else:
        seq = pool

    step = 1 if params.note_density > 0.65 else 2
    skip_prob = max(0.0, 1.0 - params.note_density) * 0.35
    velocity = max(1, min(127, params.velocity_center + cfg.velocity_offset))
    bar_start = ctx.bar * meter.bar_quarters

    events: list[NoteEvent] = []
    idx = 0
    for slot in range(0, meter.slots, step):
        skip = (slot in skips) if skips is not None else (slot != 0 and rng.random() < skip_prob)
        if skip:
            idx += 1  # keep traversal moving through rests
            continue
        pitch = seq[idx % len(seq)]
        idx += 1
        accent = 4 if slot % 8 == 0 else 0
        events.append(NoteEvent(
            bar_start + slot * GRID, step * GRID, pitch, velocity + accent, "arp",
            degree=ctx.scale.degree_of(pitch),
            chord=ctx.chord_sym,
            role="chord-tone" if ctx.scale.contains(pitch) else "borrowed",
        ))
    return events, f"arp: {pattern} pool {len(pool)} step {step}"
