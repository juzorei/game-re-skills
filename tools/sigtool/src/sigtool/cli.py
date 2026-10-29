"""sigtool: verify game signatures and pointer chains offline."""

from __future__ import annotations

import argparse
import json
import re
import sys

from . import __version__
from .binary import Binary
from .check import Signature, load_signatures, parse_read, parse_rel, run_check, values_at
from .pattern import parse_pattern
from .suggest import suggest

SHOWN_MATCHES = 10
MAX_MATCHES = 10_000


_HEX_RE = re.compile(r"^(-)?(?:0[xX])?([0-9a-fA-F]+)[hH]?$")


def hex_int(text: str) -> int:
    """Addresses and offsets are hex, with or without 0x, as in every RE tool.

    Backticks and apostrophes are dropped so WinDbg/x64dbg style ``00007ff6`c3430000`` pastes work.
    """
    match = _HEX_RE.match(text.strip().replace("`", "").replace("'", ""))
    if not match:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a hex number")
    value = int(match.group(2), 16)
    return -value if match.group(1) else value


def hex_list(text: str) -> list[int]:
    return [hex_int(part) for part in text.replace(" ", "").split(",") if part]


def int_list(text: str) -> set[int]:
    return {int(part, 0) for part in text.replace(" ", "").split(",") if part}


def _fmt(value: int | None) -> str:
    return "-" if value is None else f"{value:#x}"


def _describe(binary: Binary, section: str | None) -> str:
    ranges = ", ".join(r.label for r in binary.ranges(section))
    if binary.pe is None:
        return f"{binary.path.name} (raw, {len(binary.data):,} bytes), scanning {ranges}"
    kind = "mapped image" if binary.mapped else "PE"
    return (f"{binary.path.name} ({kind} {binary.pe.machine_name}, image base "
            f"{binary.pe.image_base:#x}), scanning {ranges}")


def _value_text(values: dict) -> str:
    parts = []
    if "rel" in values:
        rel = values["rel"]
        if "rva" in rel:
            parts.append(f"rel -> rva {rel['rva']:#x} (va {rel['va']:#x}, offset {_fmt(rel['offset'])})")
        else:
            parts.append(f"rel -> offset {rel['offset']:#x}")
    if "read" in values:
        value = values["read"]
        shown = f"{value:#x} ({value})" if isinstance(value, int) else f"{value!r}"
        parts.append(f"read = {shown}")
    return "  ".join(parts)


def cmd_scan(args) -> int:
    binary = Binary.load(args.file, mapped=args.mapped)
    pattern = parse_pattern(args.pattern)
    sig = Signature(
        "scan",
        pattern,
        rel=parse_rel(args.rel) if args.rel else None,
        read=parse_read(args.read) if args.read else None,
        section=args.section,
    )
    hits = binary.find(pattern, args.section, limit=MAX_MATCHES)
    rows = [{"offset": hit, "rva": binary.to_rva(hit), **values_at(binary, sig, hit)} for hit in hits]

    if args.json:
        print(json.dumps({"pattern": str(pattern), "count": len(hits), "matches": rows}, indent=2))
    else:
        print(f"pattern  {pattern}  ({len(pattern)} bytes, {pattern.fixed_count} fixed)")
        print(f"file     {_describe(binary, args.section)}")
        more = "+" if len(hits) >= MAX_MATCHES else ""
        print(f"matches  {len(hits)}{more}")
        shown = rows if args.all else rows[:SHOWN_MATCHES]
        for i, row in enumerate(shown, 1):
            extra = _value_text({k: v for k, v in row.items() if k in ("rel", "read")})
            print(f"  #{i}  offset {row['offset']:#x}  rva {_fmt(row['rva'])}  {extra}".rstrip())
        if len(rows) > len(shown):
            print(f"  ... {len(rows) - len(shown)} more (use --all)")
        if len(hits) == 0:
            print("no matches: check the pattern, --section and that this is the right build", file=sys.stderr)
        elif len(hits) != 1:
            print("not unique: lengthen it or anchor elsewhere", file=sys.stderr)
    return 0 if len(hits) == 1 else 1


def cmd_suggest(args) -> int:
    binary = Binary.load(args.file, mapped=args.mapped)
    offset = args.address
    if args.rva:
        converted = binary.to_offset(args.address)
        if converted is None:
            raise ValueError(f"rva {args.address:#x} isn't backed by file data")
        offset = converted
    result = suggest(
        binary,
        offset,
        min_len=args.min,
        max_len=args.max,
        extra_wildcards=int_list(args.wildcard) if args.wildcard else None,
        auto=not args.no_auto,
        section=args.section,
    )
    if args.json:
        print(json.dumps({
            "pattern": str(result.pattern),
            "length": len(result.pattern),
            "matches": result.matches,
            "unique": result.unique,
            "offset": offset,
            "rva": binary.to_rva(offset),
            "wildcards": list(result.wildcards),
        }, indent=2))
    else:
        print(f"at       offset {offset:#x}  rva {_fmt(binary.to_rva(offset))}")
        print(f"pattern  {result.pattern}")
        print(f"length   {len(result.pattern)} bytes, {result.pattern.fixed_count} fixed")
        if result.unique:
            print("matches  1 (unique)")
        else:
            print(f"matches  {result.matches}{'+' if result.matches >= 2 else ''} at {len(result.pattern)} bytes: "
                  "not unique, raise --max or start from a more distinctive instruction", file=sys.stderr)
    return 0 if result.unique else 1


def cmd_check(args) -> int:
    signatures = load_signatures(args.signatures)
    results = run_check(signatures, args.files, mapped=args.mapped)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    else:
        name_w = max(len(s.name) for s in signatures)
        current = None
        for r in results:
            if r.file != current:
                current = r.file
                print(f"== {r.file}")
            status = "ok  " if r.ok else "FAIL"
            detail = f"rva {_fmt(r.rva)}" if r.offset is not None else ""
            detail = f"{detail}  {_value_text(r.values)}".strip()
            if r.error:
                detail = f"{detail}  error: {r.error}".strip()
            print(f"  {status} {r.name:<{name_w}}  matches {r.count}  {detail}".rstrip())
        failed = sum(1 for r in results if not r.ok)
        print(f"{len(results) - failed}/{len(results)} passed")
    return 0 if all(r.ok for r in results) else 1


def cmd_chain(args) -> int:
    if sys.platform != "win32":
        raise ValueError("chain reads live process memory and only works on Windows")
    import struct

    from .binary import READ_TYPES
    from .chain import ChainError, WinProcessMemory, find_module, find_pid, walk_chain

    if args.type and args.type not in READ_TYPES:
        raise ValueError(f"unknown type {args.type!r} (use {', '.join(READ_TYPES)})")
    pid = args.pid if args.pid is not None else find_pid(args.process)
    module_name = args.module or args.process
    if not module_name:
        raise ValueError("pass --module when using --pid")
    module_base = find_module(pid, module_name)
    with WinProcessMemory(pid, args.ptr_size) as mem:
        start = module_base + args.base
        print(f"module   {module_name} @ {module_base:#x} (pid {pid}, {mem.pointer_size * 8}-bit pointers)")
        print(f"start    {module_name}+{args.base:#x} = {start:#x}")
        try:
            final, hops = walk_chain(mem, start, args.offsets)
        except ChainError as exc:
            print(f"chain broken: {exc}", file=sys.stderr)
            return 1
        for i, (hop, offset) in enumerate(zip(hops, args.offsets)):
            print(f"  [{hop.address:#x}] -> {hop.pointer:#x}  + {offset:#x} = {hop.pointer + offset:#x}")
        print(f"address  {final:#x}")
        if args.type:
            fmt = READ_TYPES[args.type]
            try:
                raw = mem.read(final, struct.calcsize(fmt))
            except OSError as exc:
                print(f"chain broken: can't read the final address: {exc}", file=sys.stderr)
                return 1
            (value,) = struct.unpack(fmt, raw)
            print(f"value    {value!r} ({args.type})")
    return 0


def cmd_pe(args) -> int:
    binary = Binary.load(args.file)
    if binary.pe is None:
        raise ValueError(f"{binary.path.name} isn't a PE file")
    pe = binary.pe
    print(f"{binary.path.name}: {pe.machine_name}, image base {pe.image_base:#x}, {len(pe.sections)} sections")
    print(f"  {'name':<8} {'rva':>10} {'vsize':>10} {'offset':>10} {'rawsize':>10}  flags")
    for s in pe.sections:
        flags = "x" if s.executable else "-"
        print(f"  {s.name:<8} {s.virtual_address:>#10x} {s.virtual_size:>#10x} "
              f"{s.raw_offset:>#10x} {s.raw_size:>#10x}  {flags}")
    return 0


def cmd_xref(args) -> int:
    from .xref import find_xrefs

    binary = Binary.load(args.file, mapped=args.mapped)
    if args.rva:
        if binary.pe is None:
            raise ValueError(f"{binary.path.name} isn't a PE file, --rva doesn't apply")
        target = args.address
    elif binary.pe is None:
        target = args.address  # raw file or mapped dump: addresses are offsets
    else:
        target = binary.to_rva(args.address)
        if target is None:
            raise ValueError(f"file offset {args.address:#x} isn't mapped to an RVA; pass an RVA with --rva")
    hits = find_xrefs(binary, target)
    if args.json:
        print(json.dumps({"target": target, "count": len(hits),
                          "xrefs": [{"offset": h.offset, "rva": h.rva, "length": h.length,
                                     "kind": h.kind} for h in hits]}, indent=2))
    else:
        print(f"file     {_describe(binary, args.section)}")
        print(f"xrefs    {len(hits)} to {target:#x}")
        for i, h in enumerate(hits[:SHOWN_MATCHES], 1):
            print(f"  #{i}  rva {h.rva:#x}  offset {h.offset:#x}  {h.kind}")
        if len(hits) > SHOWN_MATCHES:
            print(f"  ... {len(hits) - SHOWN_MATCHES} more (use --json)")
    return 0 if hits else 1


def cmd_practice(args) -> int:
    from .practice import write_practice

    for path in write_practice(args.directory):
        print(f"wrote {path}")
    print(f"\nPractice pair ready in {args.directory}. The README lists xref/suggest/scan/check")
    print("exercises: find the code that reads the GWorld-like global, signature it, read the")
    print("health field offset from the store instruction, then regression-check both versions.")
    return 0


def cmd_demo(args) -> int:
    from .demo import write_demo

    for path in write_demo(args.directory):
        print(f"wrote {path}")
    print(f"\ntry:\n  cd {args.directory}\n  sigtool check signatures.toml game-1.0.exe game-1.1.exe\n"
          f"  sigtool suggest game-1.1.exe 0x1180 --rva")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sigtool", description=__doc__)
    parser.add_argument("--version", action="version", version=f"sigtool {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_mapped(p):
        p.add_argument("--mapped", action="store_true",
                       help="file is a module dumped from memory (file offset == RVA)")

    p = sub.add_parser("scan", help="find a pattern in a file")
    p.add_argument("file")
    p.add_argument("pattern", help='e.g. "48 8B 05 ?? ?? ?? ?? 48 85 C0"')
    p.add_argument("--section", help="PE section to scan (default .text, '*' for the whole file)")
    p.add_argument("--all", action="store_true", help=f"list every match, not just the first {SHOWN_MATCHES}")
    p.add_argument("--rel", help="resolve rel32 at match+N (N:K if K more bytes follow the displacement)")
    p.add_argument("--read", help="read a value at match+N, e.g. 4:u32")
    p.add_argument("--json", action="store_true")
    add_mapped(p)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("suggest", help="build the shortest unique pattern starting at an address")
    p.add_argument("file")
    p.add_argument("address", type=hex_int, help="file offset in hex (an RVA with --rva)")
    p.add_argument("--rva", action="store_true", help="address is an RVA")
    p.add_argument("--min", type=int, default=8)
    p.add_argument("--max", type=int, default=64)
    p.add_argument("--wildcard", help="extra byte positions to wildcard, e.g. 3,4,5,6")
    p.add_argument("--no-auto", action="store_true", help="don't auto-wildcard rel32/RIP-relative operands")
    p.add_argument("--section")
    p.add_argument("--json", action="store_true")
    add_mapped(p)
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("check", help="run a signatures.toml against one or more builds")
    p.add_argument("signatures")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true")
    add_mapped(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("chain", help="walk a pointer chain in a running process (Windows, read-only)")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--process", help="process name, e.g. game.exe")
    target.add_argument("--pid", type=int)
    p.add_argument("--module", help="module holding the static base (default: the process exe)")
    p.add_argument("--base", type=hex_int, required=True, help="offset from the module base, hex")
    p.add_argument("--offsets", type=hex_list, default=[], help="comma-separated hex offsets")
    p.add_argument("--type", help="read the final address as this type (u32, f32, ...)")
    p.add_argument("--ptr-size", type=int, choices=(4, 8), help="override pointer size")
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("pe", help="show PE sections and image base")
    p.add_argument("file")
    p.set_defaults(func=cmd_pe)

    p = sub.add_parser("xref", help="find instructions that reference a data or code address")
    p.add_argument("file")
    p.add_argument("address", type=hex_int, help="target address in hex (RVA with --rva, file offset without)")
    p.add_argument("--rva", action="store_true", help="address is an RVA (PE required)")
    p.add_argument("--section", help="scan a specific section (default: executable sections)")
    p.add_argument("--json", action="store_true")
    add_mapped(p)
    p.set_defaults(func=cmd_xref)

    p = sub.add_parser("demo", help="write two synthetic builds and a signatures.toml to try sigtool on")
    p.add_argument("directory", nargs="?", default="sigtool-demo")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("practice", help="write a two-version practice 'game' (xref/suggest/check exercises)")
    p.add_argument("directory", nargs="?", default="sigtool-practice")
    p.set_defaults(func=cmd_practice)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"sigtool: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
