"""Normalization of packaging strings to a base quantity + unit.

Goal: turn strings like
    "1 кг", "1000г", "уп. 1кг", "1 литр", "5x200г", "упаковка 24 шт по 100 г",
    "10 kg", "0.5 л", "500 мл"
into a single comparable representation:
    quantity_base (float), unit_base ('g' | 'ml' | 'pcs').

Conventions:
    * Weight → grams (g).     "1 кг" → 1000 g.
    * Volume → milliliters.   "1 л" → 1000 ml.
    * Pieces → count (pcs).   "уп. 24 шт" → 24 pcs.

Multipliers inside the string ("5x200г", "упаковка 24 шт по 100 г") are
collapsed into a single base value: the *total* in the base unit, because
that is what makes prices comparable across suppliers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

UnitBase = Literal["g", "ml", "pcs"]

# Order matters: longer/more-specific patterns first so that "кг" wins over "г",
# "мл" wins over "л" (when both appear). We anchor each unit to a number so it
# cannot match the substring "кг" inside "кг" accidentally.
_UNIT_RULES: tuple[tuple[re.Pattern[str], UnitBase, float], ...] = (
    (re.compile(r"\d\s*(кг|kg|килограмм)", re.I), "g", 1000.0),
    (re.compile(r"\d\s*(мл|ml|миллилитр)", re.I), "ml", 1.0),
    (re.compile(r"\d\s*(грамм|gram)", re.I), "g", 1.0),
    # "г" only when standalone (not part of "кг"). The lookbehind/lookahead
    # exclude the "к" prefix and a following letter.
    (re.compile(r"(?<![кa-zа-я])(\d)\s*г(?!р|рамм)(?:\b|$|[^a-zа-я])", re.I), "g", 1.0),
    (re.compile(r"\d\s*(л|l|литр)(?!итр|тра)", re.I), "ml", 1000.0),
    (re.compile(r"\d\s*(шт|штуки|штук|pcs|pc|pieces?)", re.I), "pcs", 1.0),
    (re.compile(r"\d\s*(уп|упак|pack)", re.I), "pcs", 1.0),
)

_NUM = r"\d+(?:[.,]\d+)?"

# "5x200", "5х200" (Russian х), "5*200", "5 × 200"
_MULTIPLIER_RE = re.compile(rf"({_NUM})\s*[xх\*×]\s*({_NUM})")

# "24 шт по 100 г" → multiplier=24, inner=100
_PER_RE = re.compile(rf"({_NUM})\s*(?:шт|pcs|уп|упак|pack)\s*по\s*({_NUM})", re.I)

# Bare number followed (possibly with a space) by a unit word. The unit is
# everything after the number, up to end-of-string or next number.
_BARE_RE = re.compile(rf"({_NUM})\s*([a-zа-яё]+(?:\s+[a-zа-яё]+)?)", re.I)


@dataclass(frozen=True)
class NormalizedUnit:
    quantity_base: float
    unit_base: UnitBase
    matched_raw: str

    def __repr__(self) -> str:
        return f"NormalizedUnit({self.quantity_base:g} {self.unit_base})"


def normalize_packaging(text: str | None) -> NormalizedUnit | None:
    """Normalize a packaging string to base quantity + unit.

    Returns None when no quantity/unit can be parsed — the caller should
    leave the offer without normalized packaging and let the matcher fall
    back to text-similarity methods.
    """
    if not text:
        return None
    s = _collapse_spaces(text.strip().lower())
    if not s:
        return None

    # 1) "упаковка 24 шт по 100 г" — explicit "per piece" multiplier.
    if m := _PER_RE.search(s):
        count = _to_float(m.group(1))
        # The unit word + quantity of the inner item follows "по ".
        inner = normalize_packaging(s[m.end():]) or normalize_packaging(s[m.start(2):])
        if inner is not None:
            return NormalizedUnit(
                quantity_base=inner.quantity_base * count,
                unit_base=inner.unit_base,
                matched_raw=text,
            )

    # 2) "5x200г", "5х200 г", "5*200" — multiplier × inner quantity.
    if m := _MULTIPLIER_RE.search(s):
        factor = _to_float(m.group(1))
        rest = s[m.end():]
        inner = normalize_packaging(rest)
        if inner is None:
            # Try interpreting the second group as the bare quantity.
            inner = _parse_number_with_tail(m.group(2), rest)
        if inner is not None:
            return NormalizedUnit(
                quantity_base=inner.quantity_base * factor,
                unit_base=inner.unit_base,
                matched_raw=text,
            )

    # 3) Bare number + unit: "1 кг", "1000 г", "0.5 л".
    return _try_bare(s)


def _try_bare(s: str) -> NormalizedUnit | None:
    """Find the first <number><unit> pair in s and normalize it."""
    for m in _BARE_RE.finditer(s):
        result = _classify_number_and_unit(m.group(1), s)
        if result is not None:
            return result
    return None


def _parse_number_with_tail(num_str: str, tail: str) -> NormalizedUnit | None:
    """Combine an explicit number with the unit extracted from tail."""
    value = _to_float(num_str)
    for pattern, unit, multiplier in _UNIT_RULES:
        if pattern.search(f"{value:g} {tail}".strip()) or pattern.search(tail):
            return NormalizedUnit(
                quantity_base=value * multiplier,
                unit_base=unit,
                matched_raw=tail,
            )
    return None


def _classify_number_and_unit(num_str: str, full_str: str) -> NormalizedUnit | None:
    """Given a matched number and the full string, find its unit by position."""
    value = _to_float(num_str)
    # Anchor the unit search to a digit followed by the candidate unit, so
    # positional lookup stays consistent with _UNIT_RULES anchors.
    probe = f"{value:g}"
    for pattern, unit, multiplier in _UNIT_RULES:
        # Search the original string; _UNIT_RULES expect a digit prefix.
        if pattern.search(full_str):
            return NormalizedUnit(
                quantity_base=value * multiplier,
                unit_base=unit,
                matched_raw=full_str,
            )
    return None


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s)
