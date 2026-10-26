import argparse
import struct

import pytest

from sigtool.binary import Binary
from sigtool.check import load_signatures
from sigtool.cli import hex_int, main
from sigtool.demo import TEXT_RAW, TEXT_SIZE
from sigtool.pattern import parse_pattern
from sigtool.pe import parse_pe
from sigtool.suggest import auto_wildcards, suggest
from sigtool.x64 import decode, sweep


@pytest.mark.parametrize(
    "hexbytes, length, reloc",
    [
        ("48 8B 05 11 22 33 44", 7, [3, 4, 5, 6]),            # mov rax,[rip+x]
        ("48 8D 0D 11 22 33 44", 7, [3, 4, 5, 6]),            # lea rcx,[rip+x]
        ("E8 11 22 33 44", 5, [1, 2, 3, 4]),                  # call rel32
        ("0F 84 11 22 33 44", 6, [2, 3, 4, 5]),               # je rel32
        ("74 05", 2, []),                                     # je rel8
        ("F3 0F 11 81 A8 01 00 00", 8, []),                   # movss [rcx+1A8],xmm0
        ("F3 0F 10 05 11 22 33 44", 8, [4, 5, 6, 7]),         # movss xmm0,[rip+x]
        ("48 8B 41 E8", 4, []),                               # mov rax,[rcx-18]
        ("48 8B 44 24 30", 5, []),                            # mov rax,[rsp+30] (SIB, disp8)
        ("48 8B 04 25 11 22 33 44", 8, []),                   # mov rax,[abs32] (SIB, no base)
        ("80 3D 11 22 33 44 00", 7, [2, 3, 4, 5]),            # cmp byte [rip+x],0
        ("C7 05 11 22 33 44 01 00 00 00", 10, [2, 3, 4, 5]),  # mov dword [rip+x],1
        ("48 81 EC 28 01 00 00", 7, []),                      # sub rsp,128h
        ("66 0F 6F 05 11 22 33 44", 8, [4, 5, 6, 7]),         # movdqa xmm0,[rip+x]
        ("C5 FA 10 05 11 22 33 44", 8, [4, 5, 6, 7]),         # vmovss xmm0,[rip+x]
        ("C4 E2 79 18 05 11 22 33 44", 9, [5, 6, 7, 8]),      # vbroadcastss xmm0,[rip+x]
        ("48 B8 01 02 03 04 05 06 07 08", 10, []),            # mov rax,imm64
        ("F6 05 11 22 33 44 01", 7, [2, 3, 4, 5]),            # test byte [rip+x],1
        ("F7 D8", 2, []),                                     # neg eax (no imm)
        ("0F B6 05 11 22 33 44", 7, [3, 4, 5, 6]),            # movzx eax,byte [rip+x]
    ],
)
def test_decoder_lengths_and_relocations(hexbytes, length, reloc):
    insn = decode(bytes.fromhex(hexbytes), 0)
    assert insn is not None
    assert (insn.length, list(insn.relocatable)) == (length, reloc)


def test_field_offsets_containing_e8_stay_fixed():
    code = bytes.fromhex("F3 0F 11 81 E8 01 00 00 C3 48 8B 41 E8 48 85 C0")
    assert auto_wildcards(code) == set()
    assert [i.length for i in sweep(code)] == [8, 1, 4, 3]


def test_find_all_with_range_shorter_than_pattern():
    data = b"\x90" * 100 + b"\x48\x8B\x05"
    p = parse_pattern("48 8B 05")
    assert p.find_all(data, 0, 0) == []
    assert p.find_all(data, 101, 103) == []
    assert p.find_all(data, 100, 103) == [100]


def test_empty_section_doesnt_scan_the_file(tmp_path, make_build):
    path = make_build()
    data = bytearray(open(path, "rb").read())
    pe = parse_pe(bytes(data))
    table = 0x98 + 0xF0
    struct.pack_into("<8sIIII12xI", data, table + 40, b".bss", 0x100, 0x3000, 0, 0, 0xC0000080)
    path2 = tmp_path / "bss.exe"
    path2.write_bytes(bytes(data))
    assert pe.section(".text")
    assert Binary.load(path2).find(parse_pattern("48 8B 05"), ".bss") == []


def test_suggest_near_end_of_section(tmp_path):
    from sigtool.demo import build_code, build_pe

    code = bytearray(build_code())
    code[-12:] = bytes.fromhex("DE AD BE EF 01 23 45 67 89 AB CD EF")
    path = tmp_path / "tail.exe"
    path.write_bytes(build_pe(bytes(code)))
    result = suggest(Binary.load(path), TEXT_RAW + TEXT_SIZE - 12, auto=False)
    assert result.unique and len(result.pattern) == 8


@pytest.mark.parametrize("bad", ["--5", "0x-5", "0x0x10", "1_0", "+10", "- 5", "", "zz"])
def test_hex_int_rejects_garbage(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        hex_int(bad)


@pytest.mark.parametrize("good, value", [("1A8", 0x1A8), ("0x1a8", 0x1A8), ("-0x18", -0x18),
                                         ("00007ff6`c3430000", 0x7FF6C3430000), ("1A8h", 0x1A8)])
def test_hex_int_accepts_re_tool_formats(good, value):
    assert hex_int(good) == value


@pytest.mark.parametrize("body", ['pattern = 5', 'pattern = "90"\nread = 4', 'pattern = "90"\nexpect = "1"',
                                  'pattern = "90"\nrel = true'])
def test_wrong_toml_types_are_value_errors(tmp_path, body, capsys):
    path = tmp_path / "s.toml"
    path.write_text(f"[X]\n{body}\n")
    with pytest.raises(ValueError, match=r"\[X\]"):
        load_signatures(path)
    assert main(["check", str(path), str(path)]) == 2
