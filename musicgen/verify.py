"""Theory linter: executable sanity checks over the IR (PLANS.md §8.4).

M0 rules: scale membership with role-licensed chromaticism, annotation
consistency, pre-modifier grid alignment. M1 rules: pad voicing quality
(unison doubling, register, chord membership, voice movement), bass root and
chord membership, cadence realization. M14 rules (§5.8): obligations-checking —
a planted structural dissonance must discharge (a suspension resolves down by
step, a pedal terminates at a cadence, a secondary dominant resolves to its
target). Value-range checks live in NoteEvent.__post_init__.

stage="pre" lints generator output (grid-aligned); stage="post" lints after
modifiers, which may move events off-grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from musicgen.ir import GRID, HarmonicContext, Meter, NoteEvent
from musicgen.theory.pitch import pitch_name

# Roles that license a pitch outside the bar's scale. "echo" covers modifier
# repeats bleeding into the next bar's harmony (reverb-like, not a wrong note).
# "motif" is a completed signature statement (M15): licensed as a whole — its
# identity is verified by recognizability, not the note-level melodic heuristics.
CHROMATIC_ROLES = {"approach", "borrowed", "chromatic", "echo", "motif"}
MOTIF_ROLE = "motif"
# Roles that license a non-chord tone (melodic embellishment, held pedal, a
# prepared suspension, a signature statement). The obligation-bearing ones (pedal,
# suspension) also have to *discharge* — see _lint_obligations (M14, §5.8).
LICENSED_NONCHORD = CHROMATIC_ROLES | {"passing", "neighbor", "pedal", "appoggiatura", "suspension"}
SUSPENSION_ROLE, RESOLUTION_ROLE, PEDAL_ROLE, APPOGGIATURA_ROLE = (
    "suspension", "resolution", "pedal", "appoggiatura")

CADENCE_DEGREES = {"authentic": (1,), "half": (5,), "deceptive": (6,)}
PRE_CADENCE_DEGREES = {"authentic": (5, 7), "half": (2, 4), "deceptive": (5, 7)}

_DEFAULT_DRUM_PITCHES = frozenset({36, 37, 38, 42, 45, 46, 47, 49, 50, 70})  # gen.perc.DRUMS


@dataclass(frozen=True)
class LintLimits:
    max_voice_move: int = 7
    pad_range: tuple[int, int] = (52, 79)
    bass_range: tuple[int, int] = (26, 55)
    melody_range: tuple[int, int] = (54, 90)  # register_center map range [66,78] ± 12
    melody_strong_chord_ratio: float = 0.8
    leap_resolution_ratio: float = 0.9
    leap_semitones: int = 5  # intervals beyond this are leaps needing recovery
    drum_pitches: frozenset[int] = _DEFAULT_DRUM_PITCHES


@dataclass(frozen=True)
class Violation:
    rule: str
    bar: int  # 0-based; -1 for piece-level aggregate rules
    message: str

    def __str__(self) -> str:
        where = "piece" if self.bar < 0 else f"bar {self.bar + 1}"
        return f"[{self.rule}] {where}: {self.message}"


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
            if ev.role != "echo":  # echo tails may ring past the last bar
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
        if ev.degree is not None and ctx.scale.degree_of(ev.pitch) != ev.degree and ev.role != "echo":
            # echoes keep their source bar's annotations; the harmony (and
            # even the mode) may have moved on underneath them
            out.append(Violation(
                "degree", bar,
                f"{pitch_name(ev.pitch)} annotated ^{ev.degree} but is "
                f"^{ctx.scale.degree_of(ev.pitch)} in {ctx.scale.name}",
            ))


def _lint_pad(events, ctx_by_bar, meter, limits, stage, out) -> None:
    pads = sorted((e for e in events if e.layer == "pad"), key=lambda e: (e.start, e.pitch))
    groups: dict[float, list[NoteEvent]] = {}
    for ev in pads:
        groups.setdefault(ev.start, []).append(ev)

    # Voicing analysis (unison doubling, voice movement) needs simultaneous
    # chords — Strum staggers starts, so these rules are pre-modifier only.
    voicing_rules = stage == "pre"
    lo, hi = limits.pad_range
    prev_pitches: list[int] | None = None
    for start in sorted(groups):
        pitches = [e.pitch for e in groups[start]]
        bar = meter.bar_of(start)
        if voicing_rules and any(b == a for a, b in zip(pitches, pitches[1:])):
            out.append(Violation("unison", bar, f"pad voicing doubles a unison: {[pitch_name(p) for p in pitches]}"))
        for p in pitches:
            if not lo <= p <= hi:
                out.append(Violation("pad-range", bar, f"{pitch_name(p)} outside pad range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        ctx = ctx_by_bar.get(bar)
        if ctx is not None and ctx.chord_pcs:
            for ev in groups[start]:
                if ev.pitch % 12 not in ctx.chord_pcs and ev.role not in LICENSED_NONCHORD:
                    out.append(Violation("chord-tone", bar, f"pad {pitch_name(ev.pitch)} is not a member of {ctx.chord_sym} (pcs {ctx.chord_pcs})"))
        if voicing_rules and prev_pitches is not None and len(prev_pitches) == len(pitches):
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
            if ev.pitch % 12 != ctx.chord_pcs[0] and ev.role not in LICENSED_NONCHORD:
                # a pedal (held bass under shifting harmony) is a licensed non-root
                # beat-1 bass; it carries a termination obligation instead (§5.8).
                out.append(Violation(
                    "bass-root", bar,
                    f"beat-1 bass {pitch_name(ev.pitch)} is not the bass pc of {ctx.chord_sym} (pc {ctx.chord_pcs[0]})",
                ))
        elif ev.pitch % 12 not in ctx.chord_pcs and ev.role not in LICENSED_NONCHORD:
            out.append(Violation(
                "bass-chord-tone", bar,
                f"bass {pitch_name(ev.pitch)} not in {ctx.chord_sym} and role {ev.role!r} does not license it",
            ))


def _lint_melody(events, ctx_by_bar, meter, limits, out) -> None:
    melody = sorted((e for e in events if e.layer == "melody"), key=lambda e: e.start)
    if not melody:
        return
    lo, hi = limits.melody_range
    for ev in melody:
        if not lo <= ev.pitch <= hi:
            out.append(Violation("melody-range", meter.bar_of(ev.start),
                                 f"{pitch_name(ev.pitch)} outside melody range [{pitch_name(lo)}, {pitch_name(hi)}]"))

    # A completed signature statement is exempt from the constraint-first melodic
    # heuristics (strong-beat chord tones, leap recovery): its intervals are the
    # identity, licensed as a whole (M15). Its register is still bounded above.
    tuneful = [e for e in melody if e.role != MOTIF_ROLE]
    strong = set(meter.strong_slots())
    on_strong = [
        (e, ctx) for e in tuneful
        if meter.slot_of(e.start) in strong
        and (ctx := ctx_by_bar.get(meter.bar_of(e.start))) is not None
        and ctx.chord_pcs
        and ctx.cadence_slot != "cadence"   # the cadence bar is a deliberate embellished
        #   approach (appoggiatura → run → resolution), not chord-tone outlining
    ]
    if on_strong:
        chordal = sum(1 for e, ctx in on_strong if e.pitch % 12 in ctx.chord_pcs)
        ratio = chordal / len(on_strong)
        if ratio < limits.melody_strong_chord_ratio:
            out.append(Violation(
                "melody-strong-beats", -1,
                f"only {chordal}/{len(on_strong)} strong-beat melody notes are chord tones "
                f"({ratio:.2f} < {limits.melody_strong_chord_ratio})",
            ))

    leaps = resolved = 0
    for a, b, c in zip(tuneful, tuneful[1:], tuneful[2:]):
        if b.start - a.end > 2.0 or c.start - b.end > 2.0:
            continue  # a rest breaks the line; no recovery expected
        interval = b.pitch - a.pitch
        if abs(interval) <= limits.leap_semitones:
            continue
        leaps += 1
        back = c.pitch - b.pitch
        if back != 0 and (back > 0) != (interval > 0) and abs(back) <= 2:
            resolved += 1
    if leaps and resolved / leaps < limits.leap_resolution_ratio:
        out.append(Violation(
            "melody-leaps", -1,
            f"only {resolved}/{leaps} leaps beyond a P4 recover by an opposite step "
            f"({resolved / leaps:.2f} < {limits.leap_resolution_ratio})",
        ))


def _lint_perc(events, limits, meter, out) -> None:
    for ev in (e for e in events if e.layer == "perc"):
        if ev.pitch not in limits.drum_pitches:
            out.append(Violation("drum-map", meter.bar_of(ev.start),
                                 f"perc pitch {ev.pitch} not in the drum map"))


def _lint_cadences(contexts, out) -> None:
    for ctx in contexts:
        if not ctx.cadence_slot or ctx.chord is None or not ctx.cadence_policy:
            continue
        if ctx.chord.applied:
            continue  # a secondary dominant is a valid (chromatic) pre-cadence; its
            #           resolution is checked by the tonicize obligation instead
        table = CADENCE_DEGREES if ctx.cadence_slot == "cadence" else PRE_CADENCE_DEGREES
        allowed = table.get(ctx.cadence_policy)
        if allowed and ctx.chord.degree not in allowed:
            out.append(Violation(
                "cadence", ctx.bar,
                f"{ctx.cadence_slot} ({ctx.cadence_policy}) realized degree {ctx.chord.degree}, expected one of {allowed}",
            ))


def _lint_obligations(events, ctx_by_bar, meter, out) -> None:
    """M14 obligations-checking (§5.8): a planted structural dissonance must
    discharge. Dormant on output that plants none — no suspension/pedal roles and
    no context obligations means these loops find nothing, so pre-M14 renders are
    unaffected.

    Obligations:
      * a **suspension** is prepared (its pitch sounds in the same layer right
        before) and resolves down by step to a chord tone at its release;
      * a pad **appoggiatura** resolves down by step to a chord tone (the same
        obligation, unprepared — the payoff lean; melodic ones are exempt);
      * a **pedal** run (contiguous same-pitch bass) terminates at a cadence;
      * a **secondary dominant** (`ctx.obligation = "tonicize:N"`) resolves to
        degree N at the next bar.
    """
    by_layer: dict[str, list[NoteEvent]] = {}
    for ev in events:
        by_layer.setdefault(ev.layer, []).append(ev)

    for ev in events:
        is_susp = ev.role == SUSPENSION_ROLE
        # an appoggiatura carries the same resolution obligation, but only in the
        # pad — the melody's own leap / strong-beat rules govern its melodic
        # appoggiaturas, which pass through non-chord tones mid-run rather than
        # resolving to a chord tone at once.
        is_appog = ev.role == APPOGGIATURA_ROLE and ev.layer == "pad"
        if not (is_susp or is_appog):
            continue
        bar = meter.bar_of(ev.start)
        layer = by_layer[ev.layer]
        if is_susp and not any(n is not ev and n.pitch == ev.pitch and abs(n.end - ev.start) < 1e-9
                               for n in layer):
            out.append(Violation("suspension-prep", bar,
                f"{pitch_name(ev.pitch)} ({ev.layer}) suspension is unprepared "
                f"(no held tone of the same pitch precedes it)"))
        resolved = False
        for n in layer:
            if n is ev or abs(n.start - ev.end) > 1e-9 or not 1 <= ev.pitch - n.pitch <= 2:
                continue
            rctx = ctx_by_bar.get(meter.bar_of(n.start))
            if rctx is not None and rctx.chord_pcs and n.pitch % 12 in rctx.chord_pcs:
                resolved = True
                break
        if not resolved:
            kind = "suspension" if is_susp else "appoggiatura"
            out.append(Violation(kind, bar,
                f"{pitch_name(ev.pitch)} ({ev.layer}) {kind} does not resolve down "
                f"by step to a chord tone at beat {meter.beat_in_bar(ev.end):.3g}"))

    pedals = sorted((e for e in events if e.role == PEDAL_ROLE), key=lambda e: e.start)
    i = 0
    while i < len(pedals):
        j = i
        while (j + 1 < len(pedals) and pedals[j + 1].pitch == pedals[i].pitch
               and meter.bar_of(pedals[j + 1].start) - meter.bar_of(pedals[j].start) <= 1):
            j += 1
        first_bar, last_bar = meter.bar_of(pedals[i].start), meter.bar_of(pedals[j].start)
        # the pedal resolves *into* the cadence: its last held bar is the cadence,
        # or the cadence chord arrives in the bar right after.
        if not any((c := ctx_by_bar.get(b)) is not None and c.cadence_slot == "cadence"
                   for b in (last_bar, last_bar + 1)):
            out.append(Violation("pedal", first_bar,
                f"{pitch_name(pedals[i].pitch)} pedal (bars {first_bar + 1}..{last_bar + 1}) "
                f"does not terminate at a cadence"))
        i = j + 1

    for bar, ctx in ctx_by_bar.items():
        if ctx.obligation.startswith("tonicize:"):
            target = int(ctx.obligation.split(":", 1)[1])
            nxt = ctx_by_bar.get(bar + 1)
            if nxt is None or nxt.chord is None or nxt.chord.degree != target:
                out.append(Violation("tonicize", bar,
                    f"secondary dominant {ctx.chord_sym or '(?)'} does not resolve to degree {target}"))


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
    _lint_pad(events, ctx_by_bar, meter, limits, stage, out)
    _lint_bass(events, ctx_by_bar, meter, limits, out)
    if stage == "pre":  # slot-based melodic + obligation analysis assumes the unmodified grid
        _lint_melody(events, ctx_by_bar, meter, limits, out)
        _lint_obligations(events, ctx_by_bar, meter, out)
    _lint_perc(events, limits, meter, out)
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
