import pytest

from sigtool.pattern import parse_pattern


def test_ida_style_with_wildcards():
    p = parse_pattern("48 8B 05 ?? ? 4? ?F")
    assert p.values == bytes([0x48, 0x8B, 0x05, 0, 0, 0x40, 0x0F])
    assert p.masks == bytes([0xFF, 0xFF, 0xFF, 0, 0, 0xF0, 0x0F])
    assert str(p) == "48 8B 05 ?? ?? 4? ?F"


def test_compact_and_code_style_are_equivalent():
    a = parse_pattern("488B05????")
    b = parse_pattern(r"\x48\x8B\x05\x00\x00 xxx??")
    assert a == b


@pytest.mark.parametrize("bad", ["", "4", "GG", "48 8B 0", r"\x48\x8B xxx"])
def test_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_pattern(bad)


def test_find_all_respects_masks_and_bounds():
    data = bytes.fromhex("00 48 8B 05 11 22 48 8B 05 33 44 48 8B")
    p = parse_pattern("48 8B 05 ?? ??")
    assert p.find_all(data) == [1, 6]
    assert p.find_all(data, start=2) == [6]
    assert p.find_all(data, end=10) == [1]
    assert p.find_all(data, limit=1) == [1]


def test_nibble_wildcard_matching():
    p = parse_pattern("4? 8B")
    assert p.find_all(bytes.fromhex("48 8B 4C 8B 58 8B")) == [0, 2]


def test_anchor_requires_a_fixed_byte():
    with pytest.raises(ValueError):
        parse_pattern("?? ??").find_all(b"\x00\x00")


def test_anchor_picks_longest_fixed_run():
    p = parse_pattern("48 ?? 8B 05 1D ?? 90")
    assert p.anchor() == (2, bytes.fromhex("8B 05 1D"))
