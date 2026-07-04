"""Chords as scale degrees with qualities derived from the mode (PLANS.md §5.2).

A Chord is symbolic — a root degree plus extensions/inversion — and is only
realized to pitches against a context Scale. Borrowed chords (modal mixture)
carry a source_mode and realize from that mode over the same tonic, so a mode
swap re-colors a progression without rewriting it (the EMS function-preserving
trick).
"""

from __future__ import annotations

from dataclasses import dataclass

from musicgen.theory.scales import MODE_OFFSETS, Scale

ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")

# Harmonic function by root degree: tonic, pre-dominant, dominant.
FUNCTION_OF_DEGREE = {1: "T", 2: "PD", 3: "T", 4: "PD", 5: "D", 6: "T", 7: "D"}

VALID_EXTENSIONS = {"7", "9", "sus2", "sus4"}


@dataclass(frozen=True)
class Chord:
    degree: int  # 1..7 root scale degree
    extensions: tuple[str, ...] = ()
    inversion: int = 0
    source_mode: str | None = None  # realize from this mode (same tonic) when borrowed

    def __post_init__(self) -> None:
        if not 1 <= self.degree <= 7:
            raise ValueError(f"degree must be 1..7, got {self.degree}")
        bad = set(self.extensions) - VALID_EXTENSIONS
        if bad:
            raise ValueError(f"unknown extensions {sorted(bad)}")
        if "sus2" in self.extensions and "sus4" in self.extensions:
            raise ValueError("sus2 and sus4 are mutually exclusive")
        if self.source_mode is not None and self.source_mode not in MODE_OFFSETS:
            raise ValueError(f"unknown source_mode {self.source_mode!r}")
        if not 0 <= self.inversion < len(self.member_degrees()):
            raise ValueError(f"inversion {self.inversion} out of range for {len(self.member_degrees())} members")

    @property
    def function(self) -> str:
        return FUNCTION_OF_DEGREE[self.degree]

    def member_degrees(self) -> tuple[int, ...]:
        """Chord members as (wrapping) scale degrees: root-first stacked thirds,
        sus replacing the third, extensions appended."""
        d = self.degree
        if "sus2" in self.extensions:
            third = d + 1
        elif "sus4" in self.extensions:
            third = d + 3
        else:
            third = d + 2
        members = [d, third, d + 4]
        if "7" in self.extensions:
            members.append(d + 6)
        if "9" in self.extensions:
            members.append(d + 8)
        return tuple(members)

    def scale_for(self, context: Scale) -> Scale:
        if self.source_mode is None or self.source_mode == context.mode:
            return context
        return Scale(context.tonic, self.source_mode)

    def pitch_classes(self, context: Scale) -> tuple[int, ...]:
        """Member pitch classes, root first (ignores inversion)."""
        source = self.scale_for(context)
        return tuple(source.pitch_at(d, 4) % 12 for d in self.member_degrees())

    def voiced_pcs(self, context: Scale) -> tuple[int, ...]:
        """Member pcs rotated so the inversion's bass pc comes first."""
        pcs = self.pitch_classes(context)
        return pcs[self.inversion:] + pcs[: self.inversion]

    def bass_pc(self, context: Scale) -> int:
        return self.voiced_pcs(context)[0]

    def quality(self, context: Scale) -> str:
        if "sus2" in self.extensions or "sus4" in self.extensions:
            return "sus"
        pcs = self.pitch_classes(context)
        third, fifth = (pcs[1] - pcs[0]) % 12, (pcs[2] - pcs[0]) % 12
        return {(4, 7): "maj", (3, 7): "min", (3, 6): "dim", (4, 8): "aug"}.get((third, fifth), "?")

    def symbol(self, context: Scale) -> str:
        """Roman-numeral symbol in context, e.g. "V7", "iv", "bVI", "I(add9)"."""
        root_pc = self.pitch_classes(context)[0]
        diatonic_pc = context.pitch_at(self.degree, 4) % 12
        prefix = {11: "b", 1: "#"}.get((root_pc - diatonic_pc) % 12, "")
        quality = self.quality(context)
        numeral = ROMAN[self.degree - 1]
        if quality in ("min", "dim"):
            numeral = numeral.lower()
        body = prefix + numeral + ("°" if quality == "dim" else "")
        ext = set(self.extensions)
        if {"7", "9"} <= ext:
            body += "9"
        elif "7" in ext:
            body += "7"
        elif "9" in ext:
            body += "(add9)"
        if "sus2" in ext:
            body += "sus2"
        if "sus4" in ext:
            body += "sus4"
        if self.inversion:
            body += f"/{self.inversion}"
        return body
