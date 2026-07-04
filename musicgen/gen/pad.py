"""Sustained voice-led pad chords (PLANS.md §5.3). Comping rhythm arrives
with the M2 rhythm engine.
"""

from __future__ import annotations

from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.voicing import VoicingConfig, voice_chord

PAD_VELOCITY_OFFSET = -6


def generate_pad(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    prev_voicing: tuple[int, ...] | None,
    cfg: VoicingConfig,
) -> tuple[list[NoteEvent], tuple[int, ...], str]:
    """One bar of sustained chord. Returns (events, voicing, trace)."""
    # Voicing wants root-first pcs for its doubling preferences; chord_pcs is
    # bass-first (equal unless inverted).
    pcs = ctx.chord.pitch_classes(ctx.scale) if ctx.chord else ctx.chord_pcs
    voicing, cost = voice_chord(pcs, prev_voicing, cfg)
    start = ctx.bar * meter.bar_quarters
    velocity = max(1, min(127, params.velocity_center + PAD_VELOCITY_OFFSET))
    events = [
        NoteEvent(
            start, meter.bar_quarters, pitch, velocity, "pad",
            degree=ctx.scale.degree_of(pitch),
            chord=ctx.chord_sym,
            role="chord-tone" if ctx.scale.contains(pitch) else "borrowed",
        )
        for pitch in voicing
    ]
    return events, voicing, f"pad: voicing {voicing} cost {cost:.1f}"
