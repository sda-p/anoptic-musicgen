"""M15 signature-faithful realization (§5.5): a motif realized to preserve its
interval contour — transposed as a unit — recurs recognizably across harmonic
contexts, where the constraint-first path (strong beats snapped to chord tones)
bends the shape. The recognizability metric makes that measurable."""

import random

from musicgen.gen.melody import MelodyConfig, Motif, _nearest_pc_pitch, make_motif
from musicgen.gen.motif import diatonic_interval, realize_faithful, recognizability
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale, diatonic_shift, snap_to_scale

STRONG = {0, 4, 8, 12}
LO, HI = 60, 84


def _pitches(placed):
    return [p for _, _, p in placed]


def _constrained(motif, scale, pcs):
    """The constraint-first baseline (melody.py): strong beats snap to the nearest
    chord tone, weak beats to the scale — so the harmony bends the contour."""
    anchor = _nearest_pc_pitch(pcs, (LO + HI) // 2, LO, HI)
    out = []
    for (slot, _), off in zip(motif.rhythm, motif.contour):
        target = diatonic_shift(scale, anchor, off)
        out.append(_nearest_pc_pitch(pcs, target, LO, HI) if slot in STRONG
                   else snap_to_scale(scale, min(max(target, LO), HI)))
    return out


def test_faithful_preserves_contour_across_contexts():
    m = make_motif(random.Random(7), 0.6, 0.2, MelodyConfig())
    scale = Scale(0, "ionian")
    for deg in (1, 2, 4, 5, 6):
        pitches = _pitches(realize_faithful(m, scale, Chord(deg).pitch_classes(scale), LO, HI, STRONG))
        assert recognizability(m, pitches, scale) == 1.0      # shape intact in every context
        assert all(LO <= p <= HI for p in pitches)            # transposed to fit the register


def test_faithful_transposes_as_a_unit():
    # every realized diatonic interval equals the motif's contour interval exactly
    m = make_motif(random.Random(3), 0.5, 0.1, MelodyConfig())
    scale = Scale(0, "dorian")
    pitches = _pitches(realize_faithful(m, scale, Chord(1).pitch_classes(scale), LO, HI, STRONG))
    want = [b - a for a, b in zip(m.contour, m.contour[1:])]
    got = [diatonic_interval(scale, a, b) for a, b in zip(pitches, pitches[1:])]
    assert got == want


def test_recognizability_discriminates():
    m = make_motif(random.Random(1), 0.6, 0.2, MelodyConfig())
    scale = Scale(0, "ionian")
    pitches = _pitches(realize_faithful(m, scale, Chord(1).pitch_classes(scale), LO, HI, STRONG))
    assert recognizability(m, pitches, scale) == 1.0
    distorted = pitches[:]
    distorted[1] = diatonic_shift(scale, distorted[1], 1)      # bend one interval by a step
    assert recognizability(m, distorted, scale) < 1.0


def test_faithful_beats_constrained_on_recognizability():
    # averaged over contexts, the faithful path holds its shape where the
    # constraint-first path loses it (the whole point of the signature path).
    scale = Scale(0, "ionian")
    faith_scores, con_scores = [], []
    for seed in range(12):
        m = make_motif(random.Random(seed), 0.6, 0.3, MelodyConfig())
        for deg in (1, 2, 4, 5, 6):
            pcs = Chord(deg).pitch_classes(scale)
            faith_scores.append(recognizability(m, _pitches(realize_faithful(m, scale, pcs, LO, HI, STRONG)), scale))
            con_scores.append(recognizability(m, _constrained(m, scale, pcs), scale))
    assert min(faith_scores) == 1.0                            # faithful never distorts
    assert sum(con_scores) / len(con_scores) < 1.0            # constrained sometimes does


def test_recognizability_trivial_for_singletons():
    m = Motif(rhythm=((0, 4),), contour=(0,), shape="arch")
    assert recognizability(m, [72], Scale(0, "ionian")) == 1.0


def test_motif_fit_varies_with_the_chord():
    # from a fixed position (near=72), a motif's strong beats land on chord tones for
    # some chords and not others — the appropriateness the M17 director weighs.
    from musicgen.gen.motif import motif_fit  # noqa: PLC0415
    from musicgen.gen.signatures import HERO  # noqa: PLC0415
    scale = Scale(0, "ionian")
    hosts = motif_fit(HERO.motif, scale, Chord(1).pitch_classes(scale), 60, 84, {0, 4, 8, 12}, near=72)
    fights = motif_fit(HERO.motif, scale, Chord(5).pitch_classes(scale), 60, 84, {0, 4, 8, 12}, near=72)
    assert hosts == 1.0 and fights < hosts


# --- lifecycle (M15.2): a persistent signature completes only on a spend -------

from musicgen.control.mapping import MappingTable          # noqa: E402
from musicgen.gen.conductor import EngineConfig, MusicEngine  # noqa: E402
from musicgen.gen.dramaturg import DramaturgConfig         # noqa: E402
from musicgen.gen.motif import MotifLifecycle              # noqa: E402
from musicgen.ir import Meter                              # noqa: E402
from musicgen.verify import lint                           # noqa: E402


def _lifecycle_render(seed, motif_lifecycle=True, accrue=4, settle=3):
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(),
                       dramaturg=DramaturgConfig(leniency=0.5, motif_lifecycle=motif_lifecycle))
    eng = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    eng.set_affect(valence=-0.4, energy=0.7, tension=0.85)
    for _ in range(accrue * pb):
        results.append(eng.advance_bar())
    eng.set_affect(valence=0.5, energy=0.6, tension=0.08)
    for _ in range(settle * pb):
        results.append(eng.advance_bar())
    return results, eng


def test_lifecycle_advance_completes_only_on_spend():
    lc = MotifLifecycle(motif=Motif(((0, 4),), (0,), "arch"), develop_after=2)
    assert lc.advance(spend=False, phrase=0) == "introduced"
    assert lc.advance(spend=True, phrase=1) == "introduced"   # too little disguise to complete
    assert lc.advance(spend=False, phrase=2) == "developed"
    assert lc.advance(spend=True, phrase=3) == "completed"    # enough disguise + a spend
    assert lc.completed_phrase == 3
    assert lc.advance(spend=False, phrase=4) == "developed"   # the landing is one phrase


def test_lifecycle_completes_faithfully_on_the_spend():
    results, eng = _lifecycle_render(42)
    lc = eng.state.motif_lifecycle
    assert lc.completed_phrase is not None
    pb = eng.config.phrase_bars
    motif_bars = {r.bar for r in results for e in r.raw_events if e.role == "motif"}
    cadence_bar = lc.completed_phrase * pb + pb - 1
    # the faithful statement is a point event fused with the payoff cadence —
    # not phrase-length wallpaper, and never in the disguised phrases before it.
    assert motif_bars == {cadence_bar}
    ctxs = [r.context for r in results]
    assert lint([e for r in results for e in r.raw_events], ctxs, Meter(), stage="pre") == []


def test_completed_statement_fuses_with_the_cadence():
    # the payoff states the signature AT the arrival: its final note is a cadence
    # target held to the bar end, under a crescendo into the landing.
    results, eng = _lifecycle_render(42)
    lc = eng.state.motif_lifecycle
    pb = eng.config.phrase_bars
    cadence = next(r for r in results if r.bar == lc.completed_phrase * pb + pb - 1)
    mel = sorted((e for e in cadence.raw_events if e.role == "motif"), key=lambda e: e.start)
    assert len(mel) == len(lc.motif.rhythm)                    # the whole cell, once
    landing = mel[-1]
    assert landing.pitch % 12 in cadence.context.chord_pcs     # lands ON the arrival chord
    bar_end = (cadence.bar + 1) * eng.config.meter.bar_quarters
    assert abs(landing.end - bar_end) < 1e-9                   # held to the bar end
    assert landing.velocity > mel[0].velocity                  # dynamic emphasis into the landing


def test_payoff_phrase_is_not_verbatim_repetition():
    # regression (the original M15 flaw): the spend phrase looped one faithful
    # realization verbatim for every non-cadence bar. The drive bars must develop
    # the signature, not photocopy it.
    from collections import Counter  # noqa: PLC0415
    for seed in (42, 7, 11):
        results, eng = _lifecycle_render(seed)
        lc = eng.state.motif_lifecycle
        pb = eng.config.phrase_bars
        seqs = []
        for r in results:
            if r.bar // pb != lc.completed_phrase or r.context.cadence_slot == "cadence":
                continue
            mel = sorted((e for e in r.raw_events if e.layer == "melody"), key=lambda e: e.start)
            if mel:
                seqs.append(tuple(e.pitch for e in mel))
        assert len(seqs) >= 4, "the payoff drive should sound in most bars"
        assert max(Counter(seqs).values()) <= len(seqs) // 2, \
            f"seed {seed}: one pitch sequence dominates the payoff phrase"


def test_lifecycle_weaves_signature_into_fresh_phrase_material():
    _, eng = _lifecycle_render(42)
    assert eng.state.motif_lifecycle is not None
    # the phrase's own disposable motifs continue alongside the persistent
    # signature (regression: the signature used to *replace* them — monoculture)
    assert eng.state.motifs


def test_lifecycle_off_plants_no_motif_notes():
    results, eng = _lifecycle_render(42, motif_lifecycle=False)
    assert eng.state.motif_lifecycle is None
    assert not [e for r in results for e in r.raw_events if e.role == "motif"]


def test_lifecycle_is_deterministic():
    r1, _ = _lifecycle_render(7)
    r2, _ = _lifecycle_render(7)
    key = lambda e: (e.start, e.layer, e.pitch, e.role)  # noqa: E731
    assert [key(e) for r in r1 for e in r.raw_events] == [key(e) for r in r2 for e in r.raw_events]


def test_completed_statement_recognizable_in_render():
    # the DoD metric, in context: the faithful statement holds its shape across the
    # cadential harmony it lands over (where the disguised path would bend it).
    results, eng = _lifecycle_render(42)
    lc = eng.state.motif_lifecycle
    pb = eng.config.phrase_bars
    scores = []
    for r in results:
        if r.bar // pb != lc.completed_phrase:
            continue
        mel = sorted((e for e in r.raw_events if e.role == "motif"), key=lambda e: e.start)
        if mel:
            mscale = r.context.chord.scale_for(r.context.scale)
            scores.append(recognizability(lc.motif, [e.pitch for e in mel], mscale))
    assert scores and min(scores) >= 0.9


def test_introduced_glimpses_once_per_phrase():
    # introduced = phrases 0–1: ONE fragmentary glimpse per phrase at the
    # continuation onset, ending unstably (2̂/7̂) — the rest of the phrase is its
    # own material, so the glimpse reads as an event, not sixteen bars of wallpaper.
    results, eng = _lifecycle_render(42)
    pb = eng.config.phrase_bars
    checked = 0
    for r in results:
        if r.bar // pb >= 2 or r.bar % pb != pb // 2:
            continue
        mel = sorted((e for e in r.raw_events if e.layer == "melody"), key=lambda e: e.start)
        assert mel, "the glimpse bar never rests"
        checked += 1
        assert r.context.scale.degree_of(mel[-1].pitch) in (2, 7)  # 2̂ / 7̂, left hanging
    assert checked == 2, "one glimpse per introduced phrase"


def test_idle_dramaturg_keeps_melodic_variety():
    # regression (the original M15 flaw): with the dramaturg idle — tension in the
    # dead band, never accruing, never spending — the lifecycle collapsed the whole
    # piece onto one frozen cell. Idle phrases must keep near the rhythmic variety
    # of the lifecycle-off path (fresh disposable motifs per phrase).
    def idle_rhythms(motif_lifecycle):
        cfg = EngineConfig(meter=Meter(), mapper=MappingTable(),
                           dramaturg=DramaturgConfig(leniency=0.5, motif_lifecycle=motif_lifecycle))
        eng = MusicEngine(seed=42, config=cfg)
        eng.set_affect(valence=0.0, energy=0.7, tension=0.45)
        results = [eng.advance_bar() for _ in range(6 * cfg.phrase_bars)]
        rhythms = set()
        for r in results:
            mel = sorted((e for e in r.raw_events if e.layer == "melody"), key=lambda e: e.start)
            if mel and r.context.cadence_slot != "cadence":
                rhythms.add(tuple(round(e.start - r.bar * 4.0, 3) for e in mel))
        return eng, rhythms

    eng_on, on = idle_rhythms(True)
    _, off = idle_rhythms(False)
    assert eng_on.state.motif_lifecycle.state != "completed"   # idle never spends the payoff...
    assert len(on) >= len(off) * 0.7                           # ...yet variety survives


def test_make_signature_is_marked():
    # a signature needs profile to be recognizable when it returns — even drawn
    # from the flattest possible params (density 0.5, roughness 0.0).
    from musicgen.gen.melody import make_signature  # noqa: PLC0415
    for seed in range(8):
        m = make_signature(random.Random(seed), 0.5, 0.0, MelodyConfig())
        deltas = [b - a for a, b in zip(m.contour, m.contour[1:])]
        turns = [d for d in deltas if d]
        assert 3 <= len(m.rhythm) <= 7                          # motto length
        assert len({d for _, d in m.rhythm}) >= 2               # rhythmic differentiation
        assert any(abs(d) >= 2 for d in deltas)                 # a leap...
        assert any((a > 0) != (b > 0) for a, b in zip(turns, turns[1:]))  # ...and a turn
