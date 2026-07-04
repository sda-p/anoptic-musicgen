"""MusicEngine: the pull-based bar generator (PLANS.md §3).

M1 scope: static Tier-2 params and static affect (tension/valence) from
EngineConfig — the affect->params mapper arrives in M3. Chords are generated
one bar ahead so generators can see next_chord (bass approach targets); this
is the same one-bar look-ahead the live driver (M5) will use.

All sequential state lives in ConductorState (PLANS.md §9): everything else
is a pure function of (seed, bar, config).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicgen.gen import structure
from musicgen.gen.bass import BassConfig, generate_bass
from musicgen.gen.pad import generate_pad
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.rng import Seeder
from musicgen.theory.chords import Chord
from musicgen.theory.harmony import HarmonyConfig, next_chord
from musicgen.theory.scales import Scale
from musicgen.theory.voicing import VoicingConfig


@dataclass
class EngineConfig:
    meter: Meter = field(default_factory=Meter)
    params: MusicalParams = field(default_factory=MusicalParams)
    key_tonic: int = 0
    mode: str = "ionian"
    valence: float = 0.3   # static affect until the M3 mapper
    tension: float = 0.45
    phrase_bars: int = 8
    cadence_policies: tuple[str, ...] = ("authentic", "half", "deceptive", "authentic")
    harmony: HarmonyConfig = field(default_factory=HarmonyConfig)
    voicing: VoicingConfig = field(default_factory=VoicingConfig)
    bass: BassConfig = field(default_factory=BassConfig)


@dataclass
class ConductorState:
    """All sequential state. chord_queue holds (bar, chord, trace) generated
    ahead of playback; the walk's continuity lives in prev_chord."""

    bar: int = 0
    prev_chord: Chord | None = None
    chord_queue: list[tuple[int, Chord, str]] = field(default_factory=list)
    prev_voicing: tuple[int, ...] | None = None
    prev_bass_root: int | None = None


@dataclass
class BarResult:
    bar: int
    events: list[NoteEvent]
    context: HarmonicContext
    params: MusicalParams
    trace: list[str]


class MusicEngine:
    def __init__(self, seed: int = 42, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.seeder = Seeder(seed)
        self.state = ConductorState()
        self.scale = Scale(self.config.key_tonic, self.config.mode)

    def _policy(self, phrase: int) -> str:
        policies = self.config.cadence_policies
        return policies[phrase % len(policies)]

    def _gen_chord(self, bar: int) -> tuple[int, Chord, str]:
        cfg = self.config
        pos = structure.phrase_position(bar, cfg.phrase_bars)
        chord, why = next_chord(
            prev=self.state.prev_chord,
            slot=pos.slot,
            cadence_policy=self._policy(pos.phrase),
            tension=structure.effective_tension(cfg.tension, pos),
            valence=cfg.valence,
            mode=cfg.mode,
            phrase_start=pos.pos == 0,
            piece_start=bar == 0,
            cfg=cfg.harmony,
            rng=self.seeder.stream("harmony", bar),
        )
        self.state.prev_chord = chord
        return bar, chord, why

    def advance_bar(self) -> BarResult:
        cfg, state = self.config, self.state
        bar = state.bar
        while len(state.chord_queue) < 2:
            next_needed = state.chord_queue[-1][0] + 1 if state.chord_queue else bar
            state.chord_queue.append(self._gen_chord(next_needed))
        queued_bar, chord, chord_trace = state.chord_queue.pop(0)
        assert queued_bar == bar, f"chord queue out of sync: {queued_bar} != {bar}"
        upcoming = state.chord_queue[0][1]

        pos = structure.phrase_position(bar, cfg.phrase_bars)
        slot = pos.slot if pos.slot in ("pre-cadence", "cadence") else ""
        ctx = HarmonicContext(
            bar=bar,
            scale=self.scale,
            chord=chord,
            chord_sym=chord.symbol(self.scale),
            chord_pcs=chord.voiced_pcs(self.scale),
            next_chord=upcoming,
            next_chord_sym=upcoming.symbol(self.scale),
            tension=structure.effective_tension(cfg.tension, pos),
            cadence_slot=slot,
            cadence_policy=self._policy(pos.phrase) if slot else "",
        )

        events: list[NoteEvent] = []
        trace = [f"bar {bar + 1} [{pos.slot}] {ctx.chord_sym}: {chord_trace}"]
        if "pad" in cfg.params.layers:
            pad_events, voicing, pad_trace = generate_pad(ctx, cfg.meter, cfg.params, state.prev_voicing, cfg.voicing)
            events.extend(pad_events)
            state.prev_voicing = voicing
            trace.append(pad_trace)
        if "bass" in cfg.params.layers:
            bass_events, root, bass_trace = generate_bass(
                ctx, cfg.meter, cfg.params, state.prev_bass_root,
                next_bass_pc=upcoming.bass_pc(self.scale),
                cfg=cfg.bass,
                rng=self.seeder.stream("bass", bar),
            )
            events.extend(bass_events)
            state.prev_bass_root = root
            trace.append(bass_trace)

        state.bar += 1
        return BarResult(bar, events, ctx, cfg.params, trace)
