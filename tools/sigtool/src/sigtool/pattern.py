"""Byte patterns with full-byte and nibble wildcards."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEX = "0123456789abcdefABCDEF"
_CODE_STYLE = re.compile(r"^\s*((?:\\x[0-9A-Fa-f]{2})+)\s*([x?]*)\s*$")


@dataclass(frozen=True)
class Pattern:
    """A byte pattern. ``masks[i]`` selects which bits of ``values[i]`` must match."""

    values: bytes
    masks: bytes

    def __post_init__(self) -> None:
        if len(self.values) != len(self.masks):
            raise ValueError("values and masks must have the same length")
        if not self.values:
            raise ValueError("pattern is empty")

    def __len__(self) -> int:
        return len(self.values)

    def __str__(self) -> str:
        return " ".join(_format_byte(v, m) for v, m in zip(self.values, self.masks))

    @property
    def fixed_count(self) -> int:
        return sum(1 for m in self.masks if m == 0xFF)

    def anchor(self) -> tuple[int, bytes]:
        """Longest run of fully fixed bytes, used to find candidates quickly."""
        best_start, best_len = 0, 0
        run_start = None
        for i, m in enumerate(self.masks + b"\x00"):
            if m == 0xFF:
                if run_start is None:
                    run_start = i
            elif run_start is not None:
                if i - run_start > best_len:
                    best_start, best_len = run_start, i - run_start
                run_start = None
        if best_len == 0:
            raise ValueError("pattern needs at least one fully fixed byte")
        return best_start, self.values[best_start : best_start + best_len]

    def matches_at(self, data: bytes | memoryview, pos: int) -> bool:
        end = pos + len(self.values)
        if pos < 0 or end > len(data):
            return False
        for value, mask, byte in zip(self.values, self.masks, data[pos:end]):
            if byte & mask != value:
                return False
        return True

    def find_all(
        self,
        data: bytes,
        start: int = 0,
        end: int | None = None,
        limit: int | None = None,
    ) -> list[int]:
        """Return match offsets in ``data[start:end]``, at most ``limit`` of them."""
        end = len(data) if end is None else min(end, len(data))
        start = max(0, start)
        anchor_pos, anchor = self.anchor()
        if end - start < len(self.values):
            return []
        found: list[int] = []
        search_from = start + anchor_pos
        last_anchor = end - len(self.values) + anchor_pos
        while True:
            hit = data.find(anchor, search_from, last_anchor + len(anchor))
            if hit < 0:
                return found
            candidate = hit - anchor_pos
            if self.matches_at(data, candidate):
                found.append(candidate)
                if limit is not None and len(found) >= limit:
                    return found
            search_from = hit + 1


def _format_byte(value: int, mask: int) -> str:
    if mask == 0xFF:
        return f"{value:02X}"
    if mask == 0x00:
        return "??"
    hi = f"{value >> 4:X}" if mask & 0xF0 else "?"
    lo = f"{value & 0xF:X}" if mask & 0x0F else "?"
    return hi + lo


def _parse_token(token: str) -> tuple[int, int]:
    if token in ("?", "??"):
        return 0, 0
    if len(token) != 2 or any(c not in _HEX + "?" for c in token):
        raise ValueError(f"bad pattern byte {token!r}")
    value = mask = 0
    for shift, char in ((4, token[0]), (0, token[1])):
        if char != "?":
            value |= int(char, 16) << shift
            mask |= 0xF << shift
    return value, mask


def parse_pattern(text: str) -> Pattern:
    """Parse ``48 8B ?? 4?``, compact ``488B??4?`` or code-style ``\\x48\\x8B\\x00 xx?``."""
    code = _CODE_STYLE.match(text)
    if code:
        raw = bytes.fromhex(code.group(1).replace("\\x", ""))
        mask_text = code.group(2) or "x" * len(raw)
        if len(mask_text) != len(raw):
            raise ValueError("code-style mask length doesn't match the byte count")
        masks = bytes(0xFF if c == "x" else 0 for c in mask_text)
        values = bytes(b & m for b, m in zip(raw, masks))
        return Pattern(values, masks)

    tokens = text.split()
    if len(tokens) == 1 and len(tokens[0]) > 2:
        compact = tokens[0]
        if len(compact) % 2:
            raise ValueError("compact pattern needs an even number of characters")
        tokens = [compact[i : i + 2] for i in range(0, len(compact), 2)]
    if not tokens:
        raise ValueError("pattern is empty")
    pairs = [_parse_token(t) for t in tokens]
    return Pattern(bytes(v for v, _ in pairs), bytes(m for _, m in pairs))
