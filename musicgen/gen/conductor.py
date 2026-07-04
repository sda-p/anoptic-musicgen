"""MusicEngine: the pull-based bar generator (PLANS.md §3, §6.3).

With a MappingTable configured, the engine is lever-driven: set_affect() may
be called at any time; the mapper samples it per bar (density, roughness,
layers, dynamics), per beat (tempo, slew-limited), and per phrase (mode,
cadence policy — quantized to musical boundaries per the iMUSE principle;
set_affect(urgent=True) demotes the phrase quantization to the next barline).
set_override(name, value) pins any Tier-2 parameter while the rest stay live.

With mapper=None the engine runs the M1/M2 static path: params verbatim from
EngineConfig, fixed mode, cadence policies cycling from config.

Chords are generated one bar ahead so generators can see next_chord; the
look-ahead means a lever change during bar N first influences harmony at bar
N+2 (melody/rhythm/dynamics react at N+1). All sequential state lives in
ConductorState (PLANS.md §9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicgen.control import mapping
from musicgen.control.levers import Affect, validate_override
from musicgen.control.mapping import MappingTable
from musicgen.gen import structure
from musicgen.gen.arp import ArpConfig, PATTERNS as ARP_PATTERNS, generate_arp
from musicgen.gen.bass import BassConfig, generate_bass
from musicgen.gen.melody import MelodyConfig, MelodyState, Motif, generate_melody, make_motif
from musicgen.gen.pad import generate_pad
from musicgen.gen.perc import PercConfig, generate_perc
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.rng import Seeder
from musicgen.theory.chords import Chord
from musicgen.theory.harmony import HarmonyConfig, next_chord
from musicgen.theory.scales import Scale
from musicgen.theory.voicing import VoicingConfig

DEFAULT_CADENCE_CYCLE = ("authentic", "half", "deceptive", "authentic")


@dataclass
class EngineConfig:
    meter: Meter = field(default_factory=Meter)
    params: MusicalParams = field(default_factory=MusicalParams)  # static path only
    key_tonic: int = 0
    mode: str | None = None  # None: valence-driven (mapper) / ionian (static); set: pinned
    valence: float = 0.3     # initial affect
    energy: float = 0.5
    tension: float = 0.45
    phrase_bars: int = 8
    cadence_policies: tuple[str, ...] | None = None  # None: tension-driven (mapper) / default cycle (static)
    mapper: MappingTable | None = None
    harmony: HarmonyConfig = field(default_factory=HarmonyConfig)
    voicing: VoicingConfig = field(default_factory=VoicingConfig)
    bass: BassConfig = field(default_factory=BassConfig)
    melody: MelodyConfig = field(default_factory=MelodyConfig)
    arp: ArpConfig = field(default_factory=ArpConfig)
    perc: PercConfig = field(default_factory=PercConfig)


@dataclass
class ConductorState:
    """All sequential state. chord_queue holds (bar, chord, trace) generated
    ahead of playback; motifs is a re-derivable per-phrase cache."""

    bar: int = 0
    prev_chord: Chord | None = None
    chord_queue: list[tuple[int, Chord, str]] = field(default_factory=list)
    prev_voicing: tuple[int, ...] | None = None
    prev_bass_root: int | None = None
    melody: MelodyState = field(default_factory=MelodyState)
    motifs: dict[int, Motif] = field(default_factory=dict)
    last_fill: bool = False
    # mapper state (slew targets, hysteresis, phrase-quantized picks)
    current_mode: str = "ionian"
    current_tempo: float = 0.0
    current_velocity: float = 0.0
    current_articulation: float = 0.0
    active_layers: tuple[str, ...] = ()
    phrase_policies: dict[int, str] = field(default_factory=dict)
    last_emitted_tempo: float | None = None


@dataclass
class BarResult:
    bar: int
    events: list[NoteEvent]
    context: HarmonicContext
    params: MusicalParams
    affect: tuple[float, float, float]
    tempo_points: list[tuple[float, float]]  # (absolute beat, BPM)
    trace: list[str]


class MusicEngine:
    def __init__(self, seed: int = 42, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        cfg = self.config
        self.seeder = Seeder(seed)
        self.state = ConductorState()
        self.affect = Affect(cfg.valence, cfg.energy, cfg.tension).clamped()
        self.overrides: dict[str, object] = {}
        self._urgent = False

        if cfg.mapper is not None:
            self.state.current_mode = cfg.mode or mapping.nearest_mode(self.affect.valence)
            # Slew state (tempo/velocity/articulation/layers) initializes
            # lazily on the first bar, snapping to the affect active THEN —
            # not to construction-time affect (demos set levers in between).
        else:
            self.state.current_mode = cfg.mode or "ionian"
            self.state.current_tempo = cfg.params.tempo_bpm
        self.scale = Scale(cfg.key_tonic, self.state.current_mode)

    # --- lever API -----------------------------------------------------------

    def set_affect(
        self,
        *,
        valence: float | None = None,
        energy: float | None = None,
        tension: float | None = None,
        urgent: bool = False,
    ) -> None:
        """Update affect targets; sampled at musical boundaries. urgent=True
        demotes phrase-quantized changes (mode) to the next barline."""
        self.affect = self.affect.merged(valence, energy, tension)
        if urgent:
            self._urgent = True

    def set_override(self, name: str, value: object) -> None:
        validate_override(name)
        self.overrides[name] = value

    def clear_override(self, name: str) -> None:
        self.overrides.pop(name, None)

    # --- internals -----------------------------------------------------------

    def _policy(self, phrase: int) -> str:
        if "cadence_policy" in self.overrides:
            return str(self.overrides["cadence_policy"])
        if self.config.cadence_policies is not None:
            cycle = self.config.cadence_policies
            return cycle[phrase % len(cycle)]
        if self.config.mapper is None:
            return DEFAULT_CADENCE_CYCLE[phrase % len(DEFAULT_CADENCE_CYCLE)]
        if phrase not in self.state.phrase_policies:  # sampled once per phrase
            self.state.phrase_policies[phrase] = mapping.pick_cadence_policy(
                self.affect.tension, self.config.mapper)
        return self.state.phrase_policies[phrase]

    def _harmonic_rhythm(self) -> float:
        if "harmonic_rhythm" in self.overrides:
            return float(self.overrides["harmonic_rhythm"])  # type: ignore[arg-type]
        if self.config.mapper is not None:
            return mapping.harmonic_rhythm_target(self.affect, self.config.mapper)
        return self.config.params.harmonic_rhythm

    def _gen_chord(self, bar: int) -> tuple[int, Chord, str]:
        cfg = self.config
        pos = structure.phrase_position(bar, cfg.phrase_bars)
        held = (
            self._harmonic_rhythm() == 0.5
            and pos.slot == "free"
            and bar % 2 == 1
            and self.state.prev_chord is not None
        )
        if held:
            return bar, self.state.prev_chord, "held (slow harmonic rhythm)"
        chord, why = next_chord(
            prev=self.state.prev_chord,
            slot=pos.slot,
            cadence_policy=self._policy(pos.phrase),
            tension=structure.effective_tension(self.affect.tension, pos),
            valence=self.affect.valence,
            mode=self.state.current_mode,
            phrase_start=pos.pos == 0,
            piece_start=bar == 0,
            cfg=cfg.harmony,
            rng=self.seeder.stream("harmony", bar),
        )
        self.state.prev_chord = chord
        return bar, chord, why

    def _mapped_params(self, bar: int) -> tuple[MusicalParams, list[tuple[float, float]]]:
        cfg, state, a, ov = self.config, self.state, self.affect, self.overrides
        table = cfg.mapper
        assert table is not None

        if state.bar == 0 and not state.chord_queue:  # first bar: snap, don't slew
            state.current_tempo = float(ov.get("tempo_bpm", mapping.tempo_target(a, table)))
            state.current_velocity = float(ov.get("velocity_center", mapping.velocity_target(a, table)))
            state.current_articulation = float(ov.get("articulation", mapping.articulation_target(a, table)))
            state.active_layers = mapping.gate_layers((), a.energy, table)

        state.current_velocity = mapping.slew(
            state.current_velocity,
            float(ov.get("velocity_center", mapping.velocity_target(a, table))),
            table.velocity_slew_per_bar,
        )
        state.current_articulation = mapping.slew(
            state.current_articulation,
            float(ov.get("articulation", mapping.articulation_target(a, table))),
            table.articulation_slew_per_bar,
        )
        if "layers" in ov:
            state.active_layers = tuple(ov["layers"])  # type: ignore[arg-type]
        else:
            state.active_layers = mapping.gate_layers(state.active_layers, a.energy, table)

        tempo_goal = float(ov.get("tempo_bpm", mapping.tempo_target(a, table)))
        tempo_points: list[tuple[float, float]] = []
        beats = int(cfg.meter.bar_quarters)
        for beat in range(max(1, beats)):
            state.current_tempo = mapping.slew(state.current_tempo, tempo_goal, table.tempo_slew_per_beat)
            changed = state.last_emitted_tempo is None or abs(state.current_tempo - state.last_emitted_tempo) > 0.01
            if changed:
                tempo_points.append((bar * cfg.meter.bar_quarters + beat, round(state.current_tempo, 2)))
                state.last_emitted_tempo = state.current_tempo

        params = MusicalParams(
            tempo_bpm=round(state.current_tempo, 2),
            note_density=float(ov.get("note_density", mapping.density_target(a, table))),
            roughness=float(ov.get("roughness", mapping.roughness_target(a, table))),
            articulation=round(state.current_articulation, 3),
            velocity_center=int(round(state.current_velocity)),
            accent_depth=int(ov.get("accent_depth", mapping.accent_target(a, table))),
            register_center=int(ov.get("register_center", mapping.register_target(a, table))),
            layers=state.active_layers,
            harmonic_rhythm=self._harmonic_rhythm(),
            dissonance_budget=a.tension,
            cadence_policy=self._policy(structure.phrase_position(bar, cfg.phrase_bars).phrase),
        )
        return params, tempo_points

    def advance_bar(self) -> BarResult:
        cfg, state = self.config, self.state
        bar = state.bar
        pos = structure.phrase_position(bar, cfg.phrase_bars)

        if cfg.mapper is not None and (pos.pos == 0 or self._urgent):
            pinned = self.overrides.get("mode", cfg.mode)
            state.current_mode = str(pinned) if pinned else mapping.pick_mode(
                state.current_mode, self.affect.valence, cfg.mapper)
            self._urgent = False
        self.scale = Scale(cfg.key_tonic, state.current_mode)

        if cfg.mapper is not None:
            params, tempo_points = self._mapped_params(bar)
        else:
            params = cfg.params
            tempo_points = [(0.0, params.tempo_bpm)] if bar == 0 else []

        while len(state.chord_queue) < 2:
            next_needed = state.chord_queue[-1][0] + 1 if state.chord_queue else bar
            state.chord_queue.append(self._gen_chord(next_needed))
        queued_bar, chord, chord_trace = state.chord_queue.pop(0)
        assert queued_bar == bar, f"chord queue out of sync: {queued_bar} != {bar}"
        upcoming = state.chord_queue[0][1]

        slot = pos.slot if pos.slot in ("pre-cadence", "cadence") else ""
        ctx = HarmonicContext(
            bar=bar,
            scale=self.scale,
            chord=chord,
            chord_sym=chord.symbol(self.scale),
            chord_pcs=chord.voiced_pcs(self.scale),
            next_chord=upcoming,
            next_chord_sym=upcoming.symbol(self.scale),
            tension=structure.effective_tension(self.affect.tension, pos),
            cadence_slot=slot,
            cadence_policy=self._policy(pos.phrase) if slot else "",
        )

        events: list[NoteEvent] = []
        trace = [f"bar {bar + 1} [{pos.slot}] {ctx.chord_sym} ({state.current_mode}): {chord_trace}"]
        layers = params.layers
        if "pad" in layers:
            pad_events, voicing, pad_trace = generate_pad(ctx, cfg.meter, params, state.prev_voicing, cfg.voicing)
            events.extend(pad_events)
            state.prev_voicing = voicing
            trace.append(pad_trace)
        if "bass" in layers:
            bass_events, root, bass_trace = generate_bass(
                ctx, cfg.meter, params, state.prev_bass_root,
                next_bass_pc=upcoming.bass_pc(self.scale),
                cfg=cfg.bass,
                rng=self.seeder.stream("bass", bar),
            )
            events.extend(bass_events)
            state.prev_bass_root = root
            trace.append(bass_trace)
        if "melody" in layers:
            mel_events, mel_state, mel_trace = generate_melody(
                ctx, cfg.meter, params, pos, self._motif(pos.phrase, params),
                state.melody, cfg.melody, self.seeder.stream("melody", bar),
            )
            events.extend(mel_events)
            state.melody = mel_state
            trace.append(mel_trace)
        if "arp" in layers:
            pattern_rng = self.seeder.stream("arp-pattern", pos.phrase)
            arp_events, arp_trace = generate_arp(
                ctx, cfg.meter, params, pattern_rng.choice(ARP_PATTERNS),
                cfg.arp, self.seeder.stream("arp", bar),
            )
            events.extend(arp_events)
            trace.append(arp_trace)
        if "perc" in layers:
            perc_events, fill, perc_trace = generate_perc(
                ctx, cfg.meter, params, pos, state.last_fill,
                cfg.perc, self.seeder.stream("perc", bar),
            )
            events.extend(perc_events)
            state.last_fill = fill
            trace.append(perc_trace)

        state.bar += 1
        return BarResult(bar, events, ctx, params, self.affect.as_tuple(), tempo_points, trace)

    def _motif(self, phrase: int, params: MusicalParams) -> Motif:
        if phrase not in self.state.motifs:
            self.state.motifs[phrase] = make_motif(
                self.seeder.stream("motif", phrase),
                params.note_density, params.roughness, self.config.melody,
            )
        return self.state.motifs[phrase]
