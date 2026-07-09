"""M12 playground — logic tests (no audio, no web server): telemetry
serialization, the schema introspection, and the PlaygroundState control
mirror + coercion. The live engine/player/meter/websocket path is exercised by
scratch validation scripts, not here (keeps the suite fast and audio-free)."""
from __future__ import annotations

import json

import pytest

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.playground import telemetry
from musicgen.playground.state import PlaygroundState


def test_schema_is_data_driven():
    s = telemetry.schema()
    assert s["type"] == "schema"
    assert "tempo_bpm" in s["overridable"] and "mode" in s["overridable"]
    assert any(f["name"] == "tempo_base" for f in s["mapping"])
    assert isinstance(s["console"], list)
    assert s["layers"] == ["pad", "bass", "melody", "arp", "perc"]
    # modes are brightness-ordered dark -> bright
    assert [m["name"] for m in s["modes"]][0] == "phrygian"
    assert [m["name"] for m in s["modes"]][-1] == "lydian"
    json.dumps(s)  # fully serializable


def test_bar_telemetry_roundtrips():
    engine = MusicEngine(seed=1, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(valence=0.2, energy=0.7, tension=0.5)
    result = None
    for _ in range(3):
        result = engine.advance_bar()
    msg = telemetry.bar_telemetry(result, pinned=["tempo_bpm"])

    assert msg["type"] == "bar" and msg["bar"] == 2
    assert set(msg) >= {"context", "params", "affect", "trace", "events", "pinned", "tempo_points"}
    assert msg["context"]["chord_sym"] and msg["context"]["scale"]
    assert isinstance(msg["params"]["tempo_bpm"], (int, float))
    assert isinstance(msg["params"]["layers"], list)          # tuple -> list
    assert isinstance(msg["params"]["instruments"], list)
    assert msg["affect"]["energy"] == 0.7
    assert msg["pinned"] == ["tempo_bpm"]
    assert msg["trace"]                                        # decision trace carried
    assert "mapped" in msg                                     # follow/pin ghost slot
    json.dumps(msg)


def test_param_ui_and_mapped_ghost():
    s = telemetry.schema()
    groups = {g["group"]: g for g in s["param_ui"]}
    assert set(groups) == {"energy", "valence", "tension", "dsp"}
    tempo = next(p for p in groups["energy"]["params"] if p["name"] == "tempo_bpm")
    assert tempo["kind"] == "float" and tempo["min"] == 60.0 and tempo["max"] == 160.0 and tempo["boundary"] == "beat"
    mode = next(p for g in s["param_ui"] for p in g["params"] if p["name"] == "mode")
    assert mode["kind"] == "enum" and {o["value"] for o in mode["options"]} >= {"ionian", "lydian"}
    # dissonance_budget is intentionally excluded — the engine ties it to tension
    names = {p["name"] for g in s["param_ui"] for p in g["params"]}
    assert "dissonance_budget" not in names

    m = telemetry.mapped_targets((0.3, 0.5, 0.45), MappingTable())
    assert m["mode"] in {o["value"] for o in mode["options"]}
    assert 60.0 <= m["tempo_bpm"] <= 160.0
    assert isinstance(m["accent_depth"], int)
    json.dumps(m)


def test_mapping_editor_and_ab_slots():
    from dataclasses import fields as dfields

    s = telemetry.schema()
    ui = {f["name"] for g in s["mapping_ui"] for f in g["fields"]}
    allf = {f.name for f in dfields(MappingTable)}
    assert ui == allf - {"layer_gates", "instrument_tiers"}  # every constant but the nested structs
    tr = next(f for g in s["mapping_ui"] for f in g["fields"] if f["name"] == "tempo_range")
    assert tr["kind"] == "range" and tr["default"] == [60.0, 160.0]

    st = PlaygroundState()
    st.set_mapping_field("tempo_base", 99.0)
    st.store_mapping("A")
    st.set_mapping_field("tempo_base", 55.0)
    assert st.snapshot()["mapping"]["tempo_base"] == 55.0
    assert st.snapshot()["slots"] == ["A"]
    st.recall_mapping("A")                     # A/B recall restores the stored table
    assert st.snapshot()["mapping"]["tempo_base"] == 99.0
    st.reset_mapping()
    assert st.snapshot()["mapping"]["tempo_base"] == 70.0


def test_console_tuner():
    s = telemetry.schema()
    names = {f["name"] for g in s["console_ui"] for f in g["fields"]}
    assert {"fdn_t60", "shimmer_max", "limiter_ceiling"} <= names
    assert all(f["kind"] == "scalar" for g in s["console_ui"] for f in g["fields"])

    st = PlaygroundState()
    assert st.snapshot()["console"]["fdn_t60"] == 2.2
    st.set_console_fields({"fdn_t60": 3.5, "shimmer_max": 0.6})
    snap = st.snapshot()
    assert snap["console"]["fdn_t60"] == 3.5 and snap["console"]["shimmer_max"] == 0.6
    st.set_console_fields({"bogus_field": 1.0})   # unknown field ignored, no crash
    assert "bogus_field" not in st.snapshot()["console"]
    st.set_console_fields({"sample_path": 1.0})   # non-numeric field never float-coerced
    assert st._console_config.sample_path == ""


def test_dramaturg_controls():
    s = telemetry.schema()
    names = {f["name"] for g in s["dramaturg_ui"] for f in g["fields"]}
    assert {"leniency", "accrue_above", "escalate_phrases"} <= names

    st = PlaygroundState()
    assert st.snapshot()["dramaturg"]["enabled"] is False   # off by default -> byte-identical baseline
    st.set_dramaturg_fields({"enabled": True, "leniency": 0.8, "escalate_phrases": 3})
    d = st.snapshot()["dramaturg"]
    assert d["enabled"] is True
    assert d["leniency"] == 0.8 and isinstance(d["leniency"], float)
    assert d["escalate_phrases"] == 3 and isinstance(d["escalate_phrases"], int)
    st.set_dramaturg_fields({"bogus_knob": 1.0})            # unknown field ignored, no crash
    assert "bogus_knob" not in st.snapshot()["dramaturg"]


def test_perform_controls():
    s = telemetry.schema()
    assert {f["name"] for g in s["perform_ui"] for f in g["fields"]} == {"cadence_rit"}

    st = PlaygroundState()
    p = st.snapshot()["perform"]  # all off by default -> byte-identical baseline
    assert p == {"shaping": False, "cadence_rit": 0.025, "phrase_groove": False,
                 "plan_apex": False, "counterpoint": False}
    engine = st._build_engine()
    assert engine.config.cadence_rit == 0.0 and not engine.config.phrase_groove
    assert not engine.config.melody.plan_apex and not engine.config.melody.counterpoint

    st.set_perform_fields({"shaping": True, "phrase_groove": True, "plan_apex": True,
                           "counterpoint": True, "cadence_rit": 0.03})
    engine = st._build_engine()
    from musicgen.modifiers import Perform
    assert any(isinstance(m, Perform) for m in engine.config.chains["melody"])
    assert engine.config.cadence_rit == 0.03 and engine.config.phrase_groove
    assert engine.config.melody.plan_apex and engine.config.melody.counterpoint
    st.set_perform_fields({"bogus_knob": 1.0})              # unknown field ignored, no crash
    assert "bogus_knob" not in st.snapshot()["perform"]

    # the mirror survives a session round-trip (preset save/load)
    clone = PlaygroundState()
    clone.import_session(st.export_session())
    assert clone.snapshot()["perform"] == st.snapshot()["perform"]


def test_sampler_load_clear():
    st = PlaygroundState()
    assert st.snapshot()["sample"] == {"name": "", "root": 72}
    st.set_sample("/tmp/foo/bell.wav", 60)         # rides the console-rebuild path
    assert st.snapshot()["sample"] == {"name": "bell.wav", "root": 60}
    assert st._console_config.sample_path == "/tmp/foo/bell.wav"
    assert st._console_config.sample_root_midi == 60
    st.clear_sample()
    assert st.snapshot()["sample"] == {"name": "", "root": 72}
    assert st._console_config.sample_path == ""


def test_inspection_telemetry():
    from musicgen.ir import Meter

    s = telemetry.schema()
    assert s["phrase_bars"] == 8

    engine = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(valence=0.2, energy=0.7, tension=0.5)
    results = [engine.advance_bar() for _ in range(4)]
    lint = telemetry.lint_result(results, Meter())
    assert lint == {"clean": True, "violations": []}   # the engine's own output lints clean

    msg = telemetry.bar_telemetry(results[-1], [], {}, lint)
    assert msg["events"] and msg["raw_events"]           # both stages carried for the piano-roll
    assert msg["lint"]["clean"] is True
    json.dumps(msg)


def test_automation_track_mirror_and_curve():
    from musicgen.control.automation import affect_at

    st = PlaygroundState()
    snap = st.snapshot()
    assert snap["start_bar"] == 0
    assert snap["automation"]["enabled"] is False and len(snap["automation"]["points"]) == 2

    st.set_automation(enabled=True, loop_bars=32,
                      points=[{"bar": 0, "valence": -0.5, "energy": 0.1, "tension": 0.0},
                              {"bar": 8, "valence": 0.9, "energy": 1.0, "tension": 1.0}])
    a = st.snapshot()["automation"]
    assert a["enabled"] and a["loop_bars"] == 32
    mid = affect_at(st._automation_curve(), 4)                 # linear midpoint
    assert mid["valence"] == pytest.approx(0.2) and mid["energy"] == pytest.approx(0.55)
    # out-of-range points are clamped into the affect ranges (and bar >= 0)
    st.set_automation(points=[{"bar": -3, "valence": 5, "energy": -1, "tension": 2}])
    assert st.snapshot()["automation"]["points"][0] == {
        "bar": 0, "valence": 1.0, "energy": 0.0, "tension": 1.0}


def test_seek_sets_start_bar():
    st = PlaygroundState()
    st.seek(12)                                                # stopped: just records it
    assert st.snapshot()["start_bar"] == 12
    st.seek(-4)
    assert st.snapshot()["start_bar"] == 0                     # clamped non-negative
    st.seek(10_000_000)
    assert st.snapshot()["start_bar"] == 4096                  # clamped to the warm-up ceiling


def test_set_automation_is_atomic_on_bad_points():
    st = PlaygroundState()
    st.set_automation(enabled=False, loop_bars=8)
    before = [dict(p) for p in st.automation["points"]]
    with pytest.raises((KeyError, TypeError, ValueError)):
        st.set_automation(enabled=True, loop_bars=16, points=[{"bar": 0}])  # missing v/e/t
    # the bad points must abort the whole update — enabled/loop_bars unchanged
    assert st.automation["enabled"] is False and st.automation["loop_bars"] == 8
    assert st.automation["points"] == before


def test_session_export_import_roundtrip():
    st = PlaygroundState()
    st.reseed(7)
    st.set_override("tempo_bpm", 132)
    st.set_mapping_field("tempo_base", 88.0)
    st.seek(12)
    st.set_automation(enabled=True, loop_bars=16,
                      points=[{"bar": 0, "valence": 0.0, "energy": 0.0, "tension": 0.0}])
    sess = st.export_session()
    json.dumps(sess)  # a preset is a plain JSON document

    other = PlaygroundState()
    other.import_session(sess)
    s = other.snapshot()
    assert s["seed"] == 7 and s["pinned"]["tempo_bpm"] == 132.0
    assert s["mapping"]["tempo_base"] == 88.0 and other.mapper.tempo_base == 88.0
    assert s["start_bar"] == 12
    assert s["automation"]["enabled"] is True and s["automation"]["loop_bars"] == 16
    # a stale override name in an old preset is skipped, not fatal
    sess["pinned"] = {"gone_param": 1, "drive": 0.4}
    fresh = PlaygroundState()
    fresh.import_session(sess)
    assert "gone_param" not in fresh.pinned and fresh.pinned["drive"] == 0.4


def test_midi_export_is_deterministic(tmp_path):
    from musicgen.midi_io import read_notes

    a, b = tmp_path / "a.mid", tmp_path / "b.mid"
    PlaygroundState().render_export("midi", 8, str(a))
    PlaygroundState().render_export("midi", 8, str(b))
    assert a.read_bytes() == b.read_bytes()                    # deterministic bounce
    assert len(read_notes(str(a))) > 0                         # and it has notes


def test_override_mirror_and_coercion():
    st = PlaygroundState()
    st.set_override("tempo_bpm", 132)
    assert st.pinned["tempo_bpm"] == 132.0 and isinstance(st.pinned["tempo_bpm"], float)
    st.set_override("register_center", 60)
    assert st.pinned["register_center"] == 60 and isinstance(st.pinned["register_center"], int)
    st.set_override("layers", ["pad", "bass", "melody"])
    assert st.pinned["layers"] == ("pad", "bass", "melody")
    st.set_override("instruments", [["pad", "morph"], ["bass", "round"]])
    assert st.pinned["instruments"] == (("pad", "morph"), ("bass", "round"))
    st.clear_override("tempo_bpm")
    assert "tempo_bpm" not in st.pinned
    with pytest.raises(KeyError):
        st.set_override("bogus", 1)


def test_mapping_hot_edit_replaces_frozen_table():
    st = PlaygroundState()
    original = st.mapper
    assert st.mapper.tempo_base == 70.0
    st.set_mapping_field("tempo_base", 95)
    assert st.mapper.tempo_base == 95.0
    assert st.mapper is not original                          # frozen: replaced, not mutated
    assert original.tempo_base == 70.0
    st.set_mapping_field("tempo_range", [50, 180])            # structural (tuple) field
    assert st.mapper.tempo_range == (50.0, 180.0)
    with pytest.raises(KeyError):
        st.set_mapping_field("nope", 1)


def test_snapshot_shape():
    st = PlaygroundState()
    st.set_override("drive", 0.3)
    snap = st.snapshot()
    assert snap["type"] == "snapshot" and snap["running"] is False
    assert snap["pinned"]["drive"] == 0.3
    assert "tempo_base" in snap["mapping"]
    assert snap["affect"] == {"valence": 0.3, "energy": 0.5, "tension": 0.45}
    json.dumps(snap)
