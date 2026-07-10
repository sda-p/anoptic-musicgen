"""Imitative entries (REFINEMENT_PLAN C3, PLANS.md M23).

After a phrase states its material, a second voice restates the motif's
opening cell — the head, its first ⌈n/2⌉ notes — one bar later in the arp
register (or as the pad's top voice while the arp is gated off or held by the
dramaturg), at the diatonic transposition realize_faithful picks. The listener
hears the voices *listening to each other*; the machinery already existed
(motif cells, faithful realization, per-phrase caches), so this module is
mostly the collision policy: a deterministic retry list — enter on the bar,
then half a bar later, then transposed a 3rd up or down — takes the first
candidate that never clashes with the sounding melody (2nds/7ths/tritones at
overlapping onsets), falling back to the least-clashing one, so an entry
always lands and the C4 texture claim ("imitative" ⇒ an entry exists) stays
checkable. The melody's bar IR exists before the arp runs — no lookahead.

The emitted cell is cached per phrase in ConductorState.imitation_cells;
verify.lint_imitation recomputes recognizability against it. Transposition
preserves contour deltas, so a faithful entry scores 1.0 by construction and
any corruption of the emitted events drops below threshold.
"""

from __future__ import annotations

from musicgen.gen.melody import Motif
from musicgen.gen.motif import realize_faithful
from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.counterpoint import interval_class

CLASH = frozenset({1, 2, 6, 10, 11})  # 2nds, 7ths, tritone against the sounding melody
IMITATION_ROLE = "imitation"


def imitation_cell(motif: Motif) -> Motif:
    """The opening cell — the head the ear latches onto (the same fragment
    arithmetic as the M15 introduce glimpse: the first ⌈n/2⌉ notes)."""
    k = max(1, (len(motif.rhythm) + 1) // 2)
    return Motif(motif.rhythm[:k], motif.contour[:k], motif.shape)


def _shifted(cell: Motif, offset: int, slots: int) -> Motif | None:
    """The cell entered `offset` slots later, truncated at the barline (raw
    events never cross it); None when nothing survives the shift."""
    rhythm = tuple((s + offset, min(d, slots - (s + offset)))
                   for s, d in cell.rhythm if s + offset < slots)
    if not rhythm:
        return None
    return Motif(rhythm, cell.contour[: len(rhythm)], cell.shape)


def _transposed(cell: Motif, steps: int) -> Motif:
    return Motif(cell.rhythm, tuple(c + steps for c in cell.contour), cell.shape)


def _collisions(placed, melody_events, bar_start: float) -> int:
    """Count entry notes that sound a 2nd/7th/tritone against the melody note
    sounding at their onset (the doubled line is the surface's shadow, not a
    second surface — it never counts)."""
    n = 0
    for slot, _, pitch in placed:
        t = bar_start + slot * GRID
        m = next((e for e in melody_events if e.role != "doubling"
                  and e.start - 1e-9 <= t < e.end - 1e-9), None)
        if m is not None and interval_class(min(pitch, m.pitch), max(pitch, m.pitch)) in CLASH:
            n += 1
    return n


def generate_imitation(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    motif: Motif,
    melody_events: list[NoteEvent],
    host: str,
    lo: int,
    hi: int,
    velocity: int,
) -> tuple[list[NoteEvent], Motif | None, str]:
    """One imitative entry in `host`'s register, role "imitation" (licensed
    like "motif" — chord membership is the transposition picker's preference,
    not a per-note law). Deterministic: no rng, fixed retry order, first clean
    candidate wins — an imitative texture tolerates a passing 2nd sooner than
    it tolerates silence, so the least-clashing candidate is the floor."""
    cell = imitation_cell(motif)
    mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
    strong = set(meter.strong_slots())
    bar_start = ctx.bar * meter.bar_quarters

    half = _shifted(cell, meter.slots // 2, meter.slots)
    candidates: list[tuple[str, Motif | None]] = [
        ("on the bar", cell),
        ("+half-bar", half),
        ("up a 3rd", _transposed(cell, 2)),
        ("down a 3rd", _transposed(cell, -2)),
        ("+half-bar up a 3rd", _transposed(half, 2) if half else None),
        ("+half-bar down a 3rd", _transposed(half, -2) if half else None),
    ]
    best: tuple[int, str, Motif, list] | None = None
    for desc, variant in candidates:
        if variant is None:
            continue
        placed = realize_faithful(variant, mscale, ctx.chord_pcs, lo, hi, strong)
        if not placed:
            continue
        n = _collisions(placed, melody_events, bar_start)
        if best is None or n < best[0]:
            best = (n, desc, variant, placed)
        if n == 0:
            break
    if best is None:
        return [], None, "imitation: no realizable entry"

    n, desc, variant, placed = best
    vel = max(1, min(127, velocity))
    events = [NoteEvent(bar_start + slot * GRID, dur * GRID, pitch, vel, host,
                        degree=ctx.scale.degree_of(pitch), chord=ctx.chord_sym,
                        role=IMITATION_ROLE)
              for slot, dur, pitch in placed]
    emitted = Motif(variant.rhythm[: len(placed)], variant.contour[: len(placed)],
                    variant.shape)
    clash = "" if n == 0 else f", {n} clash tolerated"
    return events, emitted, f"imitation: {host} entry {desc} n={len(placed)}{clash}"
