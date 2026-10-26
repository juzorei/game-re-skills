# Pointer scanning in depth

Option labels below are taken from Cheat Engine's current source (`Pointerscanner scanoptions` dialog and the pointer scanner window). If a label isn't there in the user's build, describe the concept and check the CE wiki or forum for that version.

## Two ways to get a chain

1. Backtracking by hand with the debugger: fast for 1 to 3 levels and gives you a clear picture of the structs. Do it when the pointer scan returns too much noise.
2. Pointer scanner: brute-force search for every path from static memory to the address, filtered across restarts. Do it when backtracking hits a dead end, like a register value that's computed and not loaded.

Combining them works well. Backtrack one level to learn the field offset, then pointer scan with `Pointers must end with specific offsets`.

## Manual backtracking

1. On the value address, run `Find out what accesses this address`. Take a specific instruction such as `movss [rcx+1A8],xmm0`. Under `More information`, CE shows the register values, and the probable base address is `rcx`.
2. Run a new scan: `Exact value`, `8 Bytes` (64-bit game) or `4 Bytes` (32-bit), tick `Hex`, value = that base. Results are places that store a pointer to the object.
3. Results shown in green in the scan list are static (inside a module). If one is static, the chain is `"module"+offset -> 0x1A8`.
4. Otherwise, pick a heap result, run `Find out what accesses this address` on it to learn its own offset, and repeat one level up.
5. If no result holds exactly the base, the code may access the object through an interior pointer: look at the instruction that loads `rcx` (a few lines above, in `Show disassembler`) such as `mov rcx,[rax+30]` to learn the next offset directly.

Stop after 4 or 5 levels and switch to the pointer scanner.

## Pointermaps

A pointermap is a snapshot of every pointer in the process, taken in a few seconds. Generate it right after finding the address (right-click it in the address list, `Generate pointermap`), and save it with the address it belonged to. The heavy pointer scan can then run later, offline against the map, even after the game is closed.

The multi-restart method:

| Run | Action | Record |
|---|---|---|
| 1 | Find address, `Generate pointermap` | `run1.scandata`, address A1 |
| 2 (restart) | Find address, `Generate pointermap` | `run2.scandata`, address A2 |
| 2 | `Pointer scan for this address` on A2 with `Use saved pointermap` = run2 and `Compare results with other saved pointermap(s)` = run1 with A1 | result list |
| 3 (restart) | Find address A3, `Rescan memory - Removes pointers not pointing to the right address` with A3 | filtered list |

Restarting means closing the process. Reloading a save in the same process keeps most heap allocations, so it doesn't filter well. Also vary something cheap between runs: load a different save, a different level, or reboot. Varying the run filters more chains.

## Scan options

| Option | Recommendation | Why |
|---|---|---|
| `Scan for address` | default | faster than `Scan for addresses with value` |
| `Max level` | 4 to 5 to start, up to 7 | each level multiplies results and time |
| `Maximum offset value:` | 0x1000 to 0x2000 to start | big game objects have fields past 0x1000; going higher explodes results |
| `Pointers must end with specific offsets` | enter the field offset(s) you know | the strongest filter there is |
| `Only find paths with a static address` | on | heap-rooted chains can't survive a restart |
| `Allow stack addresses of the first thread(s) to be handled as static` | off at first | gives `THREADSTACK0` bases. They can work, but sigtool's `--module` can't express them |
| `Also accept non-module addresses` | off | same reason |
| `No looping pointers` | on | removes cycles |
| `Max different offsets per node:` | default | lower it if the scan never finishes |
| `Include system modules` | off | bases in `ntdll` or `kernel32` are rarely what you want |
| `Improve pointerscan with gathered heap data` | try if results are poor | uses heap allocation sizes to reject offsets outside the object |
| `Base address must be in specific range` | set to the game module's range when there are too many results | forces `"game.exe"+...` bases |

Negative offsets (`Also scan for negative offsets`) are rarely needed. Turn them on only if backtracking showed a `[reg-xx]` access.

## Reading results

Each row shows a `Base Address` such as `"game.exe"+02F4A1B0` and the offsets `Offset 0`, `Offset 1`, ... where `Offset 0` is applied right after the first dereference. Values are hex without `0x`. The last column shows where it points now. This row maps to:

```bash
sigtool chain --process game.exe --module game.exe --base 0x2F4A1B0 --offsets <Offset 0>,<Offset 1>,...
```

Sort by base or by level to find the families described in SKILL.md step 4. A large result list can be exported (`Export to sqlite database`) and inspected with queries.

## Choosing between survivors

- Shortest and smallest wins, but a 3-level chain through a known engine object (`GWorld`, `GameManager.instance`, a Unity static field) beats a 2-level chain through an unnamed global, because it's easier to re-find after an update.
- In Unity IL2CPP games, bases in `GameAssembly.dll` usually reach static fields of a class. That's stable across restarts but changes with every build. In Unity Mono games, the managed heap is reachable from `mono-2.0-bdwgc.dll` or `mono.dll` bases. Those chains are long. Consider a Mono or IL2CPP dumper instead of a pointer scan.
- In Unreal games, most good chains start at `GWorld` or `GEngine`: `GWorld -> OwningGameInstance -> LocalPlayers[0] -> PlayerController -> Pawn -> field`. If the survivors share such a prefix, that's the one.
