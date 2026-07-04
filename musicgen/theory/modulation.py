"""Pivot-chord key modulation (PLANS.md §5.7).

A modulation rides the phrase cadence machinery: a PIVOT chord diatonic in
both keys sounds while the old key is still in force, the new key's DOMINANT
lands on the pre-cadence slot, and the new tonic arrives on the cadence bar —
so the cadence linter validates a modulation like any other cadence. This
module holds the pure theory (finding and ranking the common chord); the
conductor owns the schedule.
"""

from __future__ import annotations

from dataclasses import dataclass

from musicgen.theory.chords import FUNCTION_OF_DEGREE, Chord
from musicgen.theory.scales import Scale

# Preference for the pivot's degree IN THE NEW KEY: the pivot launches the new
# key's cadence, so pre-dominants (ii, IV) rank first, tonic-function chords
# are serviceable, and dominant-function chords rank last (the modulation's
# own V7 supplies that function one bar later).
_NEW_DEGREE_RANK = {2: 0, 4: 1, 6: 2, 1: 3, 3: 4, 5: 8, 7: 9}
_OLD_DOMINANT_PENALTY = 6  # V/vii of the old key pull back toward the old tonic


@dataclass(frozen=True)
class Pivot:
    old_degree: int  # the common chord as a degree of the outgoing key
    new_degree: int  # the same chord as a degree of the incoming key
    pcs: tuple[int, ...]  # its pitch classes, root-first in the old key


def _score(p: Pivot) -> tuple[int, int, int]:
    penalty = _OLD_DOMINANT_PENALTY if FUNCTION_OF_DEGREE[p.old_degree] == "D" else 0
    return (_NEW_DEGREE_RANK[p.new_degree] + penalty, p.new_degree, p.old_degree)


def find_pivots(old: Scale, new: Scale) -> list[Pivot]:
    """Triads diatonic in both scales, best pivot first. Diminished triads
    are skipped (too unstable to anchor a key change). Empty when the keys
    share no usable triad — modulate directly through the new V7 instead."""
    new_by_pcs: dict[frozenset[int], int] = {}
    for d in range(1, 8):
        chord = Chord(d)
        if chord.quality(new) != "dim":
            new_by_pcs[frozenset(chord.pitch_classes(new))] = d
    out = []
    for d in range(1, 8):
        chord = Chord(d)
        pcs = chord.pitch_classes(old)
        match = new_by_pcs.get(frozenset(pcs))
        if match is not None and chord.quality(old) != "dim":
            out.append(Pivot(d, match, pcs))
    return sorted(out, key=_score)


def fifths_between(a: int, b: int) -> int:
    """Signed circle-of-fifths steps from pc a to pc b, sharpwards positive,
    normalized to -5..+6 (7*k ≡ b-a mod 12, and 7·7 ≡ 1)."""
    k = (7 * (b - a)) % 12
    return k if k <= 6 else k - 12
