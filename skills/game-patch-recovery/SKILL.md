---
name: game-patch-recovery
description: Recover a mod, memory reader, trainer or bot after a game update broke it. Confirms the patch is the cause, runs `sigtool check` across the old and new builds to see which signatures stopped matching, finds moved functions again (string xrefs, neighbouring signatures, call graph, BinDiff/Diaphora/Ghidra Version Tracking), rebuilds signatures with `sigtool suggest`, diffs Unreal/Unity SDK dumps for shifted struct field offsets, and writes an updated offsets file and signatures.toml checked against both builds. Use when the user says "broke after update", "game patched", "new version broke my mod", "offsets changed", "signature not found", "pattern returns 0 results", "pattern matches multiple times", "after the update my bot/trainer/mod stopped working", "reader returns garbage since the patch", "health is at a different offset now", or asks how to make their tool survive the next update.
---

# Game Patch Recovery

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

If the patch *added* anti-cheat to a game that didn't have it, stop at that point. Explain that working around it is out of scope, and offer to help with an offline mode or an older build if one is still available.

## What you deliver

- An updated `signatures.toml` where every entry matches exactly once in the new build, and in the old build too if the user supports both. `sigtool check` exits 0.
- An updated offsets file, versioned per build (`offsets/1.5.0.toml`, or a section per build id).
- A short report: what moved, what was fixed, and what you haven't verified yet (template at the end).

Install the verifier if it's missing:

```bash
pip install "git+https://github.com/juzorei/game-re-skills#subdirectory=tools/sigtool"
```

## 1. Confirm it's actually the patch

Don't start re-signaturing until you know the binary changed. A lot of "broken by the update" reports turn out to be a different exe, a launcher change or a bug in the tool.

- Compare build identity against the last known good one:
  - Steam: `buildid` in `steamapps/appmanifest_<appid>.acf`.
  - PE file version: PowerShell `(Get-Item game.exe).VersionInfo.FileVersion`.
  - Hash: `Get-FileHash game.exe -Algorithm SHA256` or `sha256sum game.exe`.
  - `sigtool pe game.exe` prints machine, image base and the section table (rva, vsize, offset, rawsize, flags). Different section sizes mean the code changed; identical ones don't prove it didn't, so rely on the hash. sigtool doesn't show the PE timestamp.
- Check you're hashing the right module. Unreal games usually run `<Game>-Win64-Shipping.exe` behind a small launcher exe. Unity IL2CPP code lives in `GameAssembly.dll` and its metadata in `global-metadata.dat`, not in the exe. A patch can change one without touching the other.
- If the hashes match, the patch isn't the cause. Look at the tool instead (ASLR handling, wrong process attached, 32/64-bit mismatch, permissions).

**Archive builds from now on.** Diffing needs the old binary, and the user almost never kept it. Tell them to copy the main module (plus `GameAssembly.dll` and `global-metadata.dat` for Unity) into `builds/<buildid>/` before every update, and to write down the hash. If the old build is already gone, Steam owners can sometimes fetch an older depot manifest (DepotDownloader, or the Steam console `download_depot`). Check the tool's README for current syntax. Never redistribute game files.

## 2. Run the check across both builds

```bash
sigtool check signatures.toml builds/1.4.2/game.exe builds/1.5.0/game.exe
sigtool check signatures.toml builds/1.4.2/game.exe builds/1.5.0/game.exe --json > check.json
```

Real output looks like this (from `sigtool demo`, which writes two synthetic builds you can practise on):

```console
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

Exit code: `0` if every entry matched exactly once (or its `expect` count) in every file, `1` otherwise, `2` on errors such as a missing file or a malformed TOML entry. In `--json`, each entry has `count`, `ok`, `rva` and `values` (`rel.rva` or `read`), which is what you compare between builds. If the new build is packed and you're checking a raw memory dump, add `--mapped`.

**Rehearse before you touch the real builds.** `sigtool practice` writes `gworld-demo-v0.exe`/`gworld-demo-v1.exe`, a two-version synthetic game where all the code moved, a health-field offset shifted `0x1A8`→`0x1B8`, and a `call` became a `jmp` — exactly this skill's failure modes, in 5 KB, with no game installed. Run the whole recovery flow on it (xref → suggest → rebuild the failing entry → `check` on both versions) as a warm-up. In v0 the GWorld-like global sits at RVA `0x3040`; between the versions it survived while the code around it didn't.

Sort every signature into one of four buckets. Each needs a different fix.

| Result in new build | Meaning | Go to |
|---|---|---|
| 1 match, same resolved value | Survived | nothing to do |
| 1 match, resolved `rel`/`read` value changed | Code still matches, but the target or offset moved | step 6 (update offsets) |
| 0 matches | Function changed or got recompiled differently | step 3a |
| >1 matches | Pattern too generic now (code got duplicated or inlined) | step 3b |

The "1 match, value changed" bucket is the good news. A `read = "4:u32"` signature that went from `0x1A8` to `0x1B0` has already told you the new field offset. Any hardcoded offset near it in the same struct probably shifted too. Confirm it with step 4.

## 3a. Signatures with 0 matches: find the function again

Work from cheap to expensive. Stop as soon as you have a confident address in the new build. Details and pitfalls are in [references/finding-moved-code.md](references/finding-moved-code.md).

1. **Find out why the old pattern fails.** Run `sigtool scan` with the old pattern's first half, then its second half, on the new build. If one half still matches once, the function survived and only a few bytes changed (often register allocation or a stack offset). Widen those bytes and you're done.
2. **String references.** If the function touches a unique string (log message, asset path, cvar name), find that string in the new build and follow the cross-references in IDA or Ghidra.
3. **`sigtool xref`.** If a nearby global, a vtable entry or another data symbol the function references survived the patch (check its value in both builds — `.data` RVAs often don't move even when `.text` does), `sigtool xref builds/1.5.0/game.exe <rva> --rva` lists every instruction that addresses it, no IDA needed. The hits re-anchor you directly: feed one into `suggest`. The same works for rel32 callers of a surviving function.
4. **Neighbouring signatures.** Signatures that still match tell you where their functions are now. The linker usually keeps functions from the same source file in order. If the target sat `+0x3C0` after a surviving neighbour in the old build, start looking near the same spot in the new one.
5. **Call graph.** Find a caller or callee that still matches, then follow the call edge. Unreal `exec` thunks and Unity `dump.cs` RVAs give you named entry points for free.
6. **Binary diffing**, when the patch is large:
   - BinDiff: open source (Apache 2.0), works from BinExport files out of IDA Pro, Ghidra or Binary Ninja.
   - Diaphora: IDA plugin (IDA 7.4+, Python 3).
   - Ghidra Version Tracking: built in, no plugin needed.

   Diff old against new, then jump to the matched function. Treat low-similarity matches as hints, not answers.
7. **Unity IL2CPP:** don't hunt by hand. Re-dump with Il2CppDumper (metadata up to v31; use Cpp2IL or Il2CppInspectorRedux for v35+, see the `unity-il2cpp-offsets` skill) and read the new RVA straight from the `// RVA:` comment above the method in `dump.cs`.

Once you have the new address, rebuild the signature and check it against both builds:

```bash
sigtool suggest builds/1.5.0/game.exe 0x8A41F0 --rva --min 12
sigtool scan builds/1.5.0/game.exe "<suggested pattern>"
sigtool scan builds/1.4.2/game.exe "<suggested pattern>"
```

`suggest` already wildcards rel32 operands of `E8`/`E9`/`0F 8x` and RIP-relative displacements. Widen these by hand with `--wildcard N,N` (byte indices). They change between builds without the logic changing:

- Struct displacements you aren't reading (`48 8B 81 ?? ?? ?? ??`). They shift every time a member gets added.
- Stack offsets (`[rsp+??]`) and frame sizes (`48 81 EC ?? ?? ?? ??`).
- ModRM/REX bytes, but only if the register choice keeps flipping between builds. Nibble wildcards (`4?`, `?B`) keep more uniqueness than `??`.

Don't wildcard the bytes you `read`. Their value is the whole point of the signature.

## 3b. Signatures with >1 match: re-anchor

- Lengthen: rerun `suggest` with a larger `--min`, or extend the pattern forward until it's unique.
- Re-anchor: start the pattern at a rarer instruction close by. Good candidates are a unique immediate, a float constant load, or a `lea` to a unique string.
- Move up the call graph: sign the unique caller and resolve the call with `rel`. This fixes the common case where the function got inlined into several places.
- Don't fall back to "take the 2nd match". That ordering breaks on the next patch.

## 4. Struct field offsets: diff the SDK dumps

Dump both builds with the same tool and version, then do a plain text diff:

- Unreal: Dumper-7 (inject into the running game; output goes to the configured SDK folder) or UE4SS's header and object dumps. The generated headers carry each field's offset and size in comments.
- Unity IL2CPP: Il2CppDumper `dump.cs` (field offsets appear as `// 0x1A8` when `DumpFieldOffset` is on).

```bash
git diff --no-index --stat sdk-1.4.2/ sdk-1.5.0/
git diff --no-index sdk-1.4.2/CppSDK/SDK/Game_classes.hpp sdk-1.5.0/CppSDK/SDK/Game_classes.hpp
```

One inserted member makes every later offset show up as a changed line. To find the real cause, strip the offset comments and diff again; the inserted or removed members are all that remain. The commands are in [references/struct-layout-diff.md](references/struct-layout-diff.md).

How fields move:

- An inserted member shifts everything after it in that class by its size, rounded up to the next field's alignment. A 1-byte `bool` inserted before an 8-byte pointer shifts later fields by 8, not 1.
- Members added to a **base class** shift every field in every derived class. If all `APlayerCharacter` fields moved by the same delta, check `ACharacter` or `APawn` first.
- Removed members shift things the other way. Reordered members don't follow any delta, so map them by name.
- Padding can absorb a small insertion, so fields after it may not move at all. Trust the dump, not the arithmetic.

Without a dump (custom engines), get offsets from instructions instead: sign the code that accesses the field and `read` the displacement (step 7).

## 5. Pointer chains: last resort

Re-run a pointer scan only when there's no code reference you can sign. Values that get built at runtime with no static accessor are the usual case. Scan the new build, intersect the results with a second session (restart the game), and prefer short chains rooted in the main module. Verify each hop read-only:

```bash
sigtool chain --process game.exe --module game.exe --base 0x5B2A3C8 --offsets 0x30,0x2A0,0x1B0 --type f32
```

If a chain's base is a global the code loads with `mov rax, [rip+x]`, replace the base with a `rel` signature. That fixes it for good.

## 6. Update files and re-verify

1. Write the new values into the offsets file for the new build. Keep the old build's file unchanged.
2. Update `signatures.toml`. If one pattern can't match both builds, use per-build files (`signatures.1.4.2.toml`, `signatures.1.5.0.toml`) or build-suffixed names, and pick one at runtime by build id or hash.
3. Re-run the check. `sigtool check` exits 1 if any signature doesn't match exactly once in **every** file you pass:

```bash
sigtool check signatures.toml builds/1.4.2/game.exe builds/1.5.0/game.exe   # both supported
sigtool check signatures.1.5.0.toml builds/1.5.0/game.exe                   # new only
```

4. Test the actual tool in the new build: read the value, change it in game (take damage), and confirm the reader follows. A clean check only proves the patterns are unique, not that they point at the right thing.

## 7. Prevention: make the next patch cheap

- **Resolve at startup.** Have the reader scan its signatures when it attaches and compute addresses with `rel` (the `external-memory-reader` skill builds a reader that does this from `signatures.toml`). Don't ship hardcoded RVAs. A pattern that survives the patch means nothing to fix.
- **Read field offsets from code.** `F3 0F 10 81 ?? ?? ?? ??` (`movss xmm0, [rcx+disp32]`) plus `read = "4:u32"` gives you the current Health offset on every build.
- **Fail loudly.** If a signature matches 0 or >1 times, refuse to run and name the signature. Don't read garbage memory.
- **CI-style check.** Keep a script that runs right after every update:

```bash
#!/usr/bin/env bash
set -euo pipefail
sigtool check signatures.toml builds/*/game.exe --json > check-$(date +%F).json \
  && echo "all signatures OK" || { echo "signatures broke, see JSON"; exit 1; }
```

- **Version the offsets file per build** and record the build id and hash in it, so the reader can say "unknown build" instead of guessing.

## Worked example

The user's reader for a single-player action game broke after Steam build 1.4.2 → 1.5.0. Health showed 0 and the "apply damage" hook crashed.

1. `buildid` went from 14021337 to 14388102, and the SHA-256 of `Game-Win64-Shipping.exe` differed. The user still had 1.4.2 because they copied it after reading this skill last time.
2. Results of `sigtool check signatures.toml builds/1.4.2/... builds/1.5.0/...`:
   - `GWorld` (`rel = 3`): 1 match in both builds. Target RVA changed `0x5B2A3C8` → `0x5B4F1E8`. Already handled, since the reader resolves it at startup.
   - `HealthOffset` (`read = "4:u32"`): 1 match in both builds, value `0x1A8` → `0x1B0`.
   - `ApplyDamage`: 1 match in 1.4.2, **0 in 1.5.0**. The pattern was anchored on a call site: `E8 ?? ?? ?? ?? 48 8B D8 48 85 C0 74 ?? F3 0F 10 83 A8 01 00 00`.
3. Two problems explained the 0. The pattern hardcoded the Health displacement `A8 01 00 00`, and in 1.5.0 the compiler kept the call result in `rdi` (`48 8B F8`, then `F3 0F 10 87 ...` = `[rdi+disp32]`) instead of `rbx` (`48 8B D8`, `F3 0F 10 83 ...`). The first 12 bytes with the register nibble wildcarded (`E8 ?? ?? ?? ?? 48 8B ?8 48 85 C0 74`) still matched once. That confirmed it was the same call site.
4. The SDK diff (offset comments stripped) showed one new member, `bool bIsGuarding`, added at `0x1A0` in `APlayerCharacter`. The following pointer `CurrentWeapon` (8-byte aligned) moved `0x1A0` → `0x1A8`. So `Health` moved `0x1A8` → `0x1B0` and `MaxHealth` moved `0x1AC` → `0x1B4`. That's an 8-byte shift from a 1-byte insert, because of alignment. Fields before `0x1A0` didn't move.
5. Rebuilt pattern: `E8 ?? ?? ?? ?? 48 8B ?8 48 85 C0 74 ?? F3 0F 10 8?`. The nibble wildcards cover both register choices (`D8`/`F8`, `83`/`87`), and the struct displacement is left out (trailing wildcards add nothing). `sigtool scan ... --rel 1` printed `matches  1` in each build. The rel32 at +1 resolved to the new `ApplyDamage` at RVA `0x8A41F0` (was `0x8A3E50`).
6. The new `offsets/1.5.0.toml` has Health `0x1B0` and MaxHealth `0x1B4`. 1.4.2 was left alone. `sigtool check` across both builds exited 0. In game, the reader tracked health through a hit and the hook stopped crashing.

## Report to user

```text
Build: 1.4.2 (14021337) -> 1.5.0 (14388102), Game-Win64-Shipping.exe sha256 <old>.. -> <new>..

What moved
- APlayerCharacter: +bIsGuarding at 0x1A0; CurrentWeapon 0x1A0->0x1A8, Health 0x1A8->0x1B0, MaxHealth 0x1AC->0x1B4
- ApplyDamage: RVA 0x8A3E50 -> 0x8A41F0 (signature broke: register change + hardcoded displacement)
- GWorld: RVA changed, resolved at runtime, no action needed

What I fixed
- signatures.toml: ApplyDamage re-anchored with wildcards; check passes on 1.4.2 and 1.5.0
- offsets/1.5.0.toml: new file; offsets/1.4.2.toml unchanged

Verified
- sigtool check exit 0 on both builds; health read and damage hook tested in game on 1.5.0

Not verified
- <fields read from offsets but not exercised in game, e.g. Stamina 0x1C0>
- <features untested on 1.4.2 after the change>
```

List anything you inferred but didn't test under "Not verified". Don't present a clean `sigtool check` as proof that the tool works.
