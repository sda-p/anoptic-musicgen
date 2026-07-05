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
    json.dumps(msg)


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
