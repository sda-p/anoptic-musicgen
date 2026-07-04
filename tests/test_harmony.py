import random

from musicgen.theory.harmony import CADENCE_TARGET, HarmonyConfig, next_chord

CFG = HarmonyConfig()


def _step(rng, prev=None, slot="free", policy="authentic", tension=0.45,
          valence=0.3, mode="ionian", phrase_start=False, piece_start=False):
    return next_chord(
        prev=prev, slot=slot, cadence_policy=policy, tension=tension,
        valence=valence, mode=mode, phrase_start=phrase_start,
        piece_start=piece_start, cfg=CFG, rng=rng,
    )


def test_piece_start_establishes_tonic():
    chord, why = _step(random.Random(1), piece_start=True)
    assert chord.degree == 1
    assert "tonic" in why


def test_cadence_targets_all_policies():
    for seed in range(20):
        for policy, degree in CADENCE_TARGET.items():
            chord, _ = _step(random.Random(seed), slot="cadence", policy=policy, tension=0.6)
            assert chord.degree == degree, (policy, seed)


def test_pre_cadence_prepares_policy():
    for seed in range(20):
        chord, _ = _step(random.Random(seed), slot="pre-cadence", policy="authentic")
        assert chord.degree in (5, 7)
        chord, _ = _step(random.Random(seed), slot="pre-cadence", policy="half")
        assert chord.degree in (2, 4)


def test_deterministic_given_rng():
    a, _ = _step(random.Random(7), tension=0.6)
    b, _ = _step(random.Random(7), tension=0.6)
    assert a == b


def test_dissonance_budget_tiers():
    low = [_step(random.Random(s), tension=0.1)[0] for s in range(60)]
    assert all(c.extensions == () for c in low)
    high = [_step(random.Random(s), tension=0.9)[0] for s in range(60)]
    assert any(c.extensions for c in high)


def test_borrowing_needs_negative_valence_and_bright_mode():
    dark_valence = [_step(random.Random(s), valence=-1.0)[0] for s in range(200)]
    assert any(c.source_mode == "aeolian" for c in dark_valence)
    bright_valence = [_step(random.Random(s), valence=0.5)[0] for s in range(200)]
    assert all(c.source_mode is None for c in bright_valence)
    already_dark = [_step(random.Random(s), valence=-1.0, mode="aeolian")[0] for s in range(200)]
    assert all(c.source_mode is None for c in already_dark)


def test_walk_runs_and_stays_legal():
    rng = random.Random(3)
    prev = None
    for bar in range(200):
        prev, _ = _step(rng, prev=prev, tension=0.5, phrase_start=bar % 8 == 0,
                        piece_start=bar == 0)
        assert 1 <= prev.degree <= 7
