---
name: external-memory-reader
description: Turn found offsets, pointer chains and signatures into a maintainable, read-only external Python reader for a Windows game process (ctypes ReadProcessMemory or pymem). Covers attach with minimal rights, module base lookup, signature scan at startup with a per-build cache, offsets in TOML, one-call struct reads, UE TArray/FString/FName and il2cpp String/Array/List helpers, pointer validation, per-field errors, a snapshot per tick, polling rate, and pytest tests against a FakeMemory backend. Use when the user says "write a memory reader", "ReadProcessMemory python", "pymem", "read player position from the game", "turn my Cheat Engine pointers into a script", "make an overlay/data export read the game", "my reader is slow", "my reader returns zeros", "reader broke after the update", or "how do I test my reader without the game".
---

# External Memory Reader

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

The reader is read-only by design. Never add WriteProcessMemory, VirtualAllocEx, CreateRemoteThread, DLL injection or handle elevation, even "just for testing". If the user wants to change game state, that is a different task (a mod or a trainer for an offline game) and a different skill.

## Deliverable

A small package the user can maintain across game updates:

```text
reader/
├── reader.py              from templates/reader_template.py
├── offsets.toml           chains and struct fields (data, not code)
├── signatures.toml        sigtool-compatible; resolved at startup
└── tests/test_reader.py   pytest against FakeMemory, runs on any OS
```

Done means: `pytest` passes, `sigtool check signatures.toml <game.exe>` reports every signature matching exactly once, and a live run against the game prints sane values for every field (or a named error for the ones that legitimately can't resolve right now, such as "no local player in the main menu").

## Workflow

### 1. Collect the inputs

Gather what earlier work found before writing code:

- Process and module names, bitness (the template assumes a 64-bit target).
- Signatures with their resolution mode: `rel` (RIP-relative global), `read` (a field offset embedded in an instruction) or the plain match RVA. If the user only has raw addresses, send them to the signature workflow first; hardcoded addresses break on the next patch.
- Pointer chains in Cheat Engine form (`"Game.exe"+0x1234 -> 0x10 -> 0x20`).
- Struct field offsets and types (from a class dump, `unreal-sdk-offsets` or `unity-il2cpp-offsets`).

Verify each signature before building on it:

```bash
pip install game-re-sigtool
sigtool check signatures.toml Game.exe
sigtool chain --process Game.exe --module Game.exe --base 0x1234 --offsets 0x10,0x20 --type f32
```

`sigtool chain` walks the chain the same way the reader will. If it disagrees with Cheat Engine, fix the chain now, not in the reader.

### 2. Start from the template

Copy `templates/reader_template.py`, `templates/offsets.example.toml`, `templates/signatures.example.toml` and `templates/test_reader_template.py` into the user's project. The template is stdlib-only (Python 3.11+ for `tomllib`) and already has the pieces below; adapt the config, don't rewrite the core.

| Piece | What it does |
| --- | --- |
| `MemoryBackend` | Protocol: `read(addr, size)`, `module_base(name)`, `alive()` |
| `WinProcessMemory` | ctypes, `OpenProcess(PROCESS_VM_READ \| PROCESS_QUERY_LIMITED_INFORMATION)`, Toolhelp module lookup |
| `FakeMemory` | serves reads from byte buffers; counts reads |
| `resolve_all` | scans `.text` once, caches RVAs keyed by build stamp + pattern hash |
| `follow_chain` | Cheat Engine semantics, validates every hop |
| `StructView` | one read per struct, unpack fields locally |
| `Result`, `Snapshot` | per-field value-or-error, one frozen frame per tick |
| `run` | fixed-rate loop that sleeps instead of spinning |

### 3. Attach with the least rights

Open the process with `PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION` and nothing else. That is all reading needs, it works without admin for processes the user owns, and it makes the read-only promise checkable by anyone reading the code.

Plain ctypes is the default: no dependency, and you control the access mask. pymem is fine if the user already uses it, but check which rights it requests (many versions open with full access) and pin its version. See [references/architecture.md](references/architecture.md).

Find the module base with Toolhelp (`TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32`), matching the module name case-insensitively. Never hardcode a base; ASLR moves it every launch.

### 4. Resolve signatures once, at startup

Read the module's `.text` from memory in one pass, match all patterns, and turn each into an RVA or offset. Require exactly one match; zero or several is an error with that count in the message, never a guess.

Cache successes in a JSON file keyed by the PE `TimeDateStamp` + `SizeOfImage` plus a hash of the signature definitions. A patch changes the stamp, an edited pattern changes the hash, and either one forces a rescan. Don't cache failures. If the user ships the reader, also record `FileVersion` from the version resource in logs so bug reports name the build.

Signatures stay in their own `signatures.toml` in exactly `sigtool check` format, so the same file is verified in CI against every build the user keeps.

### 5. Keep offsets in TOML

Chains and struct fields go in `offsets.toml`. A chain base is either a module RVA or a signature name; a field offset is either a number or a signature name (for `read = "N:type"` signatures). After a patch the user edits data, not Python. Keep hex in TOML (`0x1A4`); `tomllib` reads it as an int.

### 6. Read structs in blocks

One `ReadProcessMemory` per struct, then `struct.unpack_from` per field. Each call is a syscall plus a page walk in the target; twenty 4-byte reads cost about twenty times one 128-byte read. The same goes for arrays: read `count * stride` bytes once, then slice.

If a view spans fields far apart (more than a page or two), split it into two views rather than reading a large block that may cross into unmapped memory.

### 7. Engine containers

Use the helpers `read_utf16` and `read_counted_array` and get the layouts from the engine skills:

- Unreal: `TArray {T* data; int32 num; int32 max}`, `FString` is a `TArray<wchar_t>`, `FName` needs the name pool from `unreal-sdk-offsets`.
- Unity il2cpp: `System.String` length at `+0x10`, chars at `+0x14`; arrays and `List<T>` per `unity-il2cpp-offsets`.

Details and sanity checks are in [references/engine-containers.md](references/engine-containers.md). Always bound counts (`limit=`) before allocating; a garbage count of 2^31 should be an error, not a 4 GB read.

### 8. Validate every pointer

Before dereferencing, reject: null, anything outside `0x10000..0x7FFFFFFFFFFF` (non-canonical or kernel), and misaligned values for pointer-sized objects. Report which hop failed and at what address. This catches most stale chains on the first tick instead of producing plausible garbage.

### 9. Fail per field, loudly

Every view returns `Result(value)` or `Result(error="hop 1 at 0x...: null pointer")`. Never let one failed field raise out of the loop, and never substitute `0` or `0.0` for a failed read. Silent zeros are the most common reason a reader "works but shows nothing": the consumer cannot tell "health is 0" from "health could not be read".

Startup errors are different: module not found, no PE header, `OpenProcess` denied. Raise those immediately with the OS error code.

### 10. One snapshot per tick

Read everything for a tick into a frozen `Snapshot` and hand that to consumers (overlay, logger, websocket). Never let UI code read memory directly; mixing values from different ticks gives position from frame N with rotation from frame N+1.

Reads are not atomic with the game's writes. For values that must agree (a vector, a matrix), read them in the same block. If tearing still shows, read twice and keep the result when both agree.

### 11. Polling rate and CPU

Pick the rate from the consumer: 10-30 Hz for dashboards and logs, the display rate for an overlay. Sleep the remainder of each period (`run` does this); a loop without a sleep pins a core and slows the game. Measure with `time.perf_counter` around `snapshot()`; if a tick takes more than a few milliseconds, count reads with `FakeMemory.reads` in a test and merge them into blocks.

Check `alive()` every tick and exit cleanly when the game closes. Re-attach on demand rather than reusing a handle to a dead process.

### 12. Test without the game

Build tests on `FakeMemory`: a synthetic PE header plus `.text` containing the real instruction bytes of each signature, globals pointing at fake heap objects, and struct blobs packed with known values. (`sigtool practice` writes a small two-version synthetic exe built exactly like this, if you want realistic fixture material — its exercise set is the `xref`/`suggest`/`scan --read`/`check` loop feeding a reader.) Cover at least:

- every signature resolves to the expected RVA or offset;
- each chain resolves, and a null hop yields a named error;
- each view decodes the known values and costs one read;
- an unresolved signature makes dependent fields fail with its name;
- the cache is reused for the same build and ignored for a new one.

For realism, dump a struct block from the live game once (`mem.read(addr, size)` to a `.bin` file) and use it as a golden fixture. See [references/reliability-and-testing.md](references/reliability-and-testing.md).

Run the template tests to see the pattern:

```bash
cd templates && py -3 -m pytest -q
```

### 13. Verify on the live game

1. `sigtool check signatures.toml Game.exe` exits 0.
2. Start the reader with `--ticks 20`; every signature prints a value, not `FAILED`.
3. Compare two or three fields against Cheat Engine or the in-game UI, then change them in-game (move, take damage) and confirm they track.
4. Check CPU usage of the reader in Task Manager at the chosen rate.

Report what was verified live and what was only tested against FakeMemory.

## Game update checklist

When the reader breaks after a patch, follow `game-patch-recovery`. For this reader specifically:

1. The cache invalidates itself when the PE stamp changes. If it didn't, delete `*.cache.json`.
2. Run `sigtool check signatures.toml old.exe new.exe`. Any signature not at 1 match needs recovery.
3. For `read` signatures, compare the embedded offsets between builds; a changed struct layout shows up here first.
4. Re-run the struct dump for the engine (UE SDK dump or il2cpp dump) and diff field offsets into `offsets.toml`.
5. Re-capture golden fixtures, update test expectations, run pytest, then verify live (step 13).

## Common problems

| Symptom | Likely cause |
| --- | --- |
| All fields error with "hop 0 ... null" | Not in-game yet, or the global moved; check the signature |
| Values are plausible but frozen | Reading a stale copy; the chain points at a template object, not the live one |
| `OpenProcess` error 5 | Game runs elevated (run the reader elevated too) or the process is protected; if it is protected by anti-cheat, stop: out of scope |
| `ReadProcessMemory` error 299 | Partial read crossing into unmapped memory; shrink or split the view |
| Floats like `1e-41` | Wrong offset or wrong type (reading an int as float) |
| Reader slow | Many small reads; merge into struct blocks and arrays |
