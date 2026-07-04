from musicgen.control.levers import Affect
from musicgen.control.mapping import (
    MappingTable, brightness_target, gate_layers, harmonic_rhythm_target,
    nearest_mode, pick_cadence_policy, pick_mode, slew, tempo_target,
    density_target, register_target, roughness_target,
)

T = MappingTable()


def test_tempo_follows_energy_dominantly():
    calm = tempo_target(Affect(0.0, 0.1, 0.3), T)
    excited = tempo_target(Affect(0.0, 0.9, 0.3), T)
    assert excited - calm > 50
    dark = tempo_target(Affect(-1.0, 0.5, 0.3), T)
    bright = tempo_target(Affect(1.0, 0.5, 0.3), T)
    assert 0 < bright - dark < 20  # valence tints, energy dominates


def test_tempo_clamped():
    assert tempo_target(Affect(1.0, 1.0, 1.0), T) <= T.tempo_range[1]
    assert tempo_target(Affect(-1.0, 0.0, 0.0), T) >= T.tempo_range[0]


def test_density_and_roughness_rise_with_energy():
    assert density_target(Affect(0, 0.9, 0), T) > density_target(Affect(0, 0.1, 0), T)
    assert roughness_target(Affect(0, 0.9, 0.8), T) <= T.roughness_max
    assert roughness_target(Affect(0, 0.5, 0.9), T) > roughness_target(Affect(0, 0.5, 0.0), T)


def test_register_rises_with_valence():
    assert register_target(Affect(1.0, 0.5, 0.2), T) > register_target(Affect(-1.0, 0.5, 0.2), T)
    assert 66 <= register_target(Affect(-1, 0, 0), T) <= 78
    assert 66 <= register_target(Affect(1, 1, 1), T) <= 78


def test_mode_selection_spans_brightness_axis():
    assert nearest_mode(-1.0) == "phrygian"
    assert nearest_mode(1.0) == "lydian"
    assert brightness_target(0.0) == 0.5  # between dorian and mixolydian
    assert nearest_mode(0.6) in ("ionian", "mixolydian")


def test_mode_hysteresis_prevents_flapping():
    # Oscillating valence around a boundary must not toggle the mode.
    mode = pick_mode(None, 0.19, T)
    history = {mode}
    for v in (0.21, 0.17, 0.23, 0.15, 0.24):
        mode = pick_mode(mode, v, T)
        history.add(mode)
    assert len(history) == 1


def test_mode_switches_on_large_move():
    assert pick_mode("dorian", 1.0, T) == "lydian"
    assert pick_mode("lydian", -1.0, T) == "phrygian"


def test_layer_gates_and_hysteresis():
    assert gate_layers((), 0.05, T) == ("pad",)
    full = gate_layers((), 0.9, T)
    assert set(full) == {"pad", "bass", "melody", "perc", "arp"}
    # arp gates on above 0.62; once on, it stays until energy < 0.52
    on = gate_layers(("pad", "bass", "melody", "perc", "arp"), 0.58, T)
    assert "arp" in on
    off = gate_layers(("pad", "bass", "melody", "perc"), 0.58, T)
    assert "arp" not in off


def test_cadence_policy_tiers():
    assert pick_cadence_policy(0.1, T) == "authentic"
    assert pick_cadence_policy(0.5, T) == "half"
    assert pick_cadence_policy(0.9, T) == "deceptive"


def test_harmonic_rhythm_slows_when_calm():
    assert harmonic_rhythm_target(Affect(0, 0.1, 0.1), T) == 0.5
    assert harmonic_rhythm_target(Affect(0, 0.8, 0.1), T) == 1.0
    assert harmonic_rhythm_target(Affect(0, 0.1, 0.9), T) == 1.0  # tense: keep moving


def test_slew_limits_step():
    assert slew(100.0, 160.0, 2.0) == 102.0
    assert slew(100.0, 60.0, 2.0) == 98.0
    assert slew(100.0, 101.0, 2.0) == 101.0


def test_dsp_targets():
    from musicgen.control.mapping import (
        delay_send_target, drive_target, filter_cutoff_target,
        reverb_send_target, stereo_width_target,
    )

    dark_calm = Affect(-0.8, 0.1, 0.1)
    bright_hot = Affect(0.8, 0.95, 0.2)
    tense = Affect(0.0, 0.5, 0.95)

    assert filter_cutoff_target(bright_hot, T) > filter_cutoff_target(dark_calm, T) * 4
    assert 100 < filter_cutoff_target(dark_calm, T) < 1000
    assert filter_cutoff_target(bright_hot, T) < 12000

    assert reverb_send_target(tense, T) > reverb_send_target(Affect(0, 0.5, 0.1), T)
    assert reverb_send_target(dark_calm, T) > reverb_send_target(bright_hot, T)  # stillness widens
    assert 0.0 <= reverb_send_target(Affect(0, 0, 1), T) <= 0.65

    assert delay_send_target(Affect(0, 0.9, 0.9), T) > delay_send_target(dark_calm, T)
    assert drive_target(bright_hot, T) > drive_target(dark_calm, T)
    assert drive_target(Affect(0, 1, 0), T) <= 0.6
    assert stereo_width_target(Affect(1, 0, 0), T) > stereo_width_target(Affect(-1, 0, 0), T)
