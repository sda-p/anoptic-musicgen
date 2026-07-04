import random

from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.control.mapping import MappingTable
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.modifiers import (
    Accent, Articulate, Echo, Humanize, Strum, Swing, Transpose, apply_chain, default_chains,
)
from musicgen.theory.scales import Scale
from musicgen.verify import lint

METER = Meter(4, 4)
CTX = HarmonicContext(bar=0, scale=Scale(0, "ionian"), chord_sym="I", chord_pcs=(0, 4, 7))
PARAMS = MusicalParams()


def _apply(mod, events, rng_seed=1, params=PARAMS):
    return mod.apply(events, CTX, METER, params, random.Random(rng_seed))


def test_swing_delays_offbeats_only():
    events = [
        NoteEvent(0.0, 0.5, 60, 80, "melody"),   # downbeat: untouched
        NoteEvent(0.5, 0.5, 62, 80, "melody"),   # 8th offbeat: +amount/6
        NoteEvent(1.25, 0.25, 64, 80, "melody"), # 16th offbeat: +amount/12
    ]
    out = _apply(Swing(amount=0.9), events)
    assert out[0].start == 0.0
    assert abs(out[1].start - (0.5 + 0.9 / 6)) < 1e-9
    assert abs(out[2].start - (1.25 + 0.9 / 12)) < 1e-9
    assert out[1].end <= 1.0 + 1e-9, "note end preserved"


def test_humanize_bounded_and_never_before_bar():
    events = [NoteEvent(0.0, 1.0, 60, 80, "melody") for _ in range(50)]
    out = _apply(Humanize(t_sigma=0.02, v_sigma=6.0), events)
    assert all(e.start >= 0.0 for e in out)
    assert all(abs(e.start - 0.0) <= 0.04 + 1e-9 for e in out)  # 2 sigma clamp
    assert all(1 <= e.velocity <= 127 for e in out)
    assert any(e.start != 0.0 or e.velocity != 80 for e in out)
    assert _apply(Humanize(), events, 5) == _apply(Humanize(), events, 5), "seeded determinism"


def test_articulate_reads_params_when_gate_none():
    events = [NoteEvent(0.0, 1.0, 60, 80, "melody")]
    staccato = _apply(Articulate(), events, params=MusicalParams(articulation=0.5))
    assert staccato[0].dur == 0.5
    explicit = _apply(Articulate(gate=1.05), events)
    assert abs(explicit[0].dur - 1.05) < 1e-9


def test_accent_shapes_by_metric_weight():
    events = [NoteEvent(0.0, 0.25, 60, 80, "melody"),   # downbeat, weight 4
              NoteEvent(0.25, 0.25, 62, 80, "melody")]  # 16th offbeat, weight 1
    out = _apply(Accent(depth=12), events)
    assert out[0].velocity > 80 > out[1].velocity


def test_echo_appends_decaying_repeats():
    events = [NoteEvent(0.0, 0.5, 72, 100, "arp")]
    out = _apply(Echo(delay=0.75, decay=0.5, repeats=3, min_velocity=20), events)
    echoes = [e for e in out if e.role == "echo"]
    assert [e.start for e in echoes] == [0.75, 1.5]  # third repeat under floor
    assert [e.velocity for e in echoes] == [50, 25]
    assert all(e.pitch == 72 for e in echoes)


def test_strum_staggers_ascending_and_keeps_ends():
    chord = [NoteEvent(4.0, 4.0, p, 80, "pad") for p in (55, 60, 64, 72)]
    out = sorted(_apply(Strum(spread=0.06), chord), key=lambda e: e.pitch)
    starts = [e.start for e in out]
    assert starts[0] == 4.0 and starts == sorted(starts)
    assert abs(starts[-1] - 4.06) < 1e-9
    assert all(abs(e.end - 8.0) < 1e-9 for e in out)


def test_transpose_octaves_and_steps():
    events = [NoteEvent(0.0, 1.0, 60, 80, "melody", degree=1)]
    up = _apply(Transpose(octaves=1), events)
    assert up[0].pitch == 72 and up[0].degree == 1
    stepped = _apply(Transpose(steps=2), events)
    assert stepped[0].pitch == 64 and stepped[0].degree == 3


def test_chain_order_and_composition():
    events = [NoteEvent(0.0, 1.0, 60, 80, "melody")]
    out = apply_chain((Articulate(gate=0.5), Accent(depth=12)), events, CTX, METER, PARAMS, random.Random(1))
    assert out[0].dur == 0.5 and out[0].velocity > 80


def _render(seed, chains):
    engine = MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable(), chains=chains))
    engine.set_affect(valence=0.2, energy=0.7, tension=0.4)
    return [engine.advance_bar() for _ in range(12)]


def test_raw_ir_identical_with_and_without_chains():
    with_mods = _render(9, default_chains())
    without = _render(9, {})
    assert [r.raw_events for r in with_mods] == [r.raw_events for r in without]
    assert [r.events for r in without] == [r.raw_events for r in without]
    assert [r.events for r in with_mods] != [r.raw_events for r in with_mods]


def test_modified_output_deterministic():
    a = _render(4, default_chains())
    b = _render(4, default_chains())
    assert [r.events for r in a] == [r.events for r in b]


def test_echo_across_mode_boundary_is_licensed():
    # An echo annotated in its source bar (aeolian ^6 = G#) ringing into a
    # brighter bar must not trip scale/degree rules.
    contexts = [
        HarmonicContext(bar=0, scale=Scale(0, "aeolian"), chord_sym="i", chord_pcs=(0, 3, 7)),
        HarmonicContext(bar=1, scale=Scale(0, "mixolydian"), chord_sym="I", chord_pcs=(0, 4, 7)),
    ]
    stray_echo = [NoteEvent(4.25, 0.5, 68, 40, "arp", degree=6, role="echo")]
    assert lint(stray_echo, contexts, METER, stage="post") == []


def test_default_chains_lint_clean_across_seeds():
    for seed in (1, 2, 3, 4):
        results = _render(seed, default_chains())
        contexts = [r.context for r in results]
        raw = [e for r in results for e in r.raw_events]
        final = [e for r in results for e in r.events]
        violations = lint(raw, contexts, stage="pre") + lint(final, contexts, stage="post")
        assert violations == [], f"seed {seed}:\n" + "\n".join(map(str, violations))
