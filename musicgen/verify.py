"""Theory linter: executable sanity checks over the IR (PLANS.md §8.4).

M0 rules: scale membership with role-licensed chromaticism, annotation
consistency, pre-modifier grid alignment. M1 rules: pad voicing quality
(unison doubling, register, chord membership, voice movement), bass root and
chord membership, cadence realization. Value-range checks live in
NoteEvent.__post_init__.

stage="pre" lints generator output (grid-aligned); stage="post" lints after
modifiers, which may move events off-grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from musicgen.ir import GRID, HarmonicContext, Meter, NoteEvent
from musicgen.theory.pitch import pitch_name

# Roles that license a pitch outside the bar's scale.
CHROMATIC_ROLES = {"approach", "borrowed", "chromatic"}
# Roles that license a non-chord tone (melodic embellishment etc.).
LICENSED_NONCHORD = CHROMATIC_ROLES | {"passing", "neighbor", "pedal"}

CADENCE_DEGREES = {"authentic": (1,), "half": (5,), "deceptive": (6,)}
PRE_CADENCE_DEGREES = {"authentic": (5, 7), "half": (2, 4), "deceptive": (5, 7)}


@dataclass(frozen=True)
class LintLimits:
    max_voice_move: int = 7
    pad_range: tuple[int, int] = (52, 79)
    bass_range: tuple[int, int] = (26, 55)


@dataclass(frozen=True)
class Violation:
    rule: str
    bar: int  # 0-based
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] bar {self.bar + 1}: {self.message}"


class TheoryLintError(AssertionError):
    pass


def _lint_events(events, ctx_by_bar, meter, stage, out) -> None:
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
        is_chord_member = bool(ctx.chord_pcs) and ev.pitch % 12 in ctx.chord_pcs
        if not ctx.scale.contains(ev.pitch) and not is_chord_member and ev.role not in CHROMATIC_ROLES:
            # Chord members are licensed by the chord itself (chord_pcs reflect
            # borrowing); anything else chromatic needs a licensing role.
            out.append(Violation(
                "scale", bar,
                f"{pitch_name(ev.pitch)} ({ev.layer}) not in {ctx.scale.name}, not a member of "
                f"{ctx.chord_sym or 'the chord'}, and role {ev.role!r} does not license chromaticism",
            ))
        if ev.degree is not None and ctx.scale.degree_of(ev.pitch) != ev.degree:
            out.append(Violation(
                "degree", bar,
                f"{pitch_name(ev.pitch)} annotated ^{ev.degree} but is "
                f"^{ctx.scale.degree_of(ev.pitch)} in {ctx.scale.name}",
            ))


def _lint_pad(events, ctx_by_bar, meter, limits, out) -> None:
    pads = sorted((e for e in events if e.layer == "pad"), key=lambda e: (e.start, e.pitch))
    groups: dict[float, list[NoteEvent]] = {}
    for ev in pads:
        groups.setdefault(ev.start, []).append(ev)

    lo, hi = limits.pad_range
    prev_pitches: list[int] | None = None
    for start in sorted(groups):
        pitches = [e.pitch for e in groups[start]]
        bar = meter.bar_of(start)
        if any(b == a for a, b in zip(pitches, pitches[1:])):
            out.append(Violation("unison", bar, f"pad voicing doubles a unison: {[pitch_name(p) for p in pitches]}"))
        for p in pitches:
            if not lo <= p <= hi:
                out.append(Violation("pad-range", bar, f"{pitch_name(p)} outside pad range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        ctx = ctx_by_bar.get(bar)
        if ctx is not None and ctx.chord_pcs:
            for p in pitches:
                if p % 12 not in ctx.chord_pcs:
                    out.append(Violation("chord-tone", bar, f"pad {pitch_name(p)} is not a member of {ctx.chord_sym} (pcs {ctx.chord_pcs})"))
        if prev_pitches is not None and len(prev_pitches) == len(pitches):
            for i, (a, b) in enumerate(zip(prev_pitches, pitches)):
                if abs(b - a) > limits.max_voice_move:
                    out.append(Violation(
                        "voice-move", bar,
                        f"pad voice {i} leaps {abs(b - a)} semitones ({pitch_name(a)} -> {pitch_name(b)}), max {limits.max_voice_move}",
                    ))
        prev_pitches = pitches


def _lint_bass(events, ctx_by_bar, meter, limits, out) -> None:
    lo, hi = limits.bass_range
    for ev in (e for e in events if e.layer == "bass"):
        bar = meter.bar_of(ev.start)
        if not lo <= ev.pitch <= hi:
            out.append(Violation("bass-range", bar, f"{pitch_name(ev.pitch)} outside bass range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        ctx = ctx_by_bar.get(bar)
        if ctx is None or not ctx.chord_pcs:
            continue
        if meter.beat_in_bar(ev.start) == 1.0:
            if ev.pitch % 12 != ctx.chord_pcs[0]:
                out.append(Violation(
                    "bass-root", bar,
                    f"beat-1 bass {pitch_name(ev.pitch)} is not the bass pc of {ctx.chord_sym} (pc {ctx.chord_pcs[0]})",
                ))
        elif ev.pitch % 12 not in ctx.chord_pcs and ev.role not in LICENSED_NONCHORD:
            out.append(Violation(
                "bass-chord-tone", bar,
                f"bass {pitch_name(ev.pitch)} not in {ctx.chord_sym} and role {ev.role!r} does not license it",
            ))


def _lint_cadences(contexts, out) -> None:
    for ctx in contexts:
        if not ctx.cadence_slot or ctx.chord is None or not ctx.cadence_policy:
            continue
        table = CADENCE_DEGREES if ctx.cadence_slot == "cadence" else PRE_CADENCE_DEGREES
        allowed = table.get(ctx.cadence_policy)
        if allowed and ctx.chord.degree not in allowed:
            out.append(Violation(
                "cadence", ctx.bar,
                f"{ctx.cadence_slot} ({ctx.cadence_policy}) realized degree {ctx.chord.degree}, expected one of {allowed}",
            ))


def lint(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
    limits: LintLimits = LintLimits(),
) -> list[Violation]:
    ctx_by_bar = {c.bar: c for c in contexts}
    out: list[Violation] = []
    _lint_events(events, ctx_by_bar, meter, stage, out)
    _lint_pad(events, ctx_by_bar, meter, limits, out)
    _lint_bass(events, ctx_by_bar, meter, limits, out)
    _lint_cadences(contexts, out)
    return out


def assert_clean(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
    limits: LintLimits = LintLimits(),
) -> None:
    violations = lint(events, contexts, meter, stage=stage, limits=limits)
    if violations:
        raise TheoryLintError(f"{len(violations)} violation(s):\n" + "\n".join(map(str, violations)))
