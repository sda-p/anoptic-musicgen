"""Euclidean percussion with phrase-end fills (PLANS.md §5.4).

Kick follows E(k, 16) with k scaled by density (slot 0 is always a hit —
E(k, n) starts on 0). Snare anchors the backbeat, gaining rotated ghost hits
as roughness rises. Hats subdivide by density. The cadence bar may replace
its second half with a snare/tom fill (probability grows with tension), and
a fill earns a crash on the next phrase downbeat — fills double as audible
transition markers (iMUSE boundary principle).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.gen.rhythm import euclid
from musicgen.gen.structure import PhrasePos

DRUMS = {
    "kick": 36,
    "rim": 37,
    "snare": 38,
    "chat": 42,   # closed hi-hat
    "ohat": 46,   # open hi-hat
    "crash": 49,
    "ltom": 45,
    "mtom": 47,
    "htom": 50,
    "shaker": 70,
}

FILL_PATTERNS = ((10, 12, 14), (8, 10, 12, 14), (10, 12, 13, 14))
FILL_VOICES = ("snare", "htom", "mtom", "ltom")


@dataclass(frozen=True)
class PercConfig:
    fill_base_prob: float = 0.25
    fill_tension_weight: float = 0.55
    ghost_velocity: int = 52
    base_velocities: tuple[tuple[str, int], ...] = (
        ("kick", 100), ("snare", 96), ("chat", 64), ("ohat", 70), ("crash", 106),
    )


def generate_perc(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    pos: PhrasePos,
    had_fill: bool,
    cfg: PercConfig,
    rng: random.Random,
) -> tuple[list[NoteEvent], bool, str]:
    """One bar of drums. Returns (events, fill_played, trace)."""
    slots = meter.slots
    density, roughness = params.note_density, params.roughness
    vel_of = dict(cfg.base_velocities)
    dyn = params.velocity_center / 80.0

    hits: list[tuple[int, str, int]] = []  # (slot, drum, velocity)

    kick_k = 2 + round(density * 3)
    kick_slots = euclid(kick_k, slots)
    hits += [(s, "kick", vel_of["kick"]) for s in kick_slots]

    backbeat = [s for s in (slots // 4, 3 * slots // 4) if s < slots]
    hits += [(s, "snare", vel_of["snare"]) for s in backbeat]
    ghost_prob = max(0.0, roughness - 0.25) * 0.6
    hits += [
        (s, "snare", cfg.ghost_velocity)
        for s in (3, 7, 10, 15)
        if s < slots and rng.random() < ghost_prob
    ]

    hat_step = 1 if density > 0.7 else 2
    hat_drop = max(0.0, 1.0 - density) * 0.3
    for s in range(0, slots, hat_step):
        if rng.random() < hat_drop:
            continue
        drum = "ohat" if s == slots - 2 and rng.random() < 0.25 else "chat"
        accent = 6 if s % (slots // 4) == 0 else 0
        hits.append((s, drum, vel_of["chat"] + accent))

    fill = False
    trace_bits = [f"kick E({kick_k},{slots})"]
    if pos.slot == "cadence":
        fill_prob = cfg.fill_base_prob + ctx.tension * cfg.fill_tension_weight
        fill = rng.random() < fill_prob
        if fill:
            pattern = FILL_PATTERNS[rng.randrange(len(FILL_PATTERNS))]
            hits = [h for h in hits if h[0] < pattern[0]]
            for i, s in enumerate(pattern):
                voice = FILL_VOICES[min(i, len(FILL_VOICES) - 1)]
                hits.append((s, voice, 84 + i * 7))
            trace_bits.append(f"fill {pattern}")

    if had_fill and pos.pos == 0:
        hits.append((0, "crash", vel_of["crash"]))
        trace_bits.append("crash")

    bar_start = ctx.bar * meter.bar_quarters
    events = [
        NoteEvent(
            bar_start + slot * GRID, GRID, DRUMS[drum],
            max(1, min(127, round(vel * dyn))),
            "perc", role=f"drum:{drum}",
        )
        for slot, drum, vel in sorted(hits)
    ]
    return events, fill, "perc: " + ", ".join(trace_bits)
