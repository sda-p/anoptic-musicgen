import random

from musicgen.gen.melody import (
    MelodyConfig, Motif, _contour_offsets, _diatonic_shift, make_motif, phrase_variant,
)
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.theory.scales import Scale

FULL = MusicalParams(layers=("pad", "bass", "melody", "arp", "perc"))


def _run(seed=42, bars=32, **kwargs):
    kwargs.setdefault("params", FULL)
    engine = MusicEngine(seed=seed, config=EngineConfig(**kwargs))
    results = [engine.advance_bar() for _ in range(bars)]
    events = [ev for r in results for ev in r.raw_events]  # pre-modifier IR
    return results, events, [r.context for r in results]


def test_make_motif_deterministic():
    a = make_motif(random.Random(5), 0.5, 0.3, MelodyConfig())
    b = make_motif(random.Random(5), 0.5, 0.3, MelodyConfig())
    assert a == b
    assert len(a.rhythm) == len(a.contour)


def test_contour_shapes():
    assert _contour_offsets("ascent", 5, 4) == (0, 1, 2, 3, 4)
    assert _contour_offsets("descent", 5, 4) == (4, 3, 2, 1, 0)
    arch = _contour_offsets("arch", 5, 4)
    assert arch[0] == arch[-1] == 0 and max(arch) == 4
    assert _contour_offsets("zigzag", 1, 3) == (0,)


def test_variations_preserve_shape_invariants():
    motif = Motif(((0, 2), (2, 2), (4, 4), (8, 8)), (0, 1, 2, 1), "arch")
    for pos in range(8):
        varied, op = phrase_variant(motif, pos, random.Random(pos))
        assert len(varied.rhythm) == len(varied.contour), op
        assert all(s + d <= 16 for s, d in varied.rhythm), op


def test_diatonic_shift():
    c_ionian = Scale(0, "ionian")
    assert _diatonic_shift(c_ionian, 60, 1) == 62
    assert _diatonic_shift(c_ionian, 60, -1) == 59
    assert _diatonic_shift(c_ionian, 64, 1) == 65  # E->F half step
    assert _diatonic_shift(c_ionian, 60, 7) == 72  # diatonic octave


def test_melody_strong_beats_are_chord_tones():
    _, events, contexts = _run(bars=32)
    ctx_by_bar = {c.bar: c for c in contexts}
    strong = set()
    melody_strong = []
    for e in events:
        if e.layer != "melody":
            continue
        bar, slot = int(e.start // 4), round((e.start % 4) / 0.25)
        if slot in (0, 4, 8, 12):
            melody_strong.append((e, ctx_by_bar[bar]))
    assert melody_strong, "expected strong-beat melody notes"
    chordal = sum(1 for e, c in melody_strong if e.pitch % 12 in c.chord_pcs)
    assert chordal / len(melody_strong) >= 0.8


def test_cadence_bar_lands_on_policy_target():
    _, events, contexts = _run(bars=16)
    for cadence_bar in (7, 15):
        ctx = contexts[cadence_bar]
        bar_events = [e for e in events if e.layer == "melody" and int(e.start // 4) == cadence_bar]
        assert bar_events, f"no cadence melody in bar {cadence_bar}"
        last = max(bar_events, key=lambda e: e.start)
        assert last.pitch % 12 in ctx.chord_pcs, "cadence target must be a chord tone"


def test_melody_register_window():
    _, events, _ = _run(bars=32)
    center = FULL.register_center
    for e in events:
        if e.layer == "melody":
            assert center - 14 <= e.pitch <= center + 14


def test_same_seed_same_melody():
    _, a, _ = _run(seed=9, bars=12)
    _, b, _ = _run(seed=9, bars=12)
    assert [e for e in a if e.layer == "melody"] == [e for e in b if e.layer == "melody"]
