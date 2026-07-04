from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.theory.modulation import fifths_between, find_pivots
from musicgen.theory.scales import Scale
from musicgen.verify import lint

FULL_LAYERS = ("pad", "bass", "melody", "arp", "perc")


def _lint_all(results):
    contexts = [r.context for r in results]
    raw = [ev for r in results for ev in r.raw_events]
    final = [ev for r in results for ev in r.events]
    return lint(raw, contexts, stage="pre") + lint(final, contexts, stage="post")


def _assert_clean(results, label=""):
    violations = _lint_all(results)
    assert violations == [], f"{label}:\n" + "\n".join(map(str, violations))


# --- pure theory ---------------------------------------------------------------


def test_find_pivots_c_to_g():
    pivots = find_pivots(Scale(0, "ionian"), Scale(7, "ionian"))
    pairs = {(p.old_degree, p.new_degree) for p in pivots}
    # C=IV, Em=vi, G=I, Am=ii — the four consonant common triads
    assert pairs == {(1, 4), (3, 6), (5, 1), (6, 2)}
    assert pivots[0].new_degree == 2, "best pivot should be the new key's ii (Am)"
    assert pivots[-1].old_degree == 5, "the old V pulls backward; ranked last"


def test_find_pivots_skip_diminished():
    for p in find_pivots(Scale(0, "aeolian"), Scale(5, "aeolian")):
        assert 0 not in {p.old_degree % 7, p.new_degree % 7} or True  # shape check below
        # neither side may be a diminished triad
        from musicgen.theory.chords import Chord
        assert Chord(p.old_degree).quality(Scale(0, "aeolian")) != "dim"
        assert Chord(p.new_degree).quality(Scale(5, "aeolian")) != "dim"


def test_find_pivots_distant_keys_empty():
    assert find_pivots(Scale(0, "ionian"), Scale(6, "ionian")) == []


def test_fifths_between():
    assert fifths_between(0, 7) == 1     # C -> G, one sharp
    assert fifths_between(0, 5) == -1    # C -> F, one flat
    assert fifths_between(0, 2) == 2     # C -> D
    assert fifths_between(0, 10) == -2   # C -> Bb
    assert fifths_between(0, 6) == 6     # tritone: the far pole
    assert fifths_between(0, 0) == 0
    assert fifths_between(9, 4) == 1     # A -> E, relative to any anchor


# --- engine integration --------------------------------------------------------


def test_modulation_rides_the_phrase_cadence():
    engine = MusicEngine(seed=42, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    engine.request_key("G")
    results = [engine.advance_bar() for _ in range(16)]
    contexts = [r.context for r in results]

    # phrase_bars=8: pivot at bar 5 (free), V7 at 6 (pre-cadence), I at 7 (cadence)
    assert "pivot" in contexts[5].modulation
    assert contexts[5].scale.tonic == 0, "pivot bar is still analyzed in the old key"
    assert contexts[6].scale.tonic == 7, "the scale flips at the new key's dominant"
    assert contexts[6].chord.degree == 5 and "7" in contexts[6].chord.extensions
    assert contexts[6].cadence_slot == "pre-cadence"
    assert contexts[6].cadence_policy == "authentic", "a modulation forces an authentic cadence"
    assert contexts[7].chord.degree == 1 and contexts[7].cadence_slot == "cadence"
    assert all(c.scale.tonic == 7 for c in contexts[8:]), "the new key persists"
    _assert_clean(results, "modulation C->G")


def test_urgent_modulation_starts_at_first_ungenerated_bar():
    engine = MusicEngine(seed=42, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    results = [engine.advance_bar() for _ in range(3)]  # chords generated through bar 3
    engine.request_key(5, urgent=True)
    results += [engine.advance_bar() for _ in range(9)]
    contexts = [r.context for r in results]

    assert "pivot" in contexts[4].modulation or contexts[5].modulation, "window opens at bar 5 (0-based 4)"
    assert contexts[5].scale.tonic == 5, "dominant bar flips to F"
    assert contexts[6].chord.degree == 1
    assert all(c.scale.tonic == 5 for c in contexts[6:])
    _assert_clean(results, "urgent modulation C->F")


def test_urgent_window_disarms_overlapped_cadence_slots():
    # Request timed so the 3-bar window overlaps bars 6..8 (pre-cadence + cadence).
    engine = MusicEngine(seed=9, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    results = [engine.advance_bar() for _ in range(5)]
    engine.request_key("D", urgent=True)
    results += [engine.advance_bar() for _ in range(11)]
    contexts = [r.context for r in results]

    window = [c for c in contexts if c.modulation]
    assert window, "modulation window must exist"
    for c in window:
        assert c.cadence_slot == "", "urgent plans supersede the cadence slots they overlap"
    _assert_clean(results, "urgent window over cadence")


def test_all_twelve_targets_lint_clean():
    for target in range(12):
        engine = MusicEngine(seed=3, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
        engine.request_key(target)
        results = [engine.advance_bar() for _ in range(16)]
        assert results[-1].context.scale.tonic == target
        _assert_clean(results, f"target pc {target}")


def test_direct_modulation_when_no_common_chord():
    engine = MusicEngine(seed=3, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    engine.request_key(6)  # C -> F#: no shared triad
    results = [engine.advance_bar() for _ in range(16)]
    dominant_traces = [line for r in results for line in r.trace if "modulation dominant" in line]
    assert dominant_traces and "direct" in dominant_traces[0]
    assert all(not c.modulation or "pivot" not in c.modulation for c in (r.context for r in results))


def test_modulation_deterministic_and_seed_sensitive():
    def run(seed):
        engine = MusicEngine(seed=seed, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
        engine.request_key("Eb")
        return [ev for _ in range(16) for ev in engine.advance_bar().events]

    assert run(7) == run(7)
    assert run(7) != run(8)


def test_request_current_key_is_noop():
    engine = MusicEngine(seed=42, config=EngineConfig())
    engine.request_key(0)
    results = [engine.advance_bar() for _ in range(16)]
    assert all(c.scale.tonic == 0 and not c.modulation for c in (r.context for r in results))


def test_chained_requests_latest_pending_wins():
    engine = MusicEngine(seed=42, config=EngineConfig())
    engine.request_key("G")
    engine.request_key("F")  # replaces the pending G before any plan forms
    results = [engine.advance_bar() for _ in range(16)]
    assert results[-1].context.scale.tonic == 5


def test_mode_holds_during_modulation_window():
    engine = MusicEngine(seed=42, config=EngineConfig(mapper=MappingTable(), valence=0.9))
    results = [engine.advance_bar() for _ in range(3)]
    engine.request_key("G", urgent=True)
    results.append(engine.advance_bar())  # bar 4: plan formed during this bar's look-ahead
    window_mode = results[-1].context.scale.mode
    engine.set_affect(valence=-0.9, urgent=True)  # would flip the mode at the next barline
    results += [engine.advance_bar() for _ in range(8)]
    contexts = [r.context for r in results]

    arrival = next(i for i, c in enumerate(contexts) if "arrival" in c.modulation)
    for c in contexts[4 : arrival + 1]:
        assert c.scale.mode == window_mode, "mode must hold while the window is active"
    assert contexts[arrival + 1].scale.mode != window_mode, "deferred urgent flag fires after arrival"


def test_wander_walks_and_springs_home():
    cfg = EngineConfig(params=MusicalParams(layers=FULL_LAYERS), wander_phrases=1, valence=0.6)
    engine = MusicEngine(seed=11, config=cfg)
    results = [engine.advance_bar() for _ in range(64)]
    tonics = []
    for r in results:
        if not tonics or r.context.scale.tonic != tonics[-1]:
            tonics.append(r.context.scale.tonic)

    assert len(tonics) >= 4, f"wander should modulate repeatedly, saw {tonics}"
    for a, b in zip(tonics, tonics[1:]):
        assert abs(fifths_between(a, b)) == 1, "wander moves one fifth at a time"
    assert all(abs(fifths_between(0, t)) <= 2 for t in tonics), "spring keeps orbit within ±2 fifths"
    _assert_clean(results, "wander")


def test_wander_off_by_default():
    engine = MusicEngine(seed=11, config=EngineConfig(params=MusicalParams(layers=FULL_LAYERS)))
    results = [engine.advance_bar() for _ in range(32)]
    assert {r.context.scale.tonic for r in results} == {0}
