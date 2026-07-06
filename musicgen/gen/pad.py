"""Sustained voice-led pad chords (PLANS.md §5.3), with optional cadential
suspensions the dramaturg deploys (§5.8, M14). Comping rhythm arrives with the
M2 rhythm engine.
"""

from __future__ import annotations

from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.pitch import pitch_name
from musicgen.theory.voicing import VoicingConfig, voice_chord

PAD_VELOCITY_OFFSET = -6


def _suspension_pair(
    voicing: tuple[int, ...], prev_voicing: tuple[int, ...] | None, ctx: HarmonicContext,
) -> tuple[int, int] | None:
    """A prepared suspension over this bar's chord: a pitch still sounding from the
    previous bar (so it is *prepared* — the previous voicing is all chord tones)
    that is now a diatonic non-chord tone a step above one of this bar's voiced
    chord tones. Returns (target, suspended) or None — the held tone resolves down
    by step to `target` (the classic prepare→dissonance→resolution: 4–3, 9–8, …).

    Pure and deterministic. `suspended` is drawn from `prev_voicing`, so it is
    already in the pad register and needs no motion into place."""
    if not prev_voicing:
        return None
    prev, chord_pcs = set(prev_voicing), set(ctx.chord_pcs)
    best: tuple[tuple[int, int], int, int] | None = None
    for target in voicing:  # a voiced chord tone of this bar = the resolution
        for step in (1, 2):  # a semitone or whole-step suspension above it
            s = target + step
            if s in prev and s % 12 not in chord_pcs and ctx.scale.contains(s):
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
) -> tuple[list[NoteEvent], tuple[int, ...], str]:
    """One bar of sustained chord. Returns (events, voicing, trace). A cadence
    ornament delays one voice — a prepared **suspension** where one is available,
    else (on the payoff) an unprepared **appoggiatura** — struck as a non-chord
    tone and resolving down by step at the mid-bar pulse. The returned voicing is
    still the resolved chord (so the next bar voice-leads — and prepares — from the
    resolution)."""
    # Voicing wants root-first pcs for its doubling preferences; chord_pcs is
    # bass-first (equal unless inverted).
    pcs = ctx.chord.pitch_classes(ctx.scale) if ctx.chord else ctx.chord_pcs
    voicing, cost = voice_chord(pcs, prev_voicing, cfg)
    start, bar_len = ctx.bar * meter.bar_quarters, meter.bar_quarters
    velocity = max(1, min(127, params.velocity_center + PAD_VELOCITY_OFFSET))

    def note(t: float, d: float, pitch: int, role: str) -> NoteEvent:
        return NoteEvent(t, d, pitch, velocity, "pad", degree=ctx.scale.degree_of(pitch),
                         chord=ctx.chord_sym,
                         role=role or ("chord-tone" if ctx.scale.contains(pitch) else "borrowed"))

    ornament = None  # (target, dissonant, role): a suspension if preparable, else an appoggiatura
    if suspend and (pair := _suspension_pair(voicing, prev_voicing, ctx)) is not None:
        ornament = (*pair, "suspension")
    if ornament is None and appoggiatura and (pair := _appoggiatura_pair(voicing, ctx, cfg.hi)) is not None:
        ornament = (*pair, "appoggiatura")

    trace = f"pad: voicing {voicing} cost {cost:.1f}"
    if ornament is None:
        return [note(start, bar_len, pitch, "") for pitch in voicing], voicing, trace

    target, dissonant, role = ornament
    res_at = meter.pulse_quarters * max(1, meter.pulses // 2)  # resolve on the mid-bar pulse
    events = []
    for pitch in voicing:
        if pitch == target:
            events.append(note(start, res_at, dissonant, role))
            events.append(note(start + res_at, bar_len - res_at, target, "resolution"))
        else:
            events.append(note(start, bar_len, pitch, ""))
    return events, voicing, trace + f" │ {pitch_name(dissonant)}–{pitch_name(target)} {role}"
