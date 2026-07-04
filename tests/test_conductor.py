from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.verify import lint


def _run(seed=42, bars=32, **config_kwargs):
    engine = MusicEngine(seed=seed, config=EngineConfig(**config_kwargs))
    results = [engine.advance_bar() for _ in range(bars)]
    events = [ev for r in results for ev in r.events]
    contexts = [r.context for r in results]
    return results, events, contexts


def _lint_all(results):
    """Grid/melodic rules on the pre-modifier IR, bounds on what plays."""
    contexts = [r.context for r in results]
    raw = [ev for r in results for ev in r.raw_events]
    final = [ev for r in results for ev in r.events]
    return lint(raw, contexts, stage="pre") + lint(final, contexts, stage="post")


def test_32_bars_lint_clean():
    results, events, contexts = _run()
    assert events, "generator produced no events"
    assert len(contexts) == 32
    violations = _lint_all(results)
    assert violations == [], "\n".join(map(str, violations))


def test_lint_clean_across_seeds_and_modes():
    for seed in (1, 2, 3):
        for mode in ("ionian", "dorian", "aeolian"):
            results, _, _ = _run(seed=seed, bars=16, mode=mode)
            violations = _lint_all(results)
            assert violations == [], f"seed {seed} {mode}:\n" + "\n".join(map(str, violations))


def test_deterministic():
    _, events_a, _ = _run(seed=7)
    _, events_b, _ = _run(seed=7)
    assert events_a == events_b


def test_seeds_differ():
    _, events_a, _ = _run(seed=1)
    _, events_b, _ = _run(seed=2)
    assert events_a != events_b


def test_piece_opens_on_tonic():
    _, _, contexts = _run(bars=1)
    assert contexts[0].chord.degree == 1


def test_cadence_slots_populated():
    _, _, contexts = _run(bars=16)
    assert contexts[6].cadence_slot == "pre-cadence"
    assert contexts[7].cadence_slot == "cadence"
    assert contexts[7].cadence_policy == "authentic"  # first policy in the cycle
    assert contexts[15].cadence_policy == "half"
    assert contexts[7].chord.degree == 1
    assert contexts[15].chord.degree == 5


def test_next_chord_lookahead_consistent():
    results, _, _ = _run(bars=8)
    for a, b in zip(results, results[1:]):
        assert a.context.next_chord == b.context.chord


def test_layer_gating():
    _, events, _ = _run(bars=4, params=MusicalParams(layers=("pad",)))
    assert {e.layer for e in events} == {"pad"}


FULL_LAYERS = ("pad", "bass", "melody", "arp", "perc")


def test_full_texture_64_bars_lint_clean():
    results, events, contexts = _run(bars=64, params=MusicalParams(layers=FULL_LAYERS))
    assert {e.layer for e in events} == set(FULL_LAYERS)
    violations = _lint_all(results)
    assert violations == [], "\n".join(map(str, violations))


def test_full_texture_across_seeds_modes_densities():
    for seed in (1, 2):
        for mode in ("ionian", "dorian", "aeolian"):
            for density in (0.25, 0.55, 0.85):
                params = MusicalParams(note_density=density, roughness=density * 0.7, layers=FULL_LAYERS)
                results, _, _ = _run(seed=seed, bars=16, mode=mode, params=params)
                violations = _lint_all(results)
                assert violations == [], (
                    f"seed {seed} {mode} density {density}:\n" + "\n".join(map(str, violations))
                )


def test_full_texture_deterministic():
    _, a, _ = _run(seed=11, bars=16, params=MusicalParams(layers=FULL_LAYERS))
    _, b, _ = _run(seed=11, bars=16, params=MusicalParams(layers=FULL_LAYERS))
    assert a == b


def test_borrowed_chords_render_when_dark():
    # Low valence in a bright mode must still lint clean (borrowed pcs are
    # licensed by role, chord-tone checks use the borrowed pcs).
    results, _, _ = _run(seed=5, bars=32, valence=-0.9)
    violations = _lint_all(results)
    assert violations == [], "\n".join(map(str, violations))
