# Troubleshooting pointer chains

## Chain works once, then breaks

Cause: the chain went through a heap address that happened to be stable in that session, or it was only "verified" by reloading a save in the same process.

Fix:
- Rescan with pointermaps from two or three separate launches (see pointer-scanning.md).
- Verify with `sigtool chain` after closing the game completely. A chain that resolves in the session where you found it proves nothing.
- If the chain breaks only after a game update, that's expected for a hardcoded module offset. Switch the base to a signature (the `aob-signatures` skill).

## Works until a level load, respawn, or returning to the menu

The player or stats object is freed and recreated, so any chain that caches the old object (a global "last spawned pawn" variable) points to freed memory.
- Before the final rescan, do the transition, find the address again and rescan. Chains that survive go through an owner that persists (game instance, player controller, save-data manager).
- Some values only exist in a level. It's fine for the chain to fail in the main menu, as long as it resolves again once you're in game. Note that in the deliverable.

## Too many results

- Add `Pointers must end with specific offsets` with the field offset from the writing instruction.
- Lower `Max level` by one and `Maximum offset value:` to 0x1000.
- Restart again and run `Rescan memory - Removes pointers not pointing to the right address`. Each real restart typically removes most remaining false paths.
- Restrict `Base address must be in specific range` to the main game module.
- If hundreds of chains still remain and all work, they're probably equivalent routes to the same object. Take the shortest one with a game-module base, and verify it.

## No results

- Wrong address in one of the runs: the pointermap compare needs the correct address for each map. Recheck each.
- The value you found is a copy that's rebuilt each frame from a temporary buffer. Go back to step 1 and test copies by editing them.
- The real path is deeper or has a larger offset: raise `Max level` to 6 or 7, or `Maximum offset value:` to 0x4000. Expect a longer scan.
- The root isn't in a module (allocated from a script VM or a custom allocator, reached only from a thread stack). Try `Allow stack addresses of the first thread(s) to be handled as static`, but note that sigtool's `--module` can't express a `THREADSTACK0` base. Prefer a signature to the code that loads the root.
- Backtrack by hand one or two levels first, then pointer scan for that intermediate object's address instead of the value.

## Value found, but many instructions write to it

Normal. A value can be written by damage code, healing code, regeneration, save loading and UI sync.
- Use the instruction that fires for the action you control (take damage, then see which entry's count increases).
- Discard instructions in shared helpers (memcpy, generic "set property" functions). Check with `Find out what addresses this instruction accesses` whether the instruction touches many unrelated addresses.
- Different instructions may show different registers and offsets because they use different bases (one uses the component, another uses the owning actor plus a larger offset). Both can be correct. Pick the one whose base is easier to reach.
- If every writer is a `rep movs` or similar copy, the value is a copy. The real value lives where the copy comes from.

## ASLR and module bases

Windows loads modules at a randomized base each boot or launch. This is why you never record absolute addresses such as `0x7FF6A1C4A1B0`. Convert any absolute static address to `"module"+offset`:

```text
offset = absolute_address - module_base
```

Find the module base in CE (Memory View, `View` → `Enumerate DLL's and Symbols`, or the address list showing `"game.exe"+...`). sigtool resolves `--module` itself on every run, so `--base` is always the module-relative offset.

Pick the right module. Unity IL2CPP code and statics are in `GameAssembly.dll`, the engine is in `UnityPlayer.dll`. Some games ship the real game in a DLL loaded by a small launcher exe. The `--process` and `--module` values then differ.

## 32-bit vs 64-bit

- 64-bit process: every dereference reads 8 bytes. Backtracking scans use `8 Bytes`.
- 32-bit process (shown as "(32 bit)" in Task Manager, or PE machine type x86): every dereference reads 4 bytes. Backtracking scans use `4 Bytes`.
- Offsets in a 32-bit game are usually smaller, and struct layouts differ between the 32-bit and 64-bit builds of the same game. Chains don't transfer between them.
- Your own reader must use the target's pointer size, not the reader's. A 64-bit tool reading a 32-bit game must read 4-byte pointers.
- `sigtool chain` detects a WOW64 (32-bit) target and reads 4-byte pointers; its first line says `32-bit pointers` or `64-bit pointers`. If that's wrong for some reason (an emulator or a custom loader), force it with `--ptr-size 4` or `--ptr-size 8`.

## Value correct in CE, wrong in sigtool

- Wrong `--type`: health as `f32` vs `i32` reads garbage. Match the CE value type (`Float` = `f32`, `Double` = `f64`, `4 Bytes` = `i32`/`u32`, `8 Bytes` = `i64`).
- Offsets in decimal: CE shows hex without `0x`, and sigtool reads `--base`/`--offsets` as hex either way (`1A8` = `0x1A8`). A decimal `424` is read as `0x424`, which is wrong.
- Several processes with the same name (launcher plus game, or two instances): sigtool stops and lists the PIDs. Pass `--pid N --module game.exe`.
- `hop N: null pointer at ...`: the object at that level doesn't exist yet (main menu, loading screen). Get in game and rerun. `can't read`: a bad offset at the previous hop or the wrong module.
- Offsets in reverse order: `--offsets` follows CE's `Offset 0, Offset 1, ...` order (the order of the arrows in `"game.exe"+X -> a -> b`).
- One level off: sigtool adds the last offset without reading through it, as CE does. If you wrote the chain by hand and it ends at the object pointer instead of the field (for example `... -> 0x30` when the value is at `+0x1A8` of that object), append the field offset: `--offsets 0x30,0x1A8`. To read the pointer stored at a field instead of a number, read it as `--type u64` (64-bit) or `u32` (32-bit).
- Running sigtool without the needed rights: read access to another process may need the same privilege level CE used (for example both as administrator).
