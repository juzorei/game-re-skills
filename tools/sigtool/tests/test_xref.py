import json
import struct

import pytest

from sigtool.binary import Binary
from sigtool.cli import main
from sigtool.demo import GWORLD_RVA, build_pe
from sigtool.xref import find_xrefs


def nop_code(snippets: dict[int, bytes]) -> bytes:
    """0x90 filler keeps the linear sweep in sync, so snippets sit on boundaries."""
    from sigtool.demo import TEXT_SIZE

    code = bytearray(b"\x90" * TEXT_SIZE)
    for at, snippet in snippets.items():
        code[at : at + len(snippet)] = snippet
    return bytes(code)


def gworld_snippet(at: int) -> dict[int, bytes]:
    from sigtool.demo import GWORLD_AT

    next_rva = 0x1000 + at + 7
    return {at: b"\x48\x8B\x05" + struct.pack("<i", GWORLD_RVA - next_rva) + b"\x48\x85\xC0\x74\x05"}


def test_finds_rip_relative_xref_to_gworld(tmp_path):
    path = tmp_path / "g.exe"
    path.write_bytes(build_pe(nop_code(gworld_snippet(0x100))))
    hits = find_xrefs(Binary.load(path), GWORLD_RVA)
    assert len(hits) == 1
    assert hits[0].rva == 0x1100 and hits[0].kind == "rip" and hits[0].disp_offset == 3


def test_finds_branch_xrefs(tmp_path):
    call = lambda src, dst: b"\xE8" + struct.pack("<i", dst - (0x1000 + src + 5))
    je = b"\x0F\x84" + struct.pack("<i", 0x1000 - (0x1000 + 0xA0 + 6))
    path = tmp_path / "x.exe"
    path.write_bytes(build_pe(nop_code({
        0x60: call(0x60, 0x1000),
        0x80: call(0x80, 0x1000),
        0xA0: je,
    })))
    hits = find_xrefs(Binary.load(path), 0x1000)
    assert [h.kind for h in hits] == ["rel32", "rel32", "rel32"]
    assert [h.rva for h in hits] == [0x1060, 0x1080, 0x10A0]


def test_no_xrefs_to_unreferenced_address(make_build):
    assert find_xrefs(Binary.load(make_build()), 0x99999) == []


def test_cli_xref_json(tmp_path, capsys):
    exe = str(tmp_path / "g.exe")
    open(exe, "wb").write(build_pe(nop_code(gworld_snippet(0x100))))
    assert main(["xref", exe, "3040", "--rva", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["xrefs"]
    assert len(rows) == 1 and rows[0]["kind"] == "rip" and rows[0]["rva"] == 0x1100


def test_cli_xref_by_file_offset(tmp_path, capsys):
    exe = str(tmp_path / "g.exe")
    open(exe, "wb").write(build_pe(nop_code(gworld_snippet(0x100))))
    assert main(["xref", exe, "c40"]) == 0  # 0xC40 = file offset of GWorld in .data
    assert "xrefs    1" in capsys.readouterr().out


def test_cli_xref_text_and_none(tmp_path, capsys):
    exe = str(tmp_path / "g.exe")
    open(exe, "wb").write(build_pe(nop_code(gworld_snippet(0x100))))
    assert main(["xref", exe, "3040", "--rva"]) == 0 and "xrefs    1" in capsys.readouterr().out
    assert main(["xref", exe, "c40", "--rva"]) == 1 and "xrefs    0" in capsys.readouterr().out


def test_cli_xref_wrong_kind_of_address(make_build):
    exe = make_build()
    assert main(["xref", exe, "0"]) == 2  # PE header area isn't a mapped section offset


def test_xref_on_raw_file(tmp_path, capsys):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x90" * 32)
    assert main(["xref", str(path), "10"]) in (0, 1)
    assert main(["xref", str(path), "10", "--rva"]) == 2
    assert "isn't a PE" in capsys.readouterr().err
