"""Find code references to an address (data or code) in a binary.

Sweeps executable sections with the length decoder and reports every instruction whose
rel32 branch target or RIP-relative displacement resolves to the requested address.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .binary import Binary
from .x64 import Insn, sweep


@dataclass(frozen=True)
class Xref:
    offset: int               # instruction start (file offset)
    rva: int                  # instruction start (RVA)
    length: int
    kind: str                 # "rel32" for branches, "rip" for RIP-relative data
    disp_offset: int          # position of the displacement inside the instruction

    def displace(self, insn_offset: int) -> int:
        return insn_offset - self.disp_offset


def _runs(insn: Insn) -> list[tuple[int, int]]:
    """(position, size) of consecutive relocatable runs inside the instruction."""
    if not insn.relocatable:
        return []
    runs, start, prev = [], insn.relocatable[0], insn.relocatable[0]
    for pos in insn.relocatable[1:]:
        if pos != prev + 1:
            runs.append((start, prev - start + 1))
            start = pos
        prev = pos
    runs.append((start, prev - start + 1))
    return runs


def find_xrefs(binary: Binary, target_rva: int, section: str | None = None) -> list[Xref]:
    """Every instruction in an executable section whose rel32 or RIP-relative
    displacement resolves to ``target_rva``.

    The sweep decodes linearly from the section start, so instructions reached by
    falls-through-the-middle desynchronization may be missed; results are never
    false positives (the displacement arithmetic is exact), just occasionally
    incomplete on unusual binaries.
    """
    results: dict[int, Xref] = {}
    for rng in binary.ranges(section):
        for insn in sweep(binary.data[rng.start : rng.end]):
            for start, size in _runs(insn):
                if size != 4:
                    continue
                abs_start = rng.start + start
                (disp,) = struct.unpack_from("<i", binary.data, abs_start)
                next_rva = binary.to_rva(abs_start + 4)
                if next_rva is None or next_rva + disp != target_rva:
                    continue
                insn_rva = binary.to_rva(rng.start + insn.offset)
                if insn_rva is None:
                    continue
                op = binary.data[abs_start - 1]
                is_branch = op in (0xE8, 0xE9) or (
                    binary.data[abs_start - 2] == 0x0F and 0x80 <= op <= 0x8F
                )
                kind = "rel32" if is_branch else "rip"
                insn_bytes = binary.data[rng.start + insn.offset : abs_start + 4]
                # a jcc/call short form can't target rel32 range; here we only
                # ever see 4-byte displacements, so kind is decided above.
                x = Xref(rng.start + insn.offset, insn_rva, len(insn_bytes), kind, start - insn.offset)
                results.setdefault(x.offset, x)
    return [results[k] for k in sorted(results)]
