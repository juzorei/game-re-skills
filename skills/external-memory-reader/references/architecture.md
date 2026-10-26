# Architecture details

## Backends

Everything above the backend talks to `MemoryBackend`:

```python
class MemoryBackend(Protocol):
    def read(self, address: int, size: int) -> bytes: ...   # raises ReadError
    def module_base(self, name: str) -> int: ...
    def alive(self) -> bool: ...
```

Keep this interface small. It is what makes `FakeMemory` possible, and a backend that only reads cannot be misused to write.

### ctypes (default)

- `OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)`. `PROCESS_VM_READ` (0x0010) is required by `ReadProcessMemory`; `PROCESS_QUERY_LIMITED_INFORMATION` (0x1000) covers `GetExitCodeProcess` and similar queries.
- Set `argtypes`/`restype` for every kernel32 function. Without them, ctypes passes 64-bit addresses and handles as 32-bit `int` and you get truncated pointers or access violations that look random.
- Use `WinDLL("kernel32", use_last_error=True)` and `ctypes.get_last_error()` so the error code is not clobbered by other calls.
- Check both the return value and the bytes-read count. A partial read (error 299, `ERROR_PARTIAL_COPY`) means part of the range is unmapped.
- Close the handle on exit (`try/finally`).

### pymem

Fine when the user's project already uses it. Before adopting it:

- Pin the version in `requirements.txt` (`pymem==<version you tested>`).
- Check which access mask its process-open call uses in that version; several versions default to full access. If it does, open the handle yourself with the read-only mask and pass it in, or wrap only its read helpers. Read the current pymem README/source rather than trusting memory of its API.
- Wrap it in a class that implements `MemoryBackend` so the rest of the reader stays testable.

## Module base

`CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)` then `Module32FirstW/NextW`. Compare `szModule` case-insensitively.

- Error 299 from the snapshot right after the game starts means the loader is still busy. Retry after a short sleep.
- A 64-bit reader can read a 32-bit (WOW64) game, but pointers are 4 bytes and the canonical range is below 4 GB. The template assumes x64; for a 32-bit target, change `follow_chain` to read `"I"`, alignment to 4, and `USER_MAX` to `0xFFFFFFFF`.
- A 32-bit Python cannot read a 64-bit game. Check `struct.calcsize("P") == 8`.

`EnumProcessModulesEx` + `GetModuleBaseNameW` (psapi) is an alternative; it needs `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`.

## Signature resolution

Read the PE headers from the module base (they are mapped at `base`, normally in the first page): `e_lfanew` at `0x3C`, `TimeDateStamp` at PE+8, `SizeOfImage` at PE+24+56, section table at PE+24+`SizeOfOptionalHeader`. Find `.text` and read `VirtualSize` bytes from `base + VirtualAddress`.

- Scan the in-memory image, not the file on disk. Some games unpack or relocate code at load; the disk file may differ.
- If one large read fails (rare, guard pages or a protector that leaves holes), read in 1 MiB chunks and overlap them by the longest pattern length so matches across chunk borders are not lost.
- Resolution modes match `sigtool`:
  - `rel = N` -> target = match + N + 4 + disp32 (RVA of a global).
  - `rel = "N:K"` -> instruction ends K bytes after the displacement (e.g. `cmp [rip+x], imm8`, K = 1).
  - `read = "N:type"` -> value embedded in the instruction, usually a field offset.
  - neither -> RVA of the match (a function start).

### Cache key

```text
key = f"{TimeDateStamp:08X}-{SizeOfImage:X}-{sha1(signature definitions)[:12]}"
```

`TimeDateStamp` alone is not always enough: some build systems zero it or set it to a hash for reproducible builds. Adding `SizeOfImage` and, if needed, a hash of the first 64 KiB of `.text` makes collisions unlikely. For user-facing logs, read `FileVersion` from the version resource on disk (`GetFileVersionInfoW`), but don't key the cache on it alone; hotfixes often keep the version string.

Store the cache next to the config, one file per config. Write it only when every signature resolved, so a partial failure never becomes sticky.

## Config layout

`offsets.toml`:

```toml
process = "Game.exe"
module = "Game.exe"
poll_hz = 20
signatures_file = "signatures.toml"

[chains.player]
base = "LocalPlayer"   # signature name -> RVA, or an int RVA
offsets = [0x0]        # [[module+base]+0x0] -> player object

[structs.player.fields]
health = ["HealthOffset", "f"]   # offset from a `read` signature
position = [0x90, "3f"]          # tuple of three floats
```

Field formats are Python `struct` codes without the byte-order prefix (`<` is added): `f`, `d`, `i`, `I`, `q`, `Q`, `?`, `3f`, `16f` (a 4x4 matrix). Name each chain after the struct it lands on; the template pairs `chains.X` with `structs.X`.

## Process lifecycle

- Attach by name (`find_pid`) or `--pid`. If several instances run, require `--pid`.
- Check `alive()` (`GetExitCodeProcess` returns `STILL_ACTIVE` = 259) each tick.
- On exit, close the handle and either stop or wait for a new instance and re-run startup (base and signatures can differ per launch only by base; the RVA cache stays valid for the same build).
