# sigtool

A small offline CLI for the boring, error-prone parts of game reverse engineering: checking that a signature matches exactly once, resolving RIP-relative addresses, generating a pattern that survives relocation, regression-testing signatures across builds and walking pointer chains.

Python 3.11+, standard library only.

```bash
pip install game-re-sigtool
```

## Commands

```text
sigtool scan <file> <pattern> [--section .text] [--all] [--rel N[:K]] [--read N:type] [--json] [--mapped]
sigtool suggest <file> <address> [--rva] [--min 8] [--max 64] [--wildcard N,N] [--no-auto] [--json] [--mapped]
sigtool check <signatures.toml> <file> [<file> ...] [--json] [--mapped]
sigtool xref <file> <address> [--rva] [--json] [--mapped]
sigtool chain (--process game.exe | --pid N) [--module game.exe] --base 0x1234 --offsets 0x10,0x20 [--type f32]
sigtool pe <file>
sigtool demo [directory]
sigtool practice [directory]
```

Addresses and offsets are hex, with or without `0x`. Exit codes: `0` when the result is exactly one match (or the chain resolved), `1` when it isn't, `2` on errors.

## Try it in 30 seconds

`sigtool demo` writes two synthetic builds of a fake game. Between 1.0 and 1.1 the code moved and the health field shifted from `0x1A8` to `0x1B0`:

```console
$ sigtool demo && cd sigtool-demo
$ sigtool check signatures.toml game-1.0.exe game-1.1.exe
== game-1.0.exe
  ok   GWorld           matches 1  rva 0x1100  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
  ok   HealthOffset     matches 1  rva 0x1200  read = 0x1a8 (424)
  ok   OldHealthOffset  matches 1  rva 0x1200
== game-1.1.exe
  ok   GWorld           matches 1  rva 0x1180  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
  ok   HealthOffset     matches 1  rva 0x1200  read = 0x1b0 (432)
  FAIL OldHealthOffset  matches 0
5/6 passed
```

The wildcarded signatures survive the update and report the new values. The one that hardcoded the field offset fails, which is what you want to find out before your users do.

### scan

```console
$ sigtool scan game-1.1.exe "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? E8" --rel 3
pattern  48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? E8  (13 bytes, 8 fixed)
file     game-1.1.exe (PE x64, image base 0x140000000), scanning .text
matches  1
  #1  offset 0x580  rva 0x1180  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
```

Patterns use IDA/Cheat Engine syntax. `??` or `?` is a wildcard byte, `4?` and `?F` are nibble wildcards. Compact (`488B1D????????`) and code-style (`\x48\x8B\x1D\x00\x00\x00\x00 xxx????`) input works too.

On a PE file the scan covers `.text` (or every executable section if there's no `.text`). Pass `--section .rdata` for another section, or `--section '*'` for the whole file. Anything else is scanned as raw bytes.

`--rel N` resolves a 4-byte displacement at match+N relative to the end of the displacement, which is the next instruction for `mov`, `lea`, `call` and `jmp`. When an immediate follows the displacement, add its size: `cmp byte ptr [rip+x], 0` is `80 3D disp32 imm8`, so use `--rel 2:1`.

`--read 4:u32` reads a value at match+4, which is how you pull a struct field offset out of `movss xmm0, [rcx+1A8]` without hardcoding it.

### suggest

Builds the shortest pattern, starting at the address, that matches exactly once. Branch targets (`E8`, `E9`, `0F 8x`) and RIP-relative displacements are wildcarded automatically. Struct displacements like `[rcx+1A8]` are kept, because a changed field offset should break the signature loudly. Add `--wildcard 4,5,6,7` to loosen it by hand.

### check

Runs a TOML file of signatures against one or more builds and reports which still match once and what they resolve to:

```toml
[GWorld]
pattern = "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01"
rel = 3

[HealthOffset]
pattern = "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1"
read = "4:u32"

[SettingsFlag]
pattern = "80 3D ?? ?? ?? ?? 00 74"
rel = "2:1"
section = ".text"   # optional
expect = 1          # optional
```

Exit code 1 if any signature doesn't match exactly once (or `expect` times), so it drops straight into CI or a pre-release script.

### xref

Finds every instruction in an executable section whose branch target or RIP-relative displacement resolves to the given address — the question you'd normally answer with an IDA/Ghidra cross-reference list, answered offline from the file on disk. Give the RVA with `--rva`, or a file offset without it.

```console
$ sigtool xref Game.exe 0x3040 --rva
file     Game.exe (PE x64, image base 0x140000000), scanning .text
xrefs    1 to 0x3040
  #1  rva 0x1000  offset 0x400  rip
```

The sweep decodes linearly from the section start, so a handful of instructions reached only by jumping into the middle of another can be missed; what it reports is exact, never a false positive. Use the hits as anchor instructions for `scan`/`suggest`: an instruction that references your global is the most stable thing to signature.

### chain

Windows only and read-only (`PROCESS_VM_READ`). Walks a Cheat Engine style chain: `"game.exe"+0x01234 -> 0x10 -> 0x20` becomes `--module game.exe --base 0x01234 --offsets 0x10,0x20`. The static address and every intermediate result are dereferenced; the last offset is added, not dereferenced. Pointer size follows the target (WOW64 processes use 4 bytes).

### --mapped

Use it for a module dumped from memory, where file offsets equal RVAs. Scan dumps instead of the file on disk when the executable is packed.

### practice

`sigtool practice` writes a two-version synthetic "game" plus an exercise README: find the code that reads a GWorld-like global (`xref`), signature it (`suggest`), pull the health field offset out of the store instruction (`scan --read`), and regression-check both versions (`check`) — including watching a hardcoded offset fail exactly the way it fails on patch day. It's 5 KB, needs no game installed, and is the fastest way to learn the workflow the game-re-skills skills teach.
