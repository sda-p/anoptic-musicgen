"""Serialization: BarResult -> per-bar telemetry dict, and a schema snapshot
that lets the UI stay data-driven (introspected from the dataclasses, never
hand-maintained). Pure and dependency-light — the synth import (ConsoleConfig)
is deferred into schema() so the per-bar path stays free of signalflow.
"""
from __future__ import annotations

from dataclasses import fields


def to_jsonable(value):
    """Tuples -> lists, recursively; scalars/strings pass through. The IR uses
    tuples throughout (layers, instruments, EQ bands); JSON wants arrays."""
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    return value


def event_dict(ev) -> dict:
    return {
        "start": ev.start, "dur": ev.dur, "pitch": ev.pitch,
        "velocity": ev.velocity, "layer": ev.layer,
        "degree": ev.degree, "chord": ev.chord, "role": ev.role,
    }


def context_dict(ctx) -> dict:
    return {
        "bar": ctx.bar,
        "scale": ctx.scale.name,
        "chord_sym": ctx.chord_sym,
        "chord_pcs": list(ctx.chord_pcs),
        "next_chord_sym": ctx.next_chord_sym,
        "tension": ctx.tension,
        "cadence_slot": ctx.cadence_slot,
        "cadence_policy": ctx.cadence_policy,
        "modulation": ctx.modulation,
    }


def params_dict(params) -> dict:
    return {f.name: to_jsonable(getattr(params, f.name)) for f in fields(type(params))}


# the follow/pin grid, grouped by which affect lever primarily drives each param
# (name, kind, boundary[, min, max, step]); boundary is the natural musical
# quantum a change is "musical" at. dissonance_budget is omitted — the engine
# ties it to tension and ignores the override, so a control would be inert.
_GROUPS = (
    ("energy", "follows energy", (
        ("tempo_bpm", "float", "beat", 60.0, 160.0, 0.5),
        ("note_density", "float", "bar", 0.0, 1.0, 0.01),
        ("roughness", "float", "bar", 0.0, 0.6, 0.01),
        ("articulation", "float", "bar", 0.45, 1.05, 0.01),
        ("velocity_center", "int", "bar", 30, 110, 1),
        ("accent_depth", "int", "bar", 0, 30, 1),
    )),
    ("valence", "follows valence", (
        ("mode", "enum", "phrase"),
        ("register_center", "int", "bar", 48, 84, 1),
        ("stereo_width", "float", "bar", 0.0, 1.3, 0.01),
    )),
    ("tension", "follows tension", (
        ("cadence_policy", "enum", "phrase"),
        ("harmonic_rhythm", "enum", "bar"),
    )),
    ("dsp", "signal / mix", (
        ("filter_cutoff", "float", "bar", 120.0, 8000.0, 10.0),
        ("reverb_send", "float", "bar", 0.0, 1.0, 0.01),
        ("delay_send", "float", "bar", 0.0, 1.0, 0.01),
        ("drive", "float", "bar", 0.0, 1.0, 0.01),
    )),
)
_ENUM_OPTIONS = {
    "cadence_policy": [{"label": "authentic", "value": "authentic"},
                      {"label": "half", "value": "half"},
                      {"label": "deceptive", "value": "deceptive"}],
    "harmonic_rhythm": [{"label": "1 / bar", "value": 1.0},
                        {"label": "1 / 2 bars", "value": 0.5}],
    # "mode" options are filled from the brightness axis in schema()
}


def mapped_targets(affect: tuple, mapper) -> dict:
    """What the mapping table would produce for each overridable param at this
    affect (instantaneous targets, pre-slew/pre-hysteresis) — the "ghost" the
    follow/pin grid shows beside a pinned value so an override is legible as a
    departure from the heuristic."""
    from musicgen.control import mapping
    from musicgen.control.levers import Affect
    a, t = Affect(*affect), mapper
    return {
        "tempo_bpm": round(mapping.tempo_target(a, t), 2),
        "note_density": round(mapping.density_target(a, t), 3),
        "roughness": round(mapping.roughness_target(a, t), 3),
        "articulation": round(mapping.articulation_target(a, t), 3),
        "velocity_center": round(mapping.velocity_target(a, t)),
        "accent_depth": mapping.accent_target(a, t),
        "register_center": mapping.register_target(a, t),
        "harmonic_rhythm": mapping.harmonic_rhythm_target(a, t),
        "cadence_policy": mapping.pick_cadence_policy(a.tension, t),
        "mode": mapping.nearest_mode(a.valence),
        "filter_cutoff": round(mapping.filter_cutoff_target(a, t), 1),
        "reverb_send": round(mapping.reverb_send_target(a, t), 3),
        "delay_send": round(mapping.delay_send_target(a, t), 3),
        "drive": round(mapping.drive_target(a, t), 3),
        "stereo_width": round(mapping.stereo_width_target(a, t), 3),
    }


def bar_telemetry(result, pinned, mapped=None) -> dict:
    """The per-bar message pushed to every client: the whole inspection payload
    (chord/key, the params actually used, affect, the decision trace, the events
    for a piano-roll), which Tier-2 params are pinned, and the mapper's would-be
    targets (the follow/pin ghost)."""
    valence, energy, tension = result.affect
    return {
        "type": "bar",
        "bar": result.bar,
        "context": context_dict(result.context),
        "params": params_dict(result.params),
        "mapped": mapped or {},
        "affect": {"valence": valence, "energy": energy, "tension": tension},
        "tempo_points": [list(tp) for tp in result.tempo_points],
        "trace": list(result.trace),
        "events": [event_dict(ev) for ev in result.events],
        "pinned": list(pinned),
    }


def _dataclass_fields(cls) -> list[dict]:
    inst = cls()
    out = []
    for f in fields(cls):
        val = getattr(inst, f.name)
        scalar = isinstance(val, (int, float)) and not isinstance(val, bool)
        out.append({"name": f.name, "default": to_jsonable(val),
                    "kind": "scalar" if scalar else "struct"})
    return out


def schema() -> dict:
    """Everything the UI needs to render controls without hardcoding: affect
    ranges, the override whitelist, the MappingTable heuristic constants, the
    ConsoleConfig fields, the instrument tiers / GM patch table, and the
    brightness-ordered mode list. All read from the dataclasses at call time."""
    from musicgen.control.levers import OVERRIDABLE
    from musicgen.control.mapping import MappingTable
    from musicgen.ir import LAYER_NAMES, Meter, MusicalParams
    from musicgen.midi_io import GM_PATCHES
    from musicgen.theory.scales import BRIGHTNESS

    mt = MappingTable()
    patches_by_layer: dict[str, list[str]] = {}
    for layer, patch in GM_PATCHES:
        patches_by_layer.setdefault(layer, []).append(patch)

    console_fields: list[dict] = []
    try:  # ConsoleConfig pulls signalflow — present under [playground], but stay soft
        from musicgen.synth.console import ConsoleConfig
        console_fields = _dataclass_fields(ConsoleConfig)
    except Exception:  # noqa: BLE001
        pass

    enum_options = dict(_ENUM_OPTIONS)
    enum_options["mode"] = [{"label": m, "value": m}
                            for m, _ in sorted(BRIGHTNESS.items(), key=lambda kv: kv[1])]
    param_ui = []
    for group, label, specs in _GROUPS:
        rows = []
        for spec in specs:
            entry = {"name": spec[0], "kind": spec[1], "boundary": spec[2]}
            if spec[1] in ("float", "int"):
                entry["min"], entry["max"], entry["step"] = spec[3], spec[4], spec[5]
            else:
                entry["options"] = enum_options[spec[0]]
            rows.append(entry)
        param_ui.append({"group": group, "label": label, "params": rows})

    return {
        "type": "schema",
        "affect": {
            "valence": {"min": -1.0, "max": 1.0, "default": 0.3},
            "energy": {"min": 0.0, "max": 1.0, "default": 0.5},
            "tension": {"min": 0.0, "max": 1.0, "default": 0.45},
        },
        "overridable": sorted(OVERRIDABLE),
        "params": _dataclass_fields(MusicalParams),
        "mapping": _dataclass_fields(MappingTable),
        "console": console_fields,
        "instrument_tiers": to_jsonable(mt.instrument_tiers),
        "layer_gates": to_jsonable(mt.layer_gates),
        "layers": list(LAYER_NAMES),
        "layers_boundary": "bar",
        "param_ui": param_ui,
        "patches_by_layer": patches_by_layer,
        "modes": [{"name": m, "brightness": b}
                  for m, b in sorted(BRIGHTNESS.items(), key=lambda kv: kv[1])],
        "meter": {"numerator": Meter().numerator, "denominator": Meter().denominator},
    }
