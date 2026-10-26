"""Walk Cheat Engine style pointer chains. Read-only."""

from __future__ import annotations

import ctypes
import struct
import sys
from dataclasses import dataclass
from typing import Protocol


class ChainError(RuntimeError):
    pass


class MemoryReader(Protocol):
    pointer_size: int

    def read(self, address: int, size: int) -> bytes: ...


@dataclass(frozen=True)
class Hop:
    address: int
    pointer: int


def walk_chain(reader: MemoryReader, start: int, offsets: list[int]) -> tuple[int, list[Hop]]:
    """Resolve ``[[start]+o1]+o2 ...`` and return the final address plus every dereference.

    Matches Cheat Engine: the static address is dereferenced, every offset but the last is
    added and dereferenced, and the last offset is only added. ``start`` is ``module + base``.
    """
    fmt = "<Q" if reader.pointer_size == 8 else "<I"
    if not offsets:
        return start, []
    hops: list[Hop] = []
    address = start
    for index, offset in enumerate(offsets):
        try:
            raw = reader.read(address, reader.pointer_size)
        except OSError as exc:
            raise ChainError(f"hop {index}: can't read {address:#x}: {exc}") from None
        (pointer,) = struct.unpack(fmt, raw)
        hops.append(Hop(address, pointer))
        if pointer == 0:
            raise ChainError(f"hop {index}: null pointer at {address:#x}")
        address = pointer + offset
    return address, hops


if sys.platform == "win32":
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.ReadProcessMemory.restype = wintypes.BOOL
    _k32.ReadProcessMemory.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _k32.IsWow64Process.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))

    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
        ]

    for _name, _entry in (("Process32FirstW", PROCESSENTRY32W), ("Process32NextW", PROCESSENTRY32W),
                          ("Module32FirstW", MODULEENTRY32W), ("Module32NextW", MODULEENTRY32W)):
        getattr(_k32, _name).argtypes = (wintypes.HANDLE, ctypes.POINTER(_entry))
        getattr(_k32, _name).restype = wintypes.BOOL

    def _last_error(what: str) -> OSError:
        return ctypes.WinError(ctypes.get_last_error(), what)

    def find_pid(process_name: str) -> int:
        snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            raise _last_error("CreateToolhelp32Snapshot")
        try:
            entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
            ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
            matches = []
            while ok:
                if entry.szExeFile.lower() == process_name.lower():
                    matches.append(entry.th32ProcessID)
                ok = _k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snap)
        if not matches:
            raise ChainError(f"no running process named {process_name}")
        if len(matches) > 1:
            raise ChainError(f"{len(matches)} processes named {process_name}; pass --pid ({', '.join(map(str, matches))})")
        return matches[0]

    def find_module(pid: int, module_name: str) -> int:
        snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snap == INVALID_HANDLE_VALUE:
            raise _last_error("CreateToolhelp32Snapshot (modules)")
        try:
            entry = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
            ok = _k32.Module32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szModule.lower() == module_name.lower():
                    return entry.modBaseAddr or 0
                ok = _k32.Module32NextW(snap, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snap)
        raise ChainError(f"module {module_name} not loaded in pid {pid}")

    class WinProcessMemory:
        def __init__(self, pid: int, pointer_size: int | None = None):
            self.pid = pid
            self.handle = _k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not self.handle:
                raise _last_error(f"OpenProcess({pid})")
            if pointer_size is None:
                wow64 = wintypes.BOOL()
                if _k32.IsWow64Process(self.handle, ctypes.byref(wow64)) and wow64.value:
                    pointer_size = 4
                else:
                    pointer_size = 8
            self.pointer_size = pointer_size

        def read(self, address: int, size: int) -> bytes:
            buf = ctypes.create_string_buffer(size)
            done = ctypes.c_size_t()
            if not _k32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(done)):
                raise _last_error(f"ReadProcessMemory({address:#x})")
            if done.value != size:
                raise OSError(f"short read at {address:#x}: {done.value}/{size} bytes")
            return buf.raw

        def close(self) -> None:
            if self.handle:
                _k32.CloseHandle(self.handle)
                self.handle = None

        def __enter__(self) -> "WinProcessMemory":
            return self

        def __exit__(self, *exc) -> None:
            self.close()
