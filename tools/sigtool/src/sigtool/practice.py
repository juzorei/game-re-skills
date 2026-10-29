"""Practice targets: a synthetic "game" to train and test RE workflows offline.

Each practice target is a tiny PE64 with named globals, functions that use them,
and a data section with realistic structure noise. Scenarios tie the pieces
together: given a goal ("find the player's health"), the agent can run the real
workflow (xref -> suggest -> check -> chain) against a file that always works.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_BASE = 0x140000000
TEXT_RVA, TEXT_FILE, TEXT_SIZE = 0x1000, 0x400, 0x800
DATA_RVA, DATA_FILE, DATA_SIZE = 0x3000, 0xC00, 0x400
BSS_SIZE = 0x400  # uninitialized globals live at 0x3400; only their RVAs matter

GWORLD_RVA = DATA_RVA + 0x40
HEALTH_MAX_RVA = DATA_RVA + 0x60
SETTINGS_RVA = DATA_RVA + 0x80

HEALTH_FIELD = 0x1A8


def _pe_with(text: bytes, data: bytes) -> bytes:
    image = bytearray(DATA_FILE + DATA_SIZE)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    opt_size = 0xF0
    struct.pack_into("<HHIIIHH", image, 0x84, 0x8664, 3, 0, 0, 0, opt_size, 0x22)
    opt = 0x98
    struct.pack_into("<H", image, opt, 0x20B)
    struct.pack_into("<Q", image, opt + 24, IMAGE_BASE)
    table = opt + opt_size
    sections = [
        (b".text", TEXT_SIZE, TEXT_RVA, TEXT_SIZE, TEXT_FILE, 0x60000020),
        (b".data", DATA_SIZE, DATA_RVA, DATA_SIZE, DATA_FILE, 0xC0000040),
        (b".bss", BSS_SIZE, DATA_RVA + DATA_SIZE, 0, 0, 0xC0000080),
    ]
    for i, (name, vsize, vaddr, rsize, roff, chars) in enumerate(sections):
        struct.pack_into("<8sIIII12xI", image, table + i * 40, name, vsize, vaddr, rsize, roff, chars)
    image[TEXT_FILE : TEXT_FILE + len(text)] = text
    image[DATA_FILE : DATA_FILE + len(data)] = data
    return bytes(image)


def mov_rip_reg(disp32: int) -> bytes:
    return b"\x48\x8B\x05" + struct.pack("<i", disp32)


def call_rel32(disp32: int) -> bytes:
    return b"\xE8" + struct.pack("<i", disp32)


@dataclass
class PracticeBuild:
    """One synthetic build. ``version`` changes what moves between builds."""

    version: int = 0

    def build(self) -> bytes:
        # code layout (everything at stable, easy-to-sweep 0x90 padding):
        #   0x000 mov rax,[GWorld]           <- threat model: health hangs off GWorld
        #   0x010 mov rbx,[HealthMax]
        #   0x020 cmp byte [Settings+X],0    (trailing imm8, --rel 2:1 practice)
        #   0x030 UpdateHealth:               <- call target, xref practice
        #   0x050 call UpdateHealth
        gworld_at = 0x000 if self.version == 0 else 0x080
        health_max_at = 0x010 if self.version == 0 else 0x020
        settings_at = 0x020 if self.version == 0 else 0x060
        update_at = 0x030 if self.version == 0 else 0x0A0
        call_at = 0x050 if self.version == 0 else 0x0C0
        cam_op = 0xE8 if self.version == 0 else 0xE9  # compiler "changed" the call to a jmp

        code = bytearray(b"\x90" * TEXT_SIZE)

        def place(at: int, insn: bytes):
            code[at : at + len(insn)] = insn

        place(gworld_at, mov_rip_reg(GWORLD_RVA - (TEXT_RVA + gworld_at + 7)) + b"\x48\x85\xC0")
        place(health_max_at, b"\x8B\x1D" + struct.pack("<i", HEALTH_MAX_RVA - (TEXT_RVA + health_max_at + 6)))
        place(settings_at, b"\x80\x3D" + struct.pack("<i", SETTINGS_RVA - (TEXT_RVA + settings_at + 7)) + b"\x00\x75")
        # UpdateHealth(pawn): movss [rcx+HEALTH],xmm0 ; ret
        place(update_at, b"\xF3\x0F\x11\x81" + struct.pack("<I", HEALTH_FIELD + 0x10 * self.version)
              + b"\xC3")
        place(call_at, bytes([cam_op]) + struct.pack("<i", TEXT_RVA + update_at - (TEXT_RVA + call_at + 5)))

        data = bytearray(b"\xCC" * DATA_SIZE)
        struct.pack_into("<Q", data, GWORLD_RVA - DATA_RVA, 0x1122334455667788)
        struct.pack_into("<I", data, HEALTH_MAX_RVA - DATA_RVA, 100)
        struct.pack_into("<B", data, SETTINGS_RVA - DATA_RVA, 1)
        return _pe_with(bytes(code), bytes(data))


PRACTICE_README = """\
# sigtool practice: gworld-demo v{v}

A synthetic 64-bit "game" ({kb} KB) for training the game-re-skills workflows offline.

Facts you'd normally discover by reversing (spoiler, for the grader):
- a global pointer lives at rva {gworld:#x} ("GWorld" by analogy)
- a global int at rva {hmax:#x} ("MaxHealth")
- a global byte at rva {settings:#x} ("Settings")
- a function that writes a float field at [rcx+{field:#x}] around rva {update:#x} ("UpdateHealth")
- another function calls it via a rel32 branch around rva {call:#x}

Suggested exercises (each verifiable with sigtool):
1. `sigtool xref gworld-demo.exe #### --rva`     -> find the instruction that reads GWorld
2. `sigtool suggest gworld-demo.exe ####`         -> a unique signature for it
3. `sigtool scan gworld-demo.exe "F3 0F 11 81 ?? ?? ?? ?? C3" --read 4:u32` -> the health field offset
4. Write signatures.toml with entries for 1-3 and `sigtool check` against v{v2} too:
   everything must still match once; the field offset `read` differs between builds.
5. `sigtool chain` practice runs against your own process, not this file.

Between v0 and v1 the code moved and the health field shifted — exactly what a
game patch does. If your signatures survive both builds, they'd survive a patch.
"""


def write_practice(directory: str | Path) -> list[Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for version, name in ((0, "gworld-demo-v0.exe"), (1, "gworld-demo-v1.exe")):
        p = out / name
        p.write_bytes(PracticeBuild(version).build())
        paths.append(p)
    readme_target = out.parent / (out.name + "-README.md") if out.name != "sigtool-practice" else out / "README.md"
    g0 = PracticeBuild(0)
    (out / "README.md").write_text(PRACTICE_README.format(
        v=0, v2=1, kb=5, gworld=GWORLD_RVA, hmax=HEALTH_MAX_RVA, settings=SETTINGS_RVA,
        field=HEALTH_FIELD,
        update=TEXT_RVA + (0x030 if True else 0),
        call=TEXT_RVA + 0x050,
    ), encoding="utf-8")
    paths.append(out / "README.md")
    return paths


FACTS = {
    "gworld_rva": GWORLD_RVA,
    "max_health_rva": HEALTH_MAX_RVA,
    "settings_rva": SETTINGS_RVA,
    "health_field_v0": HEALTH_FIELD,
    "health_field_v1": HEALTH_FIELD + 0x10,
    "update_health_rva_v0": TEXT_RVA + 0x030,
    "update_health_rva_v1": TEXT_RVA + 0x0A0,
    "call_site_rva_v0": TEXT_RVA + 0x050,
    "call_site_rva_v1": TEXT_RVA + 0x0C0,
    "gworld_insn_rva_v0": TEXT_RVA + 0x000,
    "gworld_insn_rva_v1": TEXT_RVA + 0x080,
}
