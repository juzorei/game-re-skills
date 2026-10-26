# Diffing struct layouts between builds

Read this when you need to know which field offsets changed after a patch, and why.

## Dump both builds the same way

Use the same dumper version and the same settings for both builds. Otherwise the formatting differences drown out the real changes.

- **Unreal (Dumper-7)**: inject the x64-Release DLL into the running game. The SDK is written to `Settings::SDKGenerationPath` (default `C:\Dumper-7`, can be overridden in `Dumper-7.ini`). Rename the output folder per build. Field offsets and sizes are in comments in the generated headers.
- **Unreal (UE4SS)**: use its C++ header generator and object dumper. See the UE4SS docs for the current keybinds and config.
- **Unity IL2CPP (Il2CppDumper)**: `Il2CppDumper GameAssembly.dll global-metadata.dat out-1.5.0/`. Turn on `DumpFieldOffset` in `config.json` so that `dump.cs` has `// 0x1A8` after each field. Use Cpp2IL for Unity versions newer than Il2CppDumper supports.

If the old build is gone and you never dumped it, dump the new build and compare its layout against the offsets in the user's old offsets file, matching by field name.

## Two-pass diff

Pass 1, structure only. Strip the offset comments so that only real member changes are left:

```bash
nooffsets() { sed -E 's#//.*0x[0-9A-Fa-f]+.*$##; s#[[:space:]]+$##' "$1"; }
diff -u <(nooffsets sdk-1.4.2/Game_classes.hpp) <(nooffsets sdk-1.5.0/Game_classes.hpp)
```

On Windows without bash, `git diff --no-index` with `-I'0x[0-9A-Fa-f]+'` hides lines that differ only by an offset:

```bash
git diff --no-index -I'0x[0-9A-Fa-f]+' sdk-1.4.2/ sdk-1.5.0/
```

Pass 2, offsets. Diff with the offsets left in, but only for the classes your tool reads:

```bash
git diff --no-index --word-diff sdk-1.4.2/Game_classes.hpp sdk-1.5.0/Game_classes.hpp | grep -A40 "class APlayerCharacter"
```

For `dump.cs`, do the same thing per class. Search for `class PlayerStats` in both files and diff those blocks.

## How fields shift

Basic rule: an inserted member of size S, placed before field F, shifts F and every field after it by S rounded up to the alignment of the next member that follows the insertion. Anything already padded may absorb the shift.

Example (x64, MSVC layout):

```text
1.4.2                                  1.5.0
0x198 int32  Ammo                      0x198 int32  Ammo
0x19C (pad 4)                          0x19C (pad 4)
0x1A0 AWeapon* CurrentWeapon           0x1A0 bool   bIsGuarding      <- new
0x1A8 float  Health                    0x1A1 (pad 7)
0x1AC float  MaxHealth                 0x1A8 AWeapon* CurrentWeapon
                                       0x1B0 float  Health
                                       0x1B4 float  MaxHealth
```

A 1-byte insert pushed everything after it down by 8, because the pointer after it needs 8-byte alignment.

Other patterns:

- **Insertion into padding**: if the old layout had a gap that's big enough, the new member fills it and nothing moves. Always check the dump.
- **Base class change**: every field in every derived class moves by the same delta. A uniform delta across a whole class means the change is in a parent class. Unreal adds members to `AActor`, `APawn` and `ACharacter` often.
- **Removal**: fields move down by the removed size (alignment rules still apply). Removal can also break a signature that `read` a field which no longer exists. Check that the field still exists before trusting a `read`.
- **Type change**: an `int32` that became `int64`, or a `TArray` that became a `TMap`, changes size and alignment. Readers that cast the field also need fixing.
- **Reordering**: there's no single delta. Map each field by name.
- **Vtable changes**: a new virtual method doesn't change data offsets, but it shifts vtable indices after it. Fix any hooks that use an index.

## Without a dump

On custom engines without reflection, take offsets from the code that touches the fields:

1. Find an instruction that reads the field, for example `F3 0F 10 81 B0 01 00 00` (`movss xmm0, [rcx+0x1B0]`).
2. Sign it with `read = "4:u32"` (or `"4:u8"` for a disp8 form like `F3 0F 10 41 ??`: prefix, two opcode bytes and ModRM come first, so the displacement is at +4 in both forms).
3. A displacement can switch from disp8 to disp32 when it crosses 0x7F. That changes the instruction encoding, so keep both forms in mind.

## Writing the result

Record each changed field as old → new, along with the cause, in the report. Put the new values in a per-build offsets file:

```toml
[build]
id = "14388102"
version = "1.5.0"
sha256 = "<hash of Game-Win64-Shipping.exe>"

[APlayerCharacter]
CurrentWeapon = 0x1A8
Health        = 0x1B0
MaxHealth     = 0x1B4
```
