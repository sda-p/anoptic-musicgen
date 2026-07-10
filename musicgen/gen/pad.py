"""Sustained voice-led pad chords (PLANS.md §5.3), with optional cadential
suspensions the dramaturg deploys (§5.8, M14) and inner-voice animation
(REFINEMENT_PLAN C2): instead of a static block, a **connective** bar walks one
voice through a passing tone toward its next-bar pitch (the pad knows where it
is going — the conductor passes the upcoming chord's pcs and the voicing
optimizer is deterministic), and a **comping** bar breaks the voicing into a
slow Alberti-adjacent figure on the pulse grid. The returned voicing is always
the block target, so voice-leading memory and M14 preparation are untouched;
an ornament (suspension/appoggiatura) owns the bar and animation stands down.
"""

from __future__ import annotations

import random
from dataclasses import replace

from musicgen.gen.rhythm import rough_cell
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.pitch import pitch_name
from musicgen.theory.voicing import VoicingConfig, voice_chord

PAD_VELOCITY_OFFSET = -6
_COMPING_ORDER = (0, 2, 1, 3)  # low, mid-high, mid-low, top — Alberti-adjacent


def _connective_voice(
    voicing: tuple[int, ...], next_voicing: tuple[int, ...], ctx: HarmonicContext,
) -> tuple[int, int] | None:
    """(voice index, passing pitch) for the connective mode: the voice to
    animate — preferring one moving by a 3rd (exactly one diatonic tone lies
    between), then the highest — plus the scale tone strictly between its
    current and next-bar pitch. None when no voice travels far enough or
    nothing diatonic lies between (animation stands down to a block)."""
    if len(next_voicing) != len(voicing):
        return None
    best: tuple[tuple[bool, int], int, int] | None = None
    for i, (cur, nxt) in enumerate(zip(voicing, next_voicing)):
        gap = abs(nxt - cur)
        if gap < 2:
            continue
        between = [p for p in range(min(cur, nxt) + 1, max(cur, nxt))
                   if ctx.scale.contains(p)]
        if not between:
            continue
        mid = (cur + nxt) / 2
        key = (gap in (3, 4), i)
        if best is None or key > best[0]:
            best = (key, i, min(between, key=lambda q: (abs(q - mid), q)))
    return None if best is None else (best[1], best[2])


def _suspension_pair(
    voicing: tuple[int, ...], prev_voicing: tuple[int, ...] | None,
    chord_pcs: frozenset[int] | set[int], scale,
) -> tuple[int, int] | None:
    """A prepared suspension over a bar's chord: a pitch still sounding from the
    previous bar (so it is *prepared* — the previous voicing is all chord tones)
    that is now a diatonic non-chord tone a step above one of the bar's voiced
    chord tones. Returns (target, suspended) or None — the held tone resolves down
    by step to `target` (the classic prepare→dissonance→resolution: 4–3, 9–8, …).

    Pure and deterministic over explicit (chord_pcs, scale), so the D1 tie
    preparation can evaluate it one bar AHEAD (the same preview the C2
    animation uses). `suspended` is drawn from `prev_voicing`, so it is
    already in the pad register and needs no motion into place."""
    if not prev_voicing:
        return None
    prev = set(prev_voicing)
    best: tuple[tuple[int, int], int, int] | None = None
    for target in voicing:  # a voiced chord tone of this bar = the resolution
        for step in (1, 2):  # a semitone or whole-step suspension above it
            s = target + step
            if s in prev and s % 12 not in chord_pcs and scale.contains(s):
                key = (s, -step)  # prefer the highest suspension, then the tighter step
                if best is None or key > best[0]:
                    best = (key, target, s)
    return None if best is None else (best[1], best[2])


def _appoggiatura_pair(
    voicing: tuple[int, ...], ctx: HarmonicContext, hi: int,
) -> tuple[int, int] | None:
    """An *unprepared* accented non-chord tone a step above a voiced chord tone,
    resolving down onto it — the payoff lean (no preparation, unlike a suspension).
    Prefers leaning onto the tonic, then the highest voice; a whole-step over a
    semitone. Returns (target, appoggiatura) or None."""
    chord_pcs, tonic_pc = set(ctx.chord_pcs), ctx.scale.pitch_at(1, 4) % 12
    best: tuple[tuple[bool, int], int, int] | None = None
    for target in voicing:
        for step in (2, 1):  # a whole-step lean (e.g. D–C) reads more strongly than a semitone
            a = target + step
            if a > hi or a % 12 in chord_pcs or not ctx.scale.contains(a):
                continue
            key = (target % 12 == tonic_pc, target)  # onto the tonic first, then the top voice
            if best is None or key > best[0]:
                best = (key, target, a)
            break  # the whole-step lean wins for this target
    return None if best is None else (best[1], best[2])


def generate_pad(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    prev_voicing: tuple[int, ...] | None,
    cfg: VoicingConfig,
    suspend: bool = False,
    appoggiatura: bool = False,
    next_pcs: tuple[int, ...] | None = None,
    animate: str = "",
    rng: random.Random | None = None,
    thin: bool = False,
    tie_prep: tuple[tuple[int, ...], frozenset[int] | set[int], object] | None = None,
    prev_tie: int | None = None,
) -> tuple[list[NoteEvent], tuple[int, ...], str]:
    """One bar of sustained chord. Returns (events, voicing, trace). A cadence
    ornament delays one voice — a prepared **suspension** where one is available,
    else (on the payoff) an unprepared **appoggiatura** — struck as a non-chord
    tone and resolving down by step at the mid-bar pulse. The returned voicing is
    still the resolved chord (so the next bar voice-leads — and prepares — from the
    resolution).

    `animate` (C2, "" | "connective" | "comping") figurates an ornament-free
    bar; `next_pcs` (root-first pcs of the upcoming chord) feeds the connective
    preview, `rng` the comping figure. The returned voicing stays the block.
    `thin` (C4 "monophonic") strips the voicing to a bare root+fifth dyad —
    the leanest texture state, free of thirds entirely.

    `tie_prep` (D1: next chord's root-first pcs, its voiced-pc set, its scale)
    asks a block bar to genuinely HOLD next bar's suspension preparation: the
    same deterministic preview predicts next bar's voicing and suspension pair,
    and the preparing voice ties out across the barline. `prev_tie` closes the
    loop: when this bar's realized suspension is the pitch the previous bar
    tied out, the dissonance is a continuation ("in"), not a re-strike. A
    mispredicted preparation dissolves into a legal orphan tie."""
    # Voicing wants root-first pcs for its doubling preferences; chord_pcs is
    # bass-first (equal unless inverted).
    pcs = ctx.chord.pitch_classes(ctx.scale) if ctx.chord else ctx.chord_pcs
    if thin:
        pcs = (pcs[0], pcs[2] if len(pcs) > 2 else pcs[0])
        cfg = replace(cfg, voices=2)
    voicing, cost = voice_chord(pcs, prev_voicing, cfg)
    start, bar_len = ctx.bar * meter.bar_quarters, meter.bar_quarters
    velocity = max(1, min(127, params.velocity_center + PAD_VELOCITY_OFFSET))

    def note(t: float, d: float, pitch: int, role: str, tie: str = "") -> NoteEvent:
        return NoteEvent(t, d, pitch, velocity, "pad", degree=ctx.scale.degree_of(pitch),
                         chord=ctx.chord_sym,
                         role=role or ("chord-tone" if ctx.scale.contains(pitch) else "borrowed"),
                         tie=tie)

    ornament = None  # (target, dissonant, role): a suspension if preparable, else an appoggiatura
    if suspend and (pair := _suspension_pair(voicing, prev_voicing,
                                             set(ctx.chord_pcs), ctx.scale)) is not None:
        ornament = (*pair, "suspension")
    if ornament is None and appoggiatura and (pair := _appoggiatura_pair(voicing, ctx, cfg.hi)) is not None:
        ornament = (*pair, "appoggiatura")

    trace = f"pad: voicing {voicing} cost {cost:.1f}"
    if ornament is None and animate == "connective" and next_pcs:
        nxt, _ = voice_chord(next_pcs, voicing, cfg)
        pick = _connective_voice(voicing, nxt, ctx)
        if pick is not None:
            i, p = pick
            walk_at = bar_len - meter.pulse_quarters  # the last pulse walks on
            events = []
            for j, pitch in enumerate(voicing):
                if j == i:
                    events.append(note(start, walk_at, pitch, ""))
                    events.append(note(start + walk_at, bar_len - walk_at, p,
                                       "" if p % 12 in set(ctx.chord_pcs) else "passing"))
                else:
                    events.append(note(start, bar_len, pitch, ""))
            return events, voicing, trace + (
                f" │ animate: {pitch_name(voicing[i])}-{pitch_name(p)} walks toward "
                f"{pitch_name(nxt[i])}")
    if ornament is None and animate == "comping" and rng is not None:
        cell = rough_cell(rng, params.note_density, params.roughness,
                          slots=meter.pulses, base_step=1)
        events = [note(start + s * meter.pulse_quarters, d * meter.pulse_quarters,
                       voicing[_COMPING_ORDER[j % len(_COMPING_ORDER)] % len(voicing)], "")
                  for j, (s, d) in enumerate(cell)]
        return events, voicing, trace + f" │ animate: comping n={len(events)}"
    if ornament is None:
        held = None
        if tie_prep is not None:
            # predict next bar's voicing and suspension with the same
            # deterministic machinery next bar will run; the preparing voice
            # then ties out instead of being re-struck (D1)
            nxt_pcs, nxt_chord_pcs, nxt_scale = tie_prep
            nxt_voicing, _ = voice_chord(nxt_pcs, voicing, cfg)
            pair = _suspension_pair(nxt_voicing, voicing, nxt_chord_pcs, nxt_scale)
            if pair is not None:
                held = pair[1]
                trace += f" │ prep {pitch_name(held)}~ held across the barline"
        return ([note(start, bar_len, pitch, "", tie="out" if pitch == held else "")
                 for pitch in voicing], voicing, trace)

    target, dissonant, role = ornament
    res_at = meter.pulse_quarters * max(1, meter.pulses // 2)  # resolve on the mid-bar pulse
    events = []
    for pitch in voicing:
        if pitch == target:
            genuinely_held = role == "suspension" and prev_tie == dissonant
            events.append(note(start, res_at, dissonant, role,
                               tie="in" if genuinely_held else ""))
            events.append(note(start + res_at, bar_len - res_at, target, "resolution"))
        else:
            events.append(note(start, bar_len, pitch, ""))
    return events, voicing, trace + f" │ {pitch_name(dissonant)}–{pitch_name(target)} {role}"
