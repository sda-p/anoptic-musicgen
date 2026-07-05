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

# the live MappingTable heuristics editor, grouped by the table's own structure.
# Scalar constants + tempo_range (a "range" of two floats); the two structural
# fields (layer_gates, instrument_tiers) are omitted — nested-tuple editing is a
# later concern, and they are edited in code today.
_MAPPING_GROUPS = (
    ("tempo", ("tempo_base", "tempo_energy", "tempo_valence", "tempo_range", "tempo_slew_per_beat")),
    ("register", ("register_base", "register_valence", "register_tension")),
    ("density / roughness", ("density_base", "density_energy", "roughness_base",
                             "roughness_energy", "roughness_tension", "roughness_max")),
    ("articulation", ("articulation_legato", "articulation_energy_drop", "articulation_slew_per_bar")),
    ("dynamics", ("velocity_base", "velocity_energy", "velocity_slew_per_bar",
                  "accent_base", "accent_energy")),
    ("mode / layers", ("mode_hysteresis", "layer_hysteresis", "instrument_hysteresis")),
    ("cadence / harmony", ("cadence_authentic_max", "cadence_half_max",
                           "harmonic_slow_energy", "harmonic_slow_tension")),
    ("filter / drive", ("cutoff_base_hz", "cutoff_energy_octaves", "cutoff_valence_octaves",
                        "drive_base", "drive_energy")),
    ("sends / width", ("reverb_send_base", "reverb_send_tension", "reverb_send_stillness",
                       "delay_send_base", "delay_send_activity", "width_base", "width_valence")),
)

# the console (voice/mix) tuner — STRUCTURAL params applied via a rebuild.
# Numeric ConsoleConfig fields only; the nested tuples (EQ, sends, mod-matrix,
# FDN delays) are edited in code.
_CONSOLE_GROUPS = (
    ("reverb (FDN)", ("fdn_t60", "fdn_damping_hz", "reverb_predelay",
                      "reverb_shelf_hz", "reverb_shelf_db")),
    ("delay", ("delay_feedback", "delay_max_seconds")),
    ("chorus", ("chorus_mix", "chorus_base", "chorus_depth")),
    ("shimmer", ("shimmer_max", "shimmer_grain_rate", "shimmer_grain_duration",
                 "shimmer_history_seconds")),
    ("sweep", ("sweep_trigger_ratio", "sweep_depth")),
    ("master / limiter", ("master_makeup", "limiter_ceiling", "limiter_release",
                          "limiter_lookahead", "limiter_gain_smooth", "velocity_curve")),
    ("sidechain (detect)", ("detect_sensitivity", "detect_release")),
)


def _step_for(default) -> float:
    a = abs(float(default[0] if isinstance(default, tuple) else default))
    if a < 0.05:
        return 0.001
    if a < 1.5:
        return 0.01
    if a < 15:
        return 0.1
    if a < 150:
        return 1.0
    return 10.0


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


def lint_result(recent, meter) -> dict:
    """Lint a small window of recent bars (so cross-bar rules — voice leading,
    leap resolution — have context) and return the newest bar's status. The
    same theory linter the offline renders must pass, run live."""
    from musicgen import verify
    if not recent:
        return {"clean": True, "violations": []}
    events = [ev for r in recent for ev in r.raw_events]
    contexts = [r.context for r in recent]
    latest = recent[-1].bar
    hits = [{"rule": v.rule, "message": v.message}
            for v in verify.lint(events, contexts, meter, stage="pre")
            if v.bar in (latest, -1)]
    return {"clean": not hits, "violations": hits}


def bar_telemetry(result, pinned, mapped=None, lint=None) -> dict:
    """The per-bar message pushed to every client: the whole inspection payload
    (chord/key, the params actually used, affect, the decision trace, the post-
    and raw events for a piano-roll, the live lint status), which Tier-2 params
    are pinned, and the mapper's would-be targets (the follow/pin ghost)."""
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
        "raw_events": [event_dict(ev) for ev in result.raw_events],
        "lint": lint or {"clean": True, "violations": []},
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
    from musicgen.gen.conductor import EngineConfig
    from musicgen.ir import LAYER_NAMES, Meter, MusicalParams
    from musicgen.midi_io import GM_PATCHES
    from musicgen.theory.scales import BRIGHTNESS

    mt = MappingTable()
    patches_by_layer: dict[str, list[str]] = {}
    for layer, patch in GM_PATCHES:
        patches_by_layer.setdefault(layer, []).append(patch)

    console_fields: list[dict] = []
    console_ui: list[dict] = []
    try:  # ConsoleConfig pulls signalflow — present under [playground], but stay soft
        from musicgen.synth.console import ConsoleConfig
        console_fields = _dataclass_fields(ConsoleConfig)
        cc = ConsoleConfig()
        for group, names in _CONSOLE_GROUPS:
            console_ui.append({"group": group, "fields": [
                {"name": n, "default": to_jsonable(getattr(cc, n)),
                 "kind": "scalar", "step": _step_for(getattr(cc, n))} for n in names]})
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

    mapping_ui = []
    for group, names in _MAPPING_GROUPS:
        fields_out = []
        for name in names:
            default = getattr(mt, name)
            fields_out.append({"name": name, "default": to_jsonable(default),
                               "kind": "range" if isinstance(default, tuple) else "scalar",
                               "step": _step_for(default)})
        mapping_ui.append({"group": group, "fields": fields_out})

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
        "mapping_ui": mapping_ui,
        "console": console_fields,
        "console_ui": console_ui,
        "instrument_tiers": to_jsonable(mt.instrument_tiers),
        "layer_gates": to_jsonable(mt.layer_gates),
        "layers": list(LAYER_NAMES),
        "layers_boundary": "bar",
        "param_ui": param_ui,
        "patches_by_layer": patches_by_layer,
        "modes": [{"name": m, "brightness": b}
                  for m, b in sorted(BRIGHTNESS.items(), key=lambda kv: kv[1])],
        "meter": {"numerator": Meter().numerator, "denominator": Meter().denominator},
        "phrase_bars": EngineConfig().phrase_bars,
    }
