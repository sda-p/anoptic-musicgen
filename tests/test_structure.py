from musicgen.gen.structure import effective_tension, phrase_position


def test_slots_8_bar_phrase():
    slots = [phrase_position(bar, 8).slot for bar in range(8)]
    assert slots == ["open", "free", "free", "free", "free", "free", "pre-cadence", "cadence"]
    assert phrase_position(8, 8).slot == "open"
    assert phrase_position(8, 8).phrase == 1


def test_slots_4_bar_phrase():
    slots = [phrase_position(bar, 4).slot for bar in range(4)]
    assert slots == ["open", "free", "pre-cadence", "cadence"]


def test_tension_arc_rises_then_settles():
    tensions = [effective_tension(0.5, phrase_position(bar, 8)) for bar in range(8)]
    assert tensions[6] == max(tensions)   # peak at pre-cadence
    assert tensions[7] == min(tensions)   # settles at cadence
    assert all(0.0 <= t <= 1.0 for t in tensions)


def test_tension_clamped():
    assert effective_tension(0.9, phrase_position(6, 8)) == 1.0
    assert effective_tension(0.0, phrase_position(6, 8)) == 0.0
