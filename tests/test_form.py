"""Wave-B form features (REFINEMENT_PLAN B1–B3 / PLANS M21): the cadential
6/4, antecedent–consequent periods, and hypermetric weight — all behind
EngineConfig.form, each byte-identical when off."""

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, FormConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.gen.structure import hyper_weight
from musicgen.ir import HarmonicContext, Meter, NoteEvent
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale
from musicgen.verify import lint, lint_groove, lint_outer, lint_periods

AFFECT = {"valence": 0.2, "energy": 0.6, "tension": 0.3}
FORM_ALL = FormConfig(cadential_64=True, periods=True, hypermeter=True, bass_inversions=True)


def _render(seed, form=FORM_ALL, dram=False, affect=AFFECT, bars=48):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        mapper=MappingTable(), form=form,
        dramaturg=DramaturgConfig() if dram else None,
        melody=MelodyConfig(counterpoint=True, plan_apex=True), phrase_groove=True))
    engine.set_affect(**affect)
    return engine, [engine.advance_bar() for _ in range(bars)]


def test_form_off_is_default():
    assert EngineConfig().form == FormConfig()
    assert not (FormConfig().cadential_64 or FormConfig().periods
                or FormConfig().hypermeter or FormConfig().bass_inversions)


# --- B1: the cadential 6/4 ------------------------------------------------------

def test_cadential_64_deploys_and_discharges():
    found = 0
    for seed in (1, 2, 3):
        _, results = _render(seed, form=FormConfig(cadential_64=True))
        ctxs = {r.bar: r.context for r in results}
        for bar, ctx in ctxs.items():
            if ctx.obligation != "cadential64":
                continue
            found += 1
            assert "64" in ctx.chord_sym
            assert ctx.phrase_pos == ctx.phrase_bars - 3  # the free slot before the pre-cadence
            v = ctxs[bar + 1].chord
            assert v.degree == 5 and v.inversion == 0     # discharges onto root-position V
            assert ctxs[bar + 2].chord.degree == 1        # which cadences home
        raw = [e for r in results for e in r.raw_events]
        assert lint(raw, list(ctxs.values()), stage="pre") == []
    assert found >= 3, f"only {found} cadential 6/4s across 3 seeds"


def test_cadential_64_obligation_plant():
    scale = Scale(0, "ionian")
    plant = [
        HarmonicContext(bar=0, scale=scale, chord=Chord(1, inversion=2),
                        chord_sym="I64", chord_pcs=(7, 0, 4), obligation="cadential64"),
        HarmonicContext(bar=1, scale=scale, chord=Chord(4), chord_sym="IV",
                        chord_pcs=(5, 9, 0)),
    ]
    assert any(v.rule == "cadential64" for v in lint([], plant))
    good = [plant[0],
            HarmonicContext(bar=1, scale=scale, chord=Chord(5), chord_sym="V",
                            chord_pcs=(7, 11, 2))]
    assert lint([], good) == []


# --- B2: periods -----------------------------------------------------------------

def test_periods_commit_answer_and_lint_clean():
    committed = answers = 0
    for seed in (1, 2, 3, 4):
        engine, results = _render(seed)
        roles = engine.state.planner.periods
        committed += sum(1 for r in roles.values() if r == "antecedent")
        ctxs = {r.bar: r.context for r in results}
        for phrase, role in roles.items():
            if role != "antecedent" or (phrase + 2) * 8 > len(results):
                continue
            ante_cad, cons_cad = ctxs[phrase * 8 + 7], ctxs[phrase * 8 + 15]
            # the dramaturg may hijack a cadence; otherwise the pair must hold
            if ante_cad.cadence_policy == "half" and cons_cad.cadence_policy == "authentic":
                answers += 1
                assert ctxs[phrase * 8].chord == ctxs[phrase * 8 + 8].chord  # same opening harmony
                assert ctxs[phrase * 8].form == "antecedent"
                assert ctxs[phrase * 8 + 8].form == "consequent"
        raw = [e for r in results for e in r.raw_events]
        assert lint_periods(raw, list(ctxs.values())) == []
    assert committed >= 6 and answers >= 5, f"{committed} committed, {answers} held"


def test_period_opening_rhythms_match():
    engine, results = _render(2)
    meter = Meter()
    for phrase, role in engine.state.planner.periods.items():
        if role != "antecedent" or (phrase + 2) * 8 > len(results):
            continue
        rhythm = lambda bar: sorted(meter.slot_of(e.start) for r in results if r.bar == bar
                                    for e in r.raw_events if e.layer == "melody")
        q, a = rhythm(phrase * 8), rhythm(phrase * 8 + 8)
        if q and a:
            assert q == a, f"phrase {phrase}: {q} vs {a}"


def test_lint_periods_plant():
    scale = Scale(0, "ionian")
    def ctx(bar, form="", pos=0):
        return HarmonicContext(bar=bar, scale=scale, chord_sym="I", chord_pcs=(0, 4, 7),
                               form=form, phrase_pos=pos, phrase_bars=8)
    ctxs = ([ctx(0, "antecedent")] + [ctx(b, "antecedent", b) for b in range(1, 8)]
            + [ctx(8, "consequent")] + [ctx(b, "consequent", b - 8) for b in range(9, 16)])
    match = [NoteEvent(0.0, 1.0, 72, 80, "melody"), NoteEvent(32.0, 1.0, 74, 80, "melody")]
    assert lint_periods(match, ctxs) == []
    clash = match + [NoteEvent(33.0, 1.0, 76, 80, "melody")]  # extra onset: rhythm differs
    assert any(v.rule == "period" for v in lint_periods(clash, ctxs))
    orphan = [ctx(8, "consequent")]
    assert any(v.rule == "period" for v in lint_periods([], orphan))


def test_periods_defer_to_the_dramaturg():
    engine, results = _render(5, dram=True, affect={"valence": 0.1, "energy": 0.6, "tension": 0.9})
    assert engine.state.planner.periods == {}  # every phrase withheld: nothing to pair
    assert all(r.context.form == "" for r in results)


# --- B3: hypermeter --------------------------------------------------------------

def test_hyper_weight_profile():
    assert hyper_weight(0, 8) == 1.0
    assert hyper_weight(1, 8) == 0.4 and hyper_weight(3, 8) == 0.4
    assert hyper_weight(2, 8) == 0.7 and hyper_weight(6, 8) == 0.7
    assert hyper_weight(4, 8) == 0.85  # the mid-phrase downbeat, second-strongest
    assert hyper_weight(0, 4) == 1.0 and hyper_weight(2, 4) == 0.7


def test_hypermeter_shapes_dynamics_and_fills():
    strong = weak = 0
    fills = crashes = 0
    for seed in (1, 2, 3, 4, 5, 6):
        _, results = _render(seed, form=FormConfig(hypermeter=True))
        for r in results[8:]:  # skip the slew settling
            pos = r.context.phrase_pos
            if pos == 0:
                strong += r.params.velocity_center
            elif pos == 1:
                weak += r.params.velocity_center
            if pos == r.context.phrase_bars // 2 - 1 and any("fill" in t for t in r.trace):
                fills += 1
            if pos == r.context.phrase_bars // 2 and any("crash" in t for t in r.trace):
                crashes += 1
    assert strong > weak  # hyper-strong bars sit dynamically above hyper-weak ones
    assert fills >= 1 and crashes >= 1  # the mid-phrase boundary is punctuated sometimes


# --- B4: bass-line planning -------------------------------------------------------

def test_bass_inversions_step_the_bass():
    inverted = 0
    for seed in (1, 2, 3, 4):
        engine, results = _render(seed, form=FormConfig(bass_inversions=True))
        prev_chord = None
        run = 0
        for r in results:
            ctx = r.context
            if prev_chord is not None and ctx.chord.inversion == 1:
                inverted += 1
                assert ctx.phrase_pos not in (0, ctx.phrase_bars - 2, ctx.phrase_bars - 1), \
                    "inversions stay off the phrase anchors and cadences"
                d = (ctx.chord_pcs[0] - prev_chord.bass_pc(ctx.scale)) % 12
                assert min(d, 12 - d) <= 2, "an inverted bass must step, not leap"
                run += 1
                assert run <= 2, "never three inverted bars running"
            else:
                run = 0
            prev_chord = ctx.chord
    assert inverted >= 6, f"only {inverted} planned inversions across 4 seeds"


def _arc_render(seed):
    engine = MusicEngine(seed=seed, config=EngineConfig(
        mapper=MappingTable(), form=FORM_ALL, dramaturg=DramaturgConfig(),
        melody=MelodyConfig(counterpoint=True, plan_apex=True), phrase_groove=True))
    results = []
    for tension, bars in ((0.9, 32), (0.1, 8), (0.9, 32), (0.1, 8)):
        engine.set_affect(valence=0.0, energy=0.6, tension=tension)
        results += [engine.advance_bar() for _ in range(bars)]
    return engine, results


def test_lament_ground_alternates_with_the_pedal():
    engine, results = _arc_render(3)
    first, second = results[:40], results[40:]
    # buildup one anchors on the dominant pedal, buildup two on the lament ground
    assert any(e.role == "pedal" for r in first for e in r.raw_events)
    assert not any(r.context.obligation == "lament" for r in first)
    lament = [r.context for r in second if r.context.obligation == "lament"]
    assert lament, "the second buildup never rode the ground"
    for ctx in lament:  # the ostinato is drawn from the tetrachord cycle only
        assert (ctx.chord.degree, ctx.chord.inversion) in ((1, 0), (5, 1), (4, 1), (5, 0))
    assert engine.state.ledger.buildups >= 2


def test_lament_obligation_plant():
    scale = Scale(0, "aeolian")
    def ctx(bar, degree, inversion=0, obligation=""):
        chord = Chord(degree, inversion=inversion)
        return HarmonicContext(bar=bar, scale=scale, chord=chord,
                               chord_sym=chord.symbol(scale),
                               chord_pcs=chord.voiced_pcs(scale), obligation=obligation)
    stray = [ctx(0, 1, obligation="lament"), ctx(1, 5, 1, obligation="lament"),
             ctx(2, 4)]  # the ground stalls on iv — never reaches the dominant
    assert any(v.rule == "lament" for v in lint([], stray))
    good = [ctx(0, 1, obligation="lament"), ctx(1, 5, 1, obligation="lament"), ctx(2, 5)]
    assert not any(v.rule == "lament" for v in lint([], good))


# --- the whole stack -------------------------------------------------------------

def test_full_wave_b_stack_lints_clean():
    for dram in (False, True):
        for seed in (1, 2, 3, 4):
            _, results = _render(seed, dram=dram)
            ctxs = [r.context for r in results]
            raw = [e for r in results for e in r.raw_events]
            final = [e for r in results for e in r.events]
            violations = (lint(raw, ctxs, stage="pre") + lint(final, ctxs, stage="post")
                          + lint_outer(raw, ctxs) + lint_periods(raw, ctxs)
                          + lint_groove(raw, ctxs, {r.bar: r.params for r in results}))
            assert violations == [], f"dram={dram} seed={seed}:\n" + "\n".join(map(str, violations))


def test_wave_b_deterministic():
    _, a = _render(7, dram=True)
    _, b = _render(7, dram=True)
    assert [r.events for r in a] == [r.events for r in b]
