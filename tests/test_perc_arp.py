import random

from musicgen.gen.arp import ArpConfig, generate_arp
from musicgen.gen.perc import DRUMS, PercConfig, generate_perc
from musicgen.gen.structure import phrase_position
from musicgen.ir import HarmonicContext, Meter, MusicalParams
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale

METER = Meter(4, 4)


def _ctx(bar=0, tension=0.5, chord=None):
    scale = Scale(0, "ionian")
    chord = chord or Chord(1)
    return HarmonicContext(
        bar=bar, scale=scale, chord=chord,
        chord_sym=chord.symbol(scale), chord_pcs=chord.voiced_pcs(scale), tension=tension,
    )


def test_perc_pitches_in_drum_map():
    params = MusicalParams(note_density=0.7, roughness=0.5)
    for bar in range(16):
        events, _, _ = generate_perc(
            _ctx(bar=bar), METER, params, phrase_position(bar, 8), False,
            PercConfig(), random.Random(bar),
        )
        assert events
        assert all(e.pitch in DRUMS.values() for e in events)
        assert all(e.layer == "perc" and e.role.startswith("drum:") for e in events)


def test_perc_backbeat_and_downbeat_kick():
    events, _, _ = generate_perc(
        _ctx(), METER, MusicalParams(note_density=0.5, roughness=0.0),
        phrase_position(1, 8), False, PercConfig(), random.Random(1),
    )
    kicks = [e for e in events if e.pitch == DRUMS["kick"]]
    snares = [e for e in events if e.pitch == DRUMS["snare"]]
    assert any(e.start % 4 == 0.0 for e in kicks), "kick anchors the downbeat"
    assert {round((e.start % 4) / 0.25) for e in snares} == {4, 12}, "backbeat at low roughness"


def test_fill_probability_rises_with_tension():
    def fills(tension):
        count = 0
        for seed in range(60):
            _, fill, _ = generate_perc(
                _ctx(bar=7, tension=tension), METER, MusicalParams(),
                phrase_position(7, 8), False, PercConfig(), random.Random(seed),
            )
            count += fill
        return count

    assert fills(0.9) > fills(0.05)


def test_crash_on_phrase_downbeat_after_fill():
    events, _, trace = generate_perc(
        _ctx(bar=8), METER, MusicalParams(), phrase_position(8, 8), True,
        PercConfig(), random.Random(3),
    )
    crashes = [e for e in events if e.pitch == DRUMS["crash"]]
    assert len(crashes) == 1 and crashes[0].start == 32.0
    assert "crash" in trace


def test_arp_plays_chord_tones_on_grid():
    chord = Chord(5, ("7",))
    ctx = _ctx(chord=chord)
    events, _ = generate_arp(ctx, METER, MusicalParams(note_density=0.6), "updown",
                             ArpConfig(), random.Random(2))
    assert events
    for e in events:
        assert e.pitch % 12 in ctx.chord_pcs
        assert (e.start / 0.25) == int(e.start / 0.25), "on grid"
        assert e.layer == "arp"


def test_arp_patterns_differ():
    ctx = _ctx()
    up, _ = generate_arp(ctx, METER, MusicalParams(note_density=0.9), "up", ArpConfig(), random.Random(4))
    down, _ = generate_arp(ctx, METER, MusicalParams(note_density=0.9), "down", ArpConfig(), random.Random(4))
    assert [e.pitch for e in up] != [e.pitch for e in down]
