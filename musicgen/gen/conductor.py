"""MusicEngine: the pull-based bar generator (PLANS.md §3, §6.3).

With a MappingTable configured, the engine is lever-driven: set_affect() may
be called at any time; the mapper samples it per bar (density, roughness,
layers, dynamics), per beat (tempo, slew-limited), and per phrase (mode,
cadence policy — quantized to musical boundaries per the iMUSE principle;
set_affect(urgent=True) demotes the phrase quantization to the next barline).
set_override(name, value) pins any Tier-2 parameter while the rest stay live.
request_key(tonic) queues a pivot-chord modulation that rides the next phrase
cadence (urgent=True: the earliest ungenerated bar); wander_phrases enables
an automatic ±1-fifth key walk with a spring back toward home.

With mapper=None the engine runs the M1/M2 static path: params verbatim from
EngineConfig, fixed mode, cadence policies cycling from config.

Chords are generated one bar ahead so generators can see next_chord; the
look-ahead means a lever change during bar N first influences harmony at bar
N+2 (melody/rhythm/dynamics react at N+1). All sequential state lives in
ConductorState (PLANS.md §9).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from musicgen.control import mapping
from musicgen.control.levers import Affect, validate_override
from musicgen.control.mapping import MappingTable
from musicgen.gen import structure
from musicgen.gen.arp import ArpConfig, PATTERNS as ARP_PATTERNS, generate_arp
from musicgen.gen.bass import BassConfig, generate_bass
from musicgen.gen.dramaturg import Dramaturg, DramaturgConfig, Ledger, spend_magnitude
from musicgen.gen.melody import MelodyConfig, MelodyState, Motif, generate_melody, make_motif
from musicgen.gen.motif import MotifLifecycle
from musicgen.gen.signatures import MotifDirector, SignatureMotif
from musicgen.gen.pad import generate_pad
from musicgen.gen.perc import PercConfig, generate_perc
from musicgen.ir import LAYER_NAMES, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.modifiers import apply_chain, default_chains
from musicgen.rng import Seeder
from musicgen.theory.chords import Chord
from musicgen.theory.harmony import CADENCE_TARGET, HarmonyConfig, next_chord
from musicgen.theory.modulation import Pivot, fifths_between, find_pivots
from musicgen.theory.pitch import name_to_midi
from musicgen.theory.scales import Scale
from musicgen.theory.voicing import VoicingConfig

DEFAULT_CADENCE_CYCLE = ("authentic", "half", "deceptive", "authentic")
_MIN_MELODY_RANGE = 6  # floor the dramaturg's melody-range contraction stays above (lint-safe)
_LANDMARK_IMPORTANCE = 0.8  # a signature this important lands as a payoff arrival (§5.5, M17)


@dataclass(frozen=True)
class ModulationPlan:
    """A committed key change: the pivot bar sounds the common chord (still
    analyzed in the old key), the dominant bar sounds V7 of the new key (the
    context scale flips here), and the arrival bar lands the new tonic.
    Aligned plans (cadence_phrase set) ride a phrase cadence, so pre-cadence/
    cadence slots see degrees 5 and 1 as usual; urgent plans ignore phrase
    structure and instead disarm any cadence slot they overlap."""

    target_tonic: int
    mode: str  # mode the pivot was analyzed in (held for the window)
    pivot_bar: int
    dominant_bar: int
    arrival_bar: int
    pivot: Pivot | None  # None: direct modulation (keys share no usable triad)
    cadence_phrase: int | None  # phrase whose cadence this plan realizes

    @property
    def bars(self) -> tuple[int, int, int]:
        return (self.pivot_bar, self.dominant_bar, self.arrival_bar)


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
    wander_phrases: int | None = None  # auto-modulate ±1 fifth every N phrases (None: never)
    cadence_policies: tuple[str, ...] | None = None  # None: tension-driven (mapper) / default cycle (static)
    dramaturg: DramaturgConfig | None = None  # None: off (byte-identical); set: tension-debt ledger (§5.8, M13)
    motif_library: tuple[SignatureMotif, ...] = ()  # authored signature motifs (§5.5, M17); empty: byte-identical
    motif_leniency: float = 0.5  # signature-selection leniency when no dramaturg supplies one (M17)
    mapper: MappingTable | None = None
    chains: dict[str, tuple] = field(default_factory=default_chains)  # {} disables modifiers
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
    motif_lifecycle: MotifLifecycle | None = None  # persistent signature (M15; None when disabled)
    motif_director: MotifDirector | None = None    # authored-signature selection (M17; None when no library)
    pending_signature: Motif | None = None         # the signature to state this phrase, or None
    requested_motif: str = ""                      # the game's request_motif(tag), pending until stated
    ledger: Ledger = field(default_factory=Ledger)  # dramaturg state (unused when disabled)
    last_fill: bool = False
    # key state (home lives in EngineConfig.key_tonic)
    key_tonic: int = 0
    pending_key: tuple[int, bool] | None = None  # (target pc, urgent)
    modulation: ModulationPlan | None = None
    last_key_phrase: int = 0  # phrase of the last arrival (wander spacing)
    # mapper state (slew targets, hysteresis, phrase-quantized picks)
    current_mode: str = "ionian"
    current_tempo: float = 0.0
    current_velocity: float = 0.0
    current_articulation: float = 0.0
    active_layers: tuple[str, ...] = ()
    current_instruments: tuple[tuple[str, str], ...] = ()
    phrase_policies: dict[int, str] = field(default_factory=dict)
    last_emitted_tempo: float | None = None


@dataclass
class BarResult:
    bar: int
    events: list[NoteEvent]      # post-modifier (what plays; dumps show this)
    raw_events: list[NoteEvent]  # pre-modifier IR (grid/melodic lint runs here)
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
        self.state = ConductorState(key_tonic=cfg.key_tonic)
        self.affect = Affect(cfg.valence, cfg.energy, cfg.tension).clamped()
        self.overrides: dict[str, object] = {}
        self._urgent = False
        self.dramaturg = Dramaturg(cfg.dramaturg) if cfg.dramaturg is not None else None
        if cfg.motif_library:
            self.state.motif_director = MotifDirector(library=tuple(cfg.motif_library))

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

    def request_key(self, tonic: int | str, *, urgent: bool = False) -> None:
        """Queue a pivot-chord modulation to a new tonic (pc 0..11 or a note
        name like "Eb"). The change rides the next available phrase cadence:
        a chord diatonic in both keys two bars before the phrase end, V7 of
        the new key on the pre-cadence slot, the new tonic on the cadence
        bar. urgent=True instead starts at the earliest ungenerated bar,
        ignoring phrase alignment. A later request replaces a pending one;
        requesting the current tonic is a no-op. The home key
        (EngineConfig.key_tonic) is what the wander policy springs back to."""
        pc = name_to_midi(f"{tonic}4") % 12 if isinstance(tonic, str) else int(tonic) % 12
        self.state.pending_key = (pc, urgent)

    def request_motif(self, tag: str) -> None:
        """Bind meaning (§5.5, M17): ask the signature director to state the authored
        motif `tag` at the next musically sound phrase boundary — the game's one place
        to contribute authored knowledge. The request forces the tag past the overdue
        gate (it need only land cleanly) and persists until honoured; an unknown tag or
        an empty library is a no-op."""
        self.state.requested_motif = tag

    # --- internals -----------------------------------------------------------

    @property
    def _dramaturg_on(self) -> bool:
        """Active only when a dramaturg exists AND its (hot-swappable) config is
        enabled — so the disabled path is byte-identical to no dramaturg."""
        return self.dramaturg is not None and self.dramaturg.cfg.enabled

    @property
    def _lifecycle_on(self) -> bool:
        """The motif lifecycle needs the dramaturg (its completed statement lands
        on a spend); off ⇒ the disposable per-phrase motif, byte-identical."""
        return self._dramaturg_on and self.dramaturg.cfg.motif_lifecycle

    @property
    def _director_on(self) -> bool:
        """Authored signatures play whenever the library is non-empty (independent of
        the dramaturg — the game's leitmotifs recur regardless of tension); an empty
        library is byte-identical."""
        return self.state.motif_director is not None and bool(self.state.motif_director.library)

    def _policy(self, phrase: int) -> str:
        plan = self.state.modulation
        if plan is not None and phrase == plan.cadence_phrase:
            return "authentic"  # the modulation IS this phrase's cadence
        if "cadence_policy" in self.overrides:
            return str(self.overrides["cadence_policy"])
        if self._dramaturg_on:
            forced = self.state.ledger.phrase_cadence.get(phrase)
            if forced is not None:  # the dramaturg rations/releases the cadence (§5.8)
                return forced
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

        state = self.state
        if state.modulation is None and state.pending_key is not None:
            target, urgent = state.pending_key
            if target == state.key_tonic:
                state.pending_key = None
            elif bar >= 1 and (urgent or pos.pos == pos.bars - 3):
                state.pending_key = None
                state.modulation = self._plan_modulation(bar, target, aligned=not urgent)
        plan = state.modulation
        if plan is not None and bar in plan.bars:
            chord, why = self._modulation_chord(bar, plan, pos)
            if chord is not None:  # None: direct plan, pivot bar walks normally
                state.prev_chord = chord
                return bar, chord, why

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
            suppress_tonic=self._dramaturg_on and self.state.ledger.suppress_tonic,
            tonicize=self._tonicize_target(pos),
        )
        self.state.prev_chord = chord
        return bar, chord, why

    def _tonicize_target(self, pos: structure.PhrasePos) -> int:
        """Secondary-dominant deployment (§5.8, M14): at a sustained withholding
        phrase's pre-cadence, tonicize the deceptive target (vi) with an applied
        dominant — a chromatic push that resolves at the cadence next bar. 0 when
        not withholding, earned dissonance is off, or vi is not a stable target."""
        if not (self._dramaturg_on and self.dramaturg.cfg.earned_dissonance and pos.slot == "pre-cadence"):
            return 0
        ledger = self.state.ledger
        if ledger.phrase_cadence.get(pos.phrase) != "deceptive":
            return 0
        rung = ledger.withholding_phrases // max(1, self.dramaturg.cfg.escalate_phrases)
        if rung < 1:
            return 0
        target = CADENCE_TARGET["deceptive"]
        # only apply a dominant to a stable (maj/min) target — in a dark mode where
        # vi is diminished (e.g. dorian) it is no tonic worth tonicizing. Triad
        # quality is a function of the mode alone, so any tonic reads it.
        if Chord(target).quality(Scale(0, self.state.current_mode)) not in ("maj", "min"):
            return 0
        return target

    def _plan_modulation(self, pivot_bar: int, target: int, *, aligned: bool) -> ModulationPlan:
        """Commit a 3-bar modulation window starting at pivot_bar. The pivot
        is analyzed in the mode current NOW; the mode is held for the window
        (see advance_bar) so the analysis stays true when the bars sound."""
        mode = self.state.current_mode
        pivots = find_pivots(Scale(self.state.key_tonic, mode), Scale(target, mode))
        arrival = pivot_bar + 2
        return ModulationPlan(
            target_tonic=target,
            mode=mode,
            pivot_bar=pivot_bar,
            dominant_bar=pivot_bar + 1,
            arrival_bar=arrival,
            pivot=pivots[0] if pivots else None,
            cadence_phrase=(structure.phrase_position(arrival, self.config.phrase_bars).phrase
                            if aligned else None),
        )

    def _modulation_chord(self, bar: int, plan: ModulationPlan, pos) -> tuple[Chord | None, str]:
        new_scale = Scale(plan.target_tonic, plan.mode)
        if bar == plan.pivot_bar:
            if plan.pivot is None:
                return None, ""
            chord = Chord(plan.pivot.old_degree)  # plain triad: common to both keys by construction
            old_scale = Scale(self.state.key_tonic, plan.mode)
            return chord, (
                f"modulation pivot: {chord.symbol(old_scale)} of {old_scale.name}"
                f" = {Chord(plan.pivot.new_degree).symbol(new_scale)} of {new_scale.name}"
            )
        if bar == plan.dominant_bar:
            tension = structure.effective_tension(self.affect.tension, pos)
            chord = Chord(5, extensions=("7", "9") if tension >= 0.75 else ("7",))
            how = "via pivot" if plan.pivot is not None else "direct, no common chord"
            return chord, f"modulation dominant ({how}): {chord.symbol(new_scale)} of {new_scale.name}"
        return Chord(1), f"modulation arrival: {new_scale.name}"

    def _modulation_note(self, bar: int, plan: ModulationPlan) -> str:
        """Short key-change annotation for the context/dump/MIDI markers
        (ASCII only: SMF meta text is latin-1)."""
        new_scale = Scale(plan.target_tonic, plan.mode)
        if bar == plan.pivot_bar:
            if plan.pivot is None:
                return ""
            return f"pivot = {Chord(plan.pivot.new_degree).symbol(new_scale)} of {new_scale.name}"
        if bar == plan.dominant_bar:
            return f"-> {new_scale.name}" + ("" if plan.pivot is not None else " (direct)")
        return f"arrival: {new_scale.name}"

    def _tonic_for_bar(self, bar: int) -> int:
        """The tonic in force at a bar: flips at the planned dominant bar
        (everything from the new key's V7 onward is analyzed in the new key)."""
        plan = self.state.modulation
        if plan is not None and bar >= plan.dominant_bar:
            return plan.target_tonic
        return self.state.key_tonic

    def _wander_target(self, phrase: int) -> int:
        """±1 fifth per move, leaning sharpwards when bright and flatwards
        when dark, with a spring pulling back toward home beyond ±2 fifths."""
        state, cfg = self.state, self.config
        dist = fifths_between(cfg.key_tonic, state.key_tonic)
        if abs(dist) >= 2:
            step = -1 if dist > 0 else 1
        else:
            v = self.affect.valence
            lean = 0.35 if v > 0.15 else -0.35 if v < -0.15 else 0.0
            step = 1 if self.seeder.stream("wander", phrase).random() < 0.5 + lean else -1
        return (state.key_tonic + 7 * step) % 12

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
            filter_cutoff=float(ov.get("filter_cutoff", mapping.filter_cutoff_target(a, table))),
            reverb_send=float(ov.get("reverb_send", mapping.reverb_send_target(a, table))),
            delay_send=float(ov.get("delay_send", mapping.delay_send_target(a, table))),
            drive=float(ov.get("drive", mapping.drive_target(a, table))),
            stereo_width=float(ov.get("stereo_width", mapping.stereo_width_target(a, table))),
            instruments=state.current_instruments,
        )
        return params, tempo_points

    def _escalate(self, params: MusicalParams, intensify: float) -> MusicalParams:
        """Escalation ladder (§5.8, M13): a sustained withhold keeps building —
        push loudness / agitation / accent up with the escalation level (0..1),
        even as the tonic and top tier stay withheld (a coiled spring, not a
        plateau). Bounded so the intensified params stay in the mapped domain."""
        return replace(
            params,
            velocity_center=min(120, params.velocity_center + round(intensify * 14)),
            note_density=min(1.0, params.note_density + intensify * 0.20),
            accent_depth=params.accent_depth + round(intensify * 4),
        )

    def advance_bar(self) -> BarResult:
        cfg, state = self.config, self.state
        bar = state.bar
        pos = structure.phrase_position(bar, cfg.phrase_bars)

        # Dramaturg (§5.8, M13): decide this phrase's cadence rationing at pos 0,
        # before its cadence chord is generated ahead. Gated — a no-op when off.
        directive = None
        dramaturg_note = ""
        if self._dramaturg_on:
            directive = self.dramaturg.on_bar(state.ledger, self.affect.tension, pos)
            dramaturg_note = directive.note

        # Motif lifecycle (§5.5, M15): a persistent signature advances at each
        # phrase boundary; its completed (faithful) statement is gated on a spend.
        lifecycle_state = ""
        if self._lifecycle_on:
            if state.motif_lifecycle is None:
                state.motif_lifecycle = MotifLifecycle(make_motif(
                    self.seeder.stream("signature"), cfg.params.note_density,
                    cfg.params.roughness, cfg.melody, slots=cfg.meter.slots))
            if pos.pos == 0:
                spend = directive is not None and directive.payoff > 0
                state.motif_lifecycle.advance(spend, pos.phrase)
            lifecycle_state = state.motif_lifecycle.state

        if (cfg.wander_phrases is not None and pos.pos == 0 and bar > 0
                and state.pending_key is None and state.modulation is None
                and pos.phrase - state.last_key_phrase >= cfg.wander_phrases):
            state.pending_key = (self._wander_target(pos.phrase), False)

        # Instrument swaps are phrase-quantized like mode (urgent demotes to
        # the barline) but ignore the modulation window — timbre is harmless
        # to the pivot analysis. Read _urgent before the mode block clears it.
        instr_note = ""
        if cfg.mapper is not None and (pos.pos == 0 or self._urgent):
            pinned_instr = self.overrides.get("instruments")
            picked = (tuple(pinned_instr) if pinned_instr is not None  # type: ignore[arg-type]
                      else mapping.pick_instruments(state.current_instruments, self.affect.energy, cfg.mapper))
            if picked != state.current_instruments:
                changed = [f"{layer}={patch}" for layer, patch in picked
                           if dict(state.current_instruments).get(layer) != patch]
                instr_note = f"instruments: {' '.join(changed)} (energy {self.affect.energy:.2f})"
                state.current_instruments = picked

        # The mode holds while a modulation window is active so the pivot
        # analysis stays true; a deferred urgent flag fires after arrival.
        if cfg.mapper is not None and (pos.pos == 0 or self._urgent) and state.modulation is None:
            pinned = self.overrides.get("mode", cfg.mode)
            state.current_mode = str(pinned) if pinned else mapping.pick_mode(
                state.current_mode, self.affect.valence, cfg.mapper)
            if directive is not None and directive.brighten and not pinned:
                # the dramaturg spend brightens the mode a same-tonic step or two (§5.8, M13)
                state.current_mode = mapping.brighter_mode(state.current_mode, directive.brighten)
            self._urgent = False
        self.scale = Scale(self._tonic_for_bar(bar), state.current_mode)

        if cfg.mapper is not None:
            params, tempo_points = self._mapped_params(bar)
        else:
            params = cfg.params
            tempo_points = [(0.0, params.tempo_bpm)] if bar == 0 else []

        # Dramaturg withholding (§5.8, M13): hold a tier out of the gate set and,
        # on a sustained hold, escalate intensity — both released on the spend.
        if directive is not None:
            if directive.lock_layers:
                params = replace(params, layers=tuple(
                    lyr for lyr in params.layers if lyr not in directive.lock_layers))
            if directive.intensify:
                params = self._escalate(params, directive.intensify)

        while len(state.chord_queue) < 2:
            next_needed = state.chord_queue[-1][0] + 1 if state.chord_queue else bar
            state.chord_queue.append(self._gen_chord(next_needed))
        queued_bar, chord, chord_trace = state.chord_queue.pop(0)
        assert queued_bar == bar, f"chord queue out of sync: {queued_bar} != {bar}"
        upcoming = state.chord_queue[0][1]
        # Chords are symbolic (degrees); the look-ahead must realize the
        # upcoming one against the scale ITS bar will use, not this bar's.
        next_scale = Scale(self._tonic_for_bar(bar + 1), state.current_mode)

        slot = pos.slot if pos.slot in ("pre-cadence", "cadence") else ""
        plan = state.modulation
        mod_note = ""
        if plan is not None and bar in plan.bars:
            mod_note = self._modulation_note(bar, plan)
            if plan.cadence_phrase is None:
                slot = ""  # an urgent window supersedes any cadence slot it overlaps
        ctx = HarmonicContext(
            bar=bar,
            scale=self.scale,
            chord=chord,
            chord_sym=chord.symbol(self.scale),
            chord_pcs=chord.voiced_pcs(self.scale),
            next_chord=upcoming,
            next_chord_sym=upcoming.symbol(next_scale),
            tension=structure.effective_tension(self.affect.tension, pos),
            cadence_slot=slot,
            cadence_policy=self._policy(pos.phrase) if slot else "",
            modulation=mod_note,
            obligation=f"tonicize:{chord.applied}" if chord.applied else "",
        )

        events: list[NoteEvent] = []
        trace = [f"bar {bar + 1} [{pos.slot}] {ctx.chord_sym} ({self.scale.name}): {chord_trace}"]
        if dramaturg_note:
            trace.append(dramaturg_note)
        if instr_note:
            trace.append(instr_note)

        # Authored signatures (§5.5, M17): at a phrase boundary the director weighs
        # each signature's overdue×importance against how well this phrase's harmony
        # hosts it; a selection is stated faithfully across the phrase (below).
        if self._director_on and pos.pos == 0:
            leniency = self.dramaturg.cfg.leniency if self._dramaturg_on else cfg.motif_leniency
            lo = params.register_center - cfg.melody.range_semitones
            hi = params.register_center + cfg.melody.range_semitones
            sel = state.motif_director.select(
                self.scale, ctx.chord_pcs, lo, hi, set(cfg.meter.strong_slots()),
                leniency, near=state.melody.prev_pitch, requested=state.requested_motif)
            if sel is not None:
                sig, _transform, motif_t = sel
                state.pending_signature = motif_t
                state.motif_director.observe(sig.tag, pos.bars)
                if sig.tag == state.requested_motif:
                    state.requested_motif = ""  # the game's request has been honoured
                trace.append(state.motif_director.last)
                # A landmark lands as an *arrival*: force this phrase's cadence to
                # authentic (the M14 cadential suspension/appoggiatura follow, as the
                # overlay keys off phrase_cadence) and cash whatever tension-debt had
                # accrued — the landmark statement *is* the payoff (§5.5/§5.8).
                if sig.importance >= _LANDMARK_IMPORTANCE and self._dramaturg_on:
                    # A landmark lands as an arrival: force this phrase to an authentic
                    # cadence (the M14 cadential suspension/appoggiatura follow) and cash
                    # the accrued *debt* — the payoff. It deliberately leaves the per-bar
                    # withholding signals (pedal, tonic-circling) untouched, so they run
                    # on undisturbed to the now-authentic cadence and terminate cleanly;
                    # if tension stays high the buildup simply resumes after the arrival.
                    led = state.ledger
                    led.last_spend = spend_magnitude(led, self.dramaturg.cfg)
                    led.bars_since_authentic = led.deceptions = 0
                    led.phrase_cadence[pos.phrase] = "authentic"
                    trace.append(f"landmark '{sig.tag}' spends the ledger (payoff {led.last_spend:.2f})")
            else:
                state.pending_signature = None
                state.motif_director.age(pos.bars)
        layers = params.layers
        if "pad" in layers:
            pad_events, voicing, pad_trace = generate_pad(
                ctx, cfg.meter, params, state.prev_voicing, cfg.voicing,
                suspend=directive is not None and directive.suspend,
                appoggiatura=directive is not None and directive.appoggiatura)
            events.extend(pad_events)
            state.prev_voicing = voicing
            trace.append(pad_trace)
        if "bass" in layers:
            bass_events, root, bass_trace = generate_bass(
                ctx, cfg.meter, params, state.prev_bass_root,
                next_bass_pc=upcoming.bass_pc(next_scale),
                cfg=cfg.bass,
                rng=self.seeder.stream("bass", bar),
                pedal_degree=directive.pedal if directive is not None else 0,
            )
            events.extend(bass_events)
            state.prev_bass_root = root
            trace.append(bass_trace)
        if "melody" in layers:
            mel_cfg = cfg.melody
            if directive is not None and directive.register_cap:
                # contract the melody's ambit while withholding; it opens back up
                # on the spend (register_cap is 0 then) — the audible bloom
                mel_cfg = replace(cfg.melody, range_semitones=max(
                    _MIN_MELODY_RANGE, cfg.melody.range_semitones - directive.register_cap))
            # An authored signature (if the director launched one this phrase) is
            # stated faithfully — reusing the M15 completed path; otherwise the
            # generated lifecycle motif (or the disposable per-phrase motif).
            sig_motif = state.pending_signature if self._director_on else None
            mel_motif = sig_motif if sig_motif is not None else self._motif(pos.phrase, params)
            mel_lifecycle = "completed" if sig_motif is not None else lifecycle_state
            mel_events, mel_state, mel_trace = generate_melody(
                ctx, cfg.meter, params, pos, mel_motif,
                state.melody, mel_cfg, self.seeder.stream("melody", bar),
                lifecycle=mel_lifecycle,
            )
            events.extend(mel_events)
            state.melody = mel_state
            tag = " │ signature" if sig_motif is not None else (f" │ motif {lifecycle_state}" if lifecycle_state else "")
            trace.append(mel_trace + tag)
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

        events.sort(key=lambda e: (e.start, e.pitch))  # canonical raw-IR order
        final: list[NoteEvent] = []
        for layer in LAYER_NAMES:
            layer_events = [e for e in events if e.layer == layer]
            if not layer_events:
                continue
            chain = cfg.chains.get(layer, ())
            if chain:
                layer_events = apply_chain(
                    chain, layer_events, ctx, cfg.meter, params,
                    self.seeder.stream("mod", layer, bar),
                )
            final.extend(layer_events)
        final.sort(key=lambda e: (e.start, e.pitch))

        if plan is not None and bar == plan.arrival_bar:
            state.key_tonic = plan.target_tonic
            state.modulation = None
            state.last_key_phrase = pos.phrase

        state.bar += 1
        return BarResult(bar, final, events, ctx, params, self.affect.as_tuple(), tempo_points, trace)

    def _motif(self, phrase: int, params: MusicalParams) -> Motif:
        # With the lifecycle on, every phrase develops the one persistent signature
        # (created in advance_bar); otherwise a fresh disposable motif per phrase.
        if self._lifecycle_on and self.state.motif_lifecycle is not None:
            return self.state.motif_lifecycle.motif
        if phrase not in self.state.motifs:
            self.state.motifs[phrase] = make_motif(
                self.seeder.stream("motif", phrase),
                params.note_density, params.roughness, self.config.melody,
                slots=self.config.meter.slots,
            )
        return self.state.motifs[phrase]
