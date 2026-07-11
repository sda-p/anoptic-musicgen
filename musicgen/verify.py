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

`horizon` marks a TRUNCATED render: contexts at or beyond it are lookahead —
they let an obligation planted in the last rendered bar discharge past the edge
(a cadential 6/4 there resolves onto the V of the bar after) without themselves
being judged, since they host no events. Render N + k bars, lint the events of
the first N, pass every context, and set horizon=N. None (the default) judges
every context, which is what a complete piece wants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from musicgen.ir import GRID, HarmonicContext, Meter, NoteEvent, merge_ties
from musicgen.theory.counterpoint import (
    CONSONANT, forbidden_direct, forbidden_parallel, interval_class, motion,
)
from musicgen.theory.pitch import pitch_name

# Roles that license a pitch outside the bar's scale. "echo" covers modifier
# repeats bleeding into the next bar's harmony (reverb-like, not a wrong note).
# "motif" is a completed signature statement (M15): licensed as a whole — its
# identity is verified by recognizability, not the note-level melodic heuristics.
# "doubling" (C1) tracks the melody in the CHORD's melodic scale, so over a
# borrowed chord it may leave the context scale exactly as its source note does
# — _lint_doubling holds it to the tighter interval/membership whitelist.
# "imitation" (C3) is a faithful cell entry licensed as a whole like "motif" —
# lint_imitation verifies its identity by recognizability instead.
CHROMATIC_ROLES = {"approach", "borrowed", "chromatic", "echo", "motif", "doubling",
                   "imitation"}
MOTIF_ROLE = "motif"
DOUBLING_ROLE = "doubling"
IMITATION_ROLE = "imitation"
# Roles that license a non-chord tone (melodic embellishment, held pedal, a
# prepared suspension, a signature statement). The obligation-bearing ones (pedal,
# suspension) also have to *discharge* — see _lint_obligations (M14, §5.8).
LICENSED_NONCHORD = CHROMATIC_ROLES | {"passing", "neighbor", "pedal", "appoggiatura",
                                       "suspension"}
SUSPENSION_ROLE, RESOLUTION_ROLE, PEDAL_ROLE, APPOGGIATURA_ROLE = (
    "suspension", "resolution", "pedal", "appoggiatura")

CADENCE_DEGREES = {"authentic": (1,), "half": (5,), "deceptive": (6,)}
PRE_CADENCE_DEGREES = {"authentic": (5, 7), "half": (2, 4), "deceptive": (5, 7)}

_DEFAULT_DRUM_PITCHES = frozenset({36, 37, 38, 42, 45, 46, 47, 49, 50, 70})  # gen.perc.DRUMS


def _grid_pos(start: float, meter: Meter) -> tuple[int, float]:
    """The bar and in-bar offset a note is HARMONICALLY at. A modifier displaces
    an onset by a fraction of a grid step — a strum's stagger, humanize's jitter,
    swing — which can carry it backwards across a barline, or across a split
    bar's mid-bar chord change. The note still belongs to the harmony it was
    written against, so the harmonic rules resolve its position from the grid
    slot it was displaced FROM, not from where the jitter left it.

    Recovering that slot is exact as long as no modifier moves a note by half a
    grid step (0.125 beats), which none does: the chain's largest displacements
    (swing ~0.06, a strum stagger plus humanize ~0.05) stay well inside it. On
    pre-modifier IR this is the identity — the "grid" rule enforces alignment."""
    slot_start = round(start / GRID) * GRID
    bar = meter.bar_of(slot_start)
    return bar, slot_start - bar * meter.bar_quarters


def _judged(contexts, horizon: int | None):
    """The bars the lint actually judges. Contexts at or beyond `horizon` are
    LOOKAHEAD: they exist so that an obligation planted inside the window can
    discharge past its edge (a cadential 6/4 in the last rendered bar resolves
    onto the V of the bar after), but they are never themselves the subject of
    a rule — they host no events, so every event-shaped rule would misread
    them. `horizon=None` judges everything, which is what a complete piece
    wants."""
    return [c for c in contexts if horizon is None or c.bar < horizon]


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
    counter_range: tuple[int, int] = (55, 79)  # C5: the tenor gap (G3..G5)
    counter_consonance_ratio: float = 0.7      # strong beats consonant vs the melody
    counter_overlap_ratio: float = 0.4         # non-downbeat onsets shared with the melody


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
        bar, _ = _grid_pos(ev.start, meter)

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
        if ev.role == IMITATION_ROLE:
            # a C3 entry hosted by the pad rides ABOVE the voicing — range
            # still applies, the voicing rules (unison/voice-move) don't:
            # it is a figure, not a voice
            lo_i, hi_i = limits.pad_range
            if not lo_i <= ev.pitch <= hi_i:
                out.append(Violation("pad-range", meter.bar_of(ev.start),
                                     f"{pitch_name(ev.pitch)} outside pad range "
                                     f"[{pitch_name(lo_i)}, {pitch_name(hi_i)}]"))
            continue
        groups.setdefault(ev.start, []).append(ev)

    # Voicing analysis (unison doubling, voice movement) needs simultaneous
    # chords — Strum staggers starts, so these rules are pre-modifier only.
    voicing_rules = stage == "pre"
    lo, hi = limits.pad_range
    prev_pitches: list[int] | None = None
    for start in sorted(groups):
        pitches = [e.pitch for e in groups[start]]
        bar, offset = _grid_pos(start, meter)
        if voicing_rules and any(b == a for a, b in zip(pitches, pitches[1:])):
            out.append(Violation("unison", bar, f"pad voicing doubles a unison: {[pitch_name(p) for p in pitches]}"))
        for p in pitches:
            if not lo <= p <= hi:
                out.append(Violation("pad-range", bar, f"{pitch_name(p)} outside pad range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        ctx = ctx_by_bar.get(bar)
        if ctx is not None and ctx.chord_pcs:
            pcs = ctx.chord_pcs
            if ctx.chords:  # D3: membership against the segment in force
                chord_now = ctx.chord_at(offset)
                if chord_now is not None:
                    pcs = chord_now.voiced_pcs(ctx.scale)
            for ev in groups[start]:
                if ev.pitch % 12 not in pcs and ev.role not in LICENSED_NONCHORD:
                    out.append(Violation("chord-tone", bar, f"pad {pitch_name(ev.pitch)} is not a member of {ctx.chord_sym} (pcs {pcs})"))
        # a lone pitch is a figure note (a C2 comping strike, an ornament's
        # resolution), not a voicing — voice-leading is judged between chords
        if (voicing_rules and prev_pitches is not None
                and len(prev_pitches) == len(pitches) and len(pitches) >= 2):
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
        bar, offset = _grid_pos(ev.start, meter)
        if not lo <= ev.pitch <= hi:
            out.append(Violation("bass-range", bar, f"{pitch_name(ev.pitch)} outside bass range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        ctx = ctx_by_bar.get(bar)
        if ctx is None or not ctx.chord_pcs:
            continue
        if offset == 0.0:  # the downbeat, as WRITTEN (a humanized onset still is one)
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
        # the doubled line (C1) sits up to a 6th under the surface, so its
        # floor extends by that interval; the surface note itself is bounded
        floor = lo - 9 if ev.role == DOUBLING_ROLE else lo
        if not floor <= ev.pitch <= hi:
            out.append(Violation("melody-range", meter.bar_of(ev.start),
                                 f"{pitch_name(ev.pitch)} outside melody range [{pitch_name(lo)}, {pitch_name(hi)}]"))

    # A completed signature statement is exempt from the constraint-first melodic
    # heuristics (strong-beat chord tones, leap recovery): its intervals are the
    # identity, licensed as a whole (M15). Its register is still bounded above.
    # Doubling (C1) is a shadow of the surface, not part of the line — sampling
    # it would interleave fake leaps into the surface's triples.
    tuneful = [e for e in melody if e.role not in (MOTIF_ROLE, DOUBLING_ROLE)]
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


def _lint_ties(events, meter, out) -> None:
    """D1 tie coherence: an "in"/"both" event must continue a same-layer
    same-pitch event that ends exactly at its start and ties out. An orphan
    "out" is legal — a tie into a rest or an unhosted bar dissolves into a
    plain note (merge_ties treats it so) — but an orphan "in" claims a
    continuation that never sounded. Dormant on tie-free output."""
    by_key: dict[tuple[str, int], list[NoteEvent]] = {}
    for ev in events:
        if ev.tie:
            by_key.setdefault((ev.layer, ev.pitch), []).append(ev)
    for (layer, pitch), evs in by_key.items():
        evs.sort(key=lambda e: e.start)
        for ev in evs:
            if ev.tie in ("in", "both"):
                if not any(o is not ev and o.tie in ("out", "both")
                           and abs(o.end - ev.start) < 1e-9 for o in evs):
                    out.append(Violation("tie", meter.bar_of(ev.start),
                        f"{pitch_name(pitch)} ({layer}) ties in from nothing — no "
                        f"same-pitch note ties out into its start"))


def _lint_doubling(events, ctx_by_bar, meter, out) -> None:
    """C1 doubling contract (REFINEMENT_PLAN): every role-"doubling" note is
    simultaneous with a melody surface note a 3rd or 6th (or compound) above
    it, and is a chord member on strong slots / a melodic-scale member on weak
    ones — the whitelist the generator's post-pass obeys. Dormant on output
    that emits no doubling."""
    surface = [e for e in events if e.layer == "melody" and e.role != DOUBLING_ROLE]
    strong = set(meter.strong_slots())
    for d in (e for e in events if e.layer == "melody" and e.role == DOUBLING_ROLE):
        bar = meter.bar_of(d.start)
        src = next((m for m in surface
                    if abs(m.start - d.start) < 1e-9 and m.pitch > d.pitch), None)
        if src is None:
            out.append(Violation("doubling", bar,
                f"doubling {pitch_name(d.pitch)} has no simultaneous melody note above it"))
            continue
        if interval_class(d.pitch, src.pitch) not in (3, 4, 8, 9):
            out.append(Violation("doubling", bar,
                f"doubling {pitch_name(d.pitch)} is not a 3rd/6th below "
                f"the melody's {pitch_name(src.pitch)}"))
            continue
        ctx = ctx_by_bar.get(bar)
        if ctx is None or not ctx.chord_pcs:
            continue
        if meter.slot_of(d.start) in strong:
            if d.pitch % 12 not in ctx.chord_pcs:
                out.append(Violation("doubling", bar,
                    f"strong-slot doubling {pitch_name(d.pitch)} is not a member of {ctx.chord_sym}"))
        else:
            mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
            if not mscale.contains(d.pitch) and d.pitch % 12 not in ctx.chord_pcs:
                out.append(Violation("doubling", bar,
                    f"doubling {pitch_name(d.pitch)} is neither a {mscale.name} tone "
                    f"nor a member of {ctx.chord_sym}"))


def _lint_counter(events, ctx_by_bar, meter, limits, out) -> None:
    """C5 species set (REFINEMENT_PLAN): the countermelody stays in the tenor
    gap and never above the sounding melody; its strong beats are chord
    members and mostly consonant with the melody (3rds/6ths — P5/P8 exist but
    are what the walk couldn't avoid); no consecutive/direct perfects against
    melody OR bass; and its onsets live in the melody's holes (rhythmic
    complementarity, downbeats exempt). Dormant on output with no counter
    layer — pre-C5 renders are unaffected."""
    counter = sorted((e for e in events if e.layer == "counter" and e.role != "echo"),
                     key=lambda e: e.start)
    if not counter:
        return
    melody = sorted((e for e in events if e.layer == "melody"
                     and e.role not in (DOUBLING_ROLE, "echo")), key=lambda e: e.start)
    bass = sorted((e for e in events if e.layer == "bass"), key=lambda e: e.start)
    strong = set(meter.strong_slots())
    lo, hi = limits.counter_range

    def sounding(evs, t):
        cur = None
        for e in evs:
            if e.start > t + 1e-9:
                break
            if t < e.end - 1e-9:
                cur = e
        return cur

    melody_slots: dict[int, set[int]] = {}
    for m in melody:
        melody_slots.setdefault(meter.bar_of(m.start), set()).add(meter.slot_of(m.start))

    consonant = total = overlap = weak_onsets = 0
    vs_m: tuple[float, int, int] | None = None
    vs_b: tuple[float, int, int] | None = None
    for e in counter:
        bar, slot = meter.bar_of(e.start), meter.slot_of(e.start)
        if not lo <= e.pitch <= hi:
            out.append(Violation("counter-range", bar,
                f"{pitch_name(e.pitch)} outside counter range [{pitch_name(lo)}, {pitch_name(hi)}]"))
        m = sounding(melody, e.start)
        if m is not None and e.pitch > m.pitch:
            out.append(Violation("counter-crossing", bar,
                f"counter {pitch_name(e.pitch)} crosses above the melody's {pitch_name(m.pitch)}"))
        if slot != 0:
            weak_onsets += 1
            if slot in melody_slots.get(bar, ()):
                overlap += 1
        if slot not in strong:
            continue
        ctx = ctx_by_bar.get(bar)
        if ctx is not None and ctx.chord_pcs and e.pitch % 12 not in ctx.chord_pcs:
            out.append(Violation("counter-chord-tone", bar,
                f"strong-slot counter {pitch_name(e.pitch)} is not a member of {ctx.chord_sym}"))
        if m is not None:
            total += 1
            consonant += interval_class(e.pitch, m.pitch) in CONSONANT
            if vs_m is not None and e.start - vs_m[0] <= meter.bar_quarters + 1e-9:
                if forbidden_parallel(vs_m[1], vs_m[2], e.pitch, m.pitch):
                    out.append(Violation("counter-parallel", bar,
                        f"consecutive perfects between counter and melody: "
                        f"{pitch_name(vs_m[1])}/{pitch_name(vs_m[2])} -> "
                        f"{pitch_name(e.pitch)}/{pitch_name(m.pitch)}"))
                elif slot == 0 and forbidden_direct(vs_m[1], vs_m[2], e.pitch, m.pitch):
                    out.append(Violation("counter-direct", bar,
                        "direct perfect between counter and melody into the downbeat"))
            vs_m = (e.start, e.pitch, m.pitch)
        b = sounding(bass, e.start)
        if b is not None:
            if vs_b is not None and e.start - vs_b[0] <= meter.bar_quarters + 1e-9:
                if forbidden_parallel(vs_b[2], vs_b[1], b.pitch, e.pitch):
                    out.append(Violation("counter-parallel", bar,
                        f"consecutive perfects between counter and bass: "
                        f"{pitch_name(vs_b[1])}/{pitch_name(vs_b[2])} -> "
                        f"{pitch_name(e.pitch)}/{pitch_name(b.pitch)}"))
                elif slot == 0 and forbidden_direct(vs_b[2], vs_b[1], b.pitch, e.pitch):
                    out.append(Violation("counter-direct", bar,
                        "direct perfect between counter and bass into the downbeat"))
            vs_b = (e.start, e.pitch, b.pitch)

    if total >= 8 and consonant / total < limits.counter_consonance_ratio:
        out.append(Violation("counter-consonance", -1,
            f"only {consonant}/{total} strong-beat counter notes are consonant with the "
            f"melody ({consonant / total:.2f} < {limits.counter_consonance_ratio})"))
    if weak_onsets >= 10 and overlap / weak_onsets > limits.counter_overlap_ratio:
        out.append(Violation("counter-overlap", -1,
            f"{overlap}/{weak_onsets} off-downbeat counter onsets coincide with melody "
            f"onsets ({overlap / weak_onsets:.2f} > {limits.counter_overlap_ratio}) — "
            f"the counter should move in the melody's holes"))


def _lint_perc(events, limits, meter, out) -> None:
    for ev in (e for e in events if e.layer == "perc"):
        if ev.pitch not in limits.drum_pitches:
            out.append(Violation("drum-map", meter.bar_of(ev.start),
                                 f"perc pitch {ev.pitch} not in the drum map"))


def _lint_cadences(contexts, out, horizon=None) -> None:
    for ctx in _judged(contexts, horizon):
        if not ctx.cadence_slot or ctx.chord is None or not ctx.cadence_policy:
            continue
        if ctx.chord.applied:
            continue  # a secondary dominant is a valid (chromatic) pre-cadence; its
            #           resolution is checked by the tonicize obligation instead
        table = CADENCE_DEGREES if ctx.cadence_slot == "cadence" else PRE_CADENCE_DEGREES
        allowed = table.get(ctx.cadence_policy)
        # a D3 split bar is judged by the segment APPROACHING the cadence —
        # the harmony in force when the barline arrives
        judged = ctx.chords[-1][1] if ctx.chords else ctx.chord
        if allowed and judged.degree not in allowed:
            out.append(Violation(
                "cadence", ctx.bar,
                f"{ctx.cadence_slot} ({ctx.cadence_policy}) realized degree {judged.degree}, expected one of {allowed}",
            ))


def _lint_obligations(events, ctx_by_bar, meter, out, horizon=None) -> None:
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

    # obligations are PLANTED inside the window; ctx_by_bar reaches past it, so
    # a promise made in the last rendered bar can still be kept by a lookahead
    for ctx in _judged(ctx_by_bar.values(), horizon):
        bar = ctx.bar
        if ctx.obligation.startswith("tonicize:"):
            target = int(ctx.obligation.split(":", 1)[1])
            nxt = ctx_by_bar.get(bar + 1)
            if nxt is None or nxt.chord is None or nxt.chord.degree != target:
                out.append(Violation("tonicize", bar,
                    f"secondary dominant {ctx.chord_sym or '(?)'} does not resolve to degree {target}"))
        elif ctx.obligation == "cadential64":
            # B1: the 6/4 is a promise — a root-position dominant must follow;
            # a D3 split bar may discharge it WITHIN the bar (the mid-pulse V)
            in_bar = any(off > 0 and ch.degree == 5 and ch.inversion == 0
                         for off, ch in ctx.chords)
            nxt = ctx_by_bar.get(bar + 1)
            if not in_bar and (nxt is None or nxt.chord is None
                               or nxt.chord.degree != 5 or nxt.chord.inversion != 0):
                out.append(Violation("cadential64", bar,
                    f"cadential 6/4 {ctx.chord_sym or '(?)'} does not discharge onto "
                    f"a root-position V"))

    # B4: a lament ground (contiguous obligation "lament" bars) must reach the
    # dominant — its own last chord is degree 5, or the bar after it is.
    lament = sorted(c.bar for c in _judged(ctx_by_bar.values(), horizon)
                    if c.obligation == "lament")
    i = 0
    while i < len(lament):
        j = i
        while j + 1 < len(lament) and lament[j + 1] == lament[j] + 1:
            j += 1
        last = ctx_by_bar[lament[j]]
        nxt = ctx_by_bar.get(lament[j] + 1)

        def _is_dominant(c) -> bool:  # the bass must ARRIVE on 5̂: root position only
            return c is not None and c.chord is not None and c.chord.degree == 5 \
                and c.chord.inversion == 0

        reaches = _is_dominant(last) or _is_dominant(nxt)
        if not reaches:
            out.append(Violation("lament", lament[i],
                f"lament ground (bars {lament[i] + 1}..{lament[j] + 1}) never reaches the dominant"))
        i = j + 1


def lint_groove(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    params_by_bar: dict,
    meter: Meter = Meter(),
    *,
    horizon: int | None = None,
) -> list[Violation]:
    """A2 groove-persistence contract (REFINEMENT_PLAN): within a phrase, under
    bar-to-bar-stable shaping params (density, roughness, dynamics, layer set),
    the non-fill percussion pattern and the arp's onset mask must be identical
    across bars — pattern identity is what makes harmonic change legible.
    Cadence bars are exempt for perc (the fill is the licensed variation), as is
    the phrase-open crash. Run on pre-modifier IR; standalone (needs per-bar
    params, which lint()'s inputs don't carry) — called by tests and demos, and
    by lint() itself once phrase_groove becomes the default."""
    ctx_by_bar = {c.bar: c for c in _judged(contexts, horizon)}
    perc_pat: dict[int, list] = {}
    arp_pat: dict[int, set] = {}
    for ev in events:
        bar = meter.bar_of(ev.start)
        if ev.layer == "perc" and ev.role != "drum:crash":
            perc_pat.setdefault(bar, []).append((meter.slot_of(ev.start), ev.pitch, ev.velocity))
        elif ev.layer == "arp" and ev.role not in ("echo", IMITATION_ROLE):
            # a C3 entry overlays the arp's register without re-rolling its
            # pattern — the groove contract judges the figuration itself
            arp_pat.setdefault(bar, set()).add(meter.slot_of(ev.start))

    out: list[Violation] = []

    def check(rule: str, patterns: dict[int, tuple], skip_cadence: bool) -> None:
        last: dict[int, tuple] = {}  # phrase start bar -> (params fingerprint, pattern, bar)
        for bar in sorted(ctx_by_bar):
            ctx, p = ctx_by_bar[bar], params_by_bar.get(bar)
            if p is None or (skip_cadence and ctx.phrase_pos == ctx.phrase_bars - 1):
                continue
            fingerprint = (p.note_density, p.roughness, p.velocity_center, p.layers)
            pattern = patterns.get(bar, ())
            phrase = bar - ctx.phrase_pos
            prev = last.get(phrase)
            if prev is not None and prev[0] == fingerprint and prev[1] != pattern:
                out.append(Violation(rule, bar,
                    f"{rule} pattern re-rolled mid-phrase under stable params "
                    f"(bar {prev[2] + 1} -> bar {bar + 1})"))
            last[phrase] = (fingerprint, pattern, bar)

    check("groove-perc", {b: tuple(sorted(v)) for b, v in perc_pat.items()}, skip_cadence=True)
    check("groove-arp", {b: tuple(sorted(v)) for b, v in arp_pat.items()}, skip_cadence=False)
    return out


def lint_outer(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    contrary_min: float = 0.5,
    horizon: int | None = None,
) -> list[Violation]:
    """A3 outer-voice frame rules (REFINEMENT_PLAN): the soprano-bass pair at
    successive strong-slot melody onsets must not form consecutive perfects
    (parallel/antiparallel 5ths & 8ves) or reach a perfect by a similar-motion
    melody leap on a downbeat (direct 5ths/8ves); cadence arrivals prefer
    contrary/oblique motion across the barline (ratio rule with slack). A rest
    longer than a bar breaks the frame. Signature statements (role "motif")
    are licensed as a whole (M15 doctrine) and echoes ring free, so both are
    exempt from pair sampling. Run on pre-modifier IR; standalone like
    lint_groove — folded into lint() once the guard becomes the default."""
    bass = sorted((e for e in events if e.layer == "bass"), key=lambda e: e.start)
    melody = sorted((e for e in events if e.layer == "melody"
                     and e.role not in (MOTIF_ROLE, DOUBLING_ROLE, "echo")),
                    key=lambda e: e.start)
    strong = set(meter.strong_slots())

    def bass_at(t: float):
        cur = None
        for b in bass:
            if b.start > t + 1e-9:
                break
            if t < b.end - 1e-9:
                cur = b
        return cur

    pairs = []  # (t, melody pitch, bass pitch, bar, slot)
    for m in melody:
        slot = meter.slot_of(m.start)
        if slot not in strong:
            continue
        b = bass_at(m.start)
        if b is not None:
            pairs.append((m.start, m.pitch, b.pitch, meter.bar_of(m.start), slot))

    out: list[Violation] = []
    for (t1, m1, b1, _, _), (t2, m2, b2, bar2, slot2) in zip(pairs, pairs[1:]):
        if t2 - t1 > meter.bar_quarters + 1e-9:
            continue  # the frame broke (a rest bar / gated melody)
        name = {0: "octaves", 7: "fifths"}.get(interval_class(b2, m2), "?")
        if forbidden_parallel(b1, m1, b2, m2):
            out.append(Violation("outer-parallel", bar2,
                f"parallel {name} between melody and bass: "
                f"{pitch_name(m1)}/{pitch_name(b1)} -> {pitch_name(m2)}/{pitch_name(b2)}"))
        elif slot2 == 0 and forbidden_direct(b1, m1, b2, m2):
            out.append(Violation("outer-direct", bar2,
                f"direct {name} into the downbeat: melody leaps "
                f"{pitch_name(m1)} -> {pitch_name(m2)} in similar motion with the bass"))

    good = total = 0
    for ctx in _judged(contexts, horizon):
        if ctx.cadence_slot != "cadence":
            continue
        if ctx.phrase_pos == 0:
            continue  # an elided cadence (D2) is crashed into, not settled into —
            #           the approach-contrary preference is about the settle
        # the cadence approach mixes yardsticks deliberately: the melody is the
        # SURFACE line (the ear tracks it — e.g. the post-apex descent), while
        # the bass is the ROOT motion downbeat-to-downbeat — its approach tone
        # is an ornamental connective whose direction says nothing about the
        # harmonic arrival (2̂→1̂ over 5̂→1̂ is contrary regardless of which side
        # the approach slid in from)
        bar_start = ctx.bar * meter.bar_quarters
        before = [e for e in melody if bar_start - meter.bar_quarters - 1e-9 < e.start < bar_start - 1e-9]
        after = [e for e in melody if meter.bar_of(e.start) == ctx.bar]
        b1 = bass_at(bar_start - meter.bar_quarters)
        b2 = bass_at(bar_start)
        if before and after and b1 is not None and b2 is not None:
            total += 1
            good += motion(b1.pitch, before[-1].pitch, b2.pitch, after[0].pitch) in ("contrary", "oblique")
    if total >= 4 and good / total < contrary_min:
        out.append(Violation("outer-cadence", -1,
            f"only {good}/{total} cadences approached in contrary/oblique motion "
            f"({good / total:.2f} < {contrary_min})"))
    return out


def lint_periods(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    horizon: int | None = None,
) -> list[Violation]:
    """B2 period contract (REFINEMENT_PLAN): a committed antecedent–consequent
    pair must answer — the consequent's opening bar carries the antecedent's
    melodic rhythm (its onset slots; pitches may re-realize when the guard or a
    moved window demands it). Cadence conformance per phrase is already the
    generic cadence rule's business, since ctx carries the forced policy.
    Standalone like lint_groove/lint_outer; run on pre-modifier IR."""
    ctx_by_bar = {c.bar: c for c in _judged(contexts, horizon)}
    onsets: dict[int, list[int]] = {}
    payoff_bars: set[int] = set()
    for ev in events:
        if ev.layer == "melody" and ev.role != DOUBLING_ROLE:  # the question is the surface line
            onsets.setdefault(meter.bar_of(ev.start), []).append(meter.slot_of(ev.start))
            if ev.role == MOTIF_ROLE:  # a completed-signature statement (M15/M17)
                payoff_bars.add(meter.bar_of(ev.start))

    out: list[Violation] = []
    for bar, ctx in sorted(ctx_by_bar.items()):
        if ctx.form != "consequent" or ctx.phrase_pos != 0:
            continue
        ante_bar = bar - ctx.phrase_bars
        if ctx_by_bar.get(ante_bar) is None or ctx_by_bar[ante_bar].form != "antecedent":
            out.append(Violation("period", bar, "consequent without a recorded antecedent"))
            continue
        if any(b in payoff_bars for b in range(bar, bar + ctx.phrase_bars)):
            continue  # a dramaturg/landmark payoff overrode the answer — the arrival wins
        question = sorted(onsets.get(ante_bar, []))
        answer = sorted(onsets.get(bar, []))
        if question and answer and question != answer:
            out.append(Violation("period", bar,
                f"consequent opening rhythm {answer} does not answer the "
                f"antecedent's {question} (bar {ante_bar + 1})"))
    return out


def lint_texture(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    params_by_bar: dict,
    meter: Meter = Meter(),
    *,
    horizon: int | None = None,
) -> list[Violation]:
    """C4 texture claims (REFINEMENT_PLAN): the Tier-2 texture state is
    checkable against the sounding events, phrase by phrase — "doubled" means
    doubling sounds (whenever the melody does), "imitative" means an entry
    exists (whenever the melody layer was live at the entry bar), the lean
    states mean NO polyphony sounds, and "monophonic" additionally thins the
    pad to dyads. Dormant when params carry no texture (pre-C4 "" state).
    Standalone like lint_groove; run on pre-modifier IR."""
    ctx_by_bar = {c.bar: c for c in _judged(contexts, horizon)}
    # phrase identity = rank of the phrase's start bar — division by
    # phrase_bars breaks once the D2 clock schedules elastic segments
    starts = sorted({bar - ctx.phrase_pos for bar, ctx in ctx_by_bar.items()})
    rank = {s: i for i, s in enumerate(starts)}
    phrases: dict[int, list[int]] = {}
    for bar, ctx in ctx_by_bar.items():
        phrases.setdefault(rank[bar - ctx.phrase_pos], []).append(bar)
    by_bar: dict[int, list[NoteEvent]] = {}
    for ev in events:
        by_bar.setdefault(meter.bar_of(ev.start), []).append(ev)

    out: list[Violation] = []
    for phrase, bars in sorted(phrases.items()):
        bars.sort()
        texs = {params_by_bar[b].texture for b in bars if b in params_by_bar}
        if len(texs) != 1:
            continue  # an override flipped mid-phrase — no phrase-level claim
        tex = texs.pop()
        if not tex:
            continue
        if len(bars) < ctx_by_bar[bars[0]].phrase_bars:
            continue  # the render truncated this phrase — its claim never got room
        evs = [e for b in bars for e in by_bar.get(b, [])]
        melody = [e for e in evs if e.layer == "melody" and e.role != DOUBLING_ROLE]
        doubles = [e for e in evs if e.role == DOUBLING_ROLE]
        imits = [e for e in evs if e.role == IMITATION_ROLE]
        counter = [e for e in evs if e.layer == "counter"]
        first = bars[0]
        if tex == "doubled" and melody and not doubles:
            out.append(Violation("texture", first,
                f"phrase {phrase} claims 'doubled' but the melody sounds undoubled"))
        elif tex == "imitative" and not imits:
            entry_bar = bars[1] if len(bars) > 1 else None
            p = params_by_bar.get(entry_bar)
            if p is not None and "melody" in p.layers:
                out.append(Violation("texture", first,
                    f"phrase {phrase} claims 'imitative' but no entry sounds"))
        elif tex == "counter" and not counter:
            p = params_by_bar.get(first)
            if p is not None and "counter" in p.layers:
                out.append(Violation("texture", first,
                    f"phrase {phrase} claims 'counter' but the layer is silent"))
        elif tex in ("monophonic", "homophonic") and (doubles or imits or counter):
            out.append(Violation("texture", first,
                f"phrase {phrase} claims '{tex}' but polyphony sounds"))
        if tex == "monophonic":
            groups: dict[float, int] = {}
            for e in evs:
                if e.layer == "pad" and e.role != IMITATION_ROLE:
                    groups[e.start] = groups.get(e.start, 0) + 1
            fat = next((t for t, n in sorted(groups.items()) if n > 2), None)
            if fat is not None:
                out.append(Violation("texture", meter.bar_of(fat),
                    f"monophonic phrase {phrase} voices a {groups[fat]}-note pad"))
    return out


def lint_imitation(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    cells: dict,
    meter: Meter = Meter(),
    *,
    threshold: float = 0.9,
    horizon: int | None = None,
) -> list[Violation]:
    """C3 imitation contract (REFINEMENT_PLAN): the role-"imitation" events of
    a phrase must reproduce that phrase's cached source cell — contour-delta
    recognizability ≥ `threshold` in the entry bar's melodic scale.
    Transposition preserves deltas, so a faithful entry scores 1.0 by
    construction and a corrupted pitch drops below. Standalone like
    lint_groove: `cells` is the engine's re-derivable per-phrase cache
    (ConductorState.imitation_cells). Run on pre-modifier IR."""
    from musicgen.gen.motif import recognizability

    ctx_by_bar = {c.bar: c for c in _judged(contexts, horizon)}
    starts = sorted({bar - ctx.phrase_pos for bar, ctx in ctx_by_bar.items()})
    rank = {s: i for i, s in enumerate(starts)}  # elastic-segment-safe (D2)
    by_phrase: dict[int, list[NoteEvent]] = {}
    for ev in events:
        if ev.role == IMITATION_ROLE and ev.layer in ("arp", "pad"):
            bar = meter.bar_of(ev.start)
            ctx = ctx_by_bar.get(bar)
            if ctx is None:
                continue
            by_phrase.setdefault(rank[bar - ctx.phrase_pos], []).append(ev)

    out: list[Violation] = []
    for phrase, entry in sorted(by_phrase.items()):
        entry.sort(key=lambda e: e.start)
        bar = meter.bar_of(entry[0].start)
        cell = cells.get(phrase)
        if cell is None:
            out.append(Violation("imitation", bar,
                f"imitation events in phrase {phrase} without a recorded source cell"))
            continue
        ctx = ctx_by_bar[bar]
        mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
        score = recognizability(cell, [e.pitch for e in entry], mscale)
        if score < threshold:
            out.append(Violation("imitation", bar,
                f"imitation entry no longer carries its cell's contour "
                f"(recognizability {score:.2f} < {threshold})"))
    return out


def lint(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
    limits: LintLimits = LintLimits(),
    horizon: int | None = None,
) -> list[Violation]:
    ctx_by_bar = {c.bar: c for c in contexts}  # FULL: reaches into the lookahead
    out: list[Violation] = []
    _lint_events(events, ctx_by_bar, meter, stage, out)
    _lint_pad(events, ctx_by_bar, meter, limits, stage, out)
    _lint_bass(events, ctx_by_bar, meter, limits, out)
    if stage == "pre":  # slot-based melodic + obligation analysis assumes the unmodified grid
        # the melodic-line rules judge logical notes: a tie chain (D1) is one
        # note whose onset is its head — a tied-into downbeat is not an
        # attack, so it neither samples the strong-beat ratio nor fakes leaps
        _lint_melody(merge_ties(events), ctx_by_bar, meter, limits, out)
        _lint_obligations(events, ctx_by_bar, meter, out, horizon)
        _lint_doubling(events, ctx_by_bar, meter, out)
        _lint_counter(events, ctx_by_bar, meter, limits, out)
        _lint_ties(events, meter, out)
    _lint_perc(events, limits, meter, out)
    _lint_cadences(contexts, out, horizon)
    return out


def assert_clean(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    *,
    stage: str = "pre",
    limits: LintLimits = LintLimits(),
    horizon: int | None = None,
) -> None:
    violations = lint(events, contexts, meter, stage=stage, limits=limits,
                      horizon=horizon)
    if violations:
        raise TheoryLintError(f"{len(violations)} violation(s):\n" + "\n".join(map(str, violations)))
