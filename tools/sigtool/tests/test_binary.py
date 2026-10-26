import pytest

from sigtool.demo import DATA_RAW, GWORLD_AT, GWORLD_RVA, HEALTH_AT, IMAGE_BASE, TEXT_RAW, TEXT_RVA, build_code, build_pe
from sigtool.binary import Binary
from sigtool.pattern import parse_pattern
from sigtool.pe import PEError, parse_pe

GWORLD_SIG = parse_pattern("48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? E8")


def test_parse_pe_layout(make_build):
    pe = Binary.load(make_build()).pe
    assert pe.is_64bit and pe.machine_name == "x64" and pe.image_base == IMAGE_BASE
    assert [s.name for s in pe.sections] == [".text", ".data"]
    assert pe.section(".text").executable and not pe.section(".data").executable
    assert pe.offset_to_rva(TEXT_RAW + 0x10) == TEXT_RVA + 0x10
    assert pe.rva_to_offset(GWORLD_RVA) == DATA_RAW + 0x40
    assert pe.rva_to_offset(0x9999) is None


def test_non_pe_is_rejected():
    with pytest.raises(PEError):
        parse_pe(b"\x00" * 0x100)


def test_scan_finds_unique_match_and_resolves_rip_relative(make_build):
    binary = Binary.load(make_build())
    hits = binary.find(GWORLD_SIG)
    assert hits == [TEXT_RAW + GWORLD_AT]
    resolved = binary.resolve_rel32(hits[0], 3)
    assert resolved["rva"] == GWORLD_RVA
    assert resolved["va"] == IMAGE_BASE + GWORLD_RVA
    assert resolved["offset"] == DATA_RAW + 0x40


def test_trailing_bytes_shift_the_rel32_base(make_build):
    binary = Binary.load(make_build())
    hit = binary.find(GWORLD_SIG)[0]
    assert binary.resolve_rel32(hit, 3, 1)["rva"] == GWORLD_RVA + 1


def test_read_field_offset_from_instruction(make_build):
    binary = Binary.load(make_build(health_field=0x1B0))
    hit = binary.find(parse_pattern("F3 0F 11 81 ?? ?? ?? ?? C3"))[0]
    assert hit == TEXT_RAW + HEALTH_AT
    assert binary.read(hit + 4, "u32") == 0x1B0


def test_default_scan_stays_in_text(make_build):
    binary = Binary.load(make_build())
    assert [r.label for r in binary.ranges()] == [".text"]
    assert [r.label for r in binary.ranges("*")] == ["file"]
    with pytest.raises(ValueError, match="no section"):
        binary.ranges(".rdata")


def test_mapped_image_uses_virtual_addresses(tmp_path):
    raw = build_pe(build_code())
    image = bytearray(0x3200)
    image[: 0x400] = raw[: 0x400]
    image[TEXT_RVA : TEXT_RVA + 0x800] = raw[TEXT_RAW : TEXT_RAW + 0x800]
    path = tmp_path / "dump.bin"
    path.write_bytes(bytes(image))
    binary = Binary.load(path, mapped=True)
    hit = binary.find(GWORLD_SIG)[0]
    assert hit == TEXT_RVA + GWORLD_AT == binary.to_rva(hit)
    assert binary.resolve_rel32(hit, 3)["rva"] == GWORLD_RVA


def test_raw_file_scans_everything(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x90" * 10 + b"\x48\x8B\x05\x01\x02\x03\x04")
    binary = Binary.load(path)
    assert binary.pe is None
    assert binary.find(parse_pattern("48 8B 05")) == [10]
    assert binary.resolve_rel32(10, 3)["offset"] == 17 + 0x04030201


def test_reads_are_bounds_checked(make_build):
    binary = Binary.load(make_build())
    with pytest.raises(ValueError):
        binary.read(len(binary.data) - 2, "u32")
    with pytest.raises(ValueError):
        binary.resolve_rel32(len(binary.data) - 2, 0)
    with pytest.raises(ValueError):
        binary.read(0, "u128")
