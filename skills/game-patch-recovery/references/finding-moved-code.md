# Finding a moved function in a new build

Read this when a signature matches 0 times after a patch and step 1 of SKILL.md (splitting the pattern) didn't find it.

## Contents

- Diagnose the broken pattern
- String references
- Neighbouring signatures and linker order
- Call graph walking
- Binary diffing tools
- Engine shortcuts
- Confirming the match

## Diagnose the broken pattern

Find out what changed before you go looking for the function.

```bash
# old pattern, split into halves
sigtool scan new.exe "E8 ?? ?? ?? ?? 48 8B D8 48 85 C0"
sigtool scan new.exe "74 ?? F3 0F 10 83 A8 01 00 00"
```

- First half still unique: the function is at the same call site, and only the tail changed. Look at the bytes after the match in a disassembler and wildcard the parts that differ.
- Both halves match 0 times: the function was rewritten, or the compiler chose different instructions (a different inlining decision, or a new optimisation level). Use the methods below.
- A half matches many times: that half was never what made the pattern unique. Re-anchor on rarer bytes.

Common byte churn that doesn't mean the logic changed:

| Change | Bytes affected | Fix |
|---|---|---|
| Register allocation | REX prefix and ModRM (`48 8B D8` vs `48 8B F8`) | nibble wildcard `48 8B ?8`, or `??` |
| Struct member added | disp8/disp32 of `[reg+disp]` | wildcard the displacement |
| Bigger stack frame | `sub rsp, imm`, `[rsp+disp]` | wildcard the immediate/displacement |
| Function moved | `E8`/`E9` rel32, RIP-relative disp | `suggest` already wildcards these |
| disp8 became disp32 | instruction length changes | re-suggest; wildcards can't fix a length change |

## String references

1. Find a string the old function used. In IDA, look at its cross-references in the old build. In Ghidra, use Search > For Strings.
2. Find the same string in the new build and list its xrefs. If only one function references it, that's your candidate.
3. Wide (UTF-16) strings are common in Unreal (`TEXT("...")`). Search both encodings.

## Neighbouring signatures and linker order

MSVC usually keeps functions from one translation unit together and in source order, unless the build uses link-time code generation with a different profile. Use that:

1. Find the old-build RVAs of the broken target and of 2 or 3 signatures that still match.
2. Work out the old deltas, for example target = neighbour + 0x3C0.
3. In the new build, go to neighbour_new + 0x3C0 and look for the same prologue and the same shape. Function sizes change, so expect the delta to drift by tens to hundreds of bytes, not stay exact.

This only narrows the search. Confirm with code shape and xrefs before you trust it.

## Call graph walking

- Callee survived: find all callers of the surviving callee in the new build. Your target is usually the one with the same number of calls in the same order.
- Caller survived: find the call in the caller that matches the old call's position (for example the 3rd call after a given string load) and follow it.
- Virtual functions: if the target is a vtable slot, sign the code that loads the vtable or a unique method next to it, then re-index. A vtable index changes when a virtual method is added before it.

## Binary diffing tools

Check each tool's README for current versions and install steps.

- **BinDiff** (Google, open source, Apache 2.0). Export both builds with BinExport from IDA Pro, Ghidra or Binary Ninja, then diff the two `.BinExport` files. Sort the matched functions by similarity and look up your old address.
- **Diaphora**. IDA plugin, Python 3 (IDA 7.4 or newer). Export the old build to a SQLite database, open the new build, and diff against it. Its "best" and "partial" match lists give you old and new address pairs.
- **Ghidra Version Tracking**. Built into Ghidra. Create a session with both programs, run the correlators (exact bytes, exact mnemonics, symbol and data reference matches), and accept matches step by step.

Tips:

- Run auto-analysis on both builds with the same settings, so they get the same function boundaries.
- Matches with low similarity scores are hints, not answers. Check them with strings and call shape.
- Big Unreal executables take a long time to diff. If you know roughly where the target is, diff only that range or that subsystem.

## Engine shortcuts

- **Unity IL2CPP**: re-dump with Il2CppDumper (or Cpp2IL for newer Unity versions) and read the `// RVA: 0x...` comment above the method in `dump.cs`. Method names survive patches unless the build is obfuscated.
- **Unreal**: `UFunction`s reachable through reflection still have names after a patch, so their native thunks can be found by name with Dumper-7 or UE4SS output. Engine globals (GWorld, GNames/FNamePool, GObjects) have well-known access patterns that a dumper finds by itself. Take the new RVA from the dumper's log.

## Confirming the match

Before you rebuild the signature, check all of these:

- The same strings, constants and float literals are present.
- The same number and order of calls to known functions.
- The same field displacements, or ones that differ by exactly the delta you saw in the SDK diff.
- If you can, set a breakpoint in a single-player session and trigger the behaviour (take damage, open the menu).
