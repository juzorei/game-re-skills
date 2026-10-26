# x86-64 encoding cheatsheet for signatures

Enough encoding to read a byte pattern, know which bytes are volatile, and compute instruction lengths for resolving. When unsure, disassemble the bytes (IDA, Ghidra, x64dbg, or any online assembler/disassembler) rather than trusting memory.

## Instruction layout

```text
[legacy prefixes] [REX] [opcode 1-3 bytes] [ModRM] [SIB] [disp 0/1/4] [imm 0/1/2/4/8]
```

- Legacy prefixes: `66` operand size (16-bit, or SSE "pd/integer" forms), `F2`/`F3` (SSE scalar forms, `rep`), `65` GS segment, `64` FS segment, `F0` lock.
- REX comes after legacy prefixes and immediately before the opcode. `F3 48 0F ...` is valid, `48 F3 0F ...` is not (the REX gets ignored).
- Length to the next instruction = everything above, including any immediate after the displacement. That's why `--rel N:K` exists.

## REX prefix (40-4F)

```text
0100 W R X B
W = 64-bit operand size
R = extends ModRM.reg  (r8-r15 / xmm8-xmm15 as the reg operand)
X = extends SIB.index
B = extends ModRM.rm, SIB.base, or the register in opcode+reg forms
```

| Byte | Meaning | Example |
| --- | --- | --- |
| `48` | W | `48 8B 05 d32` = `mov rax, [rip+d32]` |
| `4C` | W+R | `4C 8B 05 d32` = `mov r8, [rip+d32]` |
| `49` | W+B | `49 8B 00` = `mov rax, [r8]` |
| `4D` | W+R+B | `4D 8B 00` = `mov r8, [r8]` |
| `41` | B | `41 B0 01` = `mov r8b, 1`; `41 57` = `push r15` |
| `44` | R | `F3 44 0F 10 05 d32` = `movss xmm8, [rip+d32]` |
| `40` | none | `40 53` = `push rbx` (MSVC uses it so a function's first instruction is 2 bytes, for hot patching) |

Register allocation changes often flip only R/B bits, which is why `4? 8B ...` sometimes survives a rebuild. `4?` also matches `40`-`47` (no W), so mask the nibble only if fixed bytes nearby keep it unique.

## ModRM byte

```text
mod(2) reg(3) rm(3)
mod 00: [rm]            (rm=100 -> SIB follows, rm=101 -> RIP-relative disp32)
mod 01: [rm + disp8]    (disp8 is sign-extended)
mod 10: [rm + disp32]
mod 11: register operand, no memory
```

Register numbers (reg or rm, low 3 bits; REX adds 8): 0 rax/xmm0, 1 rcx, 2 rdx, 3 rbx, 4 rsp, 5 rbp, 6 rsi, 7 rdi.

### RIP-relative: mod=00, rm=101

`(modrm & 0xC7) == 0x05`. The eight possible ModRM bytes are `05 0D 15 1D 25 2D 35 3D` for reg = 0..7 (rax, rcx, rdx, rbx, rsp, rbp, rsi, rdi; with REX.R: r8..r15). For opcode-extension instructions (`FF /2`, `80 /7`) the reg field is the extension, not a register: `FF 15` is `call [rip+d32]`, `80 3D` is `cmp byte [rip+d32], imm8`.

A nibble mask like `8B ?5` does not mean "any register, RIP-relative". It also matches `45`/`85` (`[rbp+disp8]`/`[rbp+disp32]`) and `C5` and up (register forms), which have different lengths. Prefer listing the anchor explicitly, or accept the overmatch only when the rest of the pattern pins it down.

### Special cases that change the length

- `[rsp+x]` and `[r12+x]` need a SIB byte: `48 8B 44 24 08` = `mov rax, [rsp+8]`, `49 8B 04 24` = `mov rax, [r12]`.
- `[rbp]` and `[r13]` can't be encoded with mod=00 (that slot is RIP-relative), so they use disp8 = 0: `48 8B 45 00` = `mov rax, [rbp]`, `49 8B 45 00` = `mov rax, [r13]`.
- disp8 covers -0x80..0x7F. `[rcx+0x7C]` is `41`-style (disp8), `[rcx+0x13C]` is `81`-style (disp32). A field moving past 0x7F changes both ModRM and length.

### SIB byte

```text
scale(2) index(3) base(3)    scale: 00=1 01=2 10=4 11=8, index=100 -> none
```

`48 8B 04 C8` = `mov rax, [rax+rcx*8]` (ModRM `04`, SIB `C8`: scale 8, index rcx, base rax).

`65 48 8B 04 25 58 00 00 00` = `mov rax, gs:[0x58]` (TLS array). ModRM `04` + SIB `25` (no index, base=101 with mod=00) means an absolute disp32, not RIP-relative. Don't resolve it with `--rel`.

## Opcodes you'll see in anchors

### Loads, stores, address computation (RIP-relative forms)

| Bytes | Instruction | Disp at | Ends after disp |
| --- | --- | --- | --- |
| `48 8B 05 d32` | `mov rax, [rip+d]` | +3 | 0 |
| `48 8B 0D d32` | `mov rcx, [rip+d]` | +3 | 0 |
| `48 8B 15 d32` | `mov rdx, [rip+d]` | +3 | 0 |
| `48 8B 1D d32` | `mov rbx, [rip+d]` | +3 | 0 |
| `48 8B 35 d32` / `3D` | `mov rsi` / `mov rdi, [rip+d]` | +3 | 0 |
| `4C 8B 05 d32` .. `4C 8B 3D d32` | `mov r8` .. `mov r15, [rip+d]` | +3 | 0 |
| `8B 05 d32` | `mov eax, [rip+d]` (32-bit load) | +2 | 0 |
| `48 89 05 d32` | `mov [rip+d], rax` | +3 | 0 |
| `48 8D 05 d32` | `lea rax, [rip+d]` | +3 | 0 |
| `48 8D 0D d32` | `lea rcx, [rip+d]` (first arg: strings, globals) | +3 | 0 |
| `48 8D 15 d32` | `lea rdx, [rip+d]` (second arg) | +3 | 0 |
| `4C 8D 05 d32` | `lea r8, [rip+d]` (third arg) | +3 | 0 |
| `48 3B 05 d32` | `cmp rax, [rip+d]` | +3 | 0 |
| `48 39 05 d32` | `cmp [rip+d], rax` | +3 | 0 |
| `F3 0F 10 05 d32` | `movss xmm0, [rip+d]` (float constant or global) | +4 | 0 |
| `F2 0F 10 05 d32` | `movsd xmm0, [rip+d]` | +4 | 0 |
| `F3 0F 11 05 d32` | `movss [rip+d], xmm0` | +4 | 0 |
| `F3 44 0F 10 05 d32` | `movss xmm8, [rip+d]` | +5 | 0 |
| `0F 28 05 d32` | `movaps xmm0, [rip+d]` | +3 | 0 |

### With trailing immediates (use `--rel N:K`)

| Bytes | Instruction | N | K |
| --- | --- | --- | --- |
| `80 3D d32 ib` | `cmp byte [rip+d], imm8` | 2 | 1 |
| `83 3D d32 ib` | `cmp dword [rip+d], imm8` | 2 | 1 |
| `48 83 3D d32 ib` | `cmp qword [rip+d], imm8` | 3 | 1 |
| `81 3D d32 id` | `cmp dword [rip+d], imm32` | 2 | 4 |
| `C6 05 d32 ib` | `mov byte [rip+d], imm8` | 2 | 1 |
| `C7 05 d32 id` | `mov dword [rip+d], imm32` | 2 | 4 |
| `48 C7 05 d32 id` | `mov qword [rip+d], imm32` (sign-extended) | 3 | 4 |
| `66 83 3D d32 ib` | `cmp word [rip+d], imm8` | 3 | 1 |

### Control flow

| Bytes | Instruction | Notes |
| --- | --- | --- |
| `E8 rel32` | `call target` | target = addr + 5 + rel32. Always wildcard rel32 |
| `E9 rel32` | `jmp target` | also tail calls and hook trampolines |
| `EB rel8` | `jmp short` | wildcard rel8 |
| `70`-`7F rel8` | short jcc | `74` je/jz, `75` jne/jnz, `72` jb, `73` jae, `76` jbe, `77` ja, `7C` jl, `7D` jge, `7E` jle, `7F` jg, `78` js, `79` jns |
| `0F 80`-`0F 8F rel32` | near jcc | same condition order: `0F 84` je, `0F 85` jne, `0F 8E` jle |
| `FF 15 d32` | `call [rip+d]` | import call through the IAT |
| `FF 25 d32` | `jmp [rip+d]` | import thunk; `FF 25 00 00 00 00` + 8-byte address is a common absolute hook |
| `FF D0` | `call rax` | `FF /2`, mod=11 |
| `FF 50 ib` | `call [rax+disp8]` | vtable call, index = disp8 / 8 |
| `FF 90 d32` | `call [rax+disp32]` | vtable call with index >= 16 |
| `FF 60 ib` | `jmp [rax+disp8]` | vtable tail call |
| `C3` | `ret` | |
| `CC` | `int3` | MSVC padding between functions |

A short jcc can become a near jcc (`74 xx` to `0F 84 xx xx xx xx`) when the code between grows past 127 bytes. That changes the pattern length, so avoid spanning long jumps.

### Field access (struct displacement)

| Bytes | Instruction | Field offset at |
| --- | --- | --- |
| `48 8B 41 ib` | `mov rax, [rcx+disp8]` | +3, u8 |
| `48 8B 81 id` | `mov rax, [rcx+disp32]` | +3, u32 |
| `8B 81 id` | `mov eax, [rcx+disp32]` | +2, u32 |
| `48 89 81 id` | `mov [rcx+disp32], rax` | +3, u32 |
| `F3 0F 10 41 ib` | `movss xmm0, [rcx+disp8]` | +4, u8 |
| `F3 0F 10 81 id` | `movss xmm0, [rcx+disp32]` | +4, u32 |
| `F3 0F 11 81 id` | `movss [rcx+disp32], xmm0` | +4, u32 |
| `F2 0F 10 81 id` | `movsd xmm0, [rcx+disp32]` | +4, u32 |
| `0F B6 81 id` | `movzx eax, byte [rcx+disp32]` | +3, u32 |
| `80 B9 id ib` | `cmp byte [rcx+disp32], imm8` | +2, u32 |
| `C6 81 id ib` | `mov byte [rcx+disp32], imm8` | +2, u32 |

The base register is in ModRM.rm (and REX.B), so `[rbx+...]` is `83`/`43` instead of `81`/`41`, `[rdi+...]` is `87`/`47`, and so on.

### Other common bytes

| Bytes | Instruction |
| --- | --- |
| `48 85 C0` | `test rax, rax` |
| `48 85 DB` | `test rbx, rbx` |
| `84 C0` | `test al, al` |
| `33 C9` / `31 C9` | `xor ecx, ecx` (MSVC tends to emit `33`, GCC/Clang `31`) |
| `B9 id` | `mov ecx, imm32` |
| `48 B8 iq` | `mov rax, imm64` (10 bytes) |
| `0F 2F C1` | `comiss xmm0, xmm1` |
| `0F 2E C1` | `ucomiss xmm0, xmm1` |
| `F3 0F 59 ..` / `58` / `5C` | `mulss` / `addss` / `subss` |
| `48 83 EC ib` | `sub rsp, imm8` (prologue) |
| `48 89 5C 24 08` | `mov [rsp+8], rbx` (prologue) |
| `90`, `66 90`, `0F 1F 00`, `0F 1F 40 00`, `0F 1F 44 00 00` | 1-5 byte NOPs (alignment) |

## What to wildcard, by byte class

- Always: rel8/rel32 of jumps and calls, RIP-relative disp32, IAT disp32, stack offsets.
- Usually: struct displacements, vtable call displacements, immediates that look like sizes, counts, enum values or hashes.
- Sometimes: REX R/B nibble and ModRM reg/rm nibble when register allocation varies. Check the overmatch first.
- Never: opcodes and ModRM mod bits. If those differ between builds, the code changed and you need a new anchor.

## 32-bit (x86) games

There's no RIP-relative addressing. Globals are absolute addresses that include the image base and are fixed up by relocations:

| Bytes | Instruction |
| --- | --- |
| `A1 addr32` | `mov eax, [addr]` |
| `8B 0D addr32` | `mov ecx, [addr]` (mod=00 rm=101 is absolute disp32 in 32-bit mode) |
| `A3 addr32` | `mov [addr], eax` |
| `FF 15 addr32` | `call [addr]` (IAT) |
| `E8 rel32` | `call` (still relative) |

Read the address with `--read N:u32`, then subtract the image base (`sigtool pe` handles PE32 and prints it, typically `0x400000`) for an RVA. Don't use `--rel` on these; only `E8`/`E9`/jcc targets are still relative. Wildcard the address bytes too, since they change with every relocation.
