"""A1 performance shaping (REFINEMENT_PLAN.md): the Perform modifier and the
conductor's cadence micro-ritardando. Both are deterministic (no rng draws), so
the tests assert exact values; the disabled paths must stay byte-identical."""

import random

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.modifiers import Perform, default_chains
from musicgen.theory.scales import Scale
from musicgen.verify import lint

METER = Meter(4, 4)
PARAMS = MusicalParams()


def _ctx(bar=0, pos=0, bars=8):
    return HarmonicContext(bar=bar, scale=Scale(0, "ionian"), chord_sym="I",
                           chord_pcs=(0, 4, 7), phrase_pos=pos, phrase_bars=bars)


def _apply(mod, events, ctx, params=PARAMS, seed=1):
    return mod.apply(events, ctx, METER, params, random.Random(seed))


def test_hairpin_crests_at_pre_cadence_and_relaxes_into_cadence():
    mod = Perform(hairpin=0.2, luftpause=0.0)
    at_open = _apply(mod, [NoteEvent(0.0, 1.0, 72, 80, "melody")], _ctx(0, 0))[0]
    at_crest = _apply(mod, [NoteEvent(26.0, 1.0, 72, 80, "melody")], _ctx(6, 6))[0]
    at_end = _apply(mod, [NoteEvent(31.0, 1.0, 72, 80, "melody")], _ctx(7, 7))[0]
    assert at_open.velocity < at_crest.velocity
    assert at_end.velocity < at_crest.velocity
    assert at_open.velocity < 80 <= at_crest.velocity  # swell centers on the base


def test_contour_tracks_pitch_around_register_center():
    mod = Perform(hairpin=0.0, contour=0.5, luftpause=0.0)
    high, low = _apply(mod, [NoteEvent(0.0, 1.0, 84, 80, "melody"),
                             NoteEvent(0.0, 1.0, 60, 80, "melody")], _ctx())
    assert high.velocity == 86 and low.velocity == 74  # ±0.5/semitone from C5


def test_agogic_stretches_phrase_open_downbeat_only():
    mod = Perform(hairpin=0.0, agogic=0.10, luftpause=0.0)
    downbeat, offbeat = _apply(mod, [NoteEvent(0.0, 1.0, 72, 80, "melody"),
                                     NoteEvent(1.0, 1.0, 72, 80, "melody")], _ctx(0, 0))
    assert abs(downbeat.dur - 1.1) < 1e-9 and offbeat.dur == 1.0
    mid_phrase = _apply(mod, [NoteEvent(12.0, 1.0, 72, 80, "melody")], _ctx(3, 3))[0]
    assert mid_phrase.dur == 1.0  # bar downbeats inside the phrase are not stretched


def test_luftpause_carves_silence_before_next_phrase():
    mod = Perform(hairpin=0.0, luftpause=0.05)
    held = _apply(mod, [NoteEvent(28.0, 4.0, 64, 80, "pad")], _ctx(7, 7))[0]
    assert abs(held.end - 31.95) < 1e-9  # trimmed to bar end minus the breath
    short = _apply(mod, [NoteEvent(28.0, 1.0, 64, 80, "pad")], _ctx(7, 7))[0]
    assert short.dur == 1.0  # already clear of the cut
    mid = _apply(mod, [NoteEvent(12.0, 4.0, 64, 80, "pad")], _ctx(3, 3))[0]
    assert mid.dur == 4.0  # only the cadence bar breathes


def test_lag_rides_behind_when_sparse_ahead_when_dense_never_before_bar():
    mod = Perform(hairpin=0.0, lag=0.02, luftpause=0.0)
    sparse = _apply(mod, [NoteEvent(5.0, 0.5, 72, 80, "melody")], _ctx(1, 1),
                    params=MusicalParams(note_density=0.2))[0]
    assert abs(sparse.start - 5.012) < 1e-9  # behind the beat
    dense = _apply(mod, [NoteEvent(5.0, 0.5, 72, 80, "melody")], _ctx(1, 1),
                   params=MusicalParams(note_density=0.9))[0]
    assert abs(dense.start - 4.984) < 1e-9  # on top of it
    clamped = _apply(mod, [NoteEvent(4.0, 0.5, 72, 80, "melody")], _ctx(1, 1),
                     params=MusicalParams(note_density=0.9))[0]
    assert clamped.start == 4.0  # never before the bar


def test_perform_draws_nothing_from_rng():
    events = [NoteEvent(0.25 * i, 0.25, 60 + i, 80, "melody") for i in range(8)]
    mod = Perform(hairpin=0.15, contour=0.4, agogic=0.1, lag=0.02)
    assert _apply(mod, events, _ctx(), seed=1) == _apply(mod, events, _ctx(), seed=99)


def test_default_chains_stay_byte_identical_without_perform():
    plain, performed = default_chains(), default_chains(perform=True)
    assert not any(isinstance(m, Perform) for chain in plain.values() for m in chain)
    for layer in ("pad", "bass", "melody", "arp"):
        assert any(isinstance(m, Perform) for m in performed[layer])
    assert plain["perc"] == performed["perc"]


def _render(seed, *, chains=None, affect=None, bars=16, **cfg):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        mapper=MappingTable(), chains=chains if chains is not None else default_chains(), **cfg))
    engine.set_affect(**(affect or {"valence": 0.2, "energy": 0.7, "tension": 0.4}))
    return [engine.advance_bar() for _ in range(bars)]


def test_raw_ir_identical_with_perform_chains():
    plain = _render(7, chains=default_chains())
    shaped = _render(7, chains=default_chains(perform=True))
    assert [r.raw_events for r in plain] == [r.raw_events for r in shaped]
    assert [r.events for r in plain] != [r.events for r in shaped]


def test_cadence_rit_static_path_emits_curve_and_recovers():
    engine = MusicEngine(seed=3, config=EngineConfig(cadence_rit=0.03))
    results = [engine.advance_bar() for _ in range(9)]
    # phrase 0 cadences authentic (default cycle); base tempo 100
    assert results[7].tempo_points == [(29.0, 99.0), (30.0, 98.0), (31.0, 97.0)]
    assert results[8].tempo_points == [(32.0, 100.0)]  # a tempo at the next downbeat
    assert any("perform: cadence rit -3.0%" in line for line in results[7].trace)
    assert all(r.tempo_points == [] for r in results[1:7])


def test_cadence_rit_off_is_byte_identical():
    plain = [MusicEngine(seed=3, config=EngineConfig()).advance_bar() for _ in range(1)]
    assert plain  # construction sanity
    a = MusicEngine(seed=3, config=EngineConfig())
    b = MusicEngine(seed=3, config=EngineConfig(cadence_rit=0.0))
    for _ in range(9):
        ra, rb = a.advance_bar(), b.advance_bar()
        assert (ra.events, ra.tempo_points, ra.trace) == (rb.events, rb.tempo_points, rb.trace)


def test_cadence_rit_mapper_path_shades_and_reemits():
    results = _render(3, affect={"valence": 0.2, "energy": 0.6, "tension": 0.1},
                      bars=9, cadence_rit=0.03)
    # tempo target 70 + 80*0.6 + 8*0.2 = 119.6, snapped at bar 0; tension 0.1 -> authentic
    assert results[0].tempo_points[0] == (0.0, 119.6)
    rit_points = results[7].tempo_points
    assert [b for b, _ in rit_points] == [29.0, 30.0, 31.0]
    bpms = [bpm for _, bpm in rit_points]
    assert bpms == sorted(bpms, reverse=True) and abs(bpms[-1] - 119.6 * 0.97) < 0.01
    assert results[8].tempo_points[0] == (32.0, 119.6)  # a tempo re-emitted


def test_cadence_rit_skips_deceptive_and_scales_with_payoff():
    engine = MusicEngine(seed=5, config=EngineConfig(
        mapper=MappingTable(), dramaturg=DramaturgConfig(), cadence_rit=0.03))
    engine.set_affect(tension=0.9)
    results = [engine.advance_bar() for _ in range(16)]  # two withholding phrases
    assert not any("perform: cadence rit" in line for r in results for line in r.trace)
    engine.set_affect(tension=0.1)  # release: phrase 2 spends the ledger
    results += [engine.advance_bar() for _ in range(8)]
    spend_rit = [line for line in results[23].trace if "perform: cadence rit" in line]
    assert spend_rit and float(spend_rit[0].split("-")[1].split("%")[0]) > 3.0


def test_perform_and_rit_lint_clean_across_seeds():
    for seed in (1, 2, 3, 4):
        results = _render(seed, chains=default_chains(perform=True), cadence_rit=0.02)
        contexts = [r.context for r in results]
        raw = [e for r in results for e in r.raw_events]
        final = [e for r in results for e in r.events]
        violations = lint(raw, contexts, stage="pre") + lint(final, contexts, stage="post")
        assert violations == [], f"seed {seed}:\n" + "\n".join(map(str, violations))


def test_rit_in_compound_meter():
    engine = MusicEngine(seed=2, config=EngineConfig(meter=Meter(6, 8), cadence_rit=0.03))
    results = [engine.advance_bar() for _ in range(9)]
    pts = results[7].tempo_points  # bar_quarters 3.0 -> beats at +1, +2
    assert [b for b, _ in pts] == [22.0, 23.0]
    assert pts[-1][1] == 97.0 and results[8].tempo_points == [(24.0, 100.0)]
