"""The affect -> musical-parameter mapping table (PLANS.md §6.2).

This is THE tunable design artifact: every perceptual constant lives in
MappingTable, and every function here is a pure map from (affect, table) to a
parameter target. Slew and hysteresis STATE live in the conductor; the
hysteresis RULES live here.

Directions (from research.md): tempo is the strongest arousal lever; mode
brightness follows valence on the Lydian..Phrygian axis; density, roughness,
articulation, dynamics, and layer count follow energy; dissonance budget and
cadence policy follow tension.
"""

from __future__ import annotations

from dataclasses import dataclass

from musicgen.control.levers import Affect
from musicgen.theory.scales import BRIGHTNESS


@dataclass(frozen=True)
class MappingTable:
    # tempo (BPM): dominated by energy, tinted by valence
    tempo_base: float = 70.0
    tempo_energy: float = 80.0
    tempo_valence: float = 8.0
    tempo_range: tuple[float, float] = (60.0, 160.0)
    tempo_slew_per_beat: float = 2.0

    # melody register center (MIDI)
    register_base: float = 72.0
    register_valence: float = 4.0
    register_tension: float = 2.0

    # note density / rhythmic roughness
    density_base: float = 0.15
    density_energy: float = 0.75
    roughness_base: float = 0.10
    roughness_energy: float = 0.30
    roughness_tension: float = 0.20
    roughness_max: float = 0.60

    # articulation gate: legato 1.05 .. staccato 0.45
    articulation_legato: float = 1.05
    articulation_energy_drop: float = 0.60
    articulation_slew_per_bar: float = 0.15

    # dynamics
    velocity_base: float = 56.0
    velocity_energy: float = 44.0
    velocity_slew_per_bar: float = 10.0
    accent_base: float = 4.0
    accent_energy: float = 14.0

    # layer gates: (layer, energy threshold); hysteresis keeps a live layer
    # on until energy drops below threshold - layer_hysteresis
    layer_gates: tuple[tuple[str, float], ...] = (
        ("pad", -1.0),
        ("bass", 0.12),
        ("melody", 0.28),
        ("perc", 0.34),
        ("arp", 0.62),
    )
    layer_hysteresis: float = 0.10

    # mode selection (brightness axis), phrase-quantized in the conductor
    mode_hysteresis: float = 0.60

    # cadence policy by tension
    cadence_authentic_max: float = 0.35
    cadence_half_max: float = 0.65

    # slow harmonic rhythm (2-bar chords) when calm
    harmonic_slow_energy: float = 0.30
    harmonic_slow_tension: float = 0.50

    # --- DSP tier (synth backend; PLANS.md M6 / SYNTHESIS.md) ---
    cutoff_base_hz: float = 350.0
    cutoff_energy_octaves: float = 4.2   # 350 Hz .. ~6.4 kHz across energy
    cutoff_valence_octaves: float = 0.5  # brightness tint
    reverb_send_base: float = 0.10       # wetter when tense and when calm
    reverb_send_tension: float = 0.30
    reverb_send_stillness: float = 0.18  # scaled by (1 - energy)
    delay_send_base: float = 0.04
    delay_send_activity: float = 0.24    # scaled by tension * energy
    drive_base: float = 0.05
    drive_energy: float = 0.45           # scaled by energy^2
    width_base: float = 0.55
    width_valence: float = 0.25


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def tempo_target(a: Affect, t: MappingTable) -> float:
    raw = t.tempo_base + t.tempo_energy * a.energy + t.tempo_valence * a.valence
    return _clamp(raw, *t.tempo_range)


def register_target(a: Affect, t: MappingTable) -> int:
    return round(t.register_base + t.register_valence * a.valence + t.register_tension * a.tension)


def density_target(a: Affect, t: MappingTable) -> float:
    return _clamp(t.density_base + t.density_energy * a.energy, 0.0, 1.0)


def roughness_target(a: Affect, t: MappingTable) -> float:
    raw = t.roughness_base + t.roughness_energy * a.energy + t.roughness_tension * a.tension
    return _clamp(raw, 0.0, t.roughness_max)


def articulation_target(a: Affect, t: MappingTable) -> float:
    return t.articulation_legato - t.articulation_energy_drop * a.energy


def velocity_target(a: Affect, t: MappingTable) -> float:
    return t.velocity_base + t.velocity_energy * a.energy


def accent_target(a: Affect, t: MappingTable) -> int:
    return round(t.accent_base + t.accent_energy * a.energy)


def brightness_target(valence: float) -> float:
    """Valence -1..+1 mapped onto the EMS brightness axis -2..+3."""
    return -2.0 + 5.0 * (valence + 1.0) / 2.0


def nearest_mode(valence: float) -> str:
    target = brightness_target(valence)
    return min(BRIGHTNESS, key=lambda m: (abs(BRIGHTNESS[m] - target), -BRIGHTNESS[m]))


def pick_mode(current: str | None, valence: float, t: MappingTable) -> str:
    """Nearest-brightness mode with a deadband: stay on the current mode
    until the target drifts more than mode_hysteresis away from it."""
    if current is None:
        return nearest_mode(valence)
    if abs(brightness_target(valence) - BRIGHTNESS[current]) < t.mode_hysteresis:
        return current
    return nearest_mode(valence)


def gate_layers(current: tuple[str, ...], energy: float, t: MappingTable) -> tuple[str, ...]:
    out = []
    for layer, threshold in t.layer_gates:
        effective = threshold - (t.layer_hysteresis if layer in current else 0.0)
        if energy > effective:
            out.append(layer)
    return tuple(out)


def pick_cadence_policy(tension: float, t: MappingTable) -> str:
    if tension < t.cadence_authentic_max:
        return "authentic"
    if tension < t.cadence_half_max:
        return "half"
    return "deceptive"


def harmonic_rhythm_target(a: Affect, t: MappingTable) -> float:
    if a.energy < t.harmonic_slow_energy and a.tension < t.harmonic_slow_tension:
        return 0.5  # one chord per two bars
    return 1.0


def slew(current: float, target: float, max_step: float) -> float:
    return current + _clamp(target - current, -max_step, max_step)


# --- DSP tier -----------------------------------------------------------------

def filter_cutoff_target(a: Affect, t: MappingTable) -> float:
    octaves = t.cutoff_energy_octaves * a.energy + t.cutoff_valence_octaves * max(0.0, a.valence)
    return t.cutoff_base_hz * 2.0 ** octaves


def reverb_send_target(a: Affect, t: MappingTable) -> float:
    raw = t.reverb_send_base + t.reverb_send_tension * a.tension + t.reverb_send_stillness * (1.0 - a.energy)
    return _clamp(raw, 0.0, 0.65)


def delay_send_target(a: Affect, t: MappingTable) -> float:
    return _clamp(t.delay_send_base + t.delay_send_activity * a.tension * a.energy, 0.0, 0.5)


def drive_target(a: Affect, t: MappingTable) -> float:
    return _clamp(t.drive_base + t.drive_energy * a.energy * a.energy, 0.0, 0.6)


def stereo_width_target(a: Affect, t: MappingTable) -> float:
    return t.width_base + t.width_valence * (a.valence + 1.0) / 2.0
