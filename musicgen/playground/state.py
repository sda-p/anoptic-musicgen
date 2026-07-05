"""PlaygroundState: owns the live session — one engine template + one realtime
player — and is the single authority for the server-side mirror of control
state (affect, pinned overrides, the live MappingTable, seed).

Every control method updates the mirror AND, if a player is running, forwards
to its thread-safe command queue (applied at a bar edge on the generation
thread). Rebuilding the engine on start re-applies the whole mirror, so edits
(a tuned heuristic, a pinned param) survive stop/start — the natural dev loop.
"""
from __future__ import annotations

from dataclasses import fields, replace

from musicgen.control.levers import validate_override
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.playground.telemetry import to_jsonable

# a tighter look-ahead than the demos: generation is µs-fast, so a small buffer
# keeps live lever moves audible within a beat instead of the default 2.5 s
_LEAD_SECONDS = 0.6
_PRIME_SECONDS = 0.2

_AFFECT_RANGE = {"valence": (-1.0, 1.0), "energy": (0.0, 1.0), "tension": (0.0, 1.0)}
_INT_OVERRIDES = {"velocity_center", "accent_depth", "register_center"}


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
        self.player = None

    # ------------------------------------------------------------- lifecycle
    def _build_engine(self) -> MusicEngine:
        cfg = EngineConfig(mapper=self.mapper, valence=self.affect["valence"],
                           energy=self.affect["energy"], tension=self.affect["tension"])
        engine = MusicEngine(seed=self.seed, config=cfg)
        for name, value in self.pinned.items():
            engine.set_override(name, value)
        return engine

    def _cc(self):
        if self._console_config is None:
            from musicgen.synth.console import ConsoleConfig
            self._console_config = ConsoleConfig(enable_meter=True)
        return self._console_config

    def _console_values(self) -> dict:
        cc = self._cc()
        return {f.name: getattr(cc, f.name) for f in fields(type(cc))
                if isinstance(getattr(cc, f.name), (int, float)) and not isinstance(getattr(cc, f.name), bool)}

    def start(self, on_bar) -> None:
        if self.player is not None:
            return
        from musicgen.synth.render import RealtimeSynthPlayer

        player = RealtimeSynthPlayer(
            self._build_engine(), on_bar=on_bar,
            lead_seconds=_LEAD_SECONDS, prime_seconds=_PRIME_SECONDS,
            config=self._cc(),
        )
        player.start()
        self.player = player

    def stop(self) -> None:
        player, self.player = self.player, None
        if player is not None:
            player.stop()

    @property
    def running(self) -> bool:
        return self.player is not None

    def level(self) -> float:
        player = self.player
        if player is None or player.console is None:
            return 0.0
        return player.console.level()

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
            kw = {k: float(v) for k, v in (("valence", valence), ("energy", energy),
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
        known = {f.name for f in fields(type(cc))}
        applied = {name: float(value) for name, value in updates.items() if name in known}
        if not applied:
            return
        self._console_config = replace(cc, **applied)
        if self.player is not None:
            self.player.set_console(self._console_config)

    def reseed(self, seed) -> None:
        self.seed = int(seed)  # takes effect on the next start()

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
        }
