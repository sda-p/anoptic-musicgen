"""Console v2 (M10): FDN reverb, chorus, ping-pong, sidechain modes,
lookahead limiter, dither. Stats-based assertions over short offline renders."""

import struct
import wave

from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.synth.console import ConsoleConfig
from musicgen.synth.patches import _keytrack
from musicgen.synth.render import render_offline


def _results(bars=3, layers=("pad", "bass", "melody", "arp", "perc"), seed=11):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        params=MusicalParams(layers=layers, note_density=0.6)))
    return [engine.advance_bar() for _ in range(bars)], engine.config.meter


def _read(path):
    with wave.open(str(path)) as w:
        n = w.getnframes()
        data = struct.unpack(f"<{n * 2}h", w.readframes(n))
    left, right = data[0::2], data[1::2]
    return left, right


def _rms(xs):
    return (sum(x * x for x in xs) / len(xs)) ** 0.5 / 32768.0


def test_keytrack_factor():
    assert abs(_keytrack(261.63, 0.4) - 1.0) < 1e-6
    assert _keytrack(1046.5, 0.4) > 1.5
    assert _keytrack(32.7, 0.3) < 1.0
    assert _keytrack(20000.0, 1.0) == 2.5 and _keytrack(10.0, 1.0) == 0.5


def test_fdn_tail_decays(tmp_path):
    results, meter = _results(bars=2, layers=("pad",))
    path = render_offline(results, meter, tmp_path / "tail.wav", tail_seconds=5.0)
    left, _ = _read(path)
    sr = 44100
    ringing = _rms(left[-int(4.0 * sr):-int(3.5 * sr)])
    end = _rms(left[-int(0.5 * sr):])
    assert end < ringing * 0.2 or end < 1e-4, (
        f"FDN tail must decay, got {ringing:.5f} -> {end:.5f}")
    assert end < 0.003, "no runaway feedback"


def test_limiter_holds_ceiling_under_slam(tmp_path):
    results, meter = _results(bars=2)
    hot = ConsoleConfig(master_makeup=8.0)  # deliberately brutal
    path = render_offline(results, meter, tmp_path / "slam.wav", config=hot)
    left, right = _read(path)
    peak = max(max(abs(s) for s in left), max(abs(s) for s in right)) / 32768.0
    assert peak <= 0.951, f"clip guard ceiling exceeded: {peak}"
    flattened = sum(1 for s in left if abs(s) >= 0.945 * 32768) / len(left)
    assert flattened < 0.001, (
        f"limiter should hold peaks below the clip guard, {flattened:.4%} slammed")


def test_sidechain_detect_mode_renders_and_differs(tmp_path):
    results, meter = _results(bars=3)
    a = render_offline(results, meter, tmp_path / "schedule.wav")
    b = render_offline(results, meter, tmp_path / "detect.wav",
                       config=ConsoleConfig(sidechain="detect"))
    assert _read(a) != _read(b), "detect mode must change the ducking"


def test_chorus_decorrelates_pad(tmp_path):
    results, meter = _results(bars=2, layers=("pad",))
    path = render_offline(results, meter, tmp_path / "pad.wav")
    left, right = _read(path)
    diff = [(l - r) for l, r in zip(left, right)]
    assert _rms(diff) > 0.01, "chorused pad must differ across channels"


def test_dither_deterministic_and_bounded(tmp_path):
    results, meter = _results(bars=2, layers=("bass",))
    a = _read(render_offline(results, meter, tmp_path / "a.wav"))
    b = _read(render_offline(results, meter, tmp_path / "b.wav"))
    assert a == b, "dithered renders must stay bit-reproducible"
    c = _read(render_offline(results, meter, tmp_path / "c.wav", dither=False))
    assert a != c, "dither must actually change the quantization"
    deltas = {abs(x - y) for x, y in zip(a[0], c[0])}
    assert max(deltas) <= 2, f"dither is +-1 LSB TPDF, saw delta {max(deltas)}"
