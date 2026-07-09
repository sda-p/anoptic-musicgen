"""PlaygroundState: owns the live session — one engine template + one realtime
player — and is the single authority for the server-side mirror of control
state (affect, pinned overrides, the live MappingTable, seed, console config,
loaded sample, jump-to-bar target, and the affect-automation track).

Every control method updates the mirror AND, if a player is running, forwards
to its thread-safe command queue (applied at a bar edge on the generation
thread). Rebuilding the engine on start re-applies the whole mirror, so edits
(a tuned heuristic, a pinned param) survive stop/start — the natural dev loop.
"""
from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

from musicgen.control.automation import affect_at
from musicgen.control.levers import validate_override
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.modifiers import default_chains
from musicgen.playground.telemetry import to_jsonable

# the performed/craft-surface mirror (REFINEMENT_PLAN waves A: A1 shaping+rit,
# A2 groove, A3 counterpoint, A4 apex): all off by default = byte-identical
# output; the panel toggles them live. cadence_rit is the depth the rit knob
# applies WHEN shaping is on (shaping off forces it to 0).
_PERFORM_DEFAULTS = {"shaping": False, "cadence_rit": 0.025,
                     "phrase_groove": False, "plan_apex": False,
                     "counterpoint": False}

# a tighter look-ahead than the demos: generation is µs-fast, so a small buffer
# keeps live lever moves audible within a beat instead of the default 2.5 s
_LEAD_SECONDS = 0.6
_MAX_SEEK_BARS = 4096  # jump-to-bar warms one bar at a time; keep the fast-forward bounded

_AFFECT_RANGE = {"valence": (-1.0, 1.0), "energy": (0.0, 1.0), "tension": (0.0, 1.0)}
_INT_OVERRIDES = {"velocity_center", "accent_depth", "register_center"}

# a gentle starter arc so the automation timeline opens with something to grab
# (disabled by default — the XY-pad drives affect until you enable it)
_DEFAULT_AUTOMATION = [
    {"bar": 0, "valence": 0.2, "energy": 0.25, "tension": 0.2},
    {"bar": 16, "valence": 0.5, "energy": 0.85, "tension": 0.7},
]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _coerce_override(name: str, value):
    """JSON values -> the exact types the engine expects for each override."""
    if name == "layers":
        return tuple(value)
    if name == "instruments":
        return tuple((layer, patch) for layer, patch in value)
    if name in ("mode", "cadence_policy"):
        return str(value)
    if name in _INT_OVERRIDES:
        return int(value)
    return float(value)


def _match_type(current, value):
    """Coerce an incoming JSON value to the structural type of a MappingTable
    field (scalar float/int, or nested tuple like tempo_range / layer_gates)."""
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, tuple):
        return tuple(_match_type(c, v) for c, v in zip(current, value))
    return value


class PlaygroundState:
    def __init__(self, seed: int = 42, mapper: MappingTable | None = None) -> None:
        self.seed = seed
        self.mapper = mapper or MappingTable()
        # EngineConfig's own affect defaults, mirrored so a rebuild resumes here
        self.affect = {"valence": 0.3, "energy": 0.5, "tension": 0.45}
        self.pinned: dict[str, object] = {}
        self.slots: dict[str, MappingTable] = {}  # A/B mapping snapshots
        self._console_config = None  # ConsoleConfig; lazy (pulls signalflow)
        self._sample = {"name": "", "root": 72}  # loaded sampler file (name for display)
        self._start_bar = 0  # jump-to-bar: where the next start() begins
        self.automation = {"enabled": False, "loop_bars": 0,
                           "points": [dict(p) for p in _DEFAULT_AUTOMATION]}
        self.exporting = False  # an offline bounce owns the one graph; blocks start()
        # dramaturg present but OFF by default -> byte-identical to no dramaturg (§5.8, M13)
        self._dramaturg_config = DramaturgConfig(enabled=False)
        # performed surface (wave A) — off by default, hot-swappable like the dramaturg
        self._perform = dict(_PERFORM_DEFAULTS)
        self.player = None

    # ------------------------------------------------------------- lifecycle
    def _build_engine(self) -> MusicEngine:
        p = self._perform
        cfg = EngineConfig(mapper=self.mapper, valence=self.affect["valence"],
                           energy=self.affect["energy"], tension=self.affect["tension"],
                           dramaturg=self._dramaturg_config,
                           chains=default_chains(perform=bool(p["shaping"])),
                           cadence_rit=float(p["cadence_rit"]) if p["shaping"] else 0.0,
                           phrase_groove=bool(p["phrase_groove"]),
                           melody=MelodyConfig(plan_apex=bool(p["plan_apex"]),
                                               counterpoint=bool(p["counterpoint"])))
        engine = MusicEngine(seed=self.seed, config=cfg)
        for name, value in self.pinned.items():
            engine.set_override(name, value)
        return engine

    def _cc(self):
        if self._console_config is None:
            from musicgen.synth.console import ConsoleConfig
            self._console_config = ConsoleConfig(enable_meter=True)
        return self._console_config

    def _numeric_console_names(self) -> set:
        """ConsoleConfig fields that are plain numbers — the only ones the editor
        may set (never coerce str/bool fields like sample_path/enable_meter)."""
        cc = self._cc()
        return {f.name for f in fields(type(cc))
                if isinstance(getattr(cc, f.name), (int, float)) and not isinstance(getattr(cc, f.name), bool)}

    def _console_values(self) -> dict:
        cc = self._cc()
        return {n: getattr(cc, n) for n in self._numeric_console_names()}

    def start(self, on_bar) -> None:
        if self.player is not None:
            return
        if self.exporting:
            raise RuntimeError("an export is in progress — try again once it finishes")
        from musicgen.synth.render import RealtimeSynthPlayer

        player = RealtimeSynthPlayer(
            self._build_engine(), on_bar=on_bar,
            lead_seconds=_LEAD_SECONDS,
            config=self._cc(), start_bar=self._start_bar,
            automation=self._player_automation(),
        )
        player.start()
        self.player = player

    def stop(self) -> None:
        player, self.player = self.player, None
        if player is not None:
            player.stop()

    def _restart(self, on_bar=None) -> None:
        """Rebuild the running player from the current mirror (used by seek and
        preset load, which change engine-construction inputs like seed/start_bar
        that can't be hot-applied). No-op when stopped."""
        if self.player is None:
            return
        cb = on_bar or self.player.on_bar
        self.stop()
        self.start(cb)

    @property
    def running(self) -> bool:
        return self.player is not None

    def level(self) -> float:
        player = self.player
        console = player.console if player is not None else None  # capture once: the
        if console is None:                                       # player thread nulls
            return 0.0                                            # console mid-rebuild
        try:
            return console.level()
        except Exception:  # noqa: BLE001
            return 0.0

    def cpu(self) -> float:
        player = self.player
        if player is None or player.console is None:
            return 0.0
        try:
            return float(player.console.graph.cpu_usage)
        except Exception:  # noqa: BLE001
            return 0.0

    # --------------------------------------------------------------- control
    def set_affect(self, valence=None, energy=None, tension=None, urgent: bool = False) -> None:
        for key, val in (("valence", valence), ("energy", energy), ("tension", tension)):
            if val is not None:
                self.affect[key] = _clamp(float(val), *_AFFECT_RANGE[key])
        if self.player is not None:
            # forward the clamped mirror values, not the raw input
            kw = {k: self.affect[k] for k, v in (("valence", valence), ("energy", energy),
                                                 ("tension", tension)) if v is not None}
            self.player.set_affect(urgent=urgent, **kw)

    def set_override(self, name: str, value) -> None:
        validate_override(name)
        coerced = _coerce_override(name, value)
        self.pinned[name] = coerced
        if self.player is not None:
            self.player.set_override(name, coerced)

    def clear_override(self, name: str) -> None:
        self.pinned.pop(name, None)
        if self.player is not None:
            self.player.clear_override(name)

    def request_key(self, tonic, urgent: bool = False) -> None:
        if self.player is not None:
            self.player.request_key(tonic, urgent=urgent)

    def set_mapping_field(self, field: str, value) -> None:
        known = {f.name: getattr(self.mapper, f.name) for f in fields(MappingTable)}
        if field not in known:
            raise KeyError(f"unknown mapping field {field!r}")
        self.mapper = replace(self.mapper, **{field: _match_type(known[field], value)})
        if self.player is not None:
            self.player.set_mapping(self.mapper)

    def reset_mapping(self) -> None:
        self.mapper = MappingTable()
        if self.player is not None:
            self.player.set_mapping(self.mapper)

    def store_mapping(self, slot: str) -> None:
        self.slots[slot] = self.mapper  # frozen table; edits replace, never mutate

    def recall_mapping(self, slot: str) -> None:
        if slot in self.slots:
            self.mapper = self.slots[slot]
            if self.player is not None:
                self.player.set_mapping(self.mapper)

    def set_console_fields(self, updates: dict) -> None:
        """Apply numeric ConsoleConfig edits — a STRUCTURAL change that rebuilds
        the console (brief gap). Only numeric fields are exposed to the editor."""
        cc = self._cc()
        numeric = self._numeric_console_names()  # ignore non-numeric fields, don't float() them
        applied = {name: float(value) for name, value in updates.items() if name in numeric}
        if not applied:
            return
        self._console_config = replace(cc, **applied)
        if self.player is not None:
            self.player.set_console(self._console_config)

    def set_dramaturg_fields(self, updates: dict) -> None:
        """Hot-swap dramaturg knobs (leniency etc. + the enable toggle) live —
        applied at the next bar edge on the generation thread, ledger preserved.
        No rebuild (unlike the console)."""
        known = {f.name: getattr(self._dramaturg_config, f.name) for f in fields(DramaturgConfig)}
        applied = {k: _match_type(known[k], v) for k, v in updates.items() if k in known}
        if not applied:
            return
        self._dramaturg_config = replace(self._dramaturg_config, **applied)
        if self.player is not None:
            self.player.set_dramaturg(self._dramaturg_config)

    def set_perform_fields(self, updates: dict) -> None:
        """Hot-swap the performed-surface knobs (REFINEMENT_PLAN wave A: A1
        shaping + cadence rit, A2 phrase groove, A4 apex planning) — applied at
        the next bar edge on the generation thread, like the dramaturg; no
        rebuild. Off across the board is byte-identical."""
        applied = {k: (float(v) if k == "cadence_rit" else bool(v))
                   for k, v in updates.items() if k in self._perform}
        if not applied:
            return
        self._perform.update(applied)
        if self.player is not None:
            self.player.set_perform(dict(self._perform))

    def set_sample(self, path: str, root_midi: int) -> None:
        """Load an uploaded audio file into the sampler ("keys") voice — a
        structural change that rebuilds the console."""
        self._console_config = replace(self._cc(), sample_path=str(path), sample_root_midi=int(root_midi))
        self._sample = {"name": Path(path).name, "root": int(root_midi)}
        if self.player is not None:
            self.player.set_console(self._console_config)

    def clear_sample(self) -> None:
        self._console_config = replace(self._cc(), sample_path="", sample_root_midi=72)
        self._sample = {"name": "", "root": 72}
        if self.player is not None:
            self.player.set_console(self._console_config)

    def reseed(self, seed) -> None:
        self.seed = int(seed)  # takes effect on the next start()

    # ---------------------------------------------------------- automation
    def _automation_curve(self):
        """Mirror -> the (bar, {v,e,t}) breakpoint form control.automation wants."""
        pts = sorted(self.automation["points"], key=lambda p: int(p["bar"]))
        return [(int(p["bar"]), {"valence": float(p["valence"]),
                                 "energy": float(p["energy"]),
                                 "tension": float(p["tension"])}) for p in pts]

    def _player_automation(self):
        if not (self.automation["enabled"] and self.automation["points"]):
            return None
        return (self._automation_curve(), int(self.automation["loop_bars"]))

    def set_automation(self, enabled=None, loop_bars=None, points=None) -> None:
        # build/validate the new points first, so a malformed list raises before
        # any of the three fields is mutated (all-or-nothing)
        new_points = None
        if points is not None:
            new_points = [{
                "bar": max(0, int(p["bar"])),
                "valence": _clamp(float(p["valence"]), *_AFFECT_RANGE["valence"]),
                "energy": _clamp(float(p["energy"]), *_AFFECT_RANGE["energy"]),
                "tension": _clamp(float(p["tension"]), *_AFFECT_RANGE["tension"]),
            } for p in points]
        if enabled is not None:
            self.automation["enabled"] = bool(enabled)
        if loop_bars is not None:
            self.automation["loop_bars"] = max(0, int(loop_bars))
        if new_points is not None:
            self.automation["points"] = new_points
        if self.player is not None:
            auto = self._player_automation()
            self.player.set_automation(auto[0] if auto else None,
                                       int(self.automation["loop_bars"]))

    def seek(self, bar) -> None:
        """Jump-to-bar: play resumes from this (deterministic) bar. Restarts a
        running player, which warms the engine there with no audio."""
        self._start_bar = max(0, min(int(bar), _MAX_SEEK_BARS))
        self._restart()

    # ------------------------------------------------------- sessions / export
    def _mapper_from_dict(self, data: dict) -> MappingTable:
        base = MappingTable()
        updates = {f.name: _match_type(getattr(base, f.name), data[f.name])
                   for f in fields(MappingTable) if f.name in data}
        return replace(base, **updates)

    def export_session(self) -> dict:
        """The full session as a JSON-able preset: seed, start bar, affect,
        pinned overrides, the whole MappingTable, console numerics, and the
        automation track. (The uploaded sample file is transient — not stored.)"""
        return {
            "seed": self.seed,
            "start_bar": self._start_bar,
            "affect": dict(self.affect),
            "pinned": {k: to_jsonable(v) for k, v in self.pinned.items()},
            "mapping": {f.name: to_jsonable(getattr(self.mapper, f.name))
                        for f in fields(MappingTable)},
            "console": self._console_values(),
            "automation": {"enabled": self.automation["enabled"],
                           "loop_bars": self.automation["loop_bars"],
                           "points": [dict(p) for p in self.automation["points"]]},
            "perform": dict(self._perform),
        }

    def import_session(self, data: dict) -> None:
        self.seed = int(data.get("seed", self.seed))
        self._start_bar = max(0, int(data.get("start_bar", 0)))
        if "affect" in data:
            self.affect = {k: _clamp(float(data["affect"].get(k, self.affect[k])),
                                     *_AFFECT_RANGE[k]) for k in self.affect}
        if "pinned" in data:
            pinned: dict[str, object] = {}
            for name, value in data["pinned"].items():
                try:
                    validate_override(name)
                    pinned[name] = _coerce_override(name, value)
                except Exception:  # noqa: BLE001
                    pass  # a stale override name from an old preset — skip it
            self.pinned = pinned
        if "mapping" in data:
            self.mapper = self._mapper_from_dict(data["mapping"])
        if "console" in data:
            numeric = self._numeric_console_names()
            nums = {k: float(v) for k, v in data["console"].items() if k in numeric}
            self._console_config = replace(self._cc(), **nums)  # keeps sample_path
        if "automation" in data:
            self.set_automation(data["automation"].get("enabled"),
                                data["automation"].get("loop_bars"),
                                data["automation"].get("points"))
        if "perform" in data:
            self._perform.update({k: (float(v) if k == "cadence_rit" else bool(v))
                                  for k, v in data["perform"].items() if k in self._perform})
        self._restart()  # rebuild a running player with the imported config

    def render_export(self, kind: str, bars: int, path) -> Path:
        """Offline bounce of the current config from bar 0 — a fresh engine
        (deterministic), driven by the automation curve if enabled: WAV via the
        synth console, or a standard-MIDI file. Caller must ensure the live
        player is stopped (one signalflow graph at a time)."""
        engine = self._build_engine()
        auto = self._player_automation()
        results = []
        for _ in range(max(1, int(bars))):
            if auto is not None:
                curve, loop = auto
                b = engine.state.bar
                engine.set_affect(**affect_at(curve, b % loop if loop > 0 else b))
            results.append(engine.advance_bar())
        meter = engine.config.meter
        if kind == "midi":
            from musicgen.midi_io import write_midi
            events = [ev for r in results for ev in r.events]
            tempo_map = sorted({(round(float(b), 6), float(bpm))
                                for r in results for b, bpm in r.tempo_points})
            if not tempo_map:
                tempo_map = [(0.0, float(results[0].params.tempo_bpm))]
            write_midi(path, events, tempo_map=tempo_map, meter=meter)
        else:
            from musicgen.synth.render import render_offline
            render_offline(results, meter, path, config=self._cc())
        return Path(path)

    # ------------------------------------------------------------- readback
    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "running": self.running,
            "seed": self.seed,
            "affect": dict(self.affect),
            "pinned": {k: to_jsonable(v) for k, v in self.pinned.items()},
            "mapping": {f.name: to_jsonable(getattr(self.mapper, f.name))
                        for f in fields(MappingTable)},
            "slots": sorted(self.slots),
            "console": self._console_values(),
            "sample": dict(self._sample),
            "start_bar": self._start_bar,
            "automation": {"enabled": self.automation["enabled"],
                           "loop_bars": self.automation["loop_bars"],
                           "points": [dict(p) for p in self.automation["points"]]},
            "dramaturg": {f.name: to_jsonable(getattr(self._dramaturg_config, f.name))
                          for f in fields(DramaturgConfig)},
            "perform": dict(self._perform),
        }
