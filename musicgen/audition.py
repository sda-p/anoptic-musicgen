"""Render and audition MIDI via FluidSynth (PLANS.md §8.5)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_SF2 = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")


def render_wav(
    midi_path: str | Path,
    wav_path: str | Path | None = None,
    *,
    sf2: str | Path = DEFAULT_SF2,
    sample_rate: int = 44100,
    gain: float = 0.7,
) -> Path:
    midi_path = Path(midi_path)
    wav_path = Path(wav_path) if wav_path else midi_path.with_suffix(".wav")
    exe = shutil.which("fluidsynth")
    if exe is None:
        raise RuntimeError("fluidsynth not found on PATH")
    if not Path(sf2).exists():
        raise FileNotFoundError(f"soundfont not found: {sf2}")
    cmd = [exe, "-ni", "-g", str(gain), "-r", str(sample_rate), "-F", str(wav_path), str(sf2), str(midi_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not wav_path.exists():
        raise RuntimeError(f"fluidsynth failed (exit {proc.returncode}):\n{proc.stderr[-2000:]}")
    return wav_path


def play(wav_path: str | Path) -> bool:
    """Best-effort blocking playback; returns False if no player is available."""
    for player in ("paplay", "aplay", "ffplay"):
        exe = shutil.which(player)
        if exe:
            args = [exe, str(wav_path)]
            if player == "ffplay":
                args = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", str(wav_path)]
            subprocess.run(args, check=False)
            return True
    return False
