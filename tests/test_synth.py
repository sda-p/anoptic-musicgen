import math
import struct
import wave

import pytest

pytest.importorskip("signalflow")

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.synth.render import render_offline

CURVE = [
    (0, {"valence": 0.3, "energy": 0.45, "tension": 0.2}),
    (6, {"valence": -0.6, "energy": 0.9, "tension": 0.8}),
]


def _wav_stats(path):
    with wave.open(str(path)) as w:
        frames, rate, channels = w.getnframes(), w.getframerate(), w.getnchannels()
        samples = struct.unpack(f"<{frames * channels}h", w.readframes(frames))
    peak = max(abs(s) for s in samples) / 32768.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
    slammed = sum(1 for s in samples if abs(s) >= 0.94 * 32768) / len(samples)
    return frames / rate, peak, rms, slammed


def _render(tmp_path, bars=6, seed=11):
    engine = MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable()))
    results = run(engine, CURVE, bars)
    path = render_offline(results, engine.config.meter, tmp_path / "synth.wav")
    expected_beats = sum(1 for _ in results) * 4
    from musicgen.clock import BeatClock
    clock = BeatClock(0.0)
    for r in results:
        for beat, bpm in r.tempo_points:
            clock.add_tempo_point(beat, bpm)
    return path, clock.time_at(expected_beats), results


def test_offline_render_produces_audio(tmp_path):
    path, musical_seconds, _ = _render(tmp_path)
    duration, peak, rms, slammed = _wav_stats(path)
    assert duration == pytest.approx(musical_seconds + 2.5, abs=1.5)
    assert rms > 0.02, "render is (near-)silent"
    assert peak <= 0.96, "hard-clip guard exceeded"
    assert slammed < 0.001, f"{slammed:.2%} of samples at the brick wall"


def test_offline_render_deterministic_length_and_content(tmp_path):
    a, _, _ = _render(tmp_path / "a", seed=7)
    b, _, _ = _render(tmp_path / "b", seed=7)
    da, _, ra, _ = _wav_stats(a)
    db, _, rb, _ = _wav_stats(b)
    assert da == db
    assert ra == pytest.approx(rb, rel=0.01)


def test_engine_state_untouched_by_synth(tmp_path):
    # Rendering must not perturb generation: same seed with and without a
    # previous render in the process yields identical events.
    engine1 = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    results1 = run(engine1, CURVE, 4)
    render_offline(results1, engine1.config.meter, tmp_path / "x.wav")
    engine2 = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    results2 = run(engine2, CURVE, 4)
    assert [r.events for r in results1] == [r.events for r in results2]


def test_dsp_params_flow_into_results():
    engine = MusicEngine(seed=1, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(valence=0.0, energy=0.2, tension=0.2)
    calm = engine.advance_bar().params
    engine.set_affect(energy=0.95, tension=0.8)
    for _ in range(3):
        hot = engine.advance_bar().params
    assert hot.filter_cutoff > calm.filter_cutoff * 3
    assert hot.drive > calm.drive
    assert hot.delay_send > calm.delay_send
