"""signalflow synthesis backend (M6): in-process DSP replacing the GM
soundfont ceiling. Consumes the same BarResult stream as the MIDI path.

The voice/console designs here double as the requirements inventory for the
Anoptic engine's in-house C audio library — see SYNTHESIS.md.
"""

from musicgen.synth.console import Console, ConsoleConfig
from musicgen.synth.render import RealtimeSynthPlayer, render_offline

__all__ = ["Console", "ConsoleConfig", "RealtimeSynthPlayer", "render_offline"]
