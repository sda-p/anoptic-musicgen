"""Guide-tone lines (REFINEMENT_PLAN C5, PLANS.md M24).

The 3rds and 7ths of successive chords threaded into a minimal-motion line —
the jazz arranger's skeleton: those two degrees carry each chord's quality
(major/minor from the 3rd, tension from the 7th), and because adjacent chords
in functional progressions share or step between them, the thread moves by
common tone or step almost everywhere. For plain triads the 5th stands in for
the missing 7th.

Pure functions, greedy and deterministic: `next_guide` continues the thread
one chord at a time (which is exactly how the pull-based conductor consumes
it — the countermelody seeds its strong beats from this), and `guide_line`
folds a whole progression for tests, dumps, and the C-spec chapter.
"""

from __future__ import annotations

from typing import Sequence

from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale


def guide_pcs(chord: Chord, scale: Scale) -> tuple[int, int]:
    """The chord's guide-tone candidates: (3rd, 7th) — the 5th standing in
    when there is no 7th. Root-first pitch_classes puts the 3rd at index 1
    (sus chords contribute their replacement tone: the color that IS the
    chord's identity there)."""
    pcs = chord.pitch_classes(scale)
    third = pcs[1]
    seventh = pcs[3] if len(pcs) > 3 else pcs[2]
    return (third, seventh)


def next_guide(prev_pc: int | None, chord: Chord, scale: Scale) -> int:
    """Continue the thread: the candidate nearest the previous pick by folded
    pitch-class distance (ties break low). The first chord takes its 3rd —
    the strongest quality-carrier."""
    cands = guide_pcs(chord, scale)
    if prev_pc is None:
        return cands[0]
    return min(cands, key=lambda pc: (min((pc - prev_pc) % 12, (prev_pc - pc) % 12), pc))


def guide_line(chords: Sequence[tuple[Chord, Scale]]) -> list[int]:
    """The whole progression's guide-tone thread, one pc per chord."""
    line: list[int] = []
    prev: int | None = None
    for chord, scale in chords:
        prev = next_guide(prev, chord, scale)
        line.append(prev)
    return line
