"""Synthetic PE64 "game builds" for trying sigtool without a real game, and for tests."""

from __future__ import annotations

import struct
from pathlib import Path

TEXT_RVA, TEXT_RAW, TEXT_SIZE = 0x1000, 0x400, 0x800
DATA_RVA, DATA_RAW, DATA_SIZE = 0x3000, 0xC00, 0x200
IMAGE_BASE = 0x140000000
GWORLD_RVA = DATA_RVA + 0x40

GWORLD_AT = 0x100      # offset of the GWorld load inside .text
HEALTH_AT = 0x200      # offset of the health store inside .text

SIGNATURES = """\
# Demo signatures. Run: sigtool check signatures.toml game-1.0.exe game-1.1.exe

[GWorld]
pattern = "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? E8"
rel = 3

[HealthOffset]
pattern = "F3 0F 11 81 ?? ?? ?? ?? C3"
read = "4:u32"

[OldHealthOffset]
# hardcodes the 1.0 field offset, so it breaks in 1.1
pattern = "F3 0F 11 81 A8 01 00 00 C3"
"""


def build_code(*, gworld_at=GWORLD_AT, health_field=0x1A8, call_target=0x1500, tamper=False) -> bytes:
    """Filler plus two recognisable snippets at known offsets."""
    code = bytearray((i * 7 + 3) & 0xFF for i in range(TEXT_SIZE))
    # mov rax,[rip+disp32] ; test rax,rax ; je +5 ; call rel32
    next_rva = TEXT_RVA + gworld_at + 7
    call_next = TEXT_RVA + gworld_at + 7 + 3 + 2 + 5
    snippet = (
        b"\x48\x8B\x05" + struct.pack("<i", GWORLD_RVA - next_rva)
        + b"\x48\x85\xC0"
        + b"\x74\x05"
        + b"\xE8" + struct.pack("<i", call_target - call_next)
    )
    if tamper:
        snippet = b"\x48\x8B\x0D" + snippet[3:]
    code[gworld_at : gworld_at + len(snippet)] = snippet
    # movss [rcx+field],xmm0 ; ret ; int3 int3
    store = b"\xF3\x0F\x11\x81" + struct.pack("<I", health_field) + b"\xC3\xCC\xCC"
    code[HEALTH_AT : HEALTH_AT + len(store)] = store
    return bytes(code)


def build_pe(code: bytes) -> bytes:
    if len(code) != TEXT_SIZE:
        raise ValueError(f"code must be {TEXT_SIZE:#x} bytes")
    image = bytearray(DATA_RAW + DATA_SIZE)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    opt_size = 0xF0
    struct.pack_into("<HHIIIHH", image, 0x84, 0x8664, 2, 0, 0, 0, opt_size, 0x22)
    opt = 0x98
    struct.pack_into("<H", image, opt, 0x20B)
    struct.pack_into("<Q", image, opt + 24, IMAGE_BASE)
    table = opt + opt_size
    sections = [
        (b".text", TEXT_SIZE, TEXT_RVA, TEXT_SIZE, TEXT_RAW, 0x60000020),
        (b".data", DATA_SIZE, DATA_RVA, DATA_SIZE, DATA_RAW, 0xC0000040),
    ]
    for i, (name, vsize, vaddr, rsize, roff, chars) in enumerate(sections):
        struct.pack_into("<8sIIII12xI", image, table + i * 40, name, vsize, vaddr, rsize, roff, chars)
    image[TEXT_RAW : TEXT_RAW + TEXT_SIZE] = code
    return bytes(image)


def write_demo(directory: str | Path) -> list[Path]:
    """Two builds where code moved and a struct field shifted, plus a signatures file."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "game-1.0.exe": build_pe(build_code()),
        "game-1.1.exe": build_pe(build_code(gworld_at=0x180, health_field=0x1B0, call_target=0x1700)),
    }
    written = []
    for name, data in files.items():
        (out / name).write_bytes(data)
        written.append(out / name)
    (out / "signatures.toml").write_text(SIGNATURES, encoding="utf-8")
    written.append(out / "signatures.toml")
    return written
