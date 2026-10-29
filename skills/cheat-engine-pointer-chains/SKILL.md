---
name: cheat-engine-pointer-chains
description: Turn a value you can see in a game (health, gold, ammo, XP, player position) into a Cheat Engine pointer chain that survives game restarts, then verify it with sigtool. Covers value scanning (exact vs unknown initial value, float/int/double, scaled or encrypted values, position vectors), "Find out what writes to this address" to get the struct base and field offset, pointer scans with saved pointermaps compared across restarts, and checking the final chain after a fresh restart. Use when the user says "pointer broke after restart", "my address changes every time", "find static address", "pointer scan", "find base address for health", "make a pointer chain", "what is "game.exe"+0x1234 -> 0x10", "Cheat Engine address doesn't work next launch", or wants a stable address to read from their own tool or trainer.
---

# Cheat Engine pointer chains

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

## What you're building

A dynamic address (heap) changes every launch. A pointer chain starts at a fixed spot inside a module and follows pointers until it lands on the value:

```text
"game.exe"+0x01234 -> 0x10 -> 0x20
address = [[game.exe + 0x1234] + 0x10] + 0x20      ; [x] = read pointer at x
```

Read it as: take `game.exe`'s load address, add `0x1234`, read a pointer there, add `0x10`, read a pointer, add `0x20`. The last offset is added, never dereferenced; the result is the address of the value itself. In sigtool terms:

```bash
sigtool chain --process game.exe --module game.exe --base 0x1234 --offsets 0x10,0x20 --type f32
```

`--base` is the module-relative offset (the number after `"game.exe"+`), `--offsets` are the arrow offsets in order, left to right. All of them are hex, with or without `0x` (`1A8` and `0x1A8` are the same; decimal `424` is not). Install sigtool with:

```bash
pip install "git+https://github.com/juzorei/game-re-skills#subdirectory=tools/sigtool"
```

```text
sigtool chain (--process game.exe | --pid N) [--module game.exe] --base 0x1234 --offsets 0x10,0x20 [--type f32] [--ptr-size 4|8]
```

- `--module` defaults to the `--process` name. With `--pid` you must pass `--module`. Use `--pid` when several processes share the exe name (sigtool refuses to guess and lists the PIDs).
- Pointer size follows the target: WOW64 (32-bit) processes are detected and read with 4-byte pointers, 64-bit with 8. `--ptr-size` overrides that.
- `--type` is one of `i8 u8 i16 u16 i32 u32 i64 u64 f32 f64`. Without it, sigtool prints the final address only.
- Windows only, read-only (`PROCESS_VM_READ`). Exit code `0` when the chain resolved; a null or unreadable hop prints `chain broken: hop N: ...` and exits `1`; bad arguments or a failed attach exit `2`.

`sigtool chain --help` shows the same flags.

Before starting, confirm the game is offline/single-player (see Scope) and ask which value the user wants and whether it's shown as an integer, a decimal, or a bar.

## Workflow

### 1. Find the value's current address

Work in Cheat Engine's main window: attach the process, pick Scan Type and Value Type, then First Scan / Next Scan. Pick the strategy from what the user can see:

| What the user sees | First scan | Value Type |
|---|---|---|
| Exact number (gold 1250) | `Exact value` 1250 | `4 Bytes`, then `8 Bytes` |
| Decimal or a bar (health 87.5, a bar) | `Unknown initial value` | `Float`, then `Double` |
| Number that may be scaled (health 87 stored as 8700) | `Unknown initial value` | `4 Bytes` / `Float` |
| Position | `Unknown initial value` on one axis | `Float` (UE5 uses `Double`) |
| Not sure | `Exact value` | `All (Byte to Double)` |

Then narrow with Next Scan: change the value in game, scan `Increased value` / `Decreased value` / `Changed value`; stand still or wait, scan `Unchanged value`. Repeat until a handful of results are left. For an exact number, rescan with the new number each time. Five to ten alternating rounds usually get under ten results.

Rules that save time:
- Change the value in a way you control (buy something, take one hit, walk forward). Random fluctuation makes changed/unchanged scans useless.
- If an exact scan finds nothing after two tries, the value is stored differently: try Float/Double, then scaled (x10, x100, x1000), then `Unknown initial value` with changed/unchanged only. Encrypted or XOR-obfuscated values need the deeper approach in [references/value-scanning.md](references/value-scanning.md).
- For position, scan the axis you can move along with increased/decreased. X, Y, Z are usually adjacent (4 bytes apart for float, 8 for double). Up is Y in Unity and Z in Unreal.
- Several results that all change together: one is the real value, the rest are copies (UI text, last-frame cache, render transform). Change each one in the address list. The one that changes the game (and reverts the UI when frozen) is the one you want. Copies that the game overwrites from the real value are useless.

Confirm the address by editing the value and seeing the game react. Don't move on until you've done this.

### 2. Get the struct base and field offset

Right-click the confirmed address and choose `Find out what writes to this address` (or `Find out what accesses this address` if it rarely changes). Make the value change in game. The window lists instructions, for example:

```text
14023A1F0 - F3 0F11 81 A8010000  - movss [rcx+000001A8],xmm0
```

That tells you the value lives at field `0x1A8` of an object whose address was in `rcx`. Select the instruction and open `More information`: it shows the registers at that moment, so `rcx` is the object base, and `value_address - 0x1A8` should equal it. Write down:

- field offset: `0x1A8` (this becomes the last offset of the chain)
- object base: the value of `rcx` this session
- instruction address and bytes (useful later for a signature)

Read the operand carefully. `[rax+rcx*4+10]` is an array element: the base is `rax`, `0x10` is the array start, and `rcx` is the index, so the chain needs the index to be stable. If the instruction writes many unrelated addresses (a shared "set float" helper), right-click it and pick `Find out what addresses this instruction accesses`. If the list grows past your one address, pick a more specific instruction or go up a level. See [references/troubleshooting.md](references/troubleshooting.md).

### 3. Pointer scan with pointermaps across restarts

A single pointer scan returns thousands of chains that only happen to work this session. Filter by comparing several game runs:

1. Session A: with the value's address found, right-click it in the address list and choose `Generate pointermap`. Save it (for example `run1.scandata`) and note the address.
2. Fully close the game, restart, load the same save, redo step 1 to find the new address (the field offset from step 2 makes this faster). Generate a second pointermap, `run2.scandata`, and note that address.
3. Right-click the current address and choose `Pointer scan for this address`. In `Pointerscanner scanoptions`:
   - tick `Use saved pointermap` and select the current run's map;
   - tick `Compare results with other saved pointermap(s)` and add the other map with the address it belonged to;
   - `Max level`: start at 4 or 5, then raise it only if you get nothing;
   - `Maximum offset value:` keep it moderate, like 0x1000 to 0x2000. Raise it only if a struct field you know about is larger;
   - tick `Pointers must end with specific offsets` and enter the field offset from step 2 (`1A8`). This cuts the results drastically;
   - keep `Only find paths with a static address` on.
4. After a third restart, find the address again and run `Pointer scanner` → `Rescan memory - Removes pointers not pointing to the right address` with the new address. Each rescan after a real restart removes coincidental chains.

Exact options and their effects are in [references/pointer-scanning.md](references/pointer-scanning.md).

### 4. Pick the best chain

From what is left, prefer, in order:
1. Base in the game's own module (`"game.exe"+...`, `"GameAssembly.dll"+...`, `"UnityPlayer.dll"+...`), not `THREADSTACK0` or a system DLL.
2. Fewer levels (2 to 3 beats 5).
3. Small, plausible offsets (`0x10`, `0x30`, `0x1A8`) over huge or odd ones.
4. Chains that share a prefix with others: many survivors ending `... -> 0x30 -> 0x1A8` through different first hops mean that `0x30` object is real. Choose the shortest base.

Double-click a candidate to add it to the address list, then load another area or save and check it still points at the value. Many chains break on level transitions, respawn, or returning to the main menu.

### 5. Verify after a fresh restart

Close the game completely, start it, load in, and run:

```bash
sigtool chain --process game.exe --module game.exe --base 0x2F4A1B0 --offsets 0x30,0x1A8 --type f32
```

Output format (real; the addresses are made up for this example):

```text
module   game.exe @ 0x7ff6a1c00000 (pid 12345, 64-bit pointers)
start    game.exe+0x2f4a1b0 = 0x7ff6a4b4a1b0
  [0x7ff6a4b4a1b0] -> 0x1f2c3a40000  + 0x30 = 0x1f2c3a40030
  [0x1f2c3a40030] -> 0x1f2d8e12500  + 0x1a8 = 0x1f2d8e126a8
address  0x1f2d8e126a8
value    87.5 (f32)
```

Each hop line is `[address read] -> pointer found  + offset = next address`. The command must exit 0 (no `hop N: null pointer` / `can't read` error), and the final value must match the screen. Then change the value in game and run it again. If the module isn't the exe (Unity: `GameAssembly.dll` or `UnityPlayer.dll`), pass that name to `--module` while keeping `--process` as the exe. Do this for at least two fresh launches before calling the chain stable.

### 6. When a chain isn't enough: signatures

A module-relative base like `"game.exe"+0x2F4A1B0` survives restarts, but usually not game updates. For a chain that survives patches, find the instruction that loads the root pointer (often `mov rax,[rip+disp32]` near the instruction from step 2), make an AOB signature for it, and resolve the base from the signature at runtime instead of hardcoding it. Use the `aob-signatures` skill for that, and keep the field offsets (they also change on updates; signatures with `read = "N:u32"` can recover them). To try that flow offline first, `sigtool practice` writes a two-version 5 KB synthetic game with a `movss [rcx+0x1A8]`-style store instruction to sign and re-check across versions.

## Chain notation cheat sheet

| Cheat Engine shows | sigtool |
|---|---|
| `"game.exe"+0x01234 -> 0x10 -> 0x20` | `--module game.exe --base 0x1234 --offsets 0x10,0x20` |
| Pointer scan row: Base Address `"game.exe"+01234`, Offset 0 `10`, Offset 1 `20` | same; CE results are hex without `0x` |
| `[[game.exe+1234]+10]+20` | same chain |

When you type a chain into the manual pointer dialog (`Add Address Manually`, tick `Pointer`), check the resolved address CE shows next to each offset row instead of trusting the field order. The order has differed between versions, and a reversed chain gives a valid-looking but wrong address.

## Troubleshooting (short)

- Chain works once, breaks after restart: it was never compared across runs. Redo step 3 with two or three pointermaps from real restarts, not reloads.
- Works until a level load or respawn: the object is recreated. Look for a chain that goes through a manager or world object instead of the player object directly, and rescan after the transition.
- Many survivors: add `Pointers must end with specific offsets`, lower `Max level`, rescan after another restart, then use the selection rules in step 4.
- No survivors: raise `Max level` by one or `Maximum offset value:` to 0x4000, check you entered the correct address per pointermap, and confirm the value is not a copy.
- Writes come from many instructions: some are copies or init code. Prefer the one that fires on the action you control. See the reference.
- ASLR: the module loads at a different address each launch, which is why chains are written as `"module"+offset`. Never hardcode an absolute base like `0x7FF6...`.
- 32 vs 64-bit: pointers are 4 bytes in a 32-bit game and 8 in a 64-bit one. `sigtool chain` detects WOW64 targets and says which it used on its `module` line (`32-bit pointers` / `64-bit pointers`); `sigtool pe game.exe` shows `x86` or `x64`. Your own reader must do the same.

Full details are in [references/troubleshooting.md](references/troubleshooting.md).

## Deliverable

End with the chain and the evidence, for example:

```json
{
  "game": "Example Game",
  "build": "1.4.2 (Steam, game.exe 2026-09-30)",
  "process": "game.exe",
  "bitness": 64,
  "value": "player health",
  "type": "f32",
  "module": "game.exe",
  "base": "0x2F4A1B0",
  "offsets": ["0x30", "0x1A8"],
  "cheat_engine": "\"game.exe\"+0x2F4A1B0 -> 0x30 -> 0x1A8",
  "writer": "game.exe+23A1F0  movss [rcx+1A8],xmm0",
  "verified": "sigtool chain after 2 fresh restarts: read 100.0 and 73.5, matching the HUD"
}
```

Report the exact `sigtool chain` command and its output. To read the chain from a standalone tool, hand the deliverable to the `external-memory-reader` skill. If you could only verify inside Cheat Engine (no Windows shell, sigtool not installed), say so and don't call the chain verified.
