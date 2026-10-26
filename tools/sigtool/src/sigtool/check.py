"""Run a signatures file against one or more builds."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .binary import Binary
from .pattern import Pattern, parse_pattern


def parse_rel(spec: int | str) -> tuple[int, int]:
    """``3`` or ``"3"`` -> (3, 0); ``"2:1"`` -> (2, 1)."""
    if isinstance(spec, int):
        return spec, 0
    at, _, extra = str(spec).partition(":")
    try:
        return int(at, 0), int(extra, 0) if extra else 0
    except ValueError:
        raise ValueError(f"rel spec {spec!r} should look like '3' or '2:1'") from None


def parse_read(spec: str) -> tuple[int, str]:
    """``"4:u32"`` -> (4, "u32")."""
    at, sep, type_name = spec.partition(":")
    try:
        if not sep:
            raise ValueError
        return int(at, 0), type_name
    except ValueError:
        raise ValueError(f"read spec {spec!r} should look like '4:u32'") from None


@dataclass(frozen=True)
class Signature:
    name: str
    pattern: Pattern
    rel: tuple[int, int] | None = None
    read: tuple[int, str] | None = None
    expect: int = 1
    section: str | None = None


@dataclass
class Result:
    name: str
    file: str
    count: int
    ok: bool
    offset: int | None = None
    rva: int | None = None
    values: dict = field(default_factory=dict)
    error: str | None = None


def load_signatures(path: str | Path) -> list[Signature]:
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    sigs = []
    for name, entry in doc.items():
        if not isinstance(entry, dict) or "pattern" not in entry:
            raise ValueError(f"[{name}] needs a 'pattern' key")
        for key, types in (("pattern", str), ("read", str), ("rel", (int, str)),
                           ("expect", int), ("section", str)):
            if key in entry and (not isinstance(entry[key], types) or isinstance(entry[key], bool)):
                raise ValueError(f"[{name}] '{key}' has the wrong type ({type(entry[key]).__name__})")
        try:
            sigs.append(
                Signature(
                    name=name,
                    pattern=parse_pattern(entry["pattern"]),
                    rel=parse_rel(entry["rel"]) if "rel" in entry else None,
                    read=parse_read(entry["read"]) if "read" in entry else None,
                    expect=int(entry.get("expect", 1)),
                    section=entry.get("section"),
                )
            )
        except ValueError as exc:
            raise ValueError(f"[{name}] {exc}") from None
    if not sigs:
        raise ValueError(f"{path} has no signatures")
    return sigs


def run_signature(binary: Binary, sig: Signature) -> Result:
    try:
        hits = binary.find(sig.pattern, sig.section, limit=max(sig.expect, 1) + 1)
    except ValueError as exc:
        return Result(sig.name, binary.path.name, 0, False, error=str(exc))
    result = Result(sig.name, binary.path.name, len(hits), len(hits) == sig.expect)
    if len(hits) != 1:
        return result
    hit = hits[0]
    result.offset, result.rva = hit, binary.to_rva(hit)
    try:
        result.values = values_at(binary, sig, hit)
    except ValueError as exc:
        result.ok, result.error = False, str(exc)
    return result


def values_at(binary: Binary, sig: Signature, hit: int) -> dict:
    values = {}
    if sig.rel is not None:
        values["rel"] = binary.resolve_rel32(hit, *sig.rel)
    if sig.read is not None:
        at, type_name = sig.read
        values["read"] = binary.read(hit + at, type_name)
    return values


def run_check(signatures: list[Signature], files: list[str | Path], mapped: bool = False) -> list[Result]:
    results = []
    for path in files:
        binary = Binary.load(path, mapped=mapped)
        results += [run_signature(binary, sig) for sig in signatures]
    return results
