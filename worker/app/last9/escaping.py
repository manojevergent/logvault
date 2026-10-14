"""Regex escaping for IDs going into a `$regex` alternation (§2.6).

Escape metacharacters but **leave hyphens literal** — hyphens are only special
inside `[...]` character classes, not in alternation, and IDs frequently contain
them (e.g. ``ID-AAA``). This mirrors the proven CLI escaper exactly.
"""

from __future__ import annotations

import re

# Note: '-' is deliberately NOT in this class (§2.6).
_META = re.compile(r"([.^$*+?()\[\]{}|\\])")


def esc(s: str) -> str:
    """Escape regex metacharacters in ``s``, leaving hyphens literal."""
    return _META.sub(r"\\\1", s)
