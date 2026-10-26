"""Minimal PE parser: just enough to map file offsets, RVAs and sections."""

from __future__ import annotations

import struct
from dataclasses import dataclass

IMAGE_SCN_MEM_EXECUTE = 0x20000000

MACHINES = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}


class PEError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_EXECUTE)


@dataclass(frozen=True)
class PEInfo:
    machine: int
    image_base: int
    is_64bit: bool
    sections: tuple[Section, ...]

    @property
    def machine_name(self) -> str:
        return MACHINES.get(self.machine, hex(self.machine))

    def section(self, name: str) -> Section | None:
        for sec in self.sections:
            if sec.name == name:
                return sec
        return None

    def section_at_offset(self, offset: int) -> Section | None:
        for sec in self.sections:
            if sec.raw_offset <= offset < sec.raw_offset + sec.raw_size:
                return sec
        return None

    def section_at_rva(self, rva: int) -> Section | None:
        for sec in self.sections:
            span = max(sec.virtual_size, sec.raw_size)
            if sec.virtual_address <= rva < sec.virtual_address + span:
                return sec
        return None

    def offset_to_rva(self, offset: int) -> int | None:
        sec = self.section_at_offset(offset)
        if sec is None:
            return None
        return offset - sec.raw_offset + sec.virtual_address

    def rva_to_offset(self, rva: int) -> int | None:
        sec = self.section_at_rva(rva)
        if sec is None or rva - sec.virtual_address >= sec.raw_size:
            return None
        return rva - sec.virtual_address + sec.raw_offset


def parse_pe(data: bytes) -> PEInfo:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PEError("not a PE file (no MZ header)")
    (pe_offset,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise PEError("not a PE file (no PE signature)")
    try:
        machine, count, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", data, pe_offset + 4)
        opt = pe_offset + 24
        (magic,) = struct.unpack_from("<H", data, opt)
        if magic == 0x20B:
            (image_base,) = struct.unpack_from("<Q", data, opt + 24)
        elif magic == 0x10B:
            (image_base,) = struct.unpack_from("<I", data, opt + 28)
        else:
            raise PEError(f"unknown optional header magic {magic:#x}")
        sections = []
        table = opt + opt_size
        for i in range(count):
            fields = struct.unpack_from("<8sIIII12xI", data, table + i * 40)
            raw_name, vsize, vaddr, rsize, roff, chars = fields
            name = raw_name.rstrip(b"\0").decode("ascii", "replace")
            sections.append(Section(name, vaddr, vsize, roff, rsize, chars))
    except struct.error as exc:
        raise PEError(f"truncated PE headers: {exc}") from None
    return PEInfo(machine, image_base, magic == 0x20B, tuple(sections))
