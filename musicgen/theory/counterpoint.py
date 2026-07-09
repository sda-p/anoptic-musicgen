"""Outer-voice counterpoint primitives (REFINEMENT_PLAN A3).

The soprano-bass frame carries tonal music; these are the species rules that
guard it: interval classification, the four motion types, and the two
prohibitions — consecutive perfects (parallel and contrary/'antiparallel'
fifths & octaves) and direct (hidden) perfects reached by a similar-motion
leap. Pure functions over pitch pairs — no IR, no state, no randomness — so
this module doubles as the outer-voice chapter of the C-engine acceptance
spec (PLANS.md §13.3). Consumers: the melody generator's strong-beat guard
(gen/melody.py) and the linter (verify.lint_outer); wave C's countermelody
adds the inner pairs.

Intervals are pitch-class intervals (mod 12), so compounds fold onto their
simple forms — a 12th is a 5th, as the rules intend. The one thing folding
loses is the parallel-vs-antiparallel distinction (P5 up to P12 by contrary
motion); strict style bans both, so the fold is harmless.
"""

from __future__ import annotations

PERFECT = frozenset({0, 7})            # unisons/octaves and fifths
CONSONANT = frozenset({0, 3, 4, 7, 8, 9})  # perfects + minor/major 3rds and 6ths


def interval_class(lower: int, upper: int) -> int:
    """Pitch-class interval of `upper` above `lower` (0..11)."""
    return (upper - lower) % 12


def is_perfect(lower: int, upper: int) -> bool:
    return interval_class(lower, upper) in PERFECT


def is_consonant(lower: int, upper: int) -> bool:
    """Consonance against the bass: P1/P8, P5, 3rds, 6ths. (The 4th counts as
    a dissonance here, as it does above a bass in species counterpoint.)"""
    return interval_class(lower, upper) in CONSONANT


def motion(prev_lower: int, prev_upper: int, lower: int, upper: int) -> str:
    """The four species motions between two verticalities:
    'oblique' (one voice holds), 'contrary' (opposite directions),
    'parallel' (same direction, same interval class), 'similar' (same
    direction, different interval class). Both static counts as oblique."""
    dl, du = lower - prev_lower, upper - prev_upper
    if dl == 0 or du == 0:
        return "oblique"
    if (dl > 0) != (du > 0):
        return "contrary"
    same = interval_class(prev_lower, prev_upper) == interval_class(lower, upper)
    return "parallel" if same else "similar"


def forbidden_parallel(prev_lower: int, prev_upper: int, lower: int, upper: int) -> bool:
    """Consecutive perfects of the same class with both voices moving — the
    parallel fifths/octaves ban, plus the contrary ('antiparallel') form the
    mod-12 fold cannot distinguish and strict style bans anyway. A repeated
    verticality (neither voice moves) or an oblique hold is allowed."""
    if lower == prev_lower or upper == prev_upper:
        return False
    ic = interval_class(lower, upper)
    return ic in PERFECT and interval_class(prev_lower, prev_upper) == ic


def forbidden_direct(prev_lower: int, prev_upper: int, lower: int, upper: int,
                     *, max_step: int = 2) -> bool:
    """Direct (hidden) fifths/octaves: similar motion into a perfect interval
    with the upper voice leaping. A stepwise upper voice is exempt (the
    classical 'horn fifths' allowance); the same-class case is the parallel
    rule's business, reported separately."""
    dl, du = lower - prev_lower, upper - prev_upper
    if dl == 0 or du == 0 or (dl > 0) != (du > 0):
        return False
    ic = interval_class(lower, upper)
    if ic not in PERFECT or interval_class(prev_lower, prev_upper) == ic:
        return False
    return abs(du) > max_step
