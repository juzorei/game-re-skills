# game-re-skills

[English](README.md) | [Русский](README.ru.md)

[![CI](https://github.com/juzorei/game-re-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/juzorei/game-re-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/juzorei/game-re-skills)](LICENSE)
[![Release](https://img.shields.io/github/v/release/juzorei/game-re-skills)](https://github.com/juzorei/game-re-skills/releases)

Agent skills for game reverse engineering, plus a small CLI that checks the agent's work.

```text
$ npx skills add juzorei/game-re-skills
$ pip install game-re-sigtool
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

The game patched: code moved and the health field shifted from `0x1A8` to `0x1B0`. The wildcarded signatures survived it and now report the new values. The one that hardcoded the offset failed — which is what you want to find out before your users do.

Coding agents already know a lot about x64, Cheat Engine and Unreal internals. What they lack is a workflow: they guess offsets, hardcode addresses that break on the next patch, and say "should work" without checking. These skills give Claude Code, Codex, Cursor, ZCode and other agents a step-by-step process for each job, and every skill ends with a result verified by `sigtool`.

## Skills

| Skill | Use it when |
|---|---|
| [cheat-engine-pointer-chains](skills/cheat-engine-pointer-chains) | You can see a value (health, gold, position) and need a pointer chain that survives restarts. |
| [aob-signatures](skills/aob-signatures) | An address changes every update and you need a pattern that doesn't, or you need to resolve `[rip+x]` and field offsets from code. |
| [unreal-sdk-offsets](skills/unreal-sdk-offsets) | UE4/UE5 game: find GObjects, GNames and GWorld, dump the SDK with Dumper-7 or UE4SS, and walk to the local player. |
| [unity-il2cpp-offsets](skills/unity-il2cpp-offsets) | Unity IL2CPP game: dump `GameAssembly.dll` + `global-metadata.dat`, read `dump.cs`, and find static instances. |
| [external-memory-reader](skills/external-memory-reader) | You have offsets and want a read-only Python reader that is fast, testable without the game, and doesn't return silent zeros. |
| [game-patch-recovery](skills/game-patch-recovery) | The game updated and your mod, reader or trainer broke. Find what moved and fix it. |

The skills point to each other. A typical path: `unreal-sdk-offsets` finds GWorld, `aob-signatures` makes it patch-proof, `external-memory-reader` reads it, and `game-patch-recovery` takes over on patch day.

## sigtool

[`tools/sigtool`](tools/sigtool) is an offline CLI (Python 3.11+, no dependencies) the skills use to verify results:

```console
$ sigtool check signatures.toml game-1.0.exe game-1.1.exe
== game-1.1.exe
  ok   GWorld           matches 1  rva 0x1180  rel -> rva 0x3040 (va 0x140003040, offset 0xc40)
  ok   HealthOffset     matches 1  rva 0x1200  read = 0x1b0 (432)
  FAIL OldHealthOffset  matches 0
```

It scans patterns (IDA/CE syntax, nibble wildcards), resolves RIP-relative targets, generates the shortest unique signature with relocatable operands wildcarded, regression-tests a signatures file across builds and walks Cheat Engine style pointer chains (Windows, read-only). Run `sigtool demo` to try it on synthetic builds.

## Install

With the [skills CLI](https://github.com/vercel-labs/skills), for any supported agent:

```bash
npx skills add juzorei/game-re-skills
```

As a Claude Code plugin:

```text
/plugin marketplace add juzorei/game-re-skills
/plugin install game-re-skills@game-re-skills
```

Manually: copy the folders from `skills/` into your agent's skills directory (`~/.claude/skills/`, `~/.agents/skills/`, `.codex/skills/` and so on).

Then install sigtool:

```bash
pip install game-re-sigtool
```

## Scope

These skills are for single-player and offline games, modding, interoperability, research and private servers you run yourself. They don't help bypass anti-cheat, hide from detection, or cheat in online multiplayer, and the agent will say so. See [SCOPE.md](SCOPE.md).

## Contributing

Corrections from people who have hit these problems on real games are the most valuable thing you can send: a struct layout that differs on some engine version, a tool flag that changed, a step that didn't work. See [CONTRIBUTING.md](CONTRIBUTING.md).

MIT licensed.
