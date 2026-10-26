"""A file to scan: raw bytes plus optional PE layout."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .pattern import Pattern
from .pe import PEError, PEInfo, parse_pe

READ_TYPES = {
    "i8": "<b", "u8": "<B", "i16": "<h", "u16": "<H",
    "i32": "<i", "u32": "<I", "i64": "<q", "u64": "<Q",
    "f32": "<f", "f64": "<d",
}


@dataclass(frozen=True)
class Range:
    start: int
    end: int
    label: str


@dataclass
class Binary:
    """``mapped=True`` means the file is a raw memory image of the module (file offset == RVA),
    as produced by reading the loaded module straight out of process memory."""

    path: Path
    data: bytes
    pe: PEInfo | None
    mapped: bool = False

    @classmethod
    def load(cls, path: str | Path, mapped: bool = False) -> "Binary":
        path = Path(path)
        data = path.read_bytes()
        try:
            pe = parse_pe(data)
        except PEError:
            pe = None
        if mapped and pe is None:
            raise ValueError(f"{path.name}: --mapped needs PE headers at the start of the dump")
        return cls(path, data, pe, mapped)

    def ranges(self, section: str | None = None) -> list[Range]:
        """Ranges to scan. PE files default to ``.text`` (or every executable section)."""
        if self.pe is None:
            if section not in (None, "*"):
                raise ValueError(f"{self.path.name} is not a PE file, --section doesn't apply")
            return [Range(0, len(self.data), "file")]
        if section == "*":
            return [Range(0, len(self.data), "file")]
        if section is not None:
            sec = self.pe.section(section)
            if sec is None:
                names = ", ".join(s.name for s in self.pe.sections)
                raise ValueError(f"no section {section!r} in {self.path.name} (have: {names})")
            return [self._section_range(sec)]
        sec = self.pe.section(".text")
        if sec is not None:
            return [self._section_range(sec)]
        executable = [self._section_range(s) for s in self.pe.sections if s.executable]
        return executable or [Range(0, len(self.data), "file")]

    def _section_range(self, sec) -> Range:
        if self.mapped:
            start, size = sec.virtual_address, max(sec.virtual_size, sec.raw_size)
        else:
            start, size = sec.raw_offset, sec.raw_size
        return Range(start, min(start + size, len(self.data)), sec.name)

    def find(self, pattern: Pattern, section: str | None = None, limit: int | None = None) -> list[int]:
        found: list[int] = []
        for rng in self.ranges(section):
            remaining = None if limit is None else limit - len(found)
            found += pattern.find_all(self.data, rng.start, rng.end, remaining)
            if limit is not None and len(found) >= limit:
                break
        return found

    def to_rva(self, offset: int) -> int | None:
        if self.mapped:
            return offset
        return None if self.pe is None else self.pe.offset_to_rva(offset)

    def to_offset(self, rva: int) -> int | None:
        if self.mapped:
            return rva if 0 <= rva < len(self.data) else None
        return None if self.pe is None else self.pe.rva_to_offset(rva)

    def read(self, offset: int, type_name: str) -> int | float:
        fmt = READ_TYPES.get(type_name)
        if fmt is None:
            raise ValueError(f"unknown type {type_name!r} (use {', '.join(READ_TYPES)})")
        if offset < 0:
            raise ValueError(f"read at negative offset {offset:#x}")
        try:
            return struct.unpack_from(fmt, self.data, offset)[0]
        except struct.error:
            raise ValueError(f"read of {type_name} at {offset:#x} is past the end of the file") from None

    def resolve_rel32(self, match: int, disp_at: int, extra: int = 0) -> dict:
        """Resolve a RIP-relative or rel32 operand at ``match + disp_at``.

        The CPU adds the displacement to the address of the next instruction, which
        is ``disp_at + 4 + extra`` bytes after the match (``extra`` covers trailing
        immediates such as the imm8 in ``cmp byte ptr [rip+x], 0``).
        """
        disp_offset = match + disp_at
        if not 0 <= disp_offset <= len(self.data) - 4:
            raise ValueError(f"rel32 at {disp_offset:#x} is outside the file")
        (disp,) = struct.unpack_from("<i", self.data, disp_offset)
        next_offset = disp_offset + 4 + extra
        result = {"disp": disp}
        next_rva = self.to_rva(next_offset)
        if next_rva is not None:
            target_rva = next_rva + disp
            result["rva"] = target_rva
            result["va"] = self.pe.image_base + target_rva
            result["offset"] = self.to_offset(target_rva)
        else:
            result["offset"] = next_offset + disp
        return result
