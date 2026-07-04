import random

from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import Meter, MusicalParams
from musicgen.modifiers import Swing
from musicgen.verify import lint

FULL_LAYERS = ("pad", "bass", "melody", "arp", "perc")
METERS = (Meter(3, 4), Meter(6, 8), Meter(12, 8))


def _run(meter, seed=42, bars=16, **params_kw):
    params = MusicalParams(layers=FULL_LAYERS, **params_kw)
    engine = MusicEngine(seed=seed, config=EngineConfig(meter=meter, params=params))
    return [engine.advance_bar() for _ in range(bars)]


def _lint_all(results, meter):
    contexts = [r.context for r in results]
    raw = [ev for r in results for ev in r.raw_events]
    final = [ev for r in results for ev in r.events]
    return lint(raw, contexts, meter, stage="pre") + lint(final, contexts, meter, stage="post")


# --- Meter model ---------------------------------------------------------------


def test_pulse_properties():
    assert (Meter(4, 4).pulses, Meter(4, 4).pulse_slots, Meter(4, 4).is_compound) == (4, 4, False)
    assert (Meter(3, 4).pulses, Meter(3, 4).pulse_slots, Meter(3, 4).is_compound) == (3, 4, False)
    assert (Meter(2, 4).pulses, Meter(2, 4).pulse_slots, Meter(2, 4).is_compound) == (2, 4, False)
    assert (Meter(6, 8).pulses, Meter(6, 8).pulse_slots, Meter(6, 8).is_compound) == (2, 6, True)
    assert (Meter(9, 8).pulses, Meter(9, 8).pulse_slots, Meter(9, 8).is_compound) == (3, 6, True)
    assert (Meter(12, 8).pulses, Meter(12, 8).pulse_slots, Meter(12, 8).is_compound) == (4, 6, True)
    assert Meter(6, 8).pulse_quarters == 1.5
    assert Meter(6, 8).slots == 12 and Meter(12, 8).slots == 24


def test_metric_weights_four_four_regression():
    assert Meter(4, 4).metric_weights() == (
        4.0, 1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0, 3.5, 1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0)


def test_metric_weights_three_four():
    assert Meter(3, 4).metric_weights() == (
        4.0, 1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0)
    assert Meter(3, 4).strong_slots() == (0, 4, 8)


def test_metric_weights_six_eight_compound():
    # Two dotted-quarter pulses — NOT six 8th-note beats.
    assert Meter(6, 8).metric_weights() == (
        4.0, 1.0, 2.0, 1.0, 2.0, 1.0, 3.5, 1.0, 2.0, 1.0, 2.0, 1.0)
    assert Meter(6, 8).strong_slots() == (0, 6)
    assert Meter(12, 8).strong_slots() == (0, 6, 12, 18)


# --- engine integration --------------------------------------------------------


def test_lint_clean_across_meters_seeds_densities():
    for meter in METERS:
        for seed in (1, 2):
            for density in (0.25, 0.55, 0.85):
                results = _run(meter, seed=seed, note_density=density, roughness=density * 0.7)
                violations = _lint_all(results, meter)
                assert violations == [], (
                    f"{meter.numerator}/{meter.denominator} seed {seed} density {density}:\n"
                    + "\n".join(map(str, violations)))


def test_raw_events_stay_inside_their_bars():
    for meter in METERS:
        results = _run(meter, bars=12, note_density=0.8, roughness=0.5)
        total = 12 * meter.bar_quarters
        for r in results:
            for ev in r.raw_events:
                assert ev.end <= total + 1e-9
                assert meter.bar_of(ev.start) == r.bar, (
                    f"{meter.numerator}/{meter.denominator}: {ev} generated for bar {r.bar}")


def test_deterministic_per_meter():
    for meter in METERS:
        a = [ev for r in _run(meter, seed=7) for ev in r.events]
        b = [ev for r in _run(meter, seed=7) for ev in r.events]
        assert a == b


def test_compound_percussion_idiom():
    results = _run(Meter(6, 8), bars=8, note_density=0.4, roughness=0.0)
    perc = [ev for r in results for ev in r.raw_events if ev.layer == "perc"]
    meter = Meter(6, 8)
    snares = {meter.slot_of(ev.start) for ev in perc if ev.role == "drum:snare"}
    kicks = {meter.slot_of(ev.start) for ev in perc if ev.role == "drum:kick"}
    assert snares == {6}, "6/8 backbeat is the second dotted quarter"
    assert kicks == {0}, "low-density 6/8 kick anchors the downbeat only"


def test_waltz_snare_on_beat_two():
    results = _run(Meter(3, 4), bars=8, note_density=0.4, roughness=0.0)
    meter = Meter(3, 4)
    snares = {meter.slot_of(ev.start)
              for r in results for ev in r.raw_events
              if ev.layer == "perc" and ev.role == "drum:snare"}
    assert snares == {4}, "3/4 snare sits on beat 2, not a 16th offbeat"


def test_swing_noop_in_compound():
    results = _run(Meter(6, 8), bars=4)
    events = [ev for r in results for ev in r.raw_events]
    ctx, meter = results[0].context, Meter(6, 8)
    assert Swing(amount=1.0).apply(events, ctx, meter, results[0].params, random.Random(0)) == events


def test_modulation_in_six_eight():
    engine = MusicEngine(seed=5, config=EngineConfig(
        meter=Meter(6, 8), params=MusicalParams(layers=FULL_LAYERS)))
    engine.request_key("G")
    results = [engine.advance_bar() for _ in range(16)]
    assert results[-1].context.scale.tonic == 7
    violations = _lint_all(results, Meter(6, 8))
    assert violations == [], "\n".join(map(str, violations))
