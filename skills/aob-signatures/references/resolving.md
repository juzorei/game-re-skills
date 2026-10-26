# Resolving addresses and offsets: worked cases

All numbers are RVAs. Add the module base at runtime. disp32 and rel32 are signed little-endian.

```text
target = (match + N) + 4 + K + int32(bytes[match+N .. match+N+4])
         \_____ address of next instruction ____/
```

N is where the displacement starts in the match. K is the number of bytes between the end of the displacement and the end of the instruction (0 unless an immediate follows). sigtool's `--rel N` is `K=0`, `--rel N:K` is the general form.

## Sanity checks after every resolve

- sigtool prints `rel -> rva R (va V, offset O)`. `offset -` means the target has no file bytes (uninitialized data past a section's raw size), which is normal for many globals.
- Run `sigtool pe game.exe` and check which section the result falls in. A global (`GWorld`, a singleton) should land in `.data` or `.bss`-like space, a string in `.rdata`, a function in `.text`. A result outside every section means a wrong N, K, or anchor.
- A function target should start at a plausible prologue or right after `CC` padding.
- Compare against the known-good address from the build you started on.

## Case 1: global loaded directly

```text
RVA 0x1A2B30: 48 8B 05 D9 4F 3C 02    mov rax, [rip+0x023C4FD9]
RVA 0x1A2B37: 48 85 C0                test rax, rax
RVA 0x1A2B3A: 74 ..                   je ...
```

Pattern `48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ??`, `rel = 3`.
next = `0x1A2B37`, target = `0x1A2B37 + 0x023C4FD9 = 0x02567B10`.

If the pattern starts two instructions earlier, say 6 bytes before the `mov`, the displacement is at `6 + 3 = 9`, so `rel = 9`. N is always counted from the start of the pattern, not of the instruction.

## Case 2: global behind a tiny getter (two hops)

Small getters like `mov rax, [rip+x]; ret` exist many times over, so a sig of the getter alone is rarely unique. Sig a distinctive caller instead, resolve the call, then resolve the getter.

```text
RVA 0x512340: E8 7B 3C 08 00          call 0x595FC0
RVA 0x512345: 48 85 C0                test rax, rax
...
RVA 0x595FC0: 48 8B 05 49 1B FD 01    mov rax, [rip+0x01FD1B49]
RVA 0x595FC7: C3                      ret
```

1. Caller sig `E8 ?? ?? ?? ?? 48 85 C0 ...`, `--rel 1`: `0x512345 + 0x00083C7B = 0x595FC0`.
2. The getter at `0x595FC0`: displacement at +3, next = `0x595FC7`, target = `0x595FC7 + 0x01FD1B49 = 0x02567B10`.

sigtool resolves one hop per signature. Verify hop 1 with `scan --rel 1` (the match line ends in `rel -> rva 0x595fc0 ...`), then verify hop 2 with `sigtool scan game.exe "48 8B 05 ?? ?? ?? ?? C3" --all --rel 3` and pick the line whose `rva` is `0x595fc0`; its `rel -> rva` should be `0x2567b10`. That scan exits 1 because the getter pattern isn't unique, which is expected here. Implement both hops in runtime code (below) and note the chain in a comment in `signatures.toml`.

## Case 3: backward call

```text
RVA 0x1A2B50: E8 4B FE FF FF          call 0x1A29A0
```

rel32 = `0xFFFFFE4B` = `-0x1B5`. next = `0x1A2B55`, target = `0x1A2B55 - 0x1B5 = 0x1A29A0`. If you get something near `0x1001A29A0`, you treated rel32 as unsigned.

## Case 4: trailing immediate

```text
RVA 0x400100: 80 3D 1C 2F 00 01 00    cmp byte ptr [rip+0x01002F1C], 0
RVA 0x400107: 74 ..
```

N = 2, K = 1 (the `00` imm8). next = `0x400107`, target = `0x400107 + 0x01002F1C = 0x01403023`. `--rel 2:1` on the command line, `rel = "2:1"` in `signatures.toml` (a string, because of the colon).

```text
RVA 0x400200: C7 05 F8 3D 00 01 01 00 00 00    mov dword ptr [rip+0x01003DF8], 1
```

N = 2, K = 4. next = `0x40020A`, target = `0x40020A + 0x01003DF8 = 0x01404002`. `--rel 2:4`.

## Case 5: field offset

```text
F3 0F 10 81 3C 01 00 00    movss xmm0, dword ptr [rcx+0x13C]
0F 2F C1                   comiss xmm0, xmm1
```

`read = "4:u32"` gives `0x13C`. For the disp8 form (`F3 0F 10 41 7C` = `[rcx+0x7C]`) use `4:u8`, or `4:i8` if the offset could be negative (rare, but happens with adjusted `this` pointers in multiple inheritance).

The base register tells you which object it is. Follow it back (`mov rcx, [rbx+0x30]` earlier means rcx is a sub-object at `+0x30` of whatever rbx is). Record the whole chain, not just the last offset.

## Case 6: vtable index

```text
48 8B 01                   mov rax, [rcx]          ; vtable
FF 90 B8 01 00 00          call qword ptr [rax+0x1B8]
```

`--read 5:u32` gives `0x1B8`, index = `0x1B8 / 8 = 55`. Small indexes use disp8: `FF 50 40` = `call [rax+0x40]`, index 8, `--read 2:u8` relative to that instruction. Wildcard the displacement, since engine updates add virtual functions.

## Case 7: anchoring on a string reference

Strings rarely move relative to the code that uses them semantically, and log/assert strings are unique. Find the string in `.rdata`, list its xrefs, and sig the code around the `lea`:

```text
48 8D 15 ?? ?? ?? ??       lea rdx, [rip+"Failed to load map %s"]
48 8B CB                   mov rcx, rbx
E8 ?? ?? ?? ??             call ...
```

The string address itself is wildcarded. Check the anchor with `--rel 3`: it should resolve to the string's RVA. Then find the instruction you actually want (the global load or the field access) a few instructions away and put the `rel`/`read` offset on that.

## Runtime code (in-process mod, single-player)

Find the match once at startup, then resolve. This scanner handles full-byte wildcards only (a nibble wildcard like `4?` would be misparsed, so expand or avoid those in runtime patterns). Verify uniqueness offline with `sigtool scan --all`, because it returns the first match.

```cpp
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <string_view>
#include <vector>

// "48 8B 05 ?? ?? ?? ??" -> {0x48, 0x8B, 0x05, -1, -1, -1, -1}
static std::vector<int> ParsePattern(std::string_view p) {
    std::vector<int> out;
    for (size_t i = 0; i < p.size();) {
        if (p[i] == ' ') { ++i; continue; }
        if (p[i] == '?') {
            out.push_back(-1);
            i += (i + 1 < p.size() && p[i + 1] == '?') ? 2 : 1;
            continue;
        }
        out.push_back(std::stoi(std::string(p.substr(i, 2)), nullptr, 16));
        i += 2;
    }
    return out;
}

static uint8_t* FindPattern(HMODULE mod, std::string_view pattern) {
    auto* base = reinterpret_cast<uint8_t*>(mod);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    auto* sec = IMAGE_FIRST_SECTION(nt);
    const auto pat = ParsePattern(pattern);
    for (WORD s = 0; s < nt->FileHeader.NumberOfSections; ++s, ++sec) {
        if (std::memcmp(sec->Name, ".text\0\0\0", 8) != 0) continue;
        uint8_t* start = base + sec->VirtualAddress;
        const size_t size = sec->Misc.VirtualSize;
        for (size_t i = 0; i + pat.size() <= size; ++i) {
            size_t j = 0;
            while (j < pat.size() && (pat[j] < 0 || start[i + j] == pat[j])) ++j;
            if (j == pat.size()) return start + i;
        }
    }
    return nullptr;
}

// n = displacement offset in the match, k = bytes after the displacement.
static uint8_t* ResolveRel(uint8_t* match, int n, int k = 0) {
    int32_t disp;
    std::memcpy(&disp, match + n, sizeof disp);
    return match + n + 4 + k + disp;
}

// Usage:
//   auto* m = FindPattern(GetModuleHandleW(nullptr), "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01");
//   if (!m) { /* log "GWorld signature not found" and disable the feature, don't crash */ }
//   auto** gworld = reinterpret_cast<void**>(ResolveRel(m, 3));
//   auto* h = FindPattern(GetModuleHandleW(nullptr), "F3 0F 10 81 ?? ?? ?? ?? 0F 2F C1");
//   uint32_t healthOff = 0; if (h) std::memcpy(&healthOff, h + 4, 4);
```

For an external tool, read the module's `.text` once (`ReadProcessMemory` from `module base + VirtualAddress`), scan the buffer, and apply the same formula using `module base + RVA of match`. Fail loudly when a signature isn't found. A silent fallback to a stale hardcoded address reads garbage.
