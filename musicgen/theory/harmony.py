"""Functional progression walk with cadence slots and a tension-tiered
dissonance budget (PLANS.md §5.2).

The walk is a weighted transition over harmonic functions (T -> PD -> D)
realized as degrees within the current mode. It is a pure function: all
sequential state (the previous chord) is passed in, all randomness comes from
the caller's per-bar stream, and every choice is explained in the returned
trace string.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.theory.chords import Chord
from musicgen.theory.scales import BRIGHTNESS

FUNCTION_TRANSITIONS = {
    "T": {"T": 0.15, "PD": 0.55, "D": 0.30},
    "PD": {"PD": 0.15, "D": 0.60, "T": 0.25},
    "D": {"T": 0.70, "D": 0.20, "PD": 0.10},  # D->PD retrogression kept rare
}
FUNCTION_CHORDS = {
    "T": ((1, 1.00), (6, 0.35), (3, 0.10)),
    "PD": ((4, 1.00), (2, 0.60)),
    "D": ((5, 1.00), (7, 0.15)),
}

# Modal mixture: degrees that may take their aeolian coloring when the context
# mode is brighter than aeolian and valence is negative (PLANS.md §5.2).
BORROWABLE_DEGREES = (4, 6, 7)

CADENCE_TARGET = {"authentic": 1, "half": 5, "deceptive": 6}
PRE_CADENCE_FUNCTION = {"authentic": "D", "half": "PD", "deceptive": "D"}


@dataclass(frozen=True)
class HarmonyConfig:
    dominant_tension_bias: float = 1.6  # multiplies ->D weights as tension -> 1
    tonic_calm_bias: float = 1.2        # multiplies ->T weights as tension -> 0
    repeat_penalty: float = 0.25        # weight multiplier for repeating a degree
    borrow_prob_max: float = 0.35       # borrowing probability at valence -1
    phrase_open_tonic_boost: float = 1.6
    tonic_suppress: float = 0.05        # weight on degree 1 in T while the dramaturg withholds (§5.8)


def _weighted(rng: random.Random, pairs: list[tuple[object, float]]) -> object:
    values, weights = zip(*pairs)
    return rng.choices(values, weights=weights)[0]


def _choose_degree(function: str, prev_degree: int | None, cfg: HarmonyConfig,
                   rng: random.Random, suppress_tonic: bool = False) -> int:
    pairs = [
        (d, w * (cfg.repeat_penalty if d == prev_degree else 1.0))
        for d, w in FUNCTION_CHORDS[function]
    ]
    if suppress_tonic and function == "T":
        # dramaturg withholding: circle the tonic via vi/iii instead of landing on I
        pairs = [(d, w * cfg.tonic_suppress if d == 1 else w) for d, w in pairs]
    return _weighted(rng, pairs)


def _maybe_borrow(degree: int, mode: str, valence: float, cfg: HarmonyConfig, rng: random.Random) -> str | None:
    if degree not in BORROWABLE_DEGREES:
        return None
    if BRIGHTNESS.get(mode, -1) <= BRIGHTNESS["aeolian"]:
        return None  # already dark; nothing to borrow
    if rng.random() < cfg.borrow_prob_max * max(0.0, -valence):
        return "aeolian"
    return None


def _choose_extensions(degree: int, tension: float, is_cadential_dominant: bool, rng: random.Random) -> tuple[str, ...]:
    """Dissonance budget tiers (PLANS.md §5.2)."""
    if tension < 0.25:
        return ()
    if tension < 0.5:
        if degree == 5 and is_cadential_dominant:
            return ("7",)
        return ("9",) if rng.random() < 0.20 else ()
    if tension < 0.75:
        if degree == 5:
            return ("7", "9") if rng.random() < 0.25 else ("7",)
        r = rng.random()
        if r < 0.35:
            return ("7",)
        if r < 0.55:
            return ("9",)
        if r < 0.65:
            return ("sus4",)
        return ()
    if degree == 5:
        return ("7", "9")
    r = rng.random()
    if r < 0.50:
        return ("7", "9") if rng.random() < 0.30 else ("7",)
    if r < 0.80:
        return ("9",)
    return ("sus4",)


def next_chord(
    *,
    prev: Chord | None,
    slot: str,  # "open" | "free" | "pre-cadence" | "cadence"
    cadence_policy: str,
    tension: float,
    valence: float,
    mode: str,
    phrase_start: bool,
    piece_start: bool,
    cfg: HarmonyConfig = HarmonyConfig(),
    rng: random.Random,
    suppress_tonic: bool = False,
) -> tuple[Chord, str]:
    """One step of the functional walk. Returns (chord, trace). suppress_tonic
    biases a tonic-function bar away from I (toward vi/iii) — the dramaturg's
    root-position-tonic withholding (§5.8); it never touches the cadence slots."""
    if piece_start:
        return Chord(1, extensions=_choose_extensions(1, tension, False, rng)), "piece start: establish tonic"

    if slot == "cadence":
        degree = CADENCE_TARGET[cadence_policy]
        source = _maybe_borrow(degree, mode, valence, cfg, rng) if cadence_policy == "deceptive" else None
        chord = Chord(
            degree,
            extensions=_choose_extensions(degree, tension, degree == 5, rng),
            source_mode=source,
        )
        return chord, f"cadence ({cadence_policy}) -> degree {degree}"

    if slot == "pre-cadence":
        function = PRE_CADENCE_FUNCTION[cadence_policy]
        if function == "D":
            degree = 5 if rng.random() < 0.90 else 7
        else:
            degree = _choose_degree(function, prev.degree if prev else None, cfg, rng)
        chord = Chord(degree, extensions=_choose_extensions(degree, tension, degree == 5, rng))
        return chord, f"pre-cadence ({cadence_policy}) -> {function}: degree {degree}"

    prev_function = prev.function if prev else "T"
    weights = dict(FUNCTION_TRANSITIONS[prev_function])
    weights["D"] *= 1.0 + (cfg.dominant_tension_bias - 1.0) * tension
    weights["T"] *= 1.0 + (cfg.tonic_calm_bias - 1.0) * (1.0 - tension)
    if phrase_start:
        weights["T"] *= cfg.phrase_open_tonic_boost
    function = _weighted(rng, list(weights.items()))
    degree = _choose_degree(function, prev.degree if prev else None, cfg, rng, suppress_tonic)
    source = _maybe_borrow(degree, mode, valence, cfg, rng)
    chord = Chord(degree, extensions=_choose_extensions(degree, tension, False, rng), source_mode=source)
    trace = (
        f"walk {prev_function}->{function} "
        f"(w T={weights['T']:.2f} PD={weights['PD']:.2f} D={weights['D']:.2f}), degree {degree}"
        + (f", borrowed from {source}" if source else "")
    )
    return chord, trace
