"""The countermelody layer (REFINEMENT_PLAN C5, PLANS.md M24).

A second real line under the melody, constraint-first like everything else —
and constrained BY the melody, whose bar IR exists before this runs:

1. **Rhythmic complementarity** — a rough_cell at reduced density is masked
   against the melody's onsets: the counter moves where the melody holds and
   holds where it moves (one oblique point of contact survives when the
   melody saturates the grid; rests are content).
2. **Strong beats** — chord members, consonant with the sounding melody
   (3rds/6ths preferred, P5/P8 rationed to what the walk can't avoid), seeded
   from the guide-tone thread (theory/guides.py): the 3rds and 7ths of
   successive chords in minimal motion — the line's skeleton.
3. **Motion** — no parallel/antiparallel perfects against melody or bass, no
   direct perfects into a downbeat (theory/counterpoint.py, the same rules
   the outer frame obeys); weak beats step diatonically toward the guide
   target, so recovery and gravity come built in.
4. **Register** — the tenor gap (G3..G5), never above the sounding melody
   (unison allowed when the melody dives; the counter yields the bar when
   even that leaves no room).

verify._lint_counter mirrors every numbered rule with plant-tested checks —
the species set that doubles as the C-spec's counterpoint chapter.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.gen.rhythm import rough_cell
from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.counterpoint import (
    CONSONANT, forbidden_direct, forbidden_parallel, interval_class,
)
from musicgen.theory.guides import next_guide
from musicgen.theory.pitch import pitch_name
from musicgen.theory.scales import diatonic_shift, snap_to_scale

STRONG_PREF = (3, 4, 8, 9)  # 3rds & 6ths (compounds fold onto them)


@dataclass(frozen=True)
class CounterConfig:
    lo: int = 55             # G3 — the tenor gap between bass and melody
    hi: int = 79             # G5
    velocity_offset: int = -10
    density_scale: float = 0.6  # the counter moves less than the melody


@dataclass
class CounterState:
    """Sequential state: the line's own memory plus the two motion chains the
    species rules judge (vs melody, vs bass), each carried across the barline
    with the same one-bar expiry the outer-voice guard uses."""

    prev_pitch: int | None = None
    guide_pc: int | None = None
    vs_melody: tuple[float, int, int] | None = None  # (t, counter, melody)
    vs_bass: tuple[float, int, int] | None = None    # (t, counter, bass)


def _sounding(events, t: float):
    cur = None
    for e in events:
        if e.start > t + 1e-9:
            break
        if t < e.end - 1e-9:
            cur = e
    return cur


def generate_counter(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    melody_events: list[NoteEvent],
    bass_events: list[NoteEvent],
    state: CounterState,
    cfg: CounterConfig,
    rng: random.Random,
) -> tuple[list[NoteEvent], CounterState, str]:
    """One bar of countermelody. Returns (events, state, trace)."""
    mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
    strong = set(meter.strong_slots())
    bar_start = ctx.bar * meter.bar_quarters
    surface = sorted((e for e in melody_events if e.role != "doubling"),
                     key=lambda e: e.start)
    bass = sorted(bass_events, key=lambda e: e.start)

    # 1. complementarity: the cell keeps the holes the melody leaves
    cell = rough_cell(rng, params.note_density * cfg.density_scale,
                      params.roughness, slots=meter.slots)
    melody_slots = {meter.slot_of(e.start) for e in surface}
    kept = [(s, d) for s, d in cell if s not in melody_slots]
    if not kept:
        # a saturated melody leaves no holes: the counter rests the bar
        # rather than shadow an onset — complementarity is the contract
        return [], CounterState(prev_pitch=state.prev_pitch, guide_pc=state.guide_pc,
                                vs_melody=state.vs_melody, vs_bass=state.vs_bass), \
            "counter: melody saturated, rests"

    # the guide thread continues regardless of what sounds — it is the
    # skeleton the strong beats reach for
    guide = next_guide(state.guide_pc, ctx.chord, ctx.scale) if ctx.chord else \
        (state.guide_pc if state.guide_pc is not None else ctx.chord_pcs[0])
    center = state.prev_pitch if state.prev_pitch is not None else (cfg.lo + cfg.hi) // 2
    target = min((p for p in range(cfg.lo + (guide - cfg.lo) % 12, cfg.hi + 1, 12)),
                 key=lambda p: (abs(p - center), p), default=center)

    placed: list[tuple[int, int, int]] = []
    prev = state.prev_pitch
    vs_m, vs_b = state.vs_melody, state.vs_bass
    yielded = 0
    for slot, dur in kept:
        t = bar_start + slot * GRID
        m = _sounding(surface, t)
        b = _sounding(bass, t)
        ceiling = min(cfg.hi, m.pitch if m is not None else cfg.hi)  # never above the melody
        if ceiling < cfg.lo:
            yielded += 1
            continue  # the melody dove into the tenor; the counter yields
        if slot in strong:
            cands = sorted((p for pc in set(ctx.chord_pcs)
                            for p in range(cfg.lo + (pc - cfg.lo) % 12, ceiling + 1, 12)),
                           key=lambda p: (abs(p - target), p))
            if not cands:
                yielded += 1
                continue

            def clean(p: int, prefer: bool) -> bool:
                if m is not None:
                    ic = interval_class(p, m.pitch)
                    if ic not in CONSONANT or (prefer and ic not in STRONG_PREF):
                        return False
                    if vs_m is not None and t - vs_m[0] <= meter.bar_quarters + 1e-9:
                        if (forbidden_parallel(vs_m[1], vs_m[2], p, m.pitch)
                                or (slot == 0 and forbidden_direct(vs_m[1], vs_m[2], p, m.pitch))):
                            return False
                if b is not None and vs_b is not None and t - vs_b[0] <= meter.bar_quarters + 1e-9:
                    if (forbidden_parallel(vs_b[2], vs_b[1], b.pitch, p)
                            or (slot == 0 and forbidden_direct(vs_b[2], vs_b[1], b.pitch, p))):
                        return False
                return True

            pitch = (next((p for p in cands if clean(p, True)), None)
                     or next((p for p in cands if clean(p, False)), None))
            if pitch is None:
                yielded += 1
                continue  # nothing both consonant and motion-clean — the counter rests
        else:
            # weak beats: one diatonic step toward the guide target (gravity
            # and leap-recovery come free — the line never leaps here)
            base = prev if prev is not None else target
            if base == target:
                pitch = snap_to_scale(mscale, base)
            else:
                pitch = diatonic_shift(mscale, base, 1 if target > base else -1)
            pitch = min(max(pitch, cfg.lo), ceiling)
            if not mscale.contains(pitch) and pitch % 12 not in ctx.chord_pcs:
                pitch = snap_to_scale(mscale, pitch)
                if pitch > ceiling:
                    pitch = diatonic_shift(mscale, pitch, -1)
        placed.append((slot, dur, pitch))
        if slot in strong:
            if m is not None:
                vs_m = (t, pitch, m.pitch)
            if b is not None:
                vs_b = (t, pitch, b.pitch)
        prev = pitch

    velocity = max(1, min(127, params.velocity_center + cfg.velocity_offset))
    events = []
    for slot, dur, pitch in placed:
        if pitch % 12 in ctx.chord_pcs:
            role = "chord-tone"
        elif ctx.scale.contains(pitch):
            role = "passing"
        else:
            role = "borrowed"
        events.append(NoteEvent(bar_start + slot * GRID, dur * GRID, pitch, velocity,
                                "counter", degree=ctx.scale.degree_of(pitch),
                                chord=ctx.chord_sym, role=role))
    new_state = CounterState(prev_pitch=prev, guide_pc=guide, vs_melody=vs_m, vs_bass=vs_b)
    trace = (f"counter: guide {pitch_name(target)} (^{ctx.scale.degree_of(target) or '-'})"
             f" n={len(placed)}" + (f", yielded {yielded}" if yielded else ""))
    return events, new_state, trace
