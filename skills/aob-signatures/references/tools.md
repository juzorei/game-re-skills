# Getting and testing signatures in common tools

Menu names and shortcuts move between versions. If one listed here isn't where it should be, check the tool's docs or README instead of guessing. Whatever tool produced the pattern, the final check is `sigtool scan` on the file (or dump) and `sigtool check` across builds.

## Pattern formats and conversion

| Style | Example | Notes |
| --- | --- | --- |
| IDA | `48 8B 05 ? ? ? ? 48 85 C0` | single `?` per byte |
| x64dbg / CE | `48 8B 05 ?? ?? ?? ?? 48 85 C0` | double `??` |
| Code style | `\x48\x8B\x05\x00\x00\x00\x00\x48\x85\xC0` + mask `xxx????xxx` | the mask decides, wildcard bytes are filler |
| Compact | `488B05????????4885C0` | |

sigtool accepts all of these (code style as `"\x48\x8B\x05\x00 xxx?"`: bytes, a space, then the mask) and prints the spaced `??` form. Store the spaced `??` form in `signatures.toml`, since it's the easiest to diff and review.

## IDA Pro

- Find the anchor: put the cursor on the global or the struct field and list cross-references (`X`). For strings, open the Strings view, pick the string, and xref it.
- Search bytes: binary/byte-sequence search (`Alt+B` in recent versions) accepts patterns with `?` wildcards. Check "find all occurrences" to see the match count.
- Generate: the community plugin [IDA-Pro-SigMaker](https://github.com/A200K/IDA-Pro-SigMaker) (A200K) builds the shortest unique signature for the selected address, or for an address's xrefs, in IDA, x64dbg, and code-style formats, and can search for an existing signature. Hotkey `Ctrl+Alt+S` per its README, which also lists the supported IDA versions. Its wildcarding is generic, so still review struct displacements and immediates by hand.
- Use Hex-Rays output to understand the code, but build the pattern from the disassembly bytes (Options → General → number of opcode bytes shows them inline).

## Ghidra

- Xrefs: right-click the label or field → References → Show References to.
- Search bytes: Search → Memory, hex format. Wildcard syntax has changed across versions, so check the dialog's help.
- Generate: Ghidra doesn't ship a signature maker. Community scripts exist, for example `makesig.py` in [nosoop/ghidra_scripts](https://github.com/nosoop/ghidra_scripts). Read a script before running it, and convert its output to the spaced format if needed.
- Ghidra shows image-base-relative addresses. Subtract the image base (Window → Memory Map, or `sigtool pe`) to get the RVA.

## x64dbg

- Find the anchor at runtime: set a hardware breakpoint on access or write on the field or global, then trigger it in game.
- Search: in the CPU view, right-click → Search for → Pattern. The `findall`/`findallmem` commands also search memory for a pattern. Results show every hit, so the count is visible.
- Generate: the [SwissArmyKnife](https://github.com/Nukem9/SwissArmyKnife) plugin (Nukem9) creates signatures in code, IDA, and PEiD styles from a selection. Check its README for the current build and supported x64dbg versions.
- Dump: the bundled Scylla plugin dumps a loaded module. Use it for packed executables (SKILL.md step 8).
- Copy bytes from the dump pane (Binary → Copy) to build a pattern by hand.

## Cheat Engine

- Find the anchor: on a found address, "Find out what accesses this address" or "...writes to this address" lists the instructions. Each one is an anchor candidate. Open it in the disassembler (Memory View).
- Search: Memory Scan with value type "Array of byte" accepts `??` wildcards. Restrict the scan to the module's range, and disable writable-only filtering when scanning code.
- Scripts: Auto Assembler's `aobscanmodule(name, module, pattern)` finds a pattern in one module and defines a symbol at the match, which is how most CE tables survive updates. Lua's `AOBScan` returns all matches. A table entry whose pattern now matches twice is the same failure `sigtool check` reports.
- CE pointer scans give you a known-good address in the current build. They don't replace a signature. Convert the base of the chain into one (see the `cheat-engine-pointer-chains` skill).

## Process dumps (packed or encrypted executables)

- Dump after the game has finished starting, since some protectors decrypt code lazily. Dump again after reaching the code path you care about if the first dump lacks it.
- A raw memory dump (module base to base + SizeOfImage) is laid out by RVA. Pass `--mapped` to `scan`, `suggest` and `check` so sigtool reads sections at their RVAs; file offset in the output then equals RVA. `--mapped` needs the PE headers at the start of the dump (it errors otherwise).
- A rebuilt PE dump (Scylla, others) has fixed-up section headers, and sigtool treats it as an ordinary PE. Don't pass `--mapped`.
- Keep dumps out of the repo and don't share them. They're the game's code. Use them only to find and verify signatures for single-player modding.
- If the process runs under anti-cheat, don't attach or dump it. That's out of scope.

## Batch regression

Keep the old builds you support (or their dumps) in a local folder outside the repo, then:

```bash
sigtool check signatures.toml builds/1.4.2/game.exe builds/1.5.0/game.exe --json
```

The exit code is already CI-ready: `0` when every signature matched exactly once (or its `expect` count), `1` otherwise, `2` on errors such as a missing file or a bad TOML entry. Add `--json` when a script needs the details: one object per signature and build with `name`, `file`, `count`, `ok`, `offset`, `rva`, `values` (`rel` with `disp`/`rva`/`va`/`offset`, or `read`) and `error`.
