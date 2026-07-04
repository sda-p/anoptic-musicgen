"""Deterministic per-(subsystem, bar) random streams (PLANS.md §9).

Bar N's material must depend only on (master seed, declared musical state),
never on how many draws other subsystems or earlier bars consumed. Each
stream is therefore derived solely from its keys via a stable hash — Python's
builtin hash() is salted per process and unusable here.
"""

from __future__ import annotations

import hashlib
import random


class Seeder:
    def __init__(self, master: int) -> None:
        self.master = master

    def stream(self, *keys: object) -> random.Random:
        """A fresh RNG determined solely by (master, *keys).

        Typical use: seeder.stream("melody", bar_index).
        """
        tag = ":".join([str(self.master), *map(str, keys)])
        digest = hashlib.blake2b(tag.encode(), digest_size=8).digest()
        return random.Random(int.from_bytes(digest, "big"))
