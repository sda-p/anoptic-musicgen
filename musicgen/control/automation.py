"""Scripted lever automation: breakpoint curves over bars (PLANS.md §10).

A Curve is a sorted sequence of (bar, {"valence", "energy", "tension"})
breakpoints; affect_at interpolates linearly between them and clamps at the
ends. run() drives an engine through a curve — the offline stand-in for a
game feeding set_affect() in real time.
"""

from __future__ import annotations

from typing import Sequence

Breakpoint = tuple[int, dict[str, float]]
KEYS = ("valence", "energy", "tension")


def affect_at(curve: Sequence[Breakpoint], bar: int) -> dict[str, float]:
    if not curve:
        raise ValueError("empty automation curve")
    for point_bar, values in curve:
        missing = [k for k in KEYS if k not in values]
        if missing:
            raise ValueError(f"breakpoint at bar {point_bar} missing {missing}")
    if bar <= curve[0][0]:
        return dict(curve[0][1])
    if bar >= curve[-1][0]:
        return dict(curve[-1][1])
    for (b0, v0), (b1, v1) in zip(curve, curve[1:]):
        if b0 <= bar <= b1:
            if b1 == b0:
                return dict(v1)
            frac = (bar - b0) / (b1 - b0)
            return {k: v0[k] + (v1[k] - v0[k]) * frac for k in KEYS}
    raise ValueError(f"curve does not cover bar {bar}")  # unreachable if sorted


def run(engine, curve: Sequence[Breakpoint], bars: int) -> list:
    """Set affect from the curve each bar, then advance. Returns BarResults."""
    results = []
    for bar in range(bars):
        engine.set_affect(**affect_at(curve, bar))
        results.append(engine.advance_bar())
    return results
