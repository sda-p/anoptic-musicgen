"""A2 groove persistence (REFINEMENT_PLAN.md): pattern-defining perc/arp draws
pinned per phrase behind EngineConfig.phrase_groove, and the lint_groove
contract checker that makes pattern identity verifiable."""

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import Meter
from musicgen.verify import lint, lint_groove

AFFECT = {"valence": 0.2, "energy": 0.8, "tension": 0.4}  # perc + arp both gated on


def _render(seed, bars=16, affect=AFFECT, **cfg):
    engine = MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable(), **cfg))
    engine.set_affect(**affect)
    return engine, [engine.advance_bar() for _ in range(bars)]


def _groove_violations(results, meter=Meter()):
    return lint_groove([e for r in results for e in r.raw_events],
                       [r.context for r in results],
                       {r.bar: r.params for r in results}, meter)


def test_phrase_groove_pins_pattern_identity():
    for seed in (1, 2, 3, 4):
        _, results = _render(seed, phrase_groove=True)
        assert _groove_violations(results) == []


def test_per_bar_rolls_break_the_contract():
    # the plant: without pinning, ghosts/hat-drops/arp-rests re-roll every bar
    # under stable levers, and the checker must catch it on every seed
    for seed in (1, 2, 3, 4):
        _, results = _render(seed, phrase_groove=False)
        rules = {v.rule for v in _groove_violations(results)}
        assert rules == {"groove-perc", "groove-arp"}, f"seed {seed}: {rules}"


def test_fills_stay_per_bar_variation():
    # pinning must not freeze the fills: cadence bars keep their per-bar roll
    fills = 0
    for seed in (1, 2, 3, 4, 5, 6):
        _, results = _render(seed, bars=32, phrase_groove=True)
        fills += sum(1 for r in results for line in r.trace if "fill" in line)
    assert fills > 0


def test_groove_off_is_default_and_feature_changes_output():
    assert EngineConfig().phrase_groove is False
    _, plain = _render(9, phrase_groove=False)
    _, pinned = _render(9, phrase_groove=True)
    perc = lambda rs: [e for r in rs for e in r.raw_events if e.layer == "perc"]
    assert perc(plain) != perc(pinned)
    # non-perc/arp layers draw from their own streams — untouched by the gate
    others = lambda rs: [e for r in rs for e in r.raw_events
                         if e.layer not in ("perc", "arp")]
    assert others(plain) == others(pinned)


def test_groove_deterministic():
    _, a = _render(5, phrase_groove=True)
    _, b = _render(5, phrase_groove=True)
    assert [r.events for r in a] == [r.events for r in b]


def test_groove_lint_clean_across_seeds():
    for seed in (1, 2, 3, 4):
        _, results = _render(seed, phrase_groove=True)
        contexts = [r.context for r in results]
        raw = [e for r in results for e in r.raw_events]
        final = [e for r in results for e in r.events]
        violations = lint(raw, contexts, stage="pre") + lint(final, contexts, stage="post")
        assert violations == [], f"seed {seed}:\n" + "\n".join(map(str, violations))


def test_groove_in_compound_meter():
    meter = Meter(6, 8)
    _, results = _render(2, meter=meter, phrase_groove=True)
    assert _groove_violations(results, meter) == []
