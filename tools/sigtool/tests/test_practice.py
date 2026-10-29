import json

from sigtool.cli import main
from sigtool.practice import FACTS, PracticeBuild, write_practice


def last_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_practice_builds_are_valid_pe():
    for version in (0, 1):
        data = PracticeBuild(version).build()
        assert data[:2] == b"MZ" and len(data) < 8192


def test_full_workflow_v0(tmp_path, capsys):
    out = tmp_path / "p"
    write_practice(out)
    exe = str(out / "gworld-demo-v0.exe")

    # 1. find the code that reads the GWorld-like global
    assert main(["xref", exe, hex(FACTS["gworld_rva"])[2:], "--rva", "--json"]) == 0
    xref = last_json(capsys)["xrefs"][0]
    assert xref["rva"] == FACTS["gworld_insn_rva_v0"]

    # 2. signature it from its file offset (rva 0x1000 -> file 0x400)
    file_off = 0x400 + (xref["rva"] - 0x1000)
    assert main(["suggest", exe, hex(file_off)[2:], "--json"]) == 0
    pattern = last_json(capsys)["pattern"]
    assert pattern.startswith("48 8B 05 ?? ?? ?? ??")

    # 3. read the health field offset from the store instruction
    assert main(["scan", exe, "F3 0F 11 81 ?? ?? ?? ?? C3", "--read", "4:u32", "--json"]) == 0
    scan = last_json(capsys)
    assert scan["matches"][0]["read"] == FACTS["health_field_v0"]

    # 4. cross-build regression: both builds match once, field offset shifted
    toml = tmp_path / "s.toml"
    toml.write_text(
        f'[GWorld]\npattern = "{pattern}"\n\n'
        '[UpdateHealth]\npattern = "F3 0F 11 81 ?? ?? ?? ?? C3"\nread = "4:u32"\n'
    )
    assert main(["check", str(toml), exe, str(out / "gworld-demo-v1.exe")]) == 0
    assert "4/4 passed" in capsys.readouterr().out
    main(["check", str(toml), exe, str(out / "gworld-demo-v1.exe"), "--json"])
    rows = last_json(capsys)
    values = {(r["name"], r["file"]): r["values"] for r in rows}
    assert values["UpdateHealth", "gworld-demo-v0.exe"]["read"] == FACTS["health_field_v0"]
    assert values["UpdateHealth", "gworld-demo-v1.exe"]["read"] == FACTS["health_field_v1"]


def test_hardcoded_guesses_break_between_versions(tmp_path, capsys):
    """The point of the practice pair: hardcoded offsets/values fail on v1."""
    out = tmp_path / "p"
    write_practice(out)
    exe0, exe1 = str(out / "gworld-demo-v0.exe"), str(out / "gworld-demo-v1.exe")

    # v0 hardcoded the health field inside the pattern: matches v0, zero on v1
    bad = tmp_path / "bad.toml"
    import struct

    le = struct.pack("<I", FACTS["health_field_v0"]).hex().upper()
    bad.write_text(
        "[OldHealthField]\npattern = \"F3 0F 11 81 "
        + " ".join(le[i : i + 2] for i in range(0, 8, 2))
        + " C3\"\n"
    )
    assert main(["check", str(bad), exe0]) == 0
    assert main(["check", str(bad), exe0, exe1]) == 1
    assert "FAIL" in capsys.readouterr().out

    # v1 changed the E8 call to an E9 jmp: a "call-anchored" signature dies too
    assert main(["scan", exe0, "E8 ?? ?? ?? ??", "--json"]) == 0
    assert last_json(capsys)["count"] == 1
    assert main(["scan", exe1, "E8 ?? ?? ?? ??", "--json"]) == 1
    assert last_json(capsys)["count"] == 0
