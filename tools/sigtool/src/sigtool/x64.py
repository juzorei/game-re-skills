"""Just enough x86-64 decoding to find instruction lengths and relocatable operands.

Not a disassembler: it knows operand sizes, not mnemonics. Unknown bytes are skipped one
at a time, so the sweep resynchronises on the next recognisable instruction.
"""

from __future__ import annotations

from dataclasses import dataclass

_PREFIXES = {0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65, 0x66, 0x67, 0xF0, 0xF2, 0xF3}

# one-byte opcodes without ModRM: opcode -> immediate kind
#   "b" imm8, "w" imm16, "z" imm32 (imm16 with 66), "v" imm32/imm64 with REX.W,
#   "rel8", "rel32", "moffs", "enter" (imm16 + imm8)
_NO_MODRM: dict[int, str | None] = {}
for _x in range(8):
    _NO_MODRM[_x * 8 + 4] = "b"
    _NO_MODRM[_x * 8 + 5] = "z"
for _op in list(range(0x50, 0x60)) + list(range(0x90, 0xA0)) + [0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB,
            0xAC, 0xAD, 0xAE, 0xAF, 0xC3, 0xC9, 0xCB, 0xCC, 0xCE, 0xCF, 0xEC, 0xED, 0xEE, 0xEF,
            0xF4, 0xF5, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0x6C, 0x6D, 0x6E, 0x6F]:
    _NO_MODRM[_op] = None
for _op in range(0x70, 0x80):
    _NO_MODRM[_op] = "rel8"
for _op in range(0xB0, 0xB8):
    _NO_MODRM[_op] = "b"
for _op in range(0xB8, 0xC0):
    _NO_MODRM[_op] = "v"
for _op in range(0xE0, 0xE4):
    _NO_MODRM[_op] = "rel8"
_NO_MODRM.update({
    0x68: "z", 0x6A: "b", 0xA0: "moffs", 0xA1: "moffs", 0xA2: "moffs", 0xA3: "moffs",
    0xA8: "b", 0xA9: "z", 0xC2: "w", 0xC8: "enter", 0xCA: "w", 0xCD: "b",
    0xE4: "b", 0xE5: "b", 0xE6: "b", 0xE7: "b", 0xE8: "rel32", 0xE9: "rel32", 0xEB: "rel8",
})

# one-byte opcodes with ModRM: opcode -> immediate kind after the ModRM operand
_MODRM: dict[int, str | None] = {}
for _x in range(8):
    for _y in range(4):
        _MODRM[_x * 8 + _y] = None
for _op in [0x63, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8C, 0x8D, 0x8E, 0x8F,
            0xD0, 0xD1, 0xD2, 0xD3, 0xFE, 0xFF] + list(range(0xD8, 0xE0)):
    _MODRM[_op] = None
_MODRM.update({0x69: "z", 0x6B: "b", 0x80: "b", 0x81: "z", 0x83: "b",
               0xC0: "b", 0xC1: "b", 0xC6: "b", 0xC7: "z", 0xF6: "grp3b", 0xF7: "grp3z"})

# 0F xx opcodes without ModRM
_0F_NO_MODRM = {0x05, 0x06, 0x07, 0x08, 0x09, 0x0B, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x37,
                0x77, 0xA0, 0xA1, 0xA2, 0xA8, 0xA9, 0xAA} | set(range(0xC8, 0xD0))
_0F_IMM8 = {0x70, 0x71, 0x72, 0x73, 0xA4, 0xAC, 0xBA, 0xC2, 0xC4, 0xC5, 0xC6}


@dataclass(frozen=True)
class Insn:
    offset: int
    length: int
    relocatable: tuple[int, ...]   # byte positions (relative to the sweep start) that move on rebuild


def _imm_size(kind: str | None, opsize16: bool, rex_w: bool, addr32: bool, modrm_reg: int) -> int:
    if kind is None:
        return 0
    if kind in ("b", "rel8"):
        return 1
    if kind == "w":
        return 2
    if kind == "enter":
        return 3
    if kind in ("z", "rel32"):
        return 2 if opsize16 and kind == "z" else 4
    if kind == "v":
        return 8 if rex_w else (2 if opsize16 else 4)
    if kind == "moffs":
        return 4 if addr32 else 8
    if kind == "grp3b":
        return 1 if modrm_reg in (0, 1) else 0
    if kind == "grp3z":
        return (2 if opsize16 else 4) if modrm_reg in (0, 1) else 0
    raise AssertionError(kind)


def _modrm_length(code: bytes, p: int) -> tuple[int, int | None, int] | None:
    """Length of ModRM+SIB+displacement at ``p``, position of a RIP-relative disp32, and reg."""
    if p >= len(code):
        return None
    modrm = code[p]
    mod, reg, rm = modrm >> 6, (modrm >> 3) & 7, modrm & 7
    if mod == 3:
        return 1, None, reg
    length = 1
    if rm == 4:
        if p + 1 >= len(code):
            return None
        length += 1
        if mod == 0 and code[p + 1] & 7 == 5:
            return length + 4, None, reg
    elif mod == 0 and rm == 5:
        return 5, p + 1, reg
    if mod == 1:
        length += 1
    elif mod == 2:
        length += 4
    return length, None, reg


def decode(code: bytes, i: int) -> Insn | None:
    """Decode the instruction at ``i``; ``None`` if the bytes aren't a recognisable one."""
    n, p = len(code), i
    opsize16 = addr32 = False
    while p < n and code[p] in _PREFIXES:
        opsize16 |= code[p] == 0x66
        addr32 |= code[p] == 0x67
        p += 1
    rex_w = False
    if p < n and 0x40 <= code[p] <= 0x4F:
        rex_w = bool(code[p] & 8)
        p += 1
    if p >= n:
        return None
    op = code[p]
    reloc: list[int] = []

    def finish(modrm_at: int, imm: int) -> Insn | None:
        decoded = _modrm_length(code, modrm_at)
        if decoded is None:
            return None
        length, rip_at, _ = decoded
        if rip_at is not None:
            reloc.extend(range(rip_at, rip_at + 4))
        end = modrm_at + length + imm
        return Insn(i, end - i, tuple(reloc)) if end <= n else None

    if op in (0xC4, 0xC5, 0x62):                   # VEX / EVEX (always, in 64-bit mode)
        if op == 0xC5:
            mmap, opcode_at = 1, p + 2
        elif op == 0xC4:
            if p + 1 >= n:
                return None
            mmap, opcode_at = code[p + 1] & 0x1F, p + 3
        else:
            if p + 1 >= n:
                return None
            mmap, opcode_at = code[p + 1] & 0x07, p + 4
        if opcode_at >= n or mmap not in (1, 2, 3):
            return None
        vop = code[opcode_at]
        imm = 1 if mmap == 3 or (mmap == 1 and vop in _0F_IMM8) else 0
        return finish(opcode_at + 1, imm)

    if op == 0x0F:
        if p + 1 >= n:
            return None
        op2 = code[p + 1]
        if 0x80 <= op2 <= 0x8F:
            end = p + 6
            return Insn(i, end - i, tuple(range(p + 2, p + 6))) if end <= n else None
        if op2 == 0x38:
            return finish(p + 3, 0)
        if op2 == 0x3A:
            return finish(p + 3, 1)
        if op2 in _0F_NO_MODRM:
            return Insn(i, p + 2 - i, ())
        return finish(p + 2, 1 if op2 in _0F_IMM8 else 0)

    if op in _MODRM:
        decoded = _modrm_length(code, p + 1)
        if decoded is None:
            return None
        imm = _imm_size(_MODRM[op], opsize16, rex_w, addr32, decoded[2])
        return finish(p + 1, imm)

    if op in _NO_MODRM:
        kind = _NO_MODRM[op]
        size = _imm_size(kind, opsize16, rex_w, addr32, 0)
        end = p + 1 + size
        if end > n:
            return None
        if kind == "rel32":
            reloc.extend(range(p + 1, end))
        return Insn(i, end - i, tuple(reloc))
    return None


def sweep(code: bytes) -> list[Insn]:
    """Linear sweep from offset 0; unknown bytes become 1-byte gaps."""
    out, i = [], 0
    while i < len(code):
        insn = decode(code, i)
        if insn is None:
            i += 1
            continue
        out.append(insn)
        i += insn.length
    return out
