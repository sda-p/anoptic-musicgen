import mido

from musicgen.control.mapping import MappingTable, pick_instruments
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen import midi_io

FULL_LAYERS = ("pad", "bass", "melody", "arp", "perc")
CALM = (("pad", "warm"), ("bass", "round"), ("melody", "soft"), ("arp", "pluck"))
HOT = (("pad", "bright"), ("bass", "driven"), ("melody", "hard"), ("arp", "glass"))


# --- mapping -------------------------------------------------------------------


def test_pick_instruments_tiers():
    t = MappingTable()
    assert pick_instruments((), 0.1, t) == CALM
    assert pick_instruments((), 0.95, t) == HOT
    mid = dict(pick_instruments((), 0.58, t))
    assert mid["melody"] == "hard" and mid["pad"] == "warm"


def test_pick_instruments_hysteresis():
    t = MappingTable()
    hot = pick_instruments((), 0.95, t)
    # dip just below the pad threshold: the sitting patch holds...
    held = dict(pick_instruments(hot, 0.55, t))
    assert held["pad"] == "bright"
    # ...but a fresh pick at the same energy chooses calm
    fresh = dict(pick_instruments((), 0.55, t))
    assert fresh["pad"] == "warm"
    # and a clear drop releases everything
    assert pick_instruments(hot, 0.2, t) == CALM


# --- engine --------------------------------------------------------------------


def _mapped(seed=42, **cfg_kw):
    return MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable(), **cfg_kw))


def test_swaps_quantize_to_phrase_boundaries():
    engine = _mapped(energy=0.2)
    results = [engine.advance_bar() for _ in range(4)]
    engine.set_affect(energy=0.95)  # not urgent: waits for the phrase seam
    results += [engine.advance_bar() for _ in range(12)]

    instruments = [r.params.instruments for r in results]
    assert instruments[0] == CALM
    changes = [i for i in range(1, len(instruments)) if instruments[i] != instruments[i - 1]]
    assert changes == [8], f"swap must land on the phrase boundary, got bars {changes}"
    assert instruments[8] == HOT


def test_urgent_swap_lands_next_bar():
    engine = _mapped(energy=0.2)
    results = [engine.advance_bar() for _ in range(3)]
    engine.set_affect(energy=0.95, urgent=True)
    results += [engine.advance_bar() for _ in range(2)]
    assert results[2].params.instruments == CALM
    assert results[3].params.instruments == HOT


def test_swap_back_with_hysteresis_and_trace():
    engine = _mapped(energy=0.9)
    results = [engine.advance_bar() for _ in range(8)]
    engine.set_affect(energy=0.15)
    results += [engine.advance_bar() for _ in range(8)]
    assert results[0].params.instruments == HOT
    assert results[8].params.instruments == CALM
    swap_lines = [line for r in results for line in r.trace if line.startswith("instruments:")]
    assert len(swap_lines) == 2, swap_lines  # initial statement + the swap back


def test_static_path_instruments_constant():
    engine = MusicEngine(seed=42, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    results = [engine.advance_bar() for _ in range(16)]
    assert {r.params.instruments for r in results} == {CALM}


def test_instruments_override_pins():
    engine = _mapped(energy=0.1)
    engine.set_override("instruments", HOT)
    results = [engine.advance_bar() for _ in range(4)]
    assert results[0].params.instruments == HOT


def test_swaps_deterministic():
    def run():
        engine = _mapped(seed=9, energy=0.2)
        out = []
        for bar in range(16):
            if bar == 5:
                engine.set_affect(energy=0.95, urgent=True)
            out.append(engine.advance_bar())
        return [(r.params.instruments, tuple(r.events)) for r in out]

    assert run() == run()


# --- MIDI ----------------------------------------------------------------------


def test_program_changes_written(tmp_path):
    engine = _mapped(energy=0.2)
    results = [engine.advance_bar() for _ in range(4)]
    engine.set_affect(energy=0.95, urgent=True)
    results += [engine.advance_bar() for _ in range(4)]

    changes: list[tuple[float, str, str]] = []
    applied: dict[str, str] = {}
    for r in results:
        for layer, patch in r.params.instruments:
            if applied.get(layer) != patch:
                applied[layer] = patch
                changes.append((r.bar * 4.0, layer, patch))
    events = [ev for r in results for ev in r.events]
    path = midi_io.write_midi(tmp_path / "swap.mid", events,
                              instrument_changes=changes)

    programs: dict[int, list[tuple[int, int]]] = {}
    for track in mido.MidiFile(path).tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "program_change":
                programs.setdefault(msg.channel, []).append((tick, msg.program))
    pad = programs[midi_io.LAYER_MIDI["pad"].channel]
    assert pad[0] == (0, midi_io.GM_PATCHES[("pad", "warm")])
    swap_tick = midi_io.beats_to_ticks(4 * 4.0)  # urgent: the bar after the 4 played
    assert (swap_tick, midi_io.GM_PATCHES[("pad", "bright")]) in pad


def test_gm_patches_cover_all_tiers():
    for layer, tiers in MappingTable().instrument_tiers:
        for name, _ in tiers:
            assert (layer, name) in midi_io.GM_PATCHES, f"unmapped patch {(layer, name)}"


def test_unknown_patch_rejected(tmp_path):
    from musicgen.ir import NoteEvent
    import pytest
    ev = NoteEvent(0.0, 1.0, 60, 80, "pad")
    with pytest.raises(ValueError, match="no GM program"):
        midi_io.write_midi(tmp_path / "bad.mid", [ev],
                           instrument_changes=[(0.0, "pad", "nonexistent")])


# --- synth backend ---------------------------------------------------------------


def test_synth_renders_hot_variants(tmp_path):
    import wave
    from musicgen.synth.render import render_offline

    engine = _mapped(seed=4, energy=0.3)
    results = [engine.advance_bar() for _ in range(2)]
    engine.set_affect(energy=0.95, urgent=True)  # swaps every layer to the hot tier
    results += [engine.advance_bar() for _ in range(4)]
    assert results[-1].params.instruments == HOT

    path = render_offline(results, engine.config.meter, tmp_path / "swap.wav")
    with wave.open(str(path)) as w:
        assert w.getnframes() > w.getframerate(), "render produced audio"
