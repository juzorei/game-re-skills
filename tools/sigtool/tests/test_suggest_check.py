import json
import struct
import sys

import pytest

from sigtool.demo import GWORLD_AT, GWORLD_RVA, HEALTH_AT, TEXT_RAW
from sigtool.binary import Binary
from sigtool.chain import ChainError, walk_chain
from sigtool.check import load_signatures, parse_read, parse_rel, run_check
from sigtool.cli import hex_int, hex_list, main
from sigtool.suggest import auto_wildcards, suggest

SNIPPET = bytes.fromhex("48 8B 05 11 22 33 44 48 85 C0 74 05 E8 55 66 77 88 F3 0F 10 05 01 02 03 04 F3 0F 11 81 A8 01 00 00")

SIGNATURES = """
[GWorld]
pattern = "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? E8"
rel = 3

[HealthOffset]
pattern = "F3 0F 11 81 ?? ?? ?? ?? C3"
read = "4:u32"
"""


def test_auto_wildcards_cover_relocatable_operands():
    wild = auto_wildcards(SNIPPET)
    assert {3, 4, 5, 6} <= wild            # mov rax,[rip+disp32]
    assert {13, 14, 15, 16} <= wild        # call rel32
    assert {21, 22, 23, 24} <= wild        # movss xmm0,[rip+disp32]
    assert not wild & set(range(29, 33))   # [rcx+0x1A8] is a field offset, kept fixed


def test_suggest_builds_unique_pattern_that_survives_relocation(make_build):
    old = Binary.load(make_build("old.exe"))
    result = suggest(old, TEXT_RAW + GWORLD_AT)
    assert result.unique
    text = str(result.pattern)
    assert text.startswith("48 8B 05 ?? ?? ?? ??")
    new = Binary.load(make_build("new.exe", gworld_at=0x180, call_target=0x1700))
    assert new.find(result.pattern) == [TEXT_RAW + 0x180]


def test_suggest_rejects_offsets_outside_scan_range(make_build):
    binary = Binary.load(make_build())
    with pytest.raises(ValueError, match="outside the scanned range"):
        suggest(binary, 0x10)


def test_suggest_reports_non_unique_code(tmp_path):
    path = tmp_path / "repeat.bin"
    path.write_bytes(b"\x90\x91" * 64)
    result = suggest(Binary.load(path), 0, max_len=16, auto=False)
    assert not result.unique and result.matches >= 2


def test_check_across_builds(tmp_path, make_build):
    sig_file = tmp_path / "signatures.toml"
    sig_file.write_text(SIGNATURES)
    sigs = load_signatures(sig_file)
    old = make_build("old.exe")
    new = make_build("new.exe", gworld_at=0x180, health_field=0x1B0)
    broken = make_build("broken.exe", tamper=True)
    results = {(r.file, r.name): r for r in run_check(sigs, [old, new, broken])}

    assert results["old.exe", "GWorld"].values["rel"]["rva"] == GWORLD_RVA
    assert results["new.exe", "GWorld"].values["rel"]["rva"] == GWORLD_RVA
    assert results["old.exe", "HealthOffset"].values["read"] == 0x1A8
    assert results["new.exe", "HealthOffset"].values["read"] == 0x1B0
    assert results["new.exe", "HealthOffset"].offset == TEXT_RAW + HEALTH_AT
    assert not results["broken.exe", "GWorld"].ok and results["broken.exe", "GWorld"].count == 0
    assert results["broken.exe", "HealthOffset"].ok


def test_bad_signatures_file(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[X]\npattern = "ZZ"\n')
    with pytest.raises(ValueError, match=r"\[X\]"):
        load_signatures(path)


def test_spec_parsers():
    assert parse_rel(3) == (3, 0)
    assert parse_rel("2:1") == (2, 1)
    assert parse_read("0x4:f32") == (4, "f32")
    assert hex_int("1A8") == 0x1A8 == hex_int("0x1a8")
    assert hex_list("10, 0x20,1A8") == [0x10, 0x20, 0x1A8]


class FakeMemory:
    pointer_size = 8

    def __init__(self, cells: dict[int, int]):
        self.cells = cells

    def read(self, address: int, size: int) -> bytes:
        if address not in self.cells:
            raise OSError("unmapped")
        return struct.pack("<Q", self.cells[address])


def test_walk_chain_matches_cheat_engine_semantics():
    mem = FakeMemory({0x1100: 0x5000, 0x5018: 0x6000})
    final, hops = walk_chain(mem, 0x1100, [0x18, 0x1A8])
    assert final == 0x61A8
    assert [(h.address, h.pointer) for h in hops] == [(0x1100, 0x5000), (0x5018, 0x6000)]


def test_walk_chain_reports_broken_hop():
    with pytest.raises(ChainError, match="hop 1: null pointer"):
        walk_chain(FakeMemory({0x1100: 0x5000, 0x5018: 0}), 0x1100, [0x18, 0x1A8])
    with pytest.raises(ChainError, match="hop 0: can't read"):
        walk_chain(FakeMemory({}), 0x1100, [0x18])


def test_cli_scan_check_suggest(tmp_path, make_build, capsys):
    exe = make_build()
    assert main(["scan", exe, "48 8B 05 ?? ?? ?? ?? 48 85 C0", "--rel", "3", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 1 and out["matches"][0]["rel"]["rva"] == GWORLD_RVA

    assert main(["scan", exe, "DE AD BE EF"]) == 1
    assert "no matches" in capsys.readouterr().err
    sig_file = tmp_path / "s.toml"
    sig_file.write_text(SIGNATURES)
    assert main(["check", str(sig_file), exe]) == 0
    assert "2/2 passed" in capsys.readouterr().out

    assert main(["suggest", exe, hex(TEXT_RAW + GWORLD_AT)]) == 0
    assert "matches  1 (unique)" in capsys.readouterr().out
    assert main(["suggest", exe, "0x1100", "--rva"]) in (0, 1)
    assert main(["pe", exe]) == 0
    assert ".text" in capsys.readouterr().out


def test_cli_errors_exit_2(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "missing.exe"), "90"]) == 2
    assert "error" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform != "win32", reason="live process read is Windows-only")
def test_win_reader_reads_own_module_header():
    import os

    from sigtool.chain import WinProcessMemory, find_module

    exe = os.path.basename(sys.executable)
    base = find_module(os.getpid(), exe)
    with WinProcessMemory(os.getpid()) as mem:
        assert mem.read(base, 2) == b"MZ"
        assert mem.pointer_size == struct.calcsize("P")
