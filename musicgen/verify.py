"""Theory linter: executable sanity checks over the IR (PLANS.md §8.4).

M0 rules: scale membership with role-licensed chromaticism, annotation
consistency, and pre-modifier grid alignment. Value-range checks live in
NoteEvent.__post_init__. Harmony/melody/voicing rules land with M1/M2.

stage="pre" lints generator output (grid-aligned); stage="post" lints after
modifiers, which are allowed to move events off-grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from musicgen.ir import GRID, HarmonicContext, Meter, NoteEvent
from musicgen.theory.pitch import pitch_name

# Roles that license a pitch outside the bar's scale.
CHROMATIC_ROLES = {"approach", "borrowed", "chromatic"}


@dataclass(frozen=True)
class Violation:
    rule: str
    bar: int  # 0-based
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] bar {self.bar + 1}: {self.message}"


class TheoryLintError(AssertionError):
    pass


def lint(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
) -> list[Violation]:
    ctx_by_bar = {c.bar: c for c in contexts}
    out: list[Violation] = []
    for ev in events:
        bar = meter.bar_of(ev.start)

        if stage == "pre":
            for field_name, value in (("start", ev.start), ("dur", ev.dur)):
                if abs(value / GRID - round(value / GRID)) > 1e-9:
                    out.append(Violation("grid", bar, f"{field_name}={value} off the {GRID}-beat grid ({ev.layer})"))

        if ev.layer == "perc":
            continue  # drums are unpitched; scale rules do not apply

        ctx = ctx_by_bar.get(bar)
        if ctx is None:
            out.append(Violation("context", bar, f"no HarmonicContext covers {ev.layer} {pitch_name(ev.pitch)}"))
            continue
        if not ctx.scale.contains(ev.pitch) and ev.role not in CHROMATIC_ROLES:
            out.append(Violation(
                "scale", bar,
                f"{pitch_name(ev.pitch)} ({ev.layer}) not in {ctx.scale.name}, "
                f"and role {ev.role!r} does not license chromaticism",
            ))
        if ev.degree is not None and ctx.scale.degree_of(ev.pitch) != ev.degree:
            out.append(Violation(
                "degree", bar,
                f"{pitch_name(ev.pitch)} annotated ^{ev.degree} but is "
                f"^{ctx.scale.degree_of(ev.pitch)} in {ctx.scale.name}",
            ))
    return out


def assert_clean(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
) -> None:
    violations = lint(events, contexts, meter, stage=stage)
    if violations:
        raise TheoryLintError(f"{len(violations)} violation(s):\n" + "\n".join(map(str, violations)))
