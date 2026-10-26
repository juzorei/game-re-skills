"""Read-only external memory reader template (Windows x64, stdlib only).

Pipeline: MemoryBackend (WinProcessMemory | FakeMemory) -> module base -> signatures
resolved once per build (cached) -> pointer chains -> StructView blocks -> one Snapshot
per tick. Read-only by design: no WriteProcessMemory, no injection, no remote threads.

Usage: py -3 reader_template.py offsets.toml [--pid N] [--ticks N]
"""
from __future__ import annotations

import argparse
import ctypes
import functools
import hashlib
import json
import re
import struct
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Protocol, TypeVar

T = TypeVar("T")
USER_MIN, USER_MAX = 0x10000, 0x7FFF_FFFF_FFFF  # canonical x64 user-mode range
TYPES = {"i8": "b", "u8": "B", "i16": "h", "u16": "H", "i32": "i", "u32": "I",
         "i64": "q", "u64": "Q", "f32": "f", "f64": "d"}


class ReadError(Exception):
    """A read failed, a pointer was invalid or a signature did not resolve."""


class MemoryBackend(Protocol):
    def read(self, address: int, size: int) -> bytes: ...
    def module_base(self, name: str) -> int: ...
    def alive(self) -> bool: ...


@dataclass(frozen=True)
class Result(Generic[T]):
    """Value or error. One bad field reports why; it never crashes the loop or reads as 0."""
    value: T | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def attempt(fn: Callable[..., T], *args) -> Result[T]:
    try:
        return Result(value=fn(*args))
    except (ReadError, KeyError, ValueError, TypeError, struct.error) as exc:
        return Result(error=f"{type(exc).__name__}: {exc}")


# --- typed reads, pointers, structs --------------------------------------------------

def read_type(mem: MemoryBackend, address: int, fmt: str):
    return struct.unpack("<" + fmt, mem.read(address, struct.calcsize("<" + fmt)))[0]


def check_pointer(ptr: int, align: int = 8) -> int:
    if ptr == 0:
        raise ReadError("null pointer")
    if not USER_MIN <= ptr <= USER_MAX:
        raise ReadError(f"pointer 0x{ptr:X} outside user space")
    if ptr % align:
        raise ReadError(f"pointer 0x{ptr:X} not {align}-byte aligned")
    return ptr


def follow_chain(mem: MemoryBackend, base: int, offsets: list[int]) -> int:
    """Cheat Engine semantics: [[base]+o1]+o2... Returns the final address, not its value."""
    addr = base
    for hop, off in enumerate(offsets):
        try:
            addr = check_pointer(read_type(mem, addr, "Q")) + off
        except ReadError as exc:
            raise ReadError(f"hop {hop} at 0x{addr:X}: {exc}") from None
    return addr


@dataclass(frozen=True)
class Field:
    offset: int
    fmt: str  # struct format: "f", "i", "Q", "3f", ...


class StructView:
    """Reads the whole struct in one call, then unpacks fields from the local copy."""

    def __init__(self, fields: dict[str, Field]):
        self.fields = fields
        self.size = max(f.offset + struct.calcsize("<" + f.fmt) for f in fields.values())

    def read(self, mem: MemoryBackend, address: int) -> dict:
        block = mem.read(address, self.size)
        out = {}
        for name, f in self.fields.items():
            vals = struct.unpack_from("<" + f.fmt, block, f.offset)
            out[name] = vals[0] if len(vals) == 1 else vals
        return out


# --- engine containers: layouts come from unreal-sdk-offsets / unity-il2cpp-offsets ---

def read_utf16(mem: MemoryBackend, data_ptr: int, count: int, limit: int = 4096) -> str:
    """Counted UTF-16 string (UE FString {data,num,max}; il2cpp String chars at +0x14)."""
    if not 0 <= count <= limit:
        raise ReadError(f"implausible string length {count}")
    if count == 0:
        return ""
    raw = mem.read(check_pointer(data_ptr, align=2), count * 2)
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00")


def read_counted_array(mem: MemoryBackend, data_ptr: int, count: int, stride: int,
                       limit: int = 100_000) -> list[bytes]:
    """{data, count} containers (UE TArray, il2cpp Array/List items): one block read."""
    if not 0 <= count <= limit:
        raise ReadError(f"implausible element count {count}")
    if count == 0:
        return []
    block = mem.read(check_pointer(data_ptr), count * stride)
    return [block[i * stride:(i + 1) * stride] for i in range(count)]


# --- signatures ------------------------------------------------------------------------

def compile_pattern(pattern: str) -> re.Pattern[bytes]:
    """IDA/CE syntax: '48 8B 05 ?? ?? ?? ??', with nibble wildcards like '4?' and '?F'."""
    parts = []
    for tok in pattern.split():
        if len(tok) != 2 and tok != "?":
            raise ValueError(f"bad pattern token {tok!r}")
        if tok in ("?", "??"):
            parts.append(b".")
        elif "?" not in tok:
            parts.append(re.escape(bytes([int(tok, 16)])))
        elif tok[1] == "?":  # high nibble fixed
            hi = int(tok[0], 16) << 4
            parts.append(b"[" + re.escape(bytes([hi])) + b"-" + re.escape(bytes([hi | 0xF])) + b"]")
        else:  # low nibble fixed
            lo = int(tok[1], 16)
            parts.append(b"[" + b"".join(re.escape(bytes([h << 4 | lo])) for h in range(16)) + b"]")
    return re.compile(b"".join(parts), re.DOTALL)


def text_section(mem: MemoryBackend, base: int) -> tuple[int, int, str]:
    """Return (rva, size, build_key) of .text from the mapped PE headers."""
    hdr = mem.read(base, 0x1000)
    if hdr[:2] != b"MZ":
        raise ReadError("no MZ header at module base")
    pe = struct.unpack_from("<I", hdr, 0x3C)[0]
    if hdr[pe:pe + 4] != b"PE\0\0":
        raise ReadError("no PE signature")
    nsec, stamp = struct.unpack_from("<HI", hdr, pe + 6)
    opt_size = struct.unpack_from("<H", hdr, pe + 20)[0]
    image_size = struct.unpack_from("<I", hdr, pe + 24 + 56)[0]
    sec = pe + 24 + opt_size
    for i in range(nsec):
        name, vsize, rva = struct.unpack_from("<8sII", hdr, sec + i * 40)
        if name.rstrip(b"\0") == b".text":
            return rva, vsize, f"{stamp:08X}-{image_size:X}"
    raise ReadError(".text section not found")


def resolve_signature(text: bytes, text_rva: int, spec: dict) -> int:
    """Return an RVA (rel / plain match) or an embedded value (read = 'N:type')."""
    hits = [m.start() for m in compile_pattern(spec["pattern"]).finditer(text)]
    if len(hits) != 1:
        raise ReadError(f"pattern matched {len(hits)} times, expected 1")
    pos = hits[0]
    if "rel" in spec:
        n, _, k = str(spec["rel"]).partition(":")
        disp_at = pos + int(n, 0)
        disp = struct.unpack_from("<i", text, disp_at)[0]
        return text_rva + disp_at + 4 + int(k or "0", 0) + disp
    if "read" in spec:
        n, _, typ = spec["read"].partition(":")
        return struct.unpack_from("<" + TYPES[typ], text, pos + int(n, 0))[0]
    return text_rva + pos


def resolve_all(mem: MemoryBackend, base: int, sigs: dict[str, dict],
                cache_path: Path | None = None) -> dict[str, Result[int]]:
    """Scan .text once; cache successes keyed by build + signature text so a patch or
    an edited pattern invalidates them. Failures are never cached."""
    rva, size, build = text_section(mem, base)
    key = build + "-" + hashlib.sha1(json.dumps(sigs, sort_keys=True).encode()).hexdigest()[:12]
    if cache_path and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("key") == key:
                return {name: Result(value=v) for name, v in cached["values"].items()}
        except (ValueError, KeyError, TypeError, AttributeError):
            pass  # corrupt cache: rescan
    text = mem.read(base + rva, size)
    out = {name: attempt(resolve_signature, text, rva, spec) for name, spec in sigs.items()}
    if cache_path and all(r.ok for r in out.values()):
        cache_path.write_text(json.dumps({"key": key, "values": {n: r.value for n, r in out.items()}}))
    return out


# --- Windows backend (ctypes, read-only) -------------------------------------------------

PROCESS_VM_READ, PROCESS_QUERY_LIMITED_INFORMATION = 0x0010, 0x1000
TH32CS_SNAPPROCESS, TH32CS_SNAPMODULE, TH32CS_SNAPMODULE32 = 0x2, 0x8, 0x10


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("th32ModuleID", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("GlblcntUsage", ctypes.c_uint32),
                ("ProccntUsage", ctypes.c_uint32), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", ctypes.c_uint32), ("hModule", ctypes.c_void_p),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


@functools.cache
def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    for fn in ("Module32FirstW", "Module32NextW", "Process32FirstW", "Process32NextW"):
        getattr(k, fn).argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    return k


def _toolhelp(flags: int, pid: int, entry_type, first: str, nxt: str):
    k = _k32()
    snap = k.CreateToolhelp32Snapshot(flags, pid)
    if snap in (None, ctypes.c_void_p(-1).value):
        raise ReadError(f"CreateToolhelp32Snapshot failed ({ctypes.get_last_error()})")
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry_type)
        ok = getattr(k, first)(snap, ctypes.byref(entry))
        while ok:
            yield entry
            ok = getattr(k, nxt)(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)


def find_pid(exe_name: str) -> int:
    for e in _toolhelp(TH32CS_SNAPPROCESS, 0, PROCESSENTRY32W, "Process32FirstW", "Process32NextW"):
        if e.szExeFile.lower() == exe_name.lower():
            return e.th32ProcessID
    raise ReadError(f"process {exe_name} not running")


class WinProcessMemory:
    """ReadProcessMemory backend. The handle has no write/operation rights on purpose."""

    def __init__(self, pid: int):
        if sys.platform != "win32":
            raise OSError("WinProcessMemory needs Windows; use FakeMemory for tests")
        self.pid = pid
        self.handle = _k32().OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not self.handle:
            raise ReadError(f"OpenProcess({pid}) failed ({ctypes.get_last_error()})")

    def read(self, address: int, size: int) -> bytes:
        buf, got = ctypes.create_string_buffer(size), ctypes.c_size_t(0)
        if not _k32().ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)) \
                or got.value != size:
            raise ReadError(f"read 0x{address:X}+{size} failed ({ctypes.get_last_error()})")
        return buf.raw

    def module_base(self, name: str) -> int:
        for e in _toolhelp(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid, MODULEENTRY32W,
                           "Module32FirstW", "Module32NextW"):
            if e.szModule.lower() == name.lower():
                return e.modBaseAddr
        raise ReadError(f"module {name} not found in pid {self.pid}")

    def alive(self) -> bool:
        code = ctypes.c_uint32()
        return bool(_k32().GetExitCodeProcess(self.handle, ctypes.byref(code))) and code.value == 259

    def close(self) -> None:
        if self.handle:
            _k32().CloseHandle(self.handle)
            self.handle = None


class FakeMemory:
    """Serves reads from byte buffers so parsing logic is testable without the game."""

    def __init__(self, regions: dict[int, bytes] | None = None, modules: dict[str, int] | None = None):
        self.regions = dict(regions or {})
        self.modules = {k.lower(): v for k, v in (modules or {}).items()}
        self.reads = 0

    def read(self, address: int, size: int) -> bytes:
        self.reads += 1
        for start, data in self.regions.items():
            if start <= address and address + size <= start + len(data):
                return bytes(data[address - start:address - start + size])
        raise ReadError(f"unmapped read 0x{address:X}+{size}")

    def module_base(self, name: str) -> int:
        try:
            return self.modules[name.lower()]
        except KeyError:
            raise ReadError(f"module {name} not found") from None

    def alive(self) -> bool:
        return True


# --- snapshot model ---------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """Everything read in one tick. Consumers only ever see a whole frame."""
    tick: int
    time: float
    views: dict[str, Result[dict]]

    def errors(self) -> dict[str, str]:
        return {k: r.error for k, r in self.views.items() if not r.ok}


class Reader:
    """Wires config (offsets TOML) to a backend. Signatures resolve once, at construction."""

    def __init__(self, mem: MemoryBackend, cfg: dict, cache_path: Path | None = None):
        self.mem = mem
        self.base = mem.module_base(cfg["module"])
        self.sigs = resolve_all(mem, self.base, cfg.get("signatures", {}), cache_path)
        self.chains = cfg.get("chains", {})
        self.views = {name: self._build_view(spec) for name, spec in cfg.get("structs", {}).items()}
        self.tick = 0

    def _value(self, ref) -> int:
        """An int from the TOML, or the name of a resolved signature."""
        if isinstance(ref, int):
            return ref
        sig = self.sigs.get(ref)
        if sig is None or not sig.ok:
            raise ReadError(f"signature {ref} unresolved: {sig.error if sig else 'not defined'}")
        return sig.value

    def _build_view(self, spec: dict) -> Result[StructView]:
        return attempt(lambda: StructView({
            name: Field(self._value(off), fmt) for name, (off, fmt) in spec["fields"].items()}))

    def address(self, chain_name: str) -> int:
        chain = self.chains[chain_name]
        return follow_chain(self.mem, self.base + self._value(chain["base"]), chain.get("offsets", []))

    def _read_view(self, name: str) -> dict:
        view = self.views[name]
        if not view.ok:
            raise ReadError(f"layout unavailable: {view.error}")
        return view.value.read(self.mem, self.address(name))

    def snapshot(self) -> Snapshot:
        self.tick += 1
        return Snapshot(self.tick, time.time(), {name: attempt(self._read_view, name) for name in self.views})


def run(reader: Reader, hz: float, on_snapshot: Callable[[Snapshot], None], ticks: int | None = None) -> None:
    """Fixed-rate loop: sleep out the rest of each period instead of spinning a core."""
    period = 1.0 / hz
    while ticks is None or reader.tick < ticks:
        start = time.perf_counter()
        on_snapshot(reader.snapshot())
        if not reader.mem.alive():
            raise ReadError("target process exited")
        time.sleep(max(0.0, period - (time.perf_counter() - start)))


def load_config(path: Path) -> dict:
    cfg = tomllib.loads(path.read_text())
    if "signatures_file" in cfg:  # signatures live in their own file so `sigtool check` can use it
        cfg["signatures"] = tomllib.loads((path.parent / cfg["signatures_file"]).read_text())
    return cfg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only external memory reader")
    ap.add_argument("config", type=Path)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--ticks", type=int)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    mem = WinProcessMemory(args.pid or find_pid(cfg["process"]))
    try:
        reader = Reader(mem, cfg, cache_path=args.config.with_suffix(".cache.json"))
        for name, r in reader.sigs.items():
            print(f"sig {name}: {hex(r.value) if r.ok else 'FAILED ' + r.error}")
        run(reader, cfg.get("poll_hz", 20), lambda s: print(s.tick, s.views), args.ticks)
    except KeyboardInterrupt:
        pass
    finally:
        mem.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
