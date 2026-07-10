"""Wave-C polyphony tests (REFINEMENT_PLAN C1–C3, PLANS.md M23).

C1 parallel doubling: a companion line in diatonic 3rds/6ths inside the melody
layer — simultaneous with its source, chord-member on strong slots, quieter,
invisible to the melodic-line/outer-voice/period linters, and byte-identical
when off. Every generator rule is mirrored by verify._lint_doubling, and the
poisoned plants prove the mirror is live.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, FormConfig, MusicEngine, TextureConfig
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.ir import NoteEvent
from musicgen.theory.counterpoint import interval_class
from musicgen.verify import (
    lint, lint_groove, lint_imitation, lint_outer, lint_periods, lint_texture,
)

BRIGHT = dict(valence=0.55, energy=0.75, tension=0.3)  # opens the C1 interim gate


def run(seed=42, bars=24, affect=BRIGHT, texture=None, dramaturg=None, **cfg_kw):
    cfg = EngineConfig(mapper=MappingTable(), chains={}, dramaturg=dramaturg,
                       texture=texture or TextureConfig(), **cfg_kw)
    engine = MusicEngine(seed=seed, config=cfg)
    engine.set_affect(**affect)
    results = [engine.advance_bar() for _ in range(bars)]
    return engine, results


def raw(results):
    return [ev for r in results for ev in r.raw_events]


def full_stack(doubling=True, animate=False, imitation=False):
    return dict(phrase_groove=True, cadence_rit=0.02,
                melody=MelodyConfig(plan_apex=True, counterpoint=True),
                form=FormConfig(cadential_64=True, periods=True,
                                hypermeter=True, bass_inversions=True),
                texture=TextureConfig(doubling=doubling, animate=animate,
                                      imitation=imitation))


# --- C1 doubling --------------------------------------------------------------

def test_texture_config_off_is_byte_identical():
    _, base = run()
    _, off = run(texture=TextureConfig())
    assert [r.raw_events for r in base] == [r.raw_events for r in off]


def test_doubling_gate_closed_at_calm_affect():
    calm = dict(valence=0.1, energy=0.4, tension=0.3)
    _, plain = run(affect=calm)
    _, gated = run(affect=calm, texture=TextureConfig(doubling=True))
    assert [r.raw_events for r in plain] == [r.raw_events for r in gated]
    assert not [e for r in gated for e in r.raw_events if e.role == "doubling"]


def test_doubling_leaves_the_surface_untouched():
    _, plain = run()
    _, doubled = run(texture=TextureConfig(doubling=True))
    surface = [[e for e in r.raw_events if e.role != "doubling"] for r in doubled]
    assert surface == [r.raw_events for r in plain]


def test_doubling_contract_thirds_sixths_below():
    _, results = run(texture=TextureConfig(doubling=True))
    events = raw(results)
    doubles = [e for e in events if e.role == "doubling"]
    assert len(doubles) > 20, "the bright affect should double most melody notes"
    surface = [e for e in events if e.layer == "melody" and e.role != "doubling"]
    for d in doubles:
        src = [m for m in surface if abs(m.start - d.start) < 1e-9 and m.pitch > d.pitch]
        assert src, f"doubling at {d.start} has no simultaneous source above"
        assert interval_class(d.pitch, src[0].pitch) in (3, 4, 8, 9)
        assert d.velocity < src[0].velocity


def test_doubling_strong_slots_are_chord_members():
    engine, results = run(texture=TextureConfig(doubling=True))
    strong = set(engine.config.meter.strong_slots())
    ctx_by_bar = {r.bar: r.context for r in results}
    meter = engine.config.meter
    checked = 0
    for e in raw(results):
        if e.role == "doubling" and meter.slot_of(e.start) in strong:
            assert e.pitch % 12 in ctx_by_bar[meter.bar_of(e.start)].chord_pcs
            checked += 1
    assert checked > 5


def test_doubling_full_stack_lints_clean():
    for dram in (None, DramaturgConfig()):
        for seed in (3, 11, 19):
            engine, results = run(seed=seed, bars=32, dramaturg=dram, **full_stack())
            events, ctxs = raw(results), [r.context for r in results]
            violations = (lint(events, ctxs) + lint_outer(events, ctxs)
                          + lint_periods(events, ctxs)
                          + lint_groove(events, ctxs, {r.bar: r.params for r in results}))
            assert not violations, "\n".join(map(str, violations))


def test_doubling_plant_wrong_interval_is_caught():
    _, results = run(texture=TextureConfig(doubling=True))
    events, ctxs = raw(results), [r.context for r in results]
    idx = next(i for i, e in enumerate(events) if e.role == "doubling")
    events[idx] = replace(events[idx], pitch=events[idx].pitch - 2)  # no longer a 3rd/6th
    assert any(v.rule == "doubling" for v in lint(events, ctxs))


def test_doubling_plant_orphan_is_caught():
    _, results = run(texture=TextureConfig(doubling=True))
    events, ctxs = raw(results), [r.context for r in results]
    d = next(e for e in events if e.role == "doubling")
    orphan = replace(d, start=d.start + 0.125)  # off its source's onset (and off-grid is a
    events.append(orphan)                       # separate rule; doubling fires regardless)
    assert any(v.rule == "doubling" for v in lint(events, ctxs))


def test_doubling_deterministic():
    _, a = run(texture=TextureConfig(doubling=True))
    _, b = run(texture=TextureConfig(doubling=True))
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


# --- C2 inner-voice animation ---------------------------------------------------

CALM = dict(valence=0.1, energy=0.25, tension=0.25)  # density < 0.40 -> connective
MID = dict(valence=0.3, energy=0.5, tension=0.35)    # density < 0.62 -> comping


def animated_traces(results, kind=""):
    return [line for r in results for line in r.trace
            if "animate:" in line and (kind in line)]


def test_animate_off_is_byte_identical():
    _, plain = run(affect=MID)
    _, off = run(affect=MID, texture=TextureConfig(doubling=True))  # other toggles inert
    assert [r.raw_events for r in plain] == [r.raw_events for r in off]


def test_animate_connective_walks_toward_the_next_voicing():
    _, results = run(affect=CALM, texture=TextureConfig(animate=True))
    walks = animated_traces(results, "walks toward")
    assert walks, "sparse bars should get connective passing tones"
    events = raw(results)
    v = lint(events, [r.context for r in results])
    assert not v, "\n".join(map(str, v))


def test_animate_comping_breaks_the_block():
    _, results = run(affect=MID, texture=TextureConfig(animate=True))
    assert animated_traces(results, "comping")
    events = raw(results)
    v = lint(events, [r.context for r in results])
    assert not v, "\n".join(map(str, v))
    # comping notes are chord tones struck one at a time on the pulse grid
    for r in results:
        if any("comping" in line for line in r.trace):
            pads = [e for e in r.raw_events if e.layer == "pad"]
            starts = {e.start for e in pads}
            assert len(starts) == len(pads), "comping strikes voices one at a time"
            for e in pads:
                assert e.pitch % 12 in r.context.chord_pcs


def test_animate_keeps_voice_leading_memory():
    eng_on, _ = run(affect=MID, texture=TextureConfig(animate=True))
    eng_off, _ = run(affect=MID)
    assert eng_on.state.prev_voicing == eng_off.state.prev_voicing, \
        "the returned voicing must stay the block target"


def test_animate_stands_down_for_the_suspension_zone():
    tense = dict(valence=0.2, energy=0.5, tension=0.75)
    engine, results = run(bars=40, affect=tense, dramaturg=DramaturgConfig(),
                          texture=TextureConfig(animate=True))
    bars = engine.config.phrase_bars
    controlled = {r.bar for r in results
                  if engine.state.ledger.phrase_cadence.get(r.bar // bars) is not None
                  and r.bar % bars >= bars - 3}
    for r in results:
        if r.bar in controlled:
            assert not any("animate:" in line for line in r.trace), \
                f"bar {r.bar} in the suspension zone must not figurate"
    events = raw(results)
    v = lint(events, [r.context for r in results])
    assert not v, "\n".join(map(str, v))


def test_animate_deterministic():
    _, a = run(affect=MID, texture=TextureConfig(animate=True))
    _, b = run(affect=MID, texture=TextureConfig(animate=True))
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


# --- C3 imitation ---------------------------------------------------------------

ACTIVE = dict(valence=0.4, energy=0.7, tension=0.35)


def test_imitation_one_entry_per_phrase():
    engine, results = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    bars = engine.config.phrase_bars
    entries = {r.bar // bars for r in results
               for line in r.trace if line.startswith("imitation:")}
    assert entries == set(engine.state.imitation_cells)
    assert len(entries) == 24 // bars, "every phrase gets its echo"
    for r in results:  # the entry lands the bar after the statement
        if any(line.startswith("imitation:") for line in r.trace):
            assert r.bar % bars == 1


def test_imitation_carries_the_cell():
    engine, results = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    events, ctxs = raw(results), [r.context for r in results]
    imit = [e for e in events if e.role == "imitation"]
    assert imit
    violations = lint_imitation(events, ctxs, engine.state.imitation_cells)
    assert not violations, "\n".join(map(str, violations))
    assert not lint(events, ctxs)


def test_imitation_pad_hosts_while_arp_is_withheld():
    engine, results = run(bars=40, affect=dict(valence=0.2, energy=0.7, tension=0.8),
                          dramaturg=DramaturgConfig(),
                          texture=TextureConfig(imitation=True))
    hosts = {e.layer for e in raw(results) if e.role == "imitation"}
    assert "pad" in hosts, "the echo must survive the dramaturg holding the arp"


def test_imitation_mostly_clean_entries():
    tolerated = entries = 0
    for seed in range(8):
        _, results = run(seed=seed, affect=ACTIVE, texture=TextureConfig(imitation=True))
        for r in results:
            for line in r.trace:
                if line.startswith("imitation:"):
                    entries += 1
                    tolerated += "tolerated" in line
    assert entries >= 20
    assert tolerated / entries < 0.5, "the retry list should resolve most clashes"


def test_imitation_plant_corrupted_entry_is_caught():
    engine, results = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    events, ctxs = raw(results), [r.context for r in results]
    idx = next(i for i, e in enumerate(events) if e.role == "imitation")
    events[idx] = replace(events[idx], pitch=events[idx].pitch + 6)  # break the contour
    assert any(v.rule == "imitation"
               for v in lint_imitation(events, ctxs, engine.state.imitation_cells))


def test_imitation_plant_missing_cell_is_caught():
    _, results = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    events, ctxs = raw(results), [r.context for r in results]
    assert any(v.rule == "imitation" for v in lint_imitation(events, ctxs, {}))


def test_imitation_deterministic():
    _, a = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    _, b = run(affect=ACTIVE, texture=TextureConfig(imitation=True))
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


# --- C4 texture as a Tier-2 parameter -------------------------------------------

ROTATE = TextureConfig(doubling=True, animate=True, imitation=True, rotate=True)


def phrase_textures(engine):
    return [engine.state.phrase_textures[p] for p in sorted(engine.state.phrase_textures)]


def test_texture_rotation_never_repeats():
    for seed in (1, 7, 23):
        engine, _ = run(seed=seed, bars=48, affect=ACTIVE, texture=ROTATE)
        seq = phrase_textures(engine)
        assert len(seq) == 6
        assert all(a != b for a, b in zip(seq, seq[1:])), seq


def test_texture_params_carry_the_state():
    engine, results = run(bars=16, affect=ACTIVE, texture=ROTATE)
    for r in results:
        assert r.params.texture == engine.state.phrase_textures[r.bar // engine.config.phrase_bars]


def test_texture_dramaturg_clamps_then_releases_the_richest():
    cfg_kw = dict(affect=dict(valence=0.3, energy=0.6, tension=0.8),
                  dramaturg=DramaturgConfig(), texture=ROTATE)
    engine, results = run(bars=8, **cfg_kw)
    # keep driving tension high, then release it
    for _ in range(16):
        results.append(engine.advance_bar())
    engine.set_affect(tension=0.15)
    for _ in range(8):
        results.append(engine.advance_bar())
    seq = phrase_textures(engine)
    assert seq[:3] == ["homophonic"] * 3, "withholding clamps the texture"
    assert seq[3] == "imitative", "the spend releases the richest enabled state"


def test_texture_monophonic_thins_the_pad():
    engine, results = run(affect=dict(valence=0.0, energy=0.2, tension=0.2), texture=ROTATE)
    mono = [r for r in results if r.params.texture == "monophonic"]
    assert mono, "calm affect should reach the monophonic state"
    for r in mono:
        starts: dict[float, int] = {}
        for e in r.raw_events:
            if e.layer == "pad":
                starts[e.start] = starts.get(e.start, 0) + 1
        assert starts and max(starts.values()) <= 2


def test_texture_consequent_keeps_the_questions_texture():
    from musicgen.gen.conductor import FormConfig
    found = False
    for seed in range(12):
        engine, _ = run(seed=seed, bars=48, affect=ACTIVE, texture=ROTATE,
                        form=FormConfig(periods=True))
        for phrase, role in engine.state.planner.periods.items():
            if role == "consequent" and phrase in engine.state.phrase_textures:
                assert (engine.state.phrase_textures[phrase]
                        == engine.state.phrase_textures[phrase - 1])
                found = True
    assert found, "no period committed across 12 seeds"


def test_texture_override_pins_the_state():
    cfg = EngineConfig(mapper=MappingTable(), chains={}, texture=ROTATE)
    engine = MusicEngine(seed=42, config=cfg)
    engine.set_affect(**ACTIVE)
    engine.set_override("texture", "doubled")
    results = [engine.advance_bar() for _ in range(16)]
    assert all(r.params.texture == "doubled" for r in results)
    assert any(e.role == "doubling" for r in results for e in r.raw_events)


def test_texture_claims_lint_clean():
    for seed in (3, 11):
        for affect in (ACTIVE, dict(valence=0.0, energy=0.25, tension=0.3)):
            engine, results = run(seed=seed, bars=32, affect=affect, texture=ROTATE)
            events, ctxs = raw(results), [r.context for r in results]
            pbb = {r.bar: r.params for r in results}
            violations = (lint(events, ctxs) + lint_texture(events, ctxs, pbb)
                          + lint_imitation(events, ctxs, engine.state.imitation_cells))
            assert not violations, "\n".join(map(str, violations))


def test_texture_plant_broken_claim_is_caught():
    engine, results = run(bars=32, affect=ACTIVE, texture=ROTATE)
    events, ctxs = raw(results), [r.context for r in results]
    pbb = {r.bar: r.params for r in results}
    doubled_phrases = [p for p, t in engine.state.phrase_textures.items() if t == "doubled"]
    assert doubled_phrases
    stripped = [e for e in events if not (e.role == "doubling"
                and meter_bar(e, engine) // engine.config.phrase_bars in doubled_phrases)]
    assert any(v.rule == "texture" for v in lint_texture(stripped, ctxs, pbb))


def meter_bar(e, engine):
    return engine.config.meter.bar_of(e.start)


def test_texture_plant_polyphony_in_a_lean_phrase_is_caught():
    engine, results = run(bars=32, affect=dict(valence=0.0, energy=0.25, tension=0.3),
                          texture=ROTATE)
    events, ctxs = raw(results), [r.context for r in results]
    pbb = {r.bar: r.params for r in results}
    lean = next(p for p, t in engine.state.phrase_textures.items()
                if t in ("monophonic", "homophonic"))
    start = lean * engine.config.phrase_bars * engine.config.meter.bar_quarters
    events.append(NoteEvent(start, 1.0, 65, 60, "melody", role="doubling"))
    assert any(v.rule == "texture" for v in lint_texture(events, ctxs, pbb))


def test_full_wave_c_stack_lints_clean():
    for dram in (None, DramaturgConfig()):
        for seed in (5, 13):
            engine, results = run(seed=seed, bars=32, dramaturg=dram,
                                  **full_stack(doubling=True, animate=True, imitation=True))
            events, ctxs = raw(results), [r.context for r in results]
            violations = (lint(events, ctxs) + lint_outer(events, ctxs)
                          + lint_periods(events, ctxs)
                          + lint_groove(events, ctxs, {r.bar: r.params for r in results})
                          + lint_imitation(events, ctxs, engine.state.imitation_cells))
            assert not violations, "\n".join(map(str, violations))


# --- C5 countermelody + guide tones ----------------------------------------------

COUNTER = TextureConfig(counter=True)  # un-rotated: energy-gated, every bar
ALL_ON = TextureConfig(doubling=True, animate=True, imitation=True,
                       rotate=True, counter=True)


def counter_run(seed=42, bars=24, affect=ACTIVE, **kw):
    return run(seed=seed, bars=bars, affect=affect, texture=COUNTER, **kw)


def test_guide_line_moves_minimally():
    from musicgen.theory.chords import Chord
    from musicgen.theory.guides import guide_line, guide_pcs
    from musicgen.theory.scales import Scale
    c = Scale(0, "ionian")
    prog = [(Chord(d), c) for d in (1, 4, 5, 1, 6, 2, 5, 1)]
    line = guide_line(prog)
    assert line[0] == guide_pcs(Chord(1), c)[0], "the thread opens on the 3rd"
    for a, b in zip(line, line[1:]):
        assert min((b - a) % 12, (a - b) % 12) <= 4, "guide tones move by common tone or step-ish"


def test_counter_obeys_the_species_rules():
    engine, results = counter_run()
    events = raw(results)
    ctr = [e for e in events if e.layer == "counter"]
    assert len(ctr) > 15
    meter = engine.config.meter
    strong = set(meter.strong_slots())
    melody = sorted((e for e in events if e.layer == "melody" and e.role != "doubling"),
                    key=lambda e: e.start)
    ctx_by_bar = {r.bar: r.context for r in results}
    for e in ctr:
        assert 55 <= e.pitch <= 79
        m = next((x for x in melody if x.start - 1e-9 <= e.start < x.end - 1e-9), None)
        if m is not None:
            assert e.pitch <= m.pitch, "the counter never crosses above the melody"
        if meter.slot_of(e.start) in strong:
            assert e.pitch % 12 in ctx_by_bar[meter.bar_of(e.start)].chord_pcs
    violations = lint(events, [r.context for r in results])
    assert not violations, "\n".join(map(str, violations))


def test_counter_moves_in_the_melodys_holes():
    engine, results = counter_run()
    meter = engine.config.meter
    overlap = onsets = 0
    for r in results:
        mel_slots = {meter.slot_of(e.start) for e in r.raw_events
                     if e.layer == "melody" and e.role != "doubling"}
        for e in r.raw_events:
            if e.layer == "counter" and meter.slot_of(e.start) != 0:
                onsets += 1
                overlap += meter.slot_of(e.start) in mel_slots
    assert onsets >= 10
    assert overlap / onsets <= 0.4


def test_counter_gated_by_energy_when_unrotated():
    _, calm = counter_run(affect=dict(valence=0.2, energy=0.35, tension=0.3))
    assert not [e for r in calm for e in r.raw_events if e.layer == "counter"]


def test_counter_withheld_then_released_as_the_payoff():
    cfg = EngineConfig(mapper=MappingTable(), chains={}, dramaturg=DramaturgConfig(),
                       texture=ALL_ON)
    engine = MusicEngine(seed=7, config=cfg)
    engine.set_affect(valence=0.3, energy=0.6, tension=0.8)
    results = [engine.advance_bar() for _ in range(24)]
    engine.set_affect(tension=0.15)
    results += [engine.advance_bar() for _ in range(8)]
    bars = engine.config.phrase_bars
    withheld = [e for r in results if r.bar < 24 for e in r.raw_events if e.layer == "counter"]
    released = [e for r in results if r.bar >= 24 for e in r.raw_events if e.layer == "counter"]
    assert not withheld, "the counter is part of the withheld texture debt"
    assert released, "the spend releases the countermelody"
    assert engine.state.phrase_textures[3] == "counter"


def test_counter_plant_crossing_is_caught():
    engine, results = counter_run()
    events, ctxs = raw(results), [r.context for r in results]
    melody = [e for e in events if e.layer == "melody" and e.role != "doubling"]
    idx, m = next((i, m) for i, e in enumerate(events) if e.layer == "counter"
                  for m in melody if m.start - 1e-9 <= e.start < m.end - 1e-9)
    events[idx] = replace(events[idx], pitch=min(127, m.pitch + 2))
    assert any(v.rule == "counter-crossing" for v in lint(events, ctxs))


def test_counter_plant_parallel_is_caught():
    engine, results = counter_run(bars=48, affect=dict(valence=0.3, energy=0.55, tension=0.3))
    events, ctxs = raw(results), [r.context for r in results]
    meter = engine.config.meter
    strong = set(meter.strong_slots())
    melody = sorted((e for e in events if e.layer == "melody" and e.role != "doubling"),
                    key=lambda e: e.start)

    def melody_at(t):
        return next((m for m in melody if m.start - 1e-9 <= t < m.end - 1e-9), None)

    ctr = sorted(((i, e) for i, e in enumerate(events)
                  if e.layer == "counter" and meter.slot_of(e.start) in strong),
                 key=lambda ie: ie[1].start)
    planted = False
    for (i1, c1), (i2, c2) in zip(ctr, ctr[1:]):
        m1, m2 = melody_at(c1.start), melody_at(c2.start)
        if (m1 is not None and m2 is not None and m1.pitch != m2.pitch
                and c2.start - c1.start <= meter.bar_quarters):
            events[i1] = replace(c1, pitch=m1.pitch - 12)
            events[i2] = replace(c2, pitch=m2.pitch - 12)  # parallel octaves
            planted = True
            break
    assert planted, "no plantable strong pair found"
    assert any(v.rule == "counter-parallel" for v in lint(events, ctxs))


def test_counter_plant_overlap_is_caught():
    engine, results = counter_run()
    events, ctxs = raw(results), [r.context for r in results]
    meter = engine.config.meter
    melody = [e for e in events if e.layer == "melody" and e.role != "doubling"
              and meter.slot_of(e.start) != 0]
    for m in melody[:40]:  # shadow the melody's own onsets — the anti-counter
        events.append(NoteEvent(m.start, m.dur, max(55, m.pitch - 12), 60, "counter"))
    assert any(v.rule == "counter-overlap" for v in lint(events, ctxs))


def test_counter_deterministic():
    _, a = counter_run()
    _, b = counter_run()
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


def test_full_wave_abc_stack_with_counter_lints_clean():
    for dram in (None, DramaturgConfig()):
        for seed in (5, 13):
            engine, results = run(seed=seed, bars=32, dramaturg=dram,
                                  phrase_groove=True, cadence_rit=0.02,
                                  melody=MelodyConfig(plan_apex=True, counterpoint=True),
                                  form=FormConfig(cadential_64=True, periods=True,
                                                  hypermeter=True, bass_inversions=True),
                                  texture=ALL_ON)
            events, ctxs = raw(results), [r.context for r in results]
            pbb = {r.bar: r.params for r in results}
            violations = (lint(events, ctxs) + lint_outer(events, ctxs)
                          + lint_periods(events, ctxs) + lint_groove(events, ctxs, pbb)
                          + lint_texture(events, ctxs, pbb)
                          + lint_imitation(events, ctxs, engine.state.imitation_cells))
            assert not violations, "\n".join(map(str, violations))
