"""M11 voice-engine chunk: wavetable morph pad, sampler keys, granular
shimmer, mod matrix, audio-rate sweep automation."""

import struct
import wave

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.synth.console import ConsoleConfig
from musicgen.synth.render import render_offline

MORPH_KEYS = (("pad", "morph"), ("bass", "round"), ("melody", "keys"), ("arp", "pluck"))


def _static(bars=3, layers=("pad", "melody"), seed=8, **params_kw):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        params=MusicalParams(layers=layers, note_density=0.5, **params_kw)))
    return [engine.advance_bar() for _ in range(bars)], engine.config.meter


def _read(path):
    with wave.open(str(path)) as w:
        n = w.getnframes()
        return struct.unpack(f"<{n * 2}h", w.readframes(n))


def _rms(xs):
    return (sum(x * x for x in xs) / len(xs)) ** 0.5 / 32768.0


def test_wavetable_and_sampler_patches_render_and_differ(tmp_path):
    results, meter = _static(instruments=MORPH_KEYS)
    default, _ = _static()
    a = render_offline(results, meter, tmp_path / "morphkeys.wav")
    b = render_offline(default, meter, tmp_path / "default.wav")
    da, db = _read(a), _read(b)
    assert _rms(da) > 0.01, "morph/keys render must produce audio"
    assert da != db, "new patches must change the sound"


def test_sampler_repitch_shortens_high_notes():
    from musicgen.synth.patches import SAMPLE_ROOT_MIDI, make_bell_sample
    import signalflow as sf
    graph = sf.AudioGraph(output_device=sf.AudioOut_Dummy(2, sample_rate=44100, buffer_size=1024),
                          start=False)
    try:
        from musicgen.synth.patches import sampler_voice
        bell = make_bell_sample(44100)
        cutoff = sf.Smooth(4000.0, 0.999)
        _, low_total = sampler_voice(SAMPLE_ROOT_MIDI - 12, 0.8, 9.0, cutoff, bell, 44100)
        _, root_total = sampler_voice(SAMPLE_ROOT_MIDI, 0.8, 9.0, cutoff, bell, 44100)
        _, high_total = sampler_voice(SAMPLE_ROOT_MIDI + 12, 0.8, 9.0, cutoff, bell, 44100)
        assert high_total < root_total < low_total, "rate repitch must scale ring time"
        assert abs(high_total * 2 - root_total) < 1e-6, "an octave up rings half as long"
    finally:
        graph.destroy()


def test_shimmer_rides_tension(tmp_path):
    calm, meter = _static(bars=3, layers=("pad",))
    # same notes, tension pinned high vs zero through the static params path
    tense_engine = MusicEngine(seed=8, config=EngineConfig(
        params=MusicalParams(layers=("pad",), note_density=0.5), tension=0.95))
    tense = [tense_engine.advance_bar() for _ in range(3)]
    a = render_offline(calm, meter, tmp_path / "calm.wav", tail_seconds=3.0)
    b = render_offline(tense, meter, tmp_path / "tense.wav", tail_seconds=3.0)
    da, db = _read(a), _read(b)
    assert da != db, "tension must engage the granular shimmer"
    # shimmer + reverb bloom: the tense tail carries clearly more energy
    tail_a, tail_b = da[-int(2.0 * 44100) * 2:], db[-int(2.0 * 44100) * 2:]
    assert _rms(tail_b) > _rms(tail_a) * 1.1


def test_mod_matrix_off_changes_output_and_stays_stable(tmp_path):
    results, meter = _static(bars=2)
    on = render_offline(results, meter, tmp_path / "mod_on.wav")
    off = render_offline(results, meter, tmp_path / "mod_off.wav",
                         config=ConsoleConfig(mod_matrix=()))
    assert _read(on) != _read(off)


def test_unknown_mod_route_rejected():
    import signalflow as sf
    import pytest
    from musicgen.synth.console import Console
    graph = sf.AudioGraph(output_device=sf.AudioOut_Dummy(2, sample_rate=44100, buffer_size=1024),
                          start=False)
    try:
        with pytest.raises(ValueError, match="unknown mod route"):
            Console(graph, ConsoleConfig(mod_matrix=(("lfo_slow", "nonsense", 0.1),)))
    finally:
        graph.destroy()


def test_sweep_engages_on_big_cutoff_rise(tmp_path):
    def run(depth, path):
        engine = MusicEngine(seed=4, config=EngineConfig(mapper=MappingTable(), energy=0.15))
        results = [engine.advance_bar() for _ in range(2)]
        engine.set_affect(energy=0.95, urgent=True)  # cutoff jumps several octaves
        results += [engine.advance_bar() for _ in range(3)]
        return render_offline(results, engine.config.meter, tmp_path / path,
                              config=ConsoleConfig(sweep_depth=depth))

    with_sweep = _read(run(0.9, "sweep.wav"))
    without = _read(run(0.0, "nosweep.wav"))
    assert with_sweep != without, "the sweep envelope must shape the rise"


def test_full_texture_with_new_patches_deterministic(tmp_path):
    def run(path):
        engine = MusicEngine(seed=13, config=EngineConfig(mapper=MappingTable(), tension=0.8))
        engine.set_override("instruments", MORPH_KEYS)
        results = [engine.advance_bar() for _ in range(4)]
        return render_offline(results, engine.config.meter, tmp_path / path)

    assert _read(run("d1.wav")) == _read(run("d2.wav")), (
        "granular/mod-matrix noise sources must stay deterministic per render")
