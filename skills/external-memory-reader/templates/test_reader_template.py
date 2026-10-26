"""pytest tests for reader_template.py. They run against FakeMemory on any OS."""
import struct
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import reader_template as rt  # noqa: E402

HERE = Path(__file__).parent
BASE = 0x7FF6_0000_0000      # module base
TEXT_RVA, TEXT_SIZE = 0x1000, 0x200
GLOBAL_RVA = 0x2000          # global pointer slot -> player object
NULL_RVA = 0x2008            # global that holds null
PLAYER = 0x2_0000_1000       # heap address of the player object
HEALTH_OFF = 0x1A4
SIGS = {
    "LocalPlayer": {"pattern": "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ??", "rel": 3},
    "HealthOffset": {"pattern": "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1", "read": "4:u32"},
}
CFG = {
    "module": "Game.exe",
    "signatures": SIGS,
    "chains": {"player": {"base": "LocalPlayer", "offsets": [0x0]},
               "camera": {"base": NULL_RVA, "offsets": [0x0, 0x30]}},
    "structs": {"player": {"fields": {"health": ["HealthOffset", "f"], "position": [0x90, "3f"]}},
                "camera": {"fields": {"fov": [0x0, "f"]}}},
}


def build_image(stamp: int = 0x5F00_0000, with_code: bool = True) -> bytearray:
    img = bytearray(0x3000)
    img[0:2] = b"MZ"
    struct.pack_into("<I", img, 0x3C, 0x80)
    img[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", img, 0x84, 0x8664, 1, stamp)   # machine, sections, stamp
    struct.pack_into("<H", img, 0x80 + 20, 0xF0)             # SizeOfOptionalHeader
    struct.pack_into("<I", img, 0x80 + 24 + 56, len(img))    # SizeOfImage
    struct.pack_into("<8sII", img, 0x80 + 24 + 0xF0, b".text", TEXT_SIZE, TEXT_RVA)
    if with_code:
        at = TEXT_RVA + 0x40   # mov rax,[rip+disp] ; test rax,rax ; jz
        disp = GLOBAL_RVA - (at + 7)
        img[at:at + 12] = b"\x48\x8B\x05" + struct.pack("<i", disp) + b"\x48\x85\xC0\x74\x05"
        at = TEXT_RVA + 0x80   # movss xmm0,[rcx+HEALTH_OFF] ; comiss xmm0,xmm1
        img[at:at + 11] = b"\xF3\x0F\x10\x81" + struct.pack("<I", HEALTH_OFF) + b"\x0F\x2F\xC1"
    struct.pack_into("<Q", img, GLOBAL_RVA, PLAYER)
    return img


def build_player(health: float = 87.5) -> bytearray:
    blob = bytearray(0x200)
    struct.pack_into("<f", blob, HEALTH_OFF, health)
    struct.pack_into("<3f", blob, 0x90, 1.0, 2.0, 3.0)
    return blob


@pytest.fixture
def mem():
    return rt.FakeMemory({BASE: build_image(), PLAYER: build_player()}, {"game.exe": BASE})


def test_pattern_wildcards():
    rx = rt.compile_pattern("48 ?? 4? ?F")
    assert rx.fullmatch(b"\x48\x00\x4A\x3F")
    assert not rx.fullmatch(b"\x48\x00\x5A\x3F")
    assert not rx.fullmatch(b"\x48\x00\x4A\x3E")
    with pytest.raises(ValueError):
        rt.compile_pattern("488")


def test_signatures_resolve(mem):
    sigs = rt.resolve_all(mem, BASE, SIGS)
    assert sigs["LocalPlayer"].value == GLOBAL_RVA
    assert sigs["HealthOffset"].value == HEALTH_OFF


def test_rel_with_trailing_bytes():
    text = b"\x80\x3D" + struct.pack("<i", 0x10) + b"\x01"   # cmp byte [rip+0x10], 1
    assert rt.resolve_signature(text, 0x1000, {"pattern": "80 3D ?? ?? ?? ?? 01", "rel": "2:1"}) \
        == 0x1000 + 7 + 0x10


def test_missing_or_ambiguous_signature_is_an_error():
    with pytest.raises(rt.ReadError, match="0 times"):
        rt.resolve_signature(b"\x90" * 16, 0, {"pattern": "CC CC"})
    with pytest.raises(rt.ReadError, match="2 times"):
        rt.resolve_signature(b"\xCC\x90\xCC", 0, {"pattern": "CC"})


def test_cache_reused_for_same_build_and_invalidated_by_patch(tmp_path):
    cache = tmp_path / "sigs.cache.json"
    mem = rt.FakeMemory({BASE: build_image()}, {"game.exe": BASE})
    rt.resolve_all(mem, BASE, SIGS, cache)
    assert cache.exists()
    # Same build stamp, code gone: cached values are used, no rescan.
    stale = rt.FakeMemory({BASE: build_image(with_code=False)}, {"game.exe": BASE})
    assert rt.resolve_all(stale, BASE, SIGS, cache)["LocalPlayer"].value == GLOBAL_RVA
    # New build stamp: cache ignored, rescan reports the broken signatures.
    patched = rt.FakeMemory({BASE: build_image(stamp=0x6000_0000, with_code=False)}, {"game.exe": BASE})
    out = rt.resolve_all(patched, BASE, SIGS, cache)
    assert not out["LocalPlayer"].ok and "0 times" in out["LocalPlayer"].error


def test_follow_chain(mem):
    assert rt.follow_chain(mem, BASE + GLOBAL_RVA, [0x90]) == PLAYER + 0x90
    assert rt.follow_chain(mem, BASE + GLOBAL_RVA, []) == BASE + GLOBAL_RVA
    with pytest.raises(rt.ReadError, match="hop 0.*null"):
        rt.follow_chain(mem, BASE + NULL_RVA, [0x0])


@pytest.mark.parametrize("ptr, msg", [(0, "null"), (0xFFFF_8000_0000_0000, "user space"),
                                      (0x2_0000_1003, "aligned"), (0x100, "user space")])
def test_check_pointer_rejects(ptr, msg):
    with pytest.raises(rt.ReadError, match=msg):
        rt.check_pointer(ptr)


def test_struct_view_is_one_read(mem):
    view = rt.StructView({"health": rt.Field(HEALTH_OFF, "f"), "position": rt.Field(0x90, "3f")})
    before = mem.reads
    out = view.read(mem, PLAYER)
    assert mem.reads - before == 1
    assert out == {"health": 87.5, "position": (1.0, 2.0, 3.0)}


def test_snapshot_reports_partial_failure(mem):
    reader = rt.Reader(mem, CFG)
    snap = reader.snapshot()
    assert snap.views["player"].value == {"health": 87.5, "position": (1.0, 2.0, 3.0)}
    assert set(snap.errors()) == {"camera"}
    assert "null" in snap.errors()["camera"]


def test_unresolved_signature_is_reported_not_zero():
    mem = rt.FakeMemory({BASE: build_image(with_code=False), PLAYER: build_player()}, {"game.exe": BASE})
    snap = rt.Reader(mem, CFG).snapshot()
    assert snap.views["player"].value is None
    assert "HealthOffset unresolved" in snap.views["player"].error


def test_unmapped_read_raises():
    with pytest.raises(rt.ReadError, match="unmapped"):
        rt.FakeMemory().read(0x1000, 4)


def test_run_loop_sees_changes_between_ticks(mem):
    reader = rt.Reader(mem, CFG)
    seen = []

    def on_snapshot(snap):
        seen.append(snap.views["player"].value["health"])
        mem.regions[PLAYER] = build_player(health=50.0)   # the "game" changes the value

    rt.run(reader, hz=1000, on_snapshot=on_snapshot, ticks=3)
    assert seen == [87.5, 50.0, 50.0]


def test_containers():
    data, arr = 0x3_0000_0000, 0x3_0000_1000
    mem = rt.FakeMemory({data: "Héllo".encode("utf-16-le"), arr: struct.pack("<3I", 7, 8, 9)})
    assert rt.read_utf16(mem, data, 5) == "Héllo"
    assert rt.read_utf16(mem, 0, 0) == ""
    assert [struct.unpack("<I", e)[0] for e in rt.read_counted_array(mem, arr, 3, 4)] == [7, 8, 9]
    with pytest.raises(rt.ReadError, match="implausible"):
        rt.read_utf16(mem, data, -1)
    with pytest.raises(rt.ReadError, match="implausible"):
        rt.read_counted_array(mem, data, 10**9, 8)


def test_example_config_loads():
    cfg = rt.load_config(HERE / "offsets.example.toml")
    assert cfg["module"] and set(cfg["signatures"]) == {"LocalPlayer", "HealthOffset"}
    assert set(cfg["structs"]) <= set(cfg["chains"])


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")
def test_win_backend_reads_own_process():
    import ctypes
    import os
    buf = ctypes.create_string_buffer(b"read-only reader", 32)
    mem = rt.WinProcessMemory(os.getpid())
    try:
        assert mem.read(ctypes.addressof(buf), 16) == b"read-only reader"
        base = mem.module_base("kernel32.dll")
        assert mem.read(base, 2) == b"MZ"
        assert rt.text_section(mem, base)[1] > 0
        assert mem.alive()
    finally:
        mem.close()
