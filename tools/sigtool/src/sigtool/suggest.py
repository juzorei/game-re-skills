"""Build the shortest unique signature that starts at a given file offset."""

from __future__ import annotations

from dataclasses import dataclass

from .binary import Binary
from .pattern import Pattern
from .x64 import sweep

def auto_wildcards(code: bytes) -> set[int]:
    """Byte positions of relocatable operands: rel32 branch targets and RIP-relative disp32.

    Uses a length decoder sweeping from the first byte, so ``code`` must start on an
    instruction boundary. Struct displacements and immediates stay fixed. Anything the
    decoder doesn't recognise is left fixed too; pass ``--wildcard`` for those.
    """
    wild: set[int] = set()
    for insn in sweep(code):
        wild.update(p for p in insn.relocatable if p < len(code))
    return wild


@dataclass(frozen=True)
class Suggestion:
    pattern: Pattern
    matches: int
    wildcards: tuple[int, ...]

    @property
    def unique(self) -> bool:
        return self.matches == 1


def _count(binary: Binary, pattern: Pattern, section: str | None) -> int:
    try:
        return len(binary.find(pattern, section, limit=2))
    except ValueError:
        return 2


def _trim(pattern: Pattern) -> Pattern:
    end = len(pattern)
    while end > 1 and pattern.masks[end - 1] == 0:
        end -= 1
    return Pattern(pattern.values[:end], pattern.masks[:end])


def suggest(
    binary: Binary,
    offset: int,
    *,
    min_len: int = 8,
    max_len: int = 64,
    extra_wildcards: set[int] | None = None,
    auto: bool = True,
    section: str | None = None,
) -> Suggestion:
    if not 0 <= offset < len(binary.data):
        raise ValueError(f"offset {offset:#x} is outside the file")
    containing = [r for r in binary.ranges(section) if r.start <= offset < r.end]
    if not containing:
        raise ValueError(
            f"offset {offset:#x} is outside the scanned range; pass --section with its section or '*'"
        )
    room = containing[0].end - offset
    max_len = max(1, min(max_len, room))
    min_len = max(1, min(min_len, max_len))
    window = binary.data[offset : offset + max_len]
    wild = set(extra_wildcards or ())
    if auto:
        wild |= auto_wildcards(window)
    wild = {w for w in wild if 0 <= w < len(window)}
    masks = bytes(0 if i in wild else 0xFF for i in range(len(window)))
    values = bytes(b & m for b, m in zip(window, masks))

    def prefix(length: int) -> Pattern:
        return Pattern(values[:length], masks[:length])

    if _count(binary, prefix(max_len), section) != 1:
        best = prefix(max_len)
        return Suggestion(_trim(best), _count(binary, best, section), tuple(sorted(wild)))

    lo, hi = min_len, max_len
    while lo < hi:
        mid = (lo + hi) // 2
        if _count(binary, prefix(mid), section) == 1:
            hi = mid
        else:
            lo = mid + 1
    result = _trim(prefix(lo))
    return Suggestion(result, 1, tuple(sorted(w for w in wild if w < len(result))))
