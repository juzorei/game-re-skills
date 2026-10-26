# Reliability, performance and testing

## Value or error, per field

```python
@dataclass(frozen=True)
class Result(Generic[T]):
    value: T | None = None
    error: str | None = None
```

- Wrap each view read in `attempt(...)`. It turns `ReadError`, `KeyError`, `ValueError`, `TypeError` and `struct.error` into `Result(error=...)`. Let other exceptions (bugs) propagate so tests catch them.
- Error messages name the hop and address: `hop 1 at 0x1F3A0010: null pointer`. That is enough to tell "not in a match yet" from "chain is stale".
- Consumers render errors explicitly (`health: n/a (null pointer)`), never as `0`.
- Rate-limit logging of repeated identical errors (log on change, not every tick).

## Pointer validation

| Check | Why |
| --- | --- |
| `ptr != 0` | Most common failure: object not spawned yet |
| `0x10000 <= ptr <= 0x7FFFFFFFFFFF` | Rejects kernel addresses, non-canonical garbage and small integers read as pointers |
| `ptr % 8 == 0` for objects | Heap objects are at least 8-aligned on x64; misalignment means a wrong offset |
| bounded counts | A garbage count must not trigger a huge read |

Validation turns "plausible garbage" into a clear error on the first tick. Relax alignment only for pointers into byte buffers (`align=1`).

## Snapshot consistency

- Build one `Snapshot` per tick and publish it atomically (assign one reference; consumers read that reference).
- Values that must agree (position + rotation, a matrix) belong in the same struct read.
- Tearing check when needed: read the block twice; accept if equal, otherwise retry once and then report `torn read`.
- Timestamp the snapshot so consumers can interpolate or detect stalls.

## Performance

- Cost is dominated by the number of `ReadProcessMemory` calls, not bytes. A 4 KiB read costs about the same as a 4-byte read.
- Count reads in tests with `FakeMemory.reads` and assert the budget, e.g. "one snapshot of 64 entities costs at most 66 reads" (header + array + one block per entity).
- Cache what does not change per session: resolved signatures, decoded FNames, class pointers, entity-type lookups.
- Use `time.perf_counter()` around `snapshot()`; log the p95 once per second, not every tick.
- Sleep out the period (`time.sleep(max(0, period - elapsed))`). On Windows the default sleep granularity is coarse (often around 1 ms or more); for steady high rates measure the actual tick interval instead of assuming it.

## Testing with FakeMemory

`FakeMemory(regions={addr: bytes}, modules={"game.exe": base})` serves any read fully inside a region and raises `ReadError` otherwise, like a real unmapped page.

Build fixtures from known values:

```python
img = bytearray(0x3000)                        # minimal PE: MZ, e_lfanew, PE\0\0, one .text section
...
at = TEXT_RVA + 0x40                           # the real instruction bytes of the signature
img[at:at + 7] = b"\x48\x8B\x05" + struct.pack("<i", GLOBAL_RVA - (at + 7))
struct.pack_into("<Q", img, GLOBAL_RVA, PLAYER)  # global -> heap object
player = bytearray(0x200)
struct.pack_into("<f", player, HEALTH_OFF, 87.5)
mem = FakeMemory({BASE: img, PLAYER: player}, {"game.exe": BASE})
```

Test checklist:

- Pattern syntax: full and nibble wildcards, bad tokens rejected.
- Each signature: expected RVA/offset; 0 and 2+ matches are errors.
- `rel = "N:K"` with trailing immediates.
- Chains: success, null hop, kernel-range hop.
- Views: exact decoded values, one read per view.
- Partial failure: one view errors, others still decode; unresolved signature names itself.
- Cache: reused for the same build key, ignored after a stamp change, failures not written.
- Loop: values change between ticks when the fake memory changes.
- Config: the shipped example TOML loads and every struct has a chain.

### Golden fixtures from the live game

Once the reader works live, dump real blocks so tests use real data:

```python
Path("fixtures/player.bin").write_bytes(mem.read(player_addr, 0x200))
```

Store the address alongside (`player.json`) and load both into `FakeMemory`. Re-capture after each patch as part of the update checklist; a diff between old and new fixtures shows moved fields.

### Windows-only tests

Mark them `@pytest.mark.skipif(sys.platform != "win32", ...)`. Reading your own process (`os.getpid()`) tests `WinProcessMemory` without a game: read a `ctypes.create_string_buffer` by address and check `kernel32.dll` starts with `MZ`.
