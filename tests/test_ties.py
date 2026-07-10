"""Wave-D tie tests (REFINEMENT_PLAN D1, PLANS.md M25).

The tie flag lets one musical note cross the barline as grid-legal halves.
Covered here: the IR merge, byte-identity when off, the three gestures
(anacrusis, held suspension preparation, cross-bar syncopation), the modifier
guards that keep chains intact through the full chain, MIDI round-tripping of
merged chains, and the orphan-"in" plant.
"""

from __future__ import annotations

import os
import tempfile

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine, TieConfig
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.ir import NoteEvent, merge_ties
from musicgen.midi_io import verify_roundtrip, write_midi
from musicgen.verify import lint

import pytest

ALL = TieConfig(anacrusis=True, suspension=True, syncopation=True)
ROUGH = dict(valence=0.2, energy=0.85, tension=0.75)  # withholding + rough


def run(ties=None, dram=None, affect=ROUGH, seed=42, bars=32, chains=False):
    cfg = EngineConfig(mapper=MappingTable(), dramaturg=dram, ties=ties or TieConfig(),
                       **({} if chains else {"chains": {}}))
    engine = MusicEngine(seed=seed, config=cfg)
    engine.set_affect(**affect)
    return engine, [engine.advance_bar() for _ in range(bars)]


def raw(results):
    return [ev for r in results for ev in r.raw_events]


# --- IR -------------------------------------------------------------------------

def test_tie_values_validated():
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 60, 80, "melody", tie="slur")


def test_merge_ties_collapses_a_chain():
    chain = [
        NoteEvent(0.0, 1.0, 60, 80, "melody", role="pickup", tie="out"),
        NoteEvent(1.0, 2.0, 60, 70, "melody", tie="both"),
        NoteEvent(3.0, 1.0, 60, 60, "melody", tie="in"),
    ]
    merged = merge_ties(chain)
    assert len(merged) == 1
    m = merged[0]
    assert (m.start, m.dur, m.velocity, m.role, m.tie) == (0.0, 4.0, 80, "pickup", "")


def test_merge_ties_orphans_and_order():
    plain = NoteEvent(0.0, 0.5, 62, 80, "melody")
    orphan_out = NoteEvent(1.0, 1.0, 64, 80, "melody", tie="out")  # into a rest
    orphan_in = NoteEvent(4.0, 1.0, 65, 80, "melody", tie="in")    # from nothing
    merged = merge_ties([plain, orphan_out, orphan_in])
    assert len(merged) == 3
    assert merged[0] is plain, "untied events pass through uncopied, in order"
    assert merged[1].dur == 1.0 and merged[1].tie == ""  # the orphan out dissolves


def test_ties_off_is_byte_identical():
    _, a = run()
    _, b = run(ties=TieConfig())
    assert [r.raw_events for r in a] == [r.raw_events for r in b]
    assert not [e for r in a for e in r.raw_events if e.tie]


# --- the three gestures -----------------------------------------------------------

def test_anacrusis_steps_into_the_next_phrase():
    found = False
    for seed in range(6):
        engine, results = run(ties=TieConfig(anacrusis=True), seed=seed)
        events = raw(results)
        pickups = [e for e in events if e.role == "pickup"]
        if not pickups:
            continue
        found = True
        bars_q = engine.config.meter.bar_quarters
        for p in pickups:
            assert engine.config.meter.bar_of(p.start) % engine.config.phrase_bars \
                == engine.config.phrase_bars - 1, "pickups live in the cadence bar"
        outs = [e for e in pickups if e.tie == "out"]
        for o in outs:
            host = [e for e in events if e.layer == "melody" and e.tie in ("in", "both")
                    and abs(e.start - o.end) < 1e-9 and e.pitch == o.pitch]
            orphaned = not host
            if host:
                assert engine.config.meter.slot_of(host[0].start) == 0
        violations = lint(events, [r.context for r in results])
        assert not violations, "\n".join(map(str, violations))
    assert found, "no anacrusis fired across 6 seeds"


def test_suspension_preparation_genuinely_held():
    found = False
    for seed in range(8):
        _, results = run(ties=TieConfig(suspension=True), dram=DramaturgConfig(), seed=seed)
        events = raw(results)
        held = [e for e in events if e.layer == "pad" and e.tie == "in"
                and e.role == "suspension"]
        if not held:
            continue
        found = True
        for s in held:
            prep = [e for e in events if e.layer == "pad" and e.tie in ("out", "both")
                    and e.pitch == s.pitch and abs(e.end - s.start) < 1e-9]
            assert prep, "an 'in' suspension must continue a held preparation"
        violations = lint(events, [r.context for r in results])
        assert not violations, "\n".join(map(str, violations))
    assert found, "no held suspension across 8 seeds"


def test_syncopation_pushes_through_the_barline():
    found = False
    for seed in range(6):
        engine, results = run(ties=TieConfig(syncopation=True), seed=seed)
        events = raw(results)
        meter = engine.config.meter
        pushed = [e for e in events if e.layer == "melody" and e.tie in ("out", "both")
                  and e.role != "pickup"]
        if not pushed:
            continue
        found = True
        for p in pushed:
            assert abs(p.end % meter.bar_quarters) < 1e-9, "the push ends AT the barline"
        violations = lint(events, [r.context for r in results])
        assert not violations, "\n".join(map(str, violations))
    assert found, "no syncopation fired across 6 seeds"


# --- consumers --------------------------------------------------------------------

def test_modifier_chains_preserve_tie_joins():
    _, results = run(ties=ALL, dram=DramaturgConfig(), chains=True)
    events = [ev for r in results for ev in r.events]  # post-modifier
    for o in (e for e in events if e.tie in ("out", "both")):
        continuation = [e for e in events if e.layer == o.layer and e.pitch == o.pitch
                        and e.tie in ("in", "both") and abs(e.start - o.end) < 1e-9]
        assert continuation or all(
            e.tie not in ("in", "both") or e.pitch != o.pitch for e in events), \
            f"chain torn at {o}"


def test_midi_roundtrip_merges_chains():
    _, results = run(ties=ALL, dram=DramaturgConfig(), chains=True)
    events = [ev for r in results for ev in r.events]
    assert any(e.tie for e in events)
    path = os.path.join(tempfile.mkdtemp(), "ties.mid")
    write_midi(path, events, tempo_map=[(0.0, 100.0)])
    problems = verify_roundtrip(path, events)
    assert not problems, "\n".join(problems[:5])


def test_plant_orphan_in_is_caught():
    _, results = run(ties=ALL)
    events = raw(results)
    events.append(NoteEvent(0.0, 1.0, 60, 80, "melody", tie="in"))
    assert any(v.rule == "tie" for v in lint(events, [r.context for r in results]))


def test_ties_deterministic():
    _, a = run(ties=ALL, dram=DramaturgConfig())
    _, b = run(ties=ALL, dram=DramaturgConfig())
    assert [r.raw_events for r in a] == [r.raw_events for r in b]
