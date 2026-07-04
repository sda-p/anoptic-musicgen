"""Tier-1 affect levers and override plumbing (PLANS.md §6.1).

Affect is the game-facing API: three floats. Everything else is derived by
the mapping table — or pinned by an override, which is how a game (or a
debugging session) freezes one musical parameter while the rest stay live.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from musicgen.ir import MusicalParams


@dataclass(frozen=True)
class Affect:
    valence: float = 0.0   # -1 .. +1
    energy: float = 0.5    # 0 .. 1
    tension: float = 0.3   # 0 .. 1

    def clamped(self) -> "Affect":
        return Affect(
            valence=max(-1.0, min(1.0, self.valence)),
            energy=max(0.0, min(1.0, self.energy)),
            tension=max(0.0, min(1.0, self.tension)),
        )

    def merged(self, valence: float | None, energy: float | None, tension: float | None) -> "Affect":
        return Affect(
            valence=self.valence if valence is None else valence,
            energy=self.energy if energy is None else energy,
            tension=self.tension if tension is None else tension,
        ).clamped()

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.valence, self.energy, self.tension)


OVERRIDABLE = frozenset(f.name for f in fields(MusicalParams)) | {"mode", "cadence_policy"}


def validate_override(name: str) -> None:
    if name not in OVERRIDABLE:
        raise KeyError(f"unknown override {name!r}; valid: {sorted(OVERRIDABLE)}")
