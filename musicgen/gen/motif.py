"""Signature-faithful motif realization (PLANS.md §5.5, M15).

The melody engine's default realization is *constraint-first* (melody.py): strong
beats snap to chord tones, so a motif's interval contour dissolves into the harmony
— right for a disposable phrase motif, wrong for a signature the ear must
*recognize*. This module adds the identity-preserving path: realize the contour
faithfully (every diatonic interval intact) and **transpose the whole cell** to the
register and best chord-tone fit, rather than bending individual notes. The
`completed` form of a lifecycle motif — and, later, authored signature motifs (M17)
— use it; a recognizability metric makes "did the shape survive" measurable.

The lifecycle (`MotifLifecycle`) makes a signature *persist* across phrases —
introduced → developed → completed — and permits the completed (full, faithful)
statement only on a dramaturg spend. The conductor selects the constraint-first or
faithful realization per state; melody.py imports `realize_faithful` from here, so
the `Motif` type is imported under TYPE_CHECKING only (runtime duck-typing on
`.rhythm` / `.contour`) to keep the dependency one-directional.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from musicgen.theory.scales import Scale, diatonic_shift, snap_to_scale

if TYPE_CHECKING:
    from musicgen.gen.melody import Motif


@dataclass
class MotifLifecycle:
    """A persistent signature motif traversing introduced → developed → completed
    (§5.5, M15). It recurs *in disguise* (constraint-first) while introduced and
    developed; the completed — full, faithful — statement is permitted only on a
    dramaturg spend, and only once enough disguised statements have accrued, so the
    shape is familiar before it lands whole. Lives in ConductorState; a pure
    function of (seed, affect trajectory, bar) like the ledger."""
    motif: "Motif"
    develop_after: int = 2          # disguised statements before it may complete
    state: str = "introduced"       # "introduced" | "developed" | "completed"
    statements: int = 0             # disguised statements so far
    completed_phrase: int | None = None

    def advance(self, spend: bool, phrase: int) -> str:
        """Advance at a phrase boundary; return this phrase's state. `spend` is the
        dramaturg's release this phrase — the only gate that admits `completed`."""
        if spend and self.statements >= self.develop_after:
            self.state = "completed"
            self.completed_phrase = phrase
        elif self.state == "completed":
            self.state = "developed"          # the landing is a one-phrase event
            self.statements += 1
        else:
            self.statements += 1
            self.state = "developed" if self.statements > self.develop_after else "introduced"
        return self.state


def diatonic_interval(scale: Scale, a: int, b: int) -> int:
    """Signed number of scale steps from a to b (both snapped to the scale)."""
    a, b = snap_to_scale(scale, a), snap_to_scale(scale, b)
    if a == b:
        return 0
    steps, p = 0, min(a, b)
    while p < max(a, b):
        p = diatonic_shift(scale, p, 1)
        steps += 1
    return steps if b > a else -steps


def realize_faithful(
    motif: Motif, scale: Scale, chord_pcs: tuple[int, ...],
    lo: int, hi: int, strong_slots: set[int], near: int | None = None,
) -> list[tuple[int, int, int]]:
    """Realize the motif preserving its contour, transposed *as a unit* to the
    register — connecting to `near` (the previous pitch, so successive statements
    don't leap) and then to the transposition whose strong-beat notes best land on
    chord tones. Returns [(slot, dur_slots, pitch)]. Because every note is `base`
    shifted by its contour offset (no per-note snapping), the interval shape is
    exact — `recognizability` is 1.0 by construction."""
    def at(base: int) -> list[int]:
        return [diatonic_shift(scale, base, off) for off in motif.contour]

    ref = near if near is not None else (lo + hi) // 2

    def score(base: int) -> tuple[int, int, int]:
        pitches = at(base)
        in_range = all(lo <= p <= hi for p in pitches)
        strong_hits = sum(1 for (slot, _), p in zip(motif.rhythm, pitches)
                          if slot in strong_slots and p % 12 in chord_pcs)
        # fit the register, then connect smoothly (small entry step), then align
        # strong beats to chord tones — smoothness before fit keeps the line legato.
        return (int(in_range), -abs(pitches[0] - ref), strong_hits)

    bases = [p for p in range(lo, hi + 1) if scale.contains(p)] or [(lo + hi) // 2]
    base = max(bases, key=score)  # transpose-whole-to-fit
    return [(slot, dur, p) for (slot, dur), p in zip(motif.rhythm, at(base))]


def motif_fit(
    motif: Motif, scale: Scale, chord_pcs: tuple[int, ...],
    lo: int, hi: int, strong_slots: set[int], near: int | None = None,
) -> float:
    """How naturally a chord sets a motif up *from where the line already is*
    (§5.5, M17): the fraction of the motif's strong-beat notes that land on chord
    tones at the transposition that connects to `near` — 1.0 when the shape drops in
    cleanly from here, low when landing it here would fight the harmony. Measured at
    the connecting transposition (not the globally best one) so it genuinely varies
    by chord and register — the appropriateness the director weighs against overdue
    pressure."""
    placed = realize_faithful(motif, scale, chord_pcs, lo, hi, strong_slots, near=near)
    strong = [p for slot, _, p in placed if slot in strong_slots]
    if not strong:
        return 1.0
    return sum(1 for p in strong if p % 12 in chord_pcs) / len(strong)


def recognizability(motif: Motif, pitches: list[int], scale: Scale) -> float:
    """Fraction of the motif's successive contour intervals preserved in the
    realized pitches (1.0 = the shape is intact). A signature realization stays
    near 1.0 across harmonic contexts; the constraint-first path, which snaps each
    strong beat to a chord tone, drops as the harmony bends the shape."""
    if len(pitches) < 2:
        return 1.0
    want = [b - a for a, b in zip(motif.contour, motif.contour[1:])]
    got = [diatonic_interval(scale, a, b) for a, b in zip(pitches, pitches[1:])]
    return sum(1 for w, g in zip(want, got) if w == g) / len(want)
