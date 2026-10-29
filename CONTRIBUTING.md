# Contributing

Thanks for helping. This file is both the contributor guide and the spec every skill in this repo follows.

## Skill layout

```text
skills/<name>/
├── SKILL.md            workflow, under ~300 lines
└── references/         deep detail the agent reads on demand
```

- `name` in frontmatter is kebab-case and matches the directory name.
- `description` says what the skill does and when to use it, including the phrasings a user would actually type ("my pointer broke after the update", "find GWorld", "dump il2cpp"). Keep it under 1024 characters.
- The body is written to the agent, in the imperative. Explain why a step matters when it isn't obvious.
- Every skill ends with a concrete deliverable: a pointer chain, a signature, an offsets file, a working reader. The agent should verify it with `sigtool` before claiming success.
- Give tool versions and UI names only when you're confident they're current. Otherwise describe the concept and tell the agent to check the tool's README.

## Scope

Every skill opens with the same short scope section (see [SCOPE.md](SCOPE.md)): single-player and offline games, modding, interoperability, education, and private servers you run yourself. The skills don't help bypass anti-cheat, hide from detection, or cheat in online multiplayer. Keep that section intact when you edit a skill.

## sigtool

`tools/sigtool` is a small offline CLI (Python 3.11+, standard library only) that skills use to verify their output. Its interface:

```text
sigtool scan <file> <pattern> [--section .text] [--all] [--rel N] [--read N:type] [--json]
sigtool suggest <file> <address> [--rva] [--min 8] [--max 64] [--wildcard N,N] [--no-auto]
sigtool check <signatures.toml> <file> [<file> ...] [--json]
sigtool xref <file> <address> [--rva] [--json]
sigtool chain --process game.exe --module game.exe --base 0x1234 --offsets 0x10,0x20 [--type f32]
sigtool pe <file>
sigtool demo [directory]
sigtool practice [directory]
```

- Patterns use IDA/Cheat Engine syntax: `48 8B 05 ?? ?? ?? ?? 48 85 C0`. `?` and `??` are full wildcards, `4?` and `?F` are nibble wildcards. Compact `488B05????????` and code-style `\x48\x8B\x05\x00 xxx?` (bytes plus `x?` mask) are accepted too.
- On a PE file, `scan` searches `.text` by default and reports both file offset and RVA. On a raw dump it searches the whole file and reports file offsets.
- `--rel N` treats the 4 bytes at match+N as a rel32 displacement and resolves the target RVA (next instruction = end of those 4 bytes; use `--rel N:K` when the instruction ends K bytes after the displacement, e.g. `cmp [rip+x], imm8`).
- `--read N:type` reads a little-endian value at match+N. Types: `i8 u8 i16 u16 i32 u32 i64 u64 f32 f64`.
- `suggest` builds the shortest unique pattern starting at the address. It wildcards rel32 operands of `E8`, `E9`, `0F 8x` and RIP-relative `ModRM` displacements automatically (heuristic, disable with `--no-auto`).
- `check` reads a TOML file of signatures and reports how many times each one matches in every build. Exit code 1 if any signature doesn't match exactly once. Format:

```toml
[GWorld]
pattern = "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01"
rel = 3            # optional: resolve rel32 at match+3 ("2:1" when 1 more byte follows the displacement)

[HealthOffset]
pattern = "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1"
read = "4:u32"     # optional: read a field offset embedded in the instruction
```

- `chain` is Windows-only and read-only. It walks `[[module+base]+o1]+o2...` the way Cheat Engine does and prints every hop.

## Before opening a PR

```bash
pip install pytest pyyaml ./tools/sigtool
python scripts/validate_skills.py
python -m pytest
```
