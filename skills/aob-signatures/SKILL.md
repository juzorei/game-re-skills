---
name: aob-signatures
description: Build array-of-bytes (AOB) signatures that survive game patches and resolve addresses or struct offsets from them. Use whenever a hardcoded address or offset broke after an update, or the user says "make a pattern", "make a sig", "sig scan", "AOB scan", "address changes every update", "my pointer broke after the patch", "find GWorld via signature", "find GNames/GObjects with a pattern", "turn this address into a signature", or "check if my signatures still work on the new build". Covers picking a stable anchor instruction, wildcarding rel32/RIP-relative displacements, field offsets, immediates and register changes, the x64 encodings involved, resolving RIP-relative targets (next instruction + disp32, including instructions with trailing immediates), extracting embedded field offsets, uniqueness vs length, getting sigs from IDA/Ghidra/x64dbg/Cheat Engine, scanning dumps of packed executables, and verifying with sigtool scan/suggest/check. Ends with a signatures.toml entry that matches exactly once.
---

# AOB signatures

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

## Why addresses break

A hardcoded address like `game.exe+0x2567B10` is a position. Any patch that adds or removes a single byte of code or data before it shifts everything after it. ASLR also moves the module base on every launch, so only `base + RVA` is meaningful, and the RVA itself moves with each build.

The *code that uses* the address mostly doesn't change. A signature describes that code with the build-specific bytes masked out, so you find the instruction again in the next build and read the new address out of it.

Two things come out of a signature:

- An address: the instruction holds a rel32 or RIP-relative disp32 pointing at a global (`GWorld`, `GNames`, a manager singleton) or a function. Resolve it.
- An offset: the instruction holds a struct field displacement (`[rcx+0x13C]`). Read it.

## Tooling

Install `sigtool` (Python 3.11+, offline, standard library only):

```bash
pip install game-re-sigtool
```

```text
sigtool scan <file> <pattern> [--section .text] [--all] [--rel N[:K]] [--read N:type] [--json] [--mapped]
sigtool suggest <file> <address> [--rva] [--min 8] [--max 64] [--wildcard N,N] [--no-auto] [--section S] [--json] [--mapped]
sigtool xref <file> <address> [--rva] [--section S] [--json] [--mapped]
sigtool check <signatures.toml> <file> [<file> ...] [--json] [--mapped]
sigtool pe <file>
sigtool demo [directory]
sigtool practice [directory]
```

Patterns use IDA/CE syntax: `48 8B 05 ?? ?? ?? ?? 48 85 C0`. `?`/`??` are full-byte wildcards, `4?`/`?F` are nibble wildcards; compact `488B05????????` and code-style `\x48\x8B\x05\x00 xxx?` work too. A pattern needs at least one fully fixed byte. On a PE, `scan` searches `.text` (or every executable section if there's no `.text`) and reports file offset and RVA; `--section .rdata` picks another section, `--section '*'` scans the whole file. Addresses (`suggest` and `xref`) are hex with or without `0x`. Exit codes: `0` = exactly one match (≥1 xref), `1` = not, `2` = error (bad file, bad pattern). `sigtool demo` writes two synthetic builds and a `signatures.toml` if you want to see the output before touching a real game, and `sigtool practice` writes a bigger exercise pair (see step 2).

## Workflow

### 1. Start from a known-good address in the current build

You need the target (global, function or field) located once, by any means: Cheat Engine pointer scan, debugger, a symbol, a known dump. Write down the RVA (`address - module base`) and the build (file version, size, or hash). Run `sigtool pe game.exe` to confirm the image base and that `.text` looks normal (see step 8 if it doesn't).

### 2. Pick the anchor instruction

Find code that references the target: in IDA/Ghidra, list xrefs to the global or the field; in CE, "Find out what accesses this address" on a field. Pick the instruction that carries the value you want, then choose among candidates:

- Prefer a cold, ordinary code path: an init function, a getter called from one place, a function that logs or references a unique string. Distinctive neighbours (a string `lea`, an odd constant, a specific call sequence) make short sigs unique.
- Avoid the first bytes of a function. Prologues (`48 89 5C 24 08`, `40 53`, `48 83 EC 20`) are generic, and they're where hooks land: overlays and other mods overwrite them with a `E9 rel32` or `FF 25 00 00 00 00 <abs64>` jump, so a live-memory scan fails when something else got there first.
- Avoid inlined code. If a tiny getter got inlined into 40 call sites, the same bytes repeat and a later build with different inlining decisions breaks the count. Pick a site that's a real function or that sits in clearly unique surroundings.
- Avoid code that's obviously generated per build (giant switch tables, unrolled loops) and hot loops that the optimizer reshuffles.
- Keep 2 or 3 anchors for important targets. When one breaks, another usually survives.

You don't need IDA or CE guesses to find the candidates. `sigtool xref` finds every instruction in an executable section whose branch target (rel32) or RIP-relative displacement resolves to a given address — offline, from the file on disk. Resolve the global's RVA first (from a dump, or from `--rel` on a signature you already have for a known reader of it), then:

```console
$ sigtool xref gworld-demo-v0.exe 0x3040 --rva
file     gworld-demo-v0.exe (PE x64, image base 0x140000000), scanning .text
xrefs    1 to 0x3040
  #1  rva 0x1000  offset 0x400  rip
```

Each hit is an instruction that touches your global — a ready-made anchor for `suggest` (`sigtool suggest gworld-demo-v0.exe 0x1000 --rva`). Pass `--rva` when the address is an RVA; without it the address is a file offset, which in a mapped dump *is* the RVA, so dumps need no flag. The sweep decodes linearly, so it never reports a false positive but can miss a few instructions reached only by mid-instruction jumps. The same call finds rel32 callers of a function, not just data references. If you mis-guessed the global's RVA, `xref` returns nothing (exit 1) — cheap to retry.

To try the whole flow (xref → suggest → scan --read → check) without a game installed, `sigtool practice` writes a 5 KB two-version synthetic game plus an exercise README; a signature built on one version must still match the other.

### 3. Decide which bytes to wildcard

Wildcard everything that encodes a location, a size, or a compiler choice. Keep opcodes, ModRM bytes, and the shape of the code.

| Bytes | Example | Why it changes |
| --- | --- | --- |
| rel32 of `E8` call, `E9` jmp, `0F 8x` jcc | `E8 ?? ?? ?? ??` | Target or caller moved |
| rel8 of `EB` / `7x` short jumps | `74 ??` | Code between jump and target changed |
| RIP-relative disp32 | `48 8B 05 ?? ?? ?? ??`, `48 8D 0D ?? ?? ?? ??` | Global or string moved |
| Struct field displacement you `read` | `F3 0F 10 81 ?? ?? ?? ??` | Fields added/removed. Other field displacements can stay fixed if you'd rather the sig break when the layout changes |
| Stack offsets | `48 8B 44 24 ??` | Locals changed |
| Immediates | `B9 ?? ?? ?? ??`, vtable index `FF 90 ?? ?? ?? ??` | Constants, enums, buffer sizes, vtable layout |
| Register choice | `4? 8B ?5` (nibbles of REX and ModRM) | Register allocator picked another register |

Register wildcards are a last resort. When the allocator changes, the surrounding code usually changes too, and every nibble you mask makes false matches likelier. Prefer another anchor.

Details, opcode tables, and how to read ModRM/REX bytes: [references/x64-encoding.md](references/x64-encoding.md). Check every byte you claim against that file or a disassembler. Don't guess encodings.

### 4. Generate a candidate, then edit it

```bash
sigtool suggest game.exe 0x1A2B30 --rva
```

The address is a file offset unless you pass `--rva`. Output:

```text
at       offset 0x580  rva 0x1180
pattern  48 8B 05 ?? ?? ?? ?? 48
length   8 bytes, 4 fixed
matches  1 (unique)
```

`suggest` grows a pattern from the address until it's unique (binary search between `--min` and `--max` bytes) and auto-wildcards `E8`/`E9`/`0F 8x` rel32 and RIP-relative disp32. That's a linear-sweep heuristic, not a disassembler. It deliberately keeps struct displacements like `[rcx+1A8]` fixed, so a changed field offset breaks the sig loudly. When the displacement *is* the value you want (`read = ...`), or an immediate is volatile, wildcard it with `--wildcard` (byte indices from the start of the pattern, e.g. `4,5,6,7`) or edit the pattern by hand, then rescan. Use `--no-auto` when the heuristic misreads data as code. If it prints `not unique`, raise `--max` or start from a more distinctive instruction.

The pattern doesn't have to start at the target instruction. Starting a few instructions earlier, at a distinctive sequence, is fine. Just account for it in the `rel`/`read` offset.

### 5. Balance uniqueness against length

- Fixed bytes buy uniqueness. Wildcards and every extra instruction buy fragility, because each extra instruction is something else a patch can change.
- Typical good signatures are 12 to 24 bytes, mostly fixed, spanning 3 to 6 instructions. Under ~8 fixed bytes rarely stays unique in a 50 MB `.text`. Past ~40 bytes, you're probably copying a whole basic block that the next build will tweak.
- Don't start or end a pattern with wildcards. They add nothing and shift the match offset.
- Uniqueness is per section. Scan the section you'll scan at runtime (default `.text`; use `--section` for others).
- If `scan --all` shows 2 matches, extend into the bytes that differ between them instead of adding more wildcards.

### 6. Resolve the address or read the offset

RIP-relative and rel32 targets are relative to the *next instruction*:

```text
target = address_of_next_instruction + (int32)disp32
```

Worked example. At RVA `0x1A2B30`:

```text
48 8B 05 D9 4F 3C 02        mov rax, [rip+0x023C4FD9]
```

The instruction is 7 bytes, so the next instruction is `0x1A2B30 + 7 = 0x1A2B37`. disp32 is little-endian `D9 4F 3C 02` = `0x023C4FD9`. Target RVA = `0x1A2B37 + 0x023C4FD9 = 0x02567B10`. At runtime, add the module base.

Negative displacements are common for calls. `E8 4B FE FF FF` at `0x1A2B50`: rel32 = `0xFFFFFE4B` = `-0x1B5`, next = `0x1A2B55`, target = `0x1A2B55 - 0x1B5 = 0x1A29A0`.

With sigtool, `--rel N` resolves the rel32 at `match + N`, assuming the instruction ends right after it:

```console
$ sigtool scan game.exe "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ??" --rel 3
pattern  48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ??  (12 bytes, 7 fixed)
file     game.exe (PE x64, image base 0x140000000), scanning .text
matches  1
  #1  offset 0x1a1f30  rva 0x1a2b30  rel -> rva 0x2567b10 (va 0x142567b10, offset 0x2566f10)
```

(Real output format; the offsets in this sample are made up to match the example. `offset` is `-` when the target is in uninitialized data with no file bytes.)

**Trailing immediates.** When an immediate follows the displacement, the instruction ends later and the plain formula is off by the immediate's size. Use `--rel N:K`, where K is the number of bytes after the disp32:

```text
80 3D 1C 2F 00 01 00        cmp byte ptr [rip+0x01002F1C], 0   (7 bytes)
```

```bash
sigtool scan game.exe "80 3D ?? ?? ?? ?? 00 74 ??" --rel 2:1
```

At RVA `0x400100`, the next instruction is `0x400107` and the target is `0x01403023`. `--rel 2` alone would give `0x01403022`, which is wrong. The same `N:K` form works in `signatures.toml` as `rel = "2:1"`. Other common cases: `C6 05 d32 imm8` (K=1), `48 83 3D d32 imm8` (K=1, N=3), `C7 05 d32 imm32` (K=4), `81 3D d32 imm32` (K=4).

**Field offsets.** Read the displacement straight out of the instruction:

```text
F3 0F 10 81 3C 01 00 00     movss xmm0, dword ptr [rcx+0x13C]
```

```bash
sigtool scan game.exe "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1" --read 4:u32    # match line ends in: read = 0x13c (316)
```

Read types: `i8 u8 i16 u16 i32 u32 i64 u64 f32 f64`, little-endian. The `N` in `--rel`/`--read` is a byte count from the start of the match (decimal, or `0x`-prefixed hex).

Offsets under 0x80 are usually encoded as disp8 (`F3 0F 10 41 7C` = `[rcx+0x7C]`, `--read 4:u8`). disp8 is sign-extended, so the compiler switches to the disp32 form (ModRM `41` becomes `81`) once a field crosses 0x7F. If a patch pushes a field across that line, the signature breaks by design. Keep a second sig or note it.

More worked cases (chained resolve through a call, vtable indexes, AOB in a function found via a string xref): [references/resolving.md](references/resolving.md).

### 7. Validate

```bash
sigtool scan game.exe "<pattern>" --all --rel 3
```

Require `matches  1` (exit code 0), and confirm the resolved RVA equals the known-good RVA from step 1. A unique match that resolves somewhere else means your anchor or offset is wrong. Without `--all`, scan lists the first 10 matches and prints `... N more (use --all)`.

### 8. Packed or encrypted executables

If `sigtool pe` shows odd sections (`.text` tiny or high-entropy, extra sections from a protector, or the sig matches 0 times on disk while it's plainly in memory), the file on disk isn't the code that runs. Scan a dump of the loaded module instead:

1. Run the game (offline/single-player), get past the startup unpacking.
2. Dump the module image with a memory dumper (x64dbg's bundled Scylla, System Informer, or similar).
3. Scan the dump. A raw memory image of the module (module base to base + SizeOfImage) is laid out by RVA: pass `--mapped` (`sigtool scan dump.bin "<pattern>" --mapped`, same for `suggest` and `check`), so sections are read at their RVAs and file offset = RVA. Without it, sigtool parses the dump's PE headers as an on-disk file and looks in the wrong place. A rebuilt PE dump (Scylla's fixed-up output) is an ordinary PE file: don't pass `--mapped`.

Use the dump only to find and verify signatures. Don't patch out the protection, rebuild a runnable unprotected exe, or redistribute it (DRM cracking is out of scope). If the game runs under anti-cheat, don't attach or dump. Stop and say so per the Scope section.

Tool-specific steps (IDA, Ghidra, x64dbg, Cheat Engine), plugins, and runtime scanning code: [references/tools.md](references/tools.md).

### 9. Regression-check across builds

Store every signature in `signatures.toml` and check it against each build you have:

```bash
sigtool check signatures.toml old.exe new.exe
```

Exit code 1 means some signature didn't match exactly once (or `expect` times) in some build; it drops straight into CI. Optional per-entry keys: `rel` (`3` or `"2:1"`), `read` (`"4:u32"`), `section` (default `.text`), `expect` (default 1). When the new build fails:

- 0 matches: something inside the pattern changed. Diff the old and new bytes at the anchor (find it in the new build via the same xref or string) and wildcard or shorten.
- 2+ matches: the pattern got too generic, or the function got inlined or duplicated. Extend it, or move the anchor.
- 1 match but the resolved value is clearly wrong: the code shape changed and you matched a different site. Re-verify against a known-good address in the new build.

Run `check` on old builds too after editing. A fix for the new build shouldn't break the old one if you still support it.

## Deliverable

A `signatures.toml` entry per target, with a comment saying what it resolves to and the builds it was verified on:

```toml
# UWorld* global. Verified: 1.4.2 (old.exe), 1.5.0 (new.exe)
[GWorld]
pattern = "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01"
rel = 3

# float Health in the player pawn
[HealthOffset]
pattern = "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1"
read = "4:u32"

# bool bSettingsLoaded, cmp byte ptr [rip+x], 0 (imm8 after the disp32)
[SettingsFlag]
pattern = "80 3D ?? ?? ?? ?? 00 74"
rel = "2:1"
```

Paste the actual `sigtool check` output next to it. The format looks like this (the addresses here are made up):

```console
$ sigtool check signatures.toml old.exe new.exe
== old.exe
  ok   GWorld        matches 1  rva 0x1a2b30  rel -> rva 0x2567b10 (va 0x142567b10, offset -)
  ok   HealthOffset  matches 1  rva 0x3c1d40  read = 0x13c (316)
  ok   SettingsFlag  matches 1  rva 0x400100  rel -> rva 0x1403023 (va 0x141403023, offset -)
== new.exe
  ok   GWorld        matches 1  rva 0x1a3f10  rel -> rva 0x2571c40 (va 0x142571c40, offset -)
  ok   HealthOffset  matches 1  rva 0x3c2e80  read = 0x144 (324)
  ok   SettingsFlag  matches 1  rva 0x401240  rel -> rva 0x140d5a3 (va 0x14140d5a3, offset -)
6/6 passed
```

A failing entry prints `FAIL <name>  matches 0` (or `matches 2`) and the command exits 1. Don't claim success until every line is `ok` with `matches 1` and the resolved values agree with an independently known address in at least one build.

## Common mistakes

- Adding disp32 to the address of the instruction or of the displacement instead of the next instruction.
- Forgetting the trailing immediate (`--rel N:K`).
- Treating disp32/rel32 as unsigned. They're signed.
- Reporting a runtime VA from a different launch. Store RVAs and add the current module base.
- Leaving a struct offset or stack offset fixed in the pattern, so it breaks on the first patch that adds a field.
- Scanning the encrypted file on disk and concluding the code isn't there.
