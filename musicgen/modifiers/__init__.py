"""Composable IR -> IR modifiers (PLANS.md §7).

Each modifier is a frozen dataclass with
    apply(events, ctx, meter, params, rng) -> list[NoteEvent]
— pure given its inputs; all randomness comes from the caller's per-(layer,
bar) stream, so the pre-modifier IR is identical whether chains run or not.

Chain order matters: slot-based modifiers (Accent) must run before
time-movers (Swing, Humanize). Params with value None read their live value
from MusicalParams (the lever hookups: Articulate.gate <- params.articulation,
Accent.depth <- params.accent_depth).

Annotations pass through; echoed copies are re-tagged role="echo", which the
linter licenses (an echo bleeding into the next bar's harmony is reverb-like
bleed, not a wrong note).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.scales import diatonic_shift

MIN_DUR = 0.1  # beats; floor for any duration-shrinking modifier


def _clamp_velocity(v: float) -> int:
    return max(1, min(127, round(v)))


@dataclass(frozen=True)
class Swing:
    """Delay off-beat 8ths toward triplet feel (16th offbeats by half)."""

    amount: float = 0.5  # 0 straight .. 1 full triplet

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        if meter.is_compound:
            return list(events)  # the feel is already ternary; nothing to swing
        out = []
        for ev in events:
            frac = ev.start % 1.0
            if abs(frac - 0.5) < 1e-6:
                shift = self.amount / 6.0
            elif abs(frac - 0.25) < 1e-6 or abs(frac - 0.75) < 1e-6:
                shift = self.amount / 12.0
            else:
                shift = 0.0
            if shift:
                ev = replace(ev, start=ev.start + shift, dur=max(MIN_DUR, ev.dur - shift))
            out.append(ev)
        return out


@dataclass(frozen=True)
class Humanize:
    """Gaussian timing/velocity jitter; never moves a note before its bar."""

    t_sigma: float = 0.015  # beats (~9 ms at 100 BPM)
    v_sigma: float = 5.0

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        bar_start = ctx.bar * meter.bar_quarters
        out = []
        for ev in events:
            dt = max(-2 * self.t_sigma, min(2 * self.t_sigma, rng.gauss(0.0, self.t_sigma)))
            dv = rng.gauss(0.0, self.v_sigma)
            out.append(replace(
                ev,
                start=round(max(bar_start, ev.start + dt), 6),
                velocity=_clamp_velocity(ev.velocity + dv),
            ))
        return out


@dataclass(frozen=True)
class Articulate:
    """Scale sounding duration: staccato (<1) to legato overlap (>1)."""

    gate: float | None = None  # None -> params.articulation

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        gate = params.articulation if self.gate is None else self.gate
        return [replace(ev, dur=max(MIN_DUR, ev.dur * gate)) for ev in events]


@dataclass(frozen=True)
class Accent:
    """Velocity shaped by the meter's accent hierarchy (run before time-movers)."""

    depth: float | None = None  # None -> params.accent_depth

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        depth = params.accent_depth if self.depth is None else self.depth
        weights = meter.metric_weights()
        out = []
        for ev in events:
            slot = meter.slot_of(ev.start)
            w = weights[slot] if 0 <= slot < len(weights) else 1.0
            out.append(replace(ev, velocity=_clamp_velocity(ev.velocity + depth * (w - 2.5) / 3.0)))
        return out


@dataclass(frozen=True)
class Perform:
    """Phrase-position-aware performance shaping (REFINEMENT_PLAN A1).

    Deterministic — systematic deviation tied to structure, where Humanize is
    noise: a velocity hairpin cresting into the pre-cadence bar and relaxing at
    the cadence, contour-tracking loudness (higher ≈ slightly louder), agogic
    stretch on phrase-open downbeats, a luftpause carved from the cadence bar's
    tails (a sliver of silence before the next phrase downbeat), and the layer
    riding behind the beat when sparse / on top when dense. Draws nothing from
    rng. Chain placement: after Articulate (legato must not refill the
    luftpause), before the time-jitter of Humanize."""

    hairpin: float = 0.12    # velocity swell depth: ±hairpin/2 across the phrase
    contour: float = 0.0     # velocity per semitone above/below register center
    agogic: float = 0.0      # dur stretch fraction on phrase-open downbeat notes
    luftpause: float = 0.05  # beats of silence before the next phrase downbeat
    lag: float = 0.0         # max beats behind (sparse) / ahead (dense) of the beat

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        bars = max(1, ctx.phrase_bars)
        phrase_len = bars * meter.bar_quarters
        phrase_start = (ctx.bar - ctx.phrase_pos) * meter.bar_quarters
        # swell peaks at the planned melodic apex (A4) when one exists, else
        # mid-pre-cadence bar — the hairpin rises to the contour peak
        crest = ((ctx.phrase_apex + 0.5) / bars if 0 <= ctx.phrase_apex < bars - 1
                 else max(0.5, bars - 1.5) / bars)
        bar_start = ctx.bar * meter.bar_quarters
        cut = bar_start + meter.bar_quarters - self.luftpause
        lag = self.lag * (1.0 - 2.0 * params.note_density)
        out = []
        for ev in events:
            frac = min(max((ev.start - phrase_start) / phrase_len, 0.0), 1.0)
            swell = frac / crest if frac <= crest else (1.0 - frac) / (1.0 - crest)
            velocity = (ev.velocity * (1.0 + self.hairpin * (swell - 0.5))
                        + self.contour * (ev.pitch - params.register_center))
            start, dur = ev.start, ev.dur
            if self.agogic and ctx.phrase_pos == 0 and meter.slot_of(ev.start) == 0:
                dur *= 1.0 + self.agogic
            if lag:
                start = round(max(bar_start, start + lag), 6)
            if self.luftpause and ctx.phrase_pos == bars - 1 and start < cut < start + dur:
                dur = max(MIN_DUR, cut - start)
            out.append(replace(ev, start=start, dur=dur, velocity=_clamp_velocity(velocity)))
        return out


@dataclass(frozen=True)
class Echo:
    """Append decaying repeats (arp/melody sparkle)."""

    delay: float = 0.75  # beats; dotted-8th classic
    decay: float = 0.55
    repeats: int = 2
    min_velocity: int = 24

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        out = list(events)
        # An echo landing exactly on a same-pitch note is masked by it — and
        # MIDI cannot represent two coincident same-pitch notes distinctly.
        occupied = {(round(ev.start, 6), ev.pitch) for ev in events}
        for ev in events:
            velocity = float(ev.velocity)
            for k in range(1, self.repeats + 1):
                velocity *= self.decay
                if velocity < self.min_velocity:
                    break
                start = round(ev.start + k * self.delay, 6)
                if (start, ev.pitch) in occupied:
                    continue
                occupied.add((start, ev.pitch))
                out.append(replace(
                    ev,
                    start=start,
                    dur=min(ev.dur, self.delay * 0.9),
                    velocity=_clamp_velocity(velocity),
                    role="echo",
                ))
        out.sort(key=lambda e: (e.start, e.pitch))
        return out


@dataclass(frozen=True)
class Strum:
    """Stagger simultaneous notes low-to-high; note ends stay put."""

    spread: float = 0.05  # beats across the whole chord

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        groups: dict[float, list[NoteEvent]] = {}
        for ev in events:
            groups.setdefault(ev.start, []).append(ev)
        out = []
        for start in sorted(groups):
            chord = sorted(groups[start], key=lambda e: e.pitch)
            n = len(chord)
            for i, ev in enumerate(chord):
                offset = self.spread * i / (n - 1) if n > 1 else 0.0
                out.append(replace(ev, start=round(ev.start + offset, 6),
                                   dur=max(MIN_DUR, ev.dur - offset)))
        return out


@dataclass(frozen=True)
class Transpose:
    """Utility: shift by octaves and/or diatonic steps (context scale).

    Note: chord/role annotations are not re-derived; keep this off layers
    with chord-membership lint rules (pad/bass) unless shifting whole octaves.
    """

    octaves: int = 0
    steps: int = 0

    def apply(self, events, ctx, meter, params, rng) -> list[NoteEvent]:
        out = []
        for ev in events:
            pitch = ev.pitch + 12 * self.octaves
            if self.steps:
                pitch = diatonic_shift(ctx.scale, pitch, self.steps)
            pitch = max(0, min(127, pitch))
            out.append(replace(ev, pitch=pitch, degree=ctx.scale.degree_of(pitch)))
        return out


def apply_chain(chain, events, ctx, meter, params, rng) -> list[NoteEvent]:
    for modifier in chain:
        events = modifier.apply(events, ctx, meter, params, rng)
    return events


def default_chains(perform: bool = False) -> dict[str, tuple]:
    """PLANS.md §7 default chains; lever hookups via None params.

    perform=True inserts the A1 Perform shaping per pitched layer — full
    treatment (contour, agogic, lay-back) on the melody line, hairpin +
    luftpause elsewhere. Perc keeps its groove dynamics (drums are one-shots;
    durations, and so a luftpause, are inaudible there). The default stays
    byte-identical to the pre-A1 chains."""
    if not perform:
        return {
            "pad": (Strum(), Humanize(t_sigma=0.010, v_sigma=3.0)),
            "bass": (Humanize(t_sigma=0.008, v_sigma=3.0),),
            "melody": (Articulate(), Accent(), Humanize()),
            "arp": (Echo(),),
            "perc": (Humanize(t_sigma=0.006, v_sigma=3.0),),
        }
    return {
        "pad": (Perform(hairpin=0.10), Strum(), Humanize(t_sigma=0.010, v_sigma=3.0)),
        "bass": (Perform(hairpin=0.10), Humanize(t_sigma=0.008, v_sigma=3.0)),
        "melody": (Articulate(), Accent(),
                   Perform(hairpin=0.14, contour=0.4, agogic=0.10, lag=0.02), Humanize()),
        "arp": (Perform(hairpin=0.10), Echo()),
        "perc": (Humanize(t_sigma=0.006, v_sigma=3.0),),
    }
