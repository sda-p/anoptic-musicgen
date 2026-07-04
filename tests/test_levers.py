import pytest

from musicgen.control.automation import affect_at, run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.theory.scales import BRIGHTNESS
from musicgen.verify import lint


def _engine(seed=42, **kwargs):
    kwargs.setdefault("mapper", MappingTable())
    return MusicEngine(seed=seed, config=EngineConfig(**kwargs))


def _advance(engine, bars):
    return [engine.advance_bar() for _ in range(bars)]


def test_mapped_engine_lints_clean():
    engine = _engine()
    engine.set_affect(valence=0.2, energy=0.6, tension=0.4)
    results = _advance(engine, 32)
    events = [e for r in results for e in r.events]
    contexts = [r.context for r in results]
    violations = lint(events, contexts)
    assert violations == [], "\n".join(map(str, violations))


def test_energy_axis_is_audible_in_structure():
    lo = _engine(seed=3)
    lo.set_affect(valence=0.0, energy=0.1, tension=0.3)
    hi = _engine(seed=3)
    hi.set_affect(valence=0.0, energy=0.9, tension=0.3)
    lo_results, hi_results = _advance(lo, 16), _advance(hi, 16)
    assert hi_results[-1].params.tempo_bpm > lo_results[-1].params.tempo_bpm + 30
    assert len(set(hi_results[0].params.layers)) > len(set(lo_results[0].params.layers))
    lo_events = [e for r in lo_results for e in r.events]
    hi_events = [e for r in hi_results for e in r.events]
    assert len(hi_events) > len(lo_events) * 1.5


def test_valence_axis_changes_mode_brightness():
    dark = _engine(seed=3)
    dark.set_affect(valence=-0.9, energy=0.5, tension=0.3)
    bright = _engine(seed=3)
    bright.set_affect(valence=0.9, energy=0.5, tension=0.3)
    dark_mode = _advance(dark, 8)[-1].context.scale.mode
    bright_mode = _advance(bright, 8)[-1].context.scale.mode
    assert BRIGHTNESS[bright_mode] > BRIGHTNESS[dark_mode]


def test_tension_axis_changes_cadence_policy():
    calm = _engine(seed=3, tension=0.1)
    tense = _engine(seed=3, tension=0.9)
    calm_ctx = _advance(calm, 8)[7].context
    tense_ctx = _advance(tense, 8)[7].context
    assert calm_ctx.cadence_policy == "authentic"
    assert tense_ctx.cadence_policy == "deceptive"


def test_tempo_slew_is_bounded_per_beat():
    engine = _engine(seed=1, energy=0.1)
    _advance(engine, 2)
    engine.set_affect(energy=1.0)  # huge tempo jump requested
    results = _advance(engine, 20)
    points = [p for r in results for p in r.tempo_points]
    for (b0, t0), (b1, t1) in zip(points, points[1:]):
        assert abs(t1 - t0) <= MappingTable().tempo_slew_per_beat * (b1 - b0) + 1e-6
    assert points[-1][1] > 140  # eventually reaches the high target


def test_mode_changes_quantize_to_phrase_unless_urgent():
    engine = _engine(seed=5, valence=0.9)
    _advance(engine, 2)
    engine.set_affect(valence=-1.0)  # request darkness mid-phrase
    results = _advance(engine, 12)
    modes = [r.context.scale.mode for r in results]
    assert modes[:6] == ["lydian"] * 6, "mode holds until the phrase boundary"
    assert modes[6] == "phrygian", "switches at bar 9 (new phrase)"

    urgent = _engine(seed=5, valence=0.9)
    _advance(urgent, 2)
    urgent.set_affect(valence=-1.0, urgent=True)
    assert urgent.advance_bar().context.scale.mode == "phrygian", "urgent demotes to next bar"


def test_pinned_mode_wins():
    engine = _engine(seed=5, mode="dorian", valence=0.9)
    results = _advance(engine, 10)
    assert {r.context.scale.mode for r in results} == {"dorian"}


def test_overrides_pin_parameters():
    engine = _engine(seed=2, energy=0.9)
    engine.set_override("tempo_bpm", 96.0)
    engine.set_override("note_density", 0.2)
    results = _advance(engine, 12)
    assert abs(results[-1].params.tempo_bpm - 96.0) < 0.01
    assert results[-1].params.note_density == 0.2
    engine.clear_override("note_density")
    assert engine.advance_bar().params.note_density > 0.5

    with pytest.raises(KeyError):
        engine.set_override("swagger", 1.0)


def test_slow_harmonic_rhythm_holds_chords():
    engine = _engine(seed=4, energy=0.1, tension=0.1)
    results = _advance(engine, 8)
    held = [line for r in results for line in r.trace if "held" in line]
    assert held, "calm affect should hold chords across two bars"
    # even bars generate, odd free bars hold: pairs are (0,1), (2,3), (4,5)
    assert results[1].context.chord == results[0].context.chord or \
           results[3].context.chord == results[2].context.chord


def test_static_path_unchanged_without_mapper():
    engine = MusicEngine(seed=42, config=EngineConfig())
    result = engine.advance_bar()
    assert result.params == EngineConfig().params
    assert result.context.scale.mode == "ionian"
    assert result.tempo_points == [(0.0, result.params.tempo_bpm)]


def test_mapped_engine_deterministic_and_seed_sensitive():
    def render(seed):
        e = _engine(seed=seed)
        e.set_affect(valence=0.1, energy=0.6, tension=0.5)
        return [ev for r in _advance(e, 12) for ev in r.events]

    assert render(7) == render(7)
    assert render(7) != render(8)


def test_lint_clean_across_automation_curves():
    curve = [
        (0, {"valence": 0.4, "energy": 0.2, "tension": 0.1}),
        (12, {"valence": -0.7, "energy": 0.95, "tension": 0.85}),
        (24, {"valence": 0.8, "energy": 0.5, "tension": 0.2}),
    ]
    for seed in (1, 2, 3):
        engine = _engine(seed=seed)
        results = run(engine, curve, 24)
        events = [e for r in results for e in r.events]
        contexts = [r.context for r in results]
        violations = lint(events, contexts)
        assert violations == [], f"seed {seed}:\n" + "\n".join(map(str, violations))
