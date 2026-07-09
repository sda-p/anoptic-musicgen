"""Euclidean percussion with phrase-end fills (PLANS.md §5.4).

In simple meters the kick follows E(k, slots) with k scaled by density (slot
0 is always a hit — E(k, n) starts on 0); compound meters get grouped kicks
instead (even pulses, plus the shuffle 8th and a pickup as density rises),
since Euclidean spreading fights the 3+3 grouping. Snare anchors odd pulses
(the backbeat generalized: beats 2+4 in 4/4, the second dotted quarter in
6/8), gaining ghost pickups as roughness rises. Hats subdivide by density and
accent pulses. The cadence bar may replace its tail with a snare/tom fill
(probability grows with tension), and a fill earns a crash on the next phrase
downbeat — fills double as audible transition markers (iMUSE boundary
principle).
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

FILL_PATTERNS = ((-6, -4, -2), (-8, -6, -4, -2), (-6, -4, -3, -2))  # slots from bar end
FILL_VOICES = ("snare", "htom", "mtom", "ltom")


def _ghost_slots(meter: Meter) -> tuple[int, ...]:
    if meter.is_compound:  # 8th-note pickups into each pulse
        return tuple(p * meter.pulse_slots - 2 for p in range(1, meter.pulses + 1))
    if meter.slots == 16:  # the classic 4/4 ghost set, kept verbatim
        return (3, 7, 10, 15)
    return tuple(p * meter.pulse_slots - 1 for p in range(1, meter.pulses + 1))


@dataclass(frozen=True)
class PercConfig:
    fill_base_prob: float = 0.25
    fill_tension_weight: float = 0.55
    ghost_velocity: int = 52
    base_velocities: tuple[tuple[str, int], ...] = (
        ("kick", 100), ("snare", 96), ("chat", 64), ("ohat", 70), ("crash", 106),
    )


@dataclass(frozen=True)
class Groove:
    """Pattern-identity draws pinned for a phrase (REFINEMENT_PLAN A2). The
    ghost-snare set, the hat-drop mask, and the open-hat choice re-rolled every
    bar under per-bar seeding; pinning them per phrase makes groove identity an
    explicit contract — pattern identity is what makes harmonic change legible.
    Fills stay per-bar: they are the licensed variation."""

    ghosts: tuple[int, ...]      # ghost-snare slots that sound this phrase
    hat_drops: frozenset[int]    # hat slots silent this phrase
    ohat: bool                   # the pre-downbeat hat opens this phrase


def make_groove(rng: random.Random, meter: Meter, density: float, roughness: float,
                cfg: PercConfig = PercConfig()) -> Groove:
    """One phrase's groove, drawn from a per-(subsystem, phrase) stream with the
    phrase-start params — the same probabilities generate_perc rolls per bar."""
    ghost_prob = max(0.0, roughness - 0.25) * 0.6
    ghosts = tuple(s for s in _ghost_slots(meter)
                   if s < meter.slots and rng.random() < ghost_prob)
    hat_step = 1 if density > 0.7 else 2
    hat_drop = max(0.0, 1.0 - density) * 0.3
    drops = frozenset(s for s in range(0, meter.slots, hat_step) if rng.random() < hat_drop)
    return Groove(ghosts, drops, rng.random() < 0.25)


def generate_perc(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    pos: PhrasePos,
    had_fill: bool,
    cfg: PercConfig,
    rng: random.Random,
    groove: Groove | None = None,
) -> tuple[list[NoteEvent], bool, str]:
    """One bar of drums. Returns (events, fill_played, trace). With a `groove`
    the stochastic pattern draws (ghosts, hat drops, open hat) come pinned from
    the phrase (A2) and the per-bar stream rolls only the fill; without one,
    behavior is byte-identical to the per-bar rolls."""
    slots = meter.slots
    density, roughness = params.note_density, params.roughness
    vel_of = dict(cfg.base_velocities)
    dyn = params.velocity_center / 80.0

    hits: list[tuple[int, str, int]] = []  # (slot, drum, velocity)

    if meter.is_compound:
        ps = meter.pulse_slots
        kicks = {p * ps for p in range(0, meter.pulses, 2)}
        if density > 0.55:
            kicks |= {p * ps + 4 for p in range(0, meter.pulses, 2)}  # the shuffle 8th
        if density > 0.75:
            kicks.add(slots - 2)  # 8th pickup into the next downbeat
        kick_slots = tuple(sorted(kicks))
        kick_trace = f"kick grouped {kick_slots}"
    else:
        kick_k = 2 + round(density * 3)
        kick_slots = euclid(kick_k, slots)
        kick_trace = f"kick E({kick_k},{slots})"
    hits += [(s, "kick", vel_of["kick"]) for s in kick_slots]

    backbeat = [p * meter.pulse_slots for p in range(1, meter.pulses, 2)]
    hits += [(s, "snare", vel_of["snare"]) for s in backbeat]
    if groove is not None:
        hits += [(s, "snare", cfg.ghost_velocity) for s in groove.ghosts]
    else:
        ghost_prob = max(0.0, roughness - 0.25) * 0.6
        hits += [
            (s, "snare", cfg.ghost_velocity)
            for s in _ghost_slots(meter)
            if s < slots and rng.random() < ghost_prob
        ]

    hat_step = 1 if density > 0.7 else 2
    hat_drop = max(0.0, 1.0 - density) * 0.3
    for s in range(0, slots, hat_step):
        if groove is not None:
            if s in groove.hat_drops:
                continue
            drum = "ohat" if s == slots - 2 and groove.ohat else "chat"
        else:
            if rng.random() < hat_drop:
                continue
            drum = "ohat" if s == slots - 2 and rng.random() < 0.25 else "chat"
        accent = 6 if s % meter.pulse_slots == 0 else 0
        hits.append((s, drum, vel_of["chat"] + accent))

    fill = False
    trace_bits = [kick_trace]
    if pos.slot == "cadence":
        fill_prob = cfg.fill_base_prob + ctx.tension * cfg.fill_tension_weight
        fill = rng.random() < fill_prob
        if fill:
            pattern = tuple(slots + o for o in FILL_PATTERNS[rng.randrange(len(FILL_PATTERNS))])
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
