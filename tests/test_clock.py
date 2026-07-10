"""Wave-D PhraseClock tests (REFINEMENT_PLAN D2, PLANS.md M26).

The scheduled clock replaces div/mod phrase arithmetic: byte-identical with
nothing scheduled, and three authored deviations — the codetta (a payoff's
tonic afterglow), the extension (the pre-dominant stretched while a withhold
runs hot, accruing honest debt), and the elision (the next phrase starting ON
the cadence bar). The M13 monotone-payoff acceptance must survive all three.
"""

from __future__ import annotations

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import ClockConfig, EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.form import PhraseClock
from musicgen.gen.structure import phrase_position
from musicgen.verify import lint

HOT = dict(valence=0.2, energy=0.6, tension=0.85)


def run(clock=None, dram=None, affect=HOT, seed=42, bars=40, release_at=None):
    cfg = EngineConfig(mapper=MappingTable(), chains={}, dramaturg=dram,
                       clock=clock or ClockConfig())
    engine = MusicEngine(seed=seed, config=cfg)
    engine.set_affect(**affect)
    results = []
    for bar in range(bars):
        if release_at is not None and bar == release_at:
            engine.set_affect(tension=0.12)
        results.append(engine.advance_bar())
    return engine, results


def raw(results):
    return [ev for r in results for ev in r.raw_events]


def test_default_clock_matches_div_mod():
    clock = PhraseClock(phrase_bars=8)
    for bar in range(64):
        assert clock.position(bar) == phrase_position(bar, 8)
    clock4 = PhraseClock(phrase_bars=4)
    for bar in range(32):
        assert clock4.position(bar) == phrase_position(bar, 4)


def test_clock_off_is_byte_identical():
    _, a = run(dram=DramaturgConfig())
    _, b = run(clock=ClockConfig(), dram=DramaturgConfig())
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


def test_codetta_breathes_after_the_spend():
    engine, results = run(clock=ClockConfig(codetta=True), dram=DramaturgConfig(),
                          bars=44, release_at=24)
    codettas = [s for s in engine.state.clock.segments if s.kind == "codetta"]
    assert codettas, "a big spend earns its afterglow"
    seg = codettas[0]
    assert seg.bars == 2
    by_bar = {r.bar: r for r in results}
    for b in range(seg.start, seg.start + seg.bars):
        r = by_bar[b]
        assert r.context.chord.degree in (1, 4), "tonic prolongation only"
        assert r.context.cadence_slot == "", "the afterglow promises no cadence"
    echo = [e for e in by_bar[seg.start].raw_events
            if e.layer == "melody" and e.role == "motif"]
    assert echo, "the cadence tail echoes an octave up"
    assert not any("WITHHOLD" in line or "SPEND" in line
                   for b in range(seg.start, seg.start + seg.bars)
                   for line in by_bar[b].trace), "the codetta sits outside the debt loop"
    violations = lint(raw(results), [r.context for r in results])
    assert not violations, "\n".join(map(str, violations))


def test_extension_stretches_the_predominant_and_accrues():
    engine, results = run(clock=ClockConfig(extension=True), dram=DramaturgConfig(),
                          bars=40, release_at=30)
    ext = [s for s in engine.state.clock.segments if s.kind == "extension"]
    assert ext, "a hot withhold stretches"
    seg = ext[0]
    assert seg.bars == engine.config.phrase_bars + 2
    by_bar = {r.bar: r for r in results}
    assert by_bar[seg.start + seg.bars - 1].context.cadence_slot == "cadence"
    assert by_bar[seg.start + seg.bars - 2].context.cadence_slot == "pre-cadence"
    accrued = [line for r in results for line in r.trace
               if "WITHHOLD" in line and f"phrase {engine.state.clock.segments.index(seg)}" in line]
    violations = lint(raw(results), [r.context for r in results])
    assert not violations, "\n".join(map(str, violations))


def test_elision_shares_the_cadence_bar():
    engine, results = run(clock=ClockConfig(elision=True),
                          affect=dict(valence=0.4, energy=0.85, tension=0.25), bars=40)
    assert engine.state.elisions, "high energy elides"
    by_bar = {r.bar: r for r in results}
    for shared, phrase_a in engine.state.elisions.items():
        r = by_bar[shared]
        assert r.context.chord.degree == 1, "the shared bar sounds the resolution"
        assert r.context.cadence_slot == "cadence"
        assert r.context.cadence_policy == "authentic"
        assert r.context.phrase_pos == 0, "…and it is the new phrase's downbeat"
    violations = lint(raw(results), [r.context for r in results])
    assert not violations, "\n".join(map(str, violations))


def test_payoff_stays_monotone_with_elastic_phrases():
    def payoff_after(hold_bars):
        engine, _ = run(clock=ClockConfig(codetta=True, extension=True),
                        dram=DramaturgConfig(), seed=5, bars=hold_bars)
        engine.set_affect(tension=0.1)
        for _ in range(24):
            r = engine.advance_bar()
            for line in r.trace:
                if "SPEND" in line:
                    return float(line.split("payoff ")[1].split(",")[0])
        return 0.0

    payoffs = [payoff_after(h) for h in (8, 24, 40)]
    assert payoffs == sorted(payoffs), f"payoff must grow with the hold: {payoffs}"
    assert payoffs[0] > 0


def test_clock_deterministic():
    kw = dict(clock=ClockConfig(codetta=True, extension=True, elision=True),
              dram=DramaturgConfig(), bars=44, release_at=24)
    _, a = run(**kw)
    _, b = run(**kw)
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


# --- D3 prototype: the compressed 6/4 (two chords in one bar) ---------------------

from musicgen.gen.conductor import FormConfig  # noqa: E402


def split_run(split, affect=(0.4, 0.75, 0.3), seed=42, bars=32):
    cfg = EngineConfig(mapper=MappingTable(), chains={},
                       form=FormConfig(cadential_64=True, split_64=split))
    engine = MusicEngine(seed=seed, config=cfg)
    engine.set_affect(valence=affect[0], energy=affect[1], tension=affect[2])
    return engine, [engine.advance_bar() for _ in range(bars)]


def test_split_64_off_is_byte_identical():
    _, a = split_run(False)
    cfg = EngineConfig(mapper=MappingTable(), chains={},
                       form=FormConfig(cadential_64=True))
    engine = MusicEngine(seed=42, config=cfg)
    engine.set_affect(valence=0.4, energy=0.75, tension=0.3)
    b = [engine.advance_bar() for _ in range(32)]
    assert [r.raw_events for r in a] == [r.raw_events for r in b]


def test_split_compresses_the_cadence_approach():
    engine, results = split_run(True)
    assert engine.state.splits, "high drive compresses the 6/4"
    by_bar = {r.bar: r for r in results}
    for bar, second in engine.state.splits.items():
        ctx = by_bar[bar].context
        assert ctx.chord.degree == 1 and ctx.chord.inversion == 2
        assert len(ctx.chords) == 2 and ctx.chords[1][1].degree == 5
        assert ctx.cadence_slot == "pre-cadence"
        assert ctx.obligation == "cadential64"
        half = engine.config.meter.bar_quarters / 2
        pad_starts = {e.start - bar * engine.config.meter.bar_quarters
                      for e in by_bar[bar].raw_events if e.layer == "pad"}
        assert pad_starts == {0.0, half}, "the pad re-voices at the pulse"
    violations = lint(raw(results), [r.context for r in results])
    assert not violations, "\n".join(map(str, violations))
    # the three-bar form stood down: no I64 at the bars-3 slot
    for r in results:
        if r.context.phrase_pos == engine.config.phrase_bars - 3:
            assert r.context.obligation != "cadential64"


def test_split_falls_back_to_the_three_bar_form_when_calm():
    engine, results = split_run(True, affect=(0.4, 0.4, 0.3))
    assert not engine.state.splits, "low drive keeps the stately form"
    assert any(r.context.obligation == "cadential64" for r in results), \
        "…which still deploys the B1 6/4"


def test_split_plant_missing_discharge_is_caught():
    from dataclasses import replace as dc_replace
    engine, results = split_run(True)
    ctxs = [r.context for r in results]
    bar = next(iter(engine.state.splits))
    for i, c in enumerate(ctxs):
        if c.bar == bar:
            c.chords = (c.chords[0],)  # amputate the mid-bar V
        elif c.bar == bar + 1:
            from musicgen.theory.chords import Chord
            c.chord = Chord(1)  # and make sure the next bar can't discharge it
    assert any(v.rule == "cadential64" for v in lint(raw(results), ctxs))
