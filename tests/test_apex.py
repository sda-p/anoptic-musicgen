"""A4 single-apex contour planning (REFINEMENT_PLAN.md): one planned melodic
peak per phrase behind MelodyConfig.plan_apex — a hard ceiling below the apex
for every other bar, the apex realized as a chord tone with leap-recovery
gap-fill, and the A1 hairpin cresting at the planned apex bar."""

from collections import defaultdict

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.modifiers import default_chains
from musicgen.verify import lint, lint_groove

AFFECT = {"valence": 0.2, "energy": 0.6, "tension": 0.35}


def _render(seed, bars=32, affect=AFFECT, **cfg):
    cfg.setdefault("melody", MelodyConfig(plan_apex=True))
    engine = MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable(), **cfg))
    engine.set_affect(**affect)
    return engine, [engine.advance_bar() for _ in range(bars)]


def _melody_by_phrase_bar(results, phrase, phrase_bars=8):
    by_bar: dict[int, list[int]] = defaultdict(list)
    for r in results[phrase * phrase_bars:(phrase + 1) * phrase_bars]:
        for ev in r.raw_events:
            if ev.layer == "melody":
                by_bar[r.bar - phrase * phrase_bars].append(ev.pitch)
    return by_bar


def test_non_apex_bars_stay_below_the_apex():
    for seed in (1, 2, 3):
        engine, results = _render(seed)
        for phrase in range(4):
            plan = engine.state.apexes[phrase]
            by_bar = _melody_by_phrase_bar(results, phrase)
            for pos, pitches in by_bar.items():
                if pos != plan.pos:
                    assert max(pitches) <= plan.pitch - 1, \
                        f"seed {seed} phrase {phrase} bar {pos} exceeds the apex ceiling"


def test_apex_bar_carries_the_phrase_peak():
    # the apex realizes as the nearest chord tone, so it may occasionally land
    # below the ceiling — soft by design (the plan); it must dominate overall
    hits = total = 0
    for seed in (1, 2, 3):
        engine, results = _render(seed)
        for phrase in range(4):
            plan = engine.state.apexes[phrase]
            by_bar = _melody_by_phrase_bar(results, phrase)
            if not by_bar:
                continue
            total += 1
            phrase_max = max(p for pitches in by_bar.values() for p in pitches)
            hits += plan.pos in by_bar and max(by_bar[plan.pos]) == phrase_max
    assert total >= 10 and hits / total >= 0.75, f"{hits}/{total}"


def test_apex_bar_never_rests():
    for seed in (1, 2, 3, 4):
        engine, results = _render(seed)
        for phrase in range(4):
            plan = engine.state.apexes[phrase]
            r = results[phrase * 8 + plan.pos]
            if "melody" in r.params.layers:
                assert any(e.layer == "melody" for e in r.raw_events), \
                    f"seed {seed} phrase {phrase}: apex bar rested"


def test_context_carries_the_apex_and_hairpin_crests_there():
    engine, results = _render(3, chains=default_chains(perform=True))
    for phrase in range(4):
        plan = engine.state.apexes[phrase]
        for r in results[phrase * 8:(phrase + 1) * 8]:
            assert r.context.phrase_apex == plan.pos
        # the shaped melody swells into the apex bar: louder there than at the open
        vel = {r.bar - phrase * 8: [e.velocity for e in r.events if e.layer == "melody"]
               for r in results[phrase * 8:(phrase + 1) * 8]}
        if vel.get(0) and vel.get(plan.pos):
            open_mean = sum(vel[0]) / len(vel[0])
            apex_mean = sum(vel[plan.pos]) / len(vel[plan.pos])
            assert apex_mean > open_mean, f"phrase {phrase}: no swell into the apex"


def test_apex_off_is_default():
    assert MelodyConfig().plan_apex is False
    assert EngineConfig().melody.plan_apex is False


def test_full_wave_a_stack_lints_clean():
    # A1+A2+A4 + dramaturg together — the playground configuration — through a
    # withhold-and-release arc, both lint stages plus the groove contract
    for seed in (1, 2, 3, 4):
        engine = MusicEngine(seed=seed, config=EngineConfig(
            mapper=MappingTable(), dramaturg=DramaturgConfig(),
            chains=default_chains(perform=True), cadence_rit=0.025,
            phrase_groove=True, melody=MelodyConfig(plan_apex=True)))
        engine.set_affect(valence=0.1, energy=0.7, tension=0.85)
        results = [engine.advance_bar() for _ in range(16)]
        engine.set_affect(tension=0.15)  # release: the spend phrase
        results += [engine.advance_bar() for _ in range(16)]
        contexts = [r.context for r in results]
        raw = [e for r in results for e in r.raw_events]
        final = [e for r in results for e in r.events]
        violations = (lint(raw, contexts, stage="pre")
                      + lint(final, contexts, stage="post")
                      + lint_groove(raw, contexts, {r.bar: r.params for r in results}))
        assert violations == [], f"seed {seed}:\n" + "\n".join(map(str, violations))
