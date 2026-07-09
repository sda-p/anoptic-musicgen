"""A3 outer-voice counterpoint (REFINEMENT_PLAN.md): the pure species rules in
theory/counterpoint.py, the verify.lint_outer frame checker, and the melody
generator's guard behind MelodyConfig.counterpoint."""

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.ir import HarmonicContext, Meter, NoteEvent
from musicgen.theory.counterpoint import (
    forbidden_direct, forbidden_parallel, interval_class, is_consonant, motion,
)
from musicgen.theory.scales import Scale
from musicgen.verify import lint, lint_outer

METER = Meter(4, 4)


# --- the pure rules -----------------------------------------------------------

def test_interval_and_consonance():
    assert interval_class(48, 67) == 7          # C3 under G4: a (compound) fifth
    assert interval_class(48, 72) == 0          # octaves fold
    assert is_consonant(48, 64) and is_consonant(48, 69)   # 3rd, 6th
    assert not is_consonant(48, 65) and not is_consonant(48, 62)  # 4th, 2nd


def test_motion_classification():
    assert motion(48, 67, 48, 69) == "oblique"    # bass holds
    assert motion(48, 67, 50, 65) == "contrary"
    assert motion(48, 67, 50, 69) == "parallel"   # fifths marching up
    assert motion(48, 64, 50, 69) == "similar"    # same direction, new interval
    assert motion(48, 67, 48, 67) == "oblique"    # static verticality


def test_forbidden_parallel():
    assert forbidden_parallel(48, 67, 50, 69)      # parallel fifths
    assert forbidden_parallel(48, 72, 50, 74)      # parallel octaves
    assert forbidden_parallel(48, 72, 43, 67)      # contrary ('antiparallel') octaves
    assert not forbidden_parallel(48, 67, 48, 69)  # oblique: bass held
    assert not forbidden_parallel(48, 67, 50, 66)  # arrives on a 4th
    assert not forbidden_parallel(48, 64, 50, 69)  # 3rd -> 5th, only one perfect
    assert not forbidden_parallel(48, 72, 48, 72)  # repeated verticality


def test_forbidden_direct():
    assert forbidden_direct(48, 64, 55, 79)       # similar melody leap into an octave
    assert forbidden_direct(48, 64, 55, 67)       # E4 -> G4: a minor-3rd leap into a fifth
    assert not forbidden_direct(48, 65, 55, 67)   # F4 -> G4 steps into the fifth: exempt
    assert not forbidden_direct(48, 64, 43, 67)   # contrary motion is always fine
    assert not forbidden_direct(48, 67, 50, 69)   # same class = the parallel rule's case


# --- the linter ---------------------------------------------------------------

def _ctx(bar, cadence=""):
    return HarmonicContext(bar=bar, scale=Scale(0, "ionian"), chord_sym="I",
                           chord_pcs=(0, 4, 7), cadence_slot=cadence,
                           phrase_pos=bar % 8, phrase_bars=8)


def _pair_bars(m1, b1, m2, b2):
    """Two bars: a whole-bar bass note under a strong-slot melody note each."""
    return [
        NoteEvent(0.0, 1.0, m1, 80, "melody"), NoteEvent(0.0, 4.0, b1, 80, "bass"),
        NoteEvent(4.0, 1.0, m2, 80, "melody"), NoteEvent(4.0, 4.0, b2, 80, "bass"),
    ]


def test_lint_outer_catches_planted_parallels_and_directs():
    fifths = lint_outer(_pair_bars(67, 48, 69, 50), [_ctx(0), _ctx(1)], METER)
    assert [v.rule for v in fifths] == ["outer-parallel"] and "fifths" in fifths[0].message
    octaves = lint_outer(_pair_bars(72, 48, 74, 50), [_ctx(0), _ctx(1)], METER)
    assert [v.rule for v in octaves] == ["outer-parallel"] and "octaves" in octaves[0].message
    direct = lint_outer(_pair_bars(64, 48, 79, 55), [_ctx(0), _ctx(1)], METER)
    assert [v.rule for v in direct] == ["outer-direct"]


def test_lint_outer_allows_clean_and_broken_frames():
    assert lint_outer(_pair_bars(67, 48, 65, 50), [_ctx(0), _ctx(1)], METER) == []  # 5th -> 4th
    # a rest longer than a bar breaks the frame: the same forbidden pair, two bars apart
    events = [
        NoteEvent(0.0, 1.0, 67, 80, "melody"), NoteEvent(0.0, 4.0, 48, 80, "bass"),
        NoteEvent(8.0, 1.0, 69, 80, "melody"), NoteEvent(8.0, 4.0, 50, 80, "bass"),
    ]
    assert lint_outer(events, [_ctx(0), _ctx(1), _ctx(2)], METER) == []
    # signature statements are licensed as a whole: same plant, role "motif"
    planted = _pair_bars(67, 48, 69, 50)
    exempt = [e if e.layer == "bass" else
              NoteEvent(e.start, e.dur, e.pitch, e.velocity, "melody", role="motif")
              for e in planted]
    assert lint_outer(exempt, [_ctx(0), _ctx(1)], METER) == []


# --- the guard ----------------------------------------------------------------

AFFECTS = (
    {"valence": 0.2, "energy": 0.6, "tension": 0.35},
    {"valence": -0.4, "energy": 0.8, "tension": 0.6},
    {"valence": 0.0, "energy": 0.5, "tension": 0.45},
)


def _render(seed, counterpoint, affect, dram=False, bars=32):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        mapper=MappingTable(),
        dramaturg=DramaturgConfig() if dram else None,
        melody=MelodyConfig(counterpoint=counterpoint, plan_apex=True),
        phrase_groove=True))
    engine.set_affect(**affect)
    results = [engine.advance_bar() for _ in range(bars)]
    raw = [e for r in results for e in r.raw_events]
    return results, raw, [r.context for r in results]


def test_unguarded_frame_violates_across_seeds():
    # the plant: without the guard, parallels/directs occur — proving both that
    # the checker sees them and that the guard has real work to do
    found = 0
    for seed in (1, 2, 3):
        _, raw, ctxs = _render(seed, False, AFFECTS[0])
        found += len(lint_outer(raw, ctxs))
    assert found >= 5, f"only {found} violations planted"


def test_guarded_frame_is_clean_across_seeds_and_affects():
    for dram in (False, True):
        for affect in AFFECTS:
            for seed in (1, 2, 3, 4, 5):
                results, raw, ctxs = _render(seed, True, affect, dram=dram)
                violations = lint_outer(raw, ctxs) + lint(raw, ctxs, stage="pre")
                assert violations == [], (f"dram={dram} affect={affect} seed={seed}:\n"
                                          + "\n".join(map(str, violations)))


def test_counterpoint_off_is_default_and_feature_changes_output():
    assert MelodyConfig().counterpoint is False
    _, plain, _ = _render(3, False, AFFECTS[0])
    _, guarded, _ = _render(3, True, AFFECTS[0])
    mel = lambda evs: [e for e in evs if e.layer == "melody"]
    assert mel(plain) != mel(guarded)
    # the guard only touches the melody: every other layer is byte-identical
    other = lambda evs: [e for e in evs if e.layer != "melody"]
    assert other(plain) == other(guarded)


def test_guard_is_deterministic():
    _, a, _ = _render(6, True, AFFECTS[1], dram=True)
    _, b, _ = _render(6, True, AFFECTS[1], dram=True)
    assert a == b
