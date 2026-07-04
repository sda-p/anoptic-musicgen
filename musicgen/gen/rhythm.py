"""Rhythm primitives: Euclidean patterns and Gundlach/EMS roughness ops
(PLANS.md §5.4).

Euclidean E(k, n) spreads k hits as evenly as possible over n slots — the
backbone of the percussion layer. rough_cell starts from an even 8th-note
pulse and stochastically merges neighbors (syncopation), splits long notes
(busyness), and drops notes (rests); roughness and density steer the odds.
"""

from __future__ import annotations

import random


def euclid(k: int, n: int, rotation: int = 0) -> tuple[int, ...]:
    """Slot indices of the Euclidean rhythm E(k, n), optionally rotated.
    E(3, 8) -> (0, 3, 6), the tresillo; E(4, 16) -> four on the floor."""
    k = max(0, min(k, n))
    hits = [i for i in range(n) if (i * k) % n < k]
    return tuple(sorted((h + rotation) % n for h in hits))


def rough_cell(
    rng: random.Random,
    density: float,
    roughness: float,
    slots: int = 16,
    base_step: int = 2,
) -> tuple[tuple[int, int], ...]:
    """One bar's rhythm cell as (slot, dur_slots) pairs.

    Starts from an even pulse every base_step slots (8ths on the 16th grid),
    then: merges adjacent pairs with probability ~ roughness (merges across
    beat boundaries are the syncopation), splits notes at high density, and
    drops notes at low density (rests are content). Always keeps >= 2 notes
    with the first on its original slot.
    """
    notes = [(s, base_step) for s in range(0, slots, base_step)]

    merged: list[tuple[int, int]] = []
    i = 0
    while i < len(notes):
        if i + 1 < len(notes) and rng.random() < roughness * 0.6:
            merged.append((notes[i][0], notes[i][1] + notes[i + 1][1]))
            i += 2
        else:
            merged.append(notes[i])
            i += 1

    split: list[tuple[int, int]] = []
    split_prob = max(0.0, density - 0.6) * 0.8
    for s, d in merged:
        if d >= 2 and rng.random() < split_prob:
            split.append((s, d // 2))
            split.append((s + d // 2, d - d // 2))
        else:
            split.append((s, d))

    drop_prob = max(0.0, 1.0 - density) * 0.55
    kept = [n for j, n in enumerate(split) if j == 0 or rng.random() >= drop_prob]
    if len(kept) < 2:
        kept = split[:2]
    return tuple(kept)
