---
name: unreal-sdk-offsets
description: Get from an Unreal Engine 4/5 game executable to working offsets for an external reader or mod. Identifies the engine version, finds GObjects (FUObjectArray), GNames (TNameEntryArray or FNamePool) and GWorld, dumps the SDK with Dumper-7 or UE4SS, walks GWorld -> GameInstance -> LocalPlayers -> PlayerController -> Pawn -> RootComponent -> location, and writes an offsets file plus signatures.toml verified with sigtool. Use whenever the user says "find GWorld", "GObjects GNames", "dump UE4 SDK", "UE5 offsets", "Dumper-7", "UE4SS", "Unreal offsets broke after update", "read player position in an Unreal game", "FNamePool", "decode FName", or names a `<Game>-Win64-Shipping.exe`.
---

# Unreal SDK offsets

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

Unreal games ship with full reflection data (every UClass, UProperty and its offset lives in memory). You don't reverse structs by hand. You find three globals, let a dumper read the reflection, and copy the offsets you need. The work that remains is picking the right binary, choosing a dumper, signing the globals so they survive updates, and verifying the chain.

Install the verifier first:

```bash
pip install game-re-sigtool
```

## 1. Pick the right binary and identify the engine version

1. Find the real executable. `Game.exe` in the install root is usually a small launcher stub. The engine lives in `<Game>/Binaries/Win64/<Game>-Win64-Shipping.exe`, so run all scans against that file. `-Test` or no suffix means a non-shipping build, which may keep extra fields (see references).
2. Read the version:
   - Run `sigtool pe <Game>-Win64-Shipping.exe` and check the section table (it prints rva, vsize, offset, rawsize and an `x` flag for executable sections). A tiny `.text`, odd section names, or high-entropy sections suggest a packer (see Caveats).
   - Check Explorer > Properties > Details. Many games leave the engine version in FileVersion/ProductVersion (for example `4.26.2.0`), but some replace it with the game's own version.
   - Search for the build branch string, stored as UTF-16: `++UE4+Release-4.26`, `++UE5+Release-5.3`. Use `strings -el <exe> | grep -m3 '++UE'` where binutils is installed. Otherwise scan for the UTF-16 bytes of `++UE`: `sigtool scan <exe> "2B 00 2B 00 55 00 45 00" --section .rdata --all` (or `--section '*'` if it isn't in `.rdata`), then open the reported file offset in a hex viewer to read the rest of the string. sigtool prints offsets, not the bytes. Engine forks show custom branches like `++Studio+Main`. Treat those as "custom engine" and expect moved fields.
   - Once a dumper runs, take its reported version as authoritative. Dumper-7 names its output folder `<GameVersion>-<GameName>`, and UE4SS prints the detected version to its console/log.
3. Write down `UE major.minor` because it decides GNames layout (4.23 cut-over), GObjects layout (4.21 cut-over) and float vs double vectors (UE5).

## 2. Know the three globals

Full layouts per version are in [references/struct-layouts.md](references/struct-layouts.md). Remember these points:

- **GObjects** (`GUObjectArray`, type `FUObjectArray`). Its `ObjObjects` member is a `TUObjectArray`. From about 4.21 (verify in the dump) it's chunked: `Objects` (FUObjectItem**) at +0x00, `PreAllocatedObjects` +0x08, `MaxElements` +0x10, `NumElements` +0x14, `MaxChunks` +0x18, `NumChunks` +0x1C, with 64K (0x10000) items per chunk. Item `i` is `Objects[i / 0x10000][i % 0x10000]`, and each `FUObjectItem` starts with `UObject* Object`. The item is usually 0x18 bytes, but measure the stride and don't assume it. Before 4.21 it's a flat array: `Objects` +0x0, `Max` +0x8, `Num` +0xC.
- **GNames**.
  - Before 4.23: `TNameEntryArray`, a pointer to an array of chunk pointers with 0x4000 entries per chunk. Entry `i` is `Chunks[i / 0x4000][i % 0x4000]`, which points to an `FNameEntry`.
  - 4.23 and later: `FNamePool`, whose allocator has `Blocks[]` at +0x10. The ComparisonIndex is an `FNameEntryHandle`: `Block = id >> 16`, `Offset = id & 0xFFFF`, `entry = Blocks[Block] + Offset * stride`. The stride is 2 (alignof(FNameEntry)) in normal builds and 4 in some builds. Dumper-7 measures it from the header size. The 2-byte header packs `bIsWide:1, LowercaseProbeHash:5, Len:10`, and some games shift these bits.
- **GWorld** (`UWorldProxy`). Its first member is `UWorld*`, so `[module + GWorld]` is the current world. It changes on every map load, so re-read it each time and never cache it.

Core value types:

| Type | Layout (x64) |
|---|---|
| `TArray<T>` | `T* Data` +0x0, `int32 Num` +0x8, `int32 Max` +0xC (0x10 total) |
| `FString` | `TArray<wchar_t>`. Num counts the null terminator, UTF-16 |
| `FName` | `int32 ComparisonIndex` +0x0, `int32 Number` +0x4. The string is `Name` when Number is 0, otherwise `Name_<Number-1>` |
| `UObject` | vtable +0x0, `ObjectFlags` +0x8, `InternalIndex` +0xC, `ClassPrivate` +0x10, `NamePrivate` +0x18, `OuterPrivate` +0x20 (0x28 total) |
| `FVector` | UE4: 3 x float (0xC). UE5: 3 x double (0x18), from Large World Coordinates |
| `FRotator` | UE4: float Pitch, Yaw, Roll. UE5: doubles |

Large World Coordinates matter more than they look. On UE5, read location as `f64`, and expect every struct containing a vector to grow and shift. Don't port UE4 offsets to a UE5 build of the same game.

## 3. Dump the SDK

Pick one tool. Both inject into the running game, so only use them on offline/single-player titles. Never use them against an anti-cheat-protected process (see Scope).

**Dumper-7** (github.com/Encryqed/Dumper-7, supports all UE4 and UE5):
- Build the DLL as x64-Release and inject it once the game reaches the main menu.
- Output goes to `C:/Dumper-7/<GameVersion>-<GameName>/` by default. To change that, put a `Dumper-7.ini` with a `[Settings]` section next to the game exe or in `C:/Dumper-7`. Useful keys are `SDKGenerationPath`, `SleepTimeout`, `DumpKey`, `ShouldAutoUnload`.
- The output folder contains `CppSDK/`, `Mappings/` (`.usmap`), `IDAMappings/`, `Dumpspace/`, and `GObjects-Dump.txt`.
- Globals live in `CppSDK/SDK/Basic.hpp` under `namespace Offsets`: `GObjects`, `AppendString`, `GNames`, `GWorld`, `ProcessEvent`, `ProcessEventIdx`. These are offsets from the module base (RVAs). `Offsets::GObjects` points at the `TUObjectArray` (ObjObjects), which is usually `GUObjectArray + 0x10`.
- Class members are in `CppSDK/SDK/<Package>_classes.hpp` (`Engine_classes.hpp` holds UWorld, APlayerController, AActor and friends). Every member line ends with `// 0xOFFSET(0xSIZE)(flags)`.
- If auto-detection fails, override it in `Generator::InitEngineCore()`. Use `ObjectArray::Init(...)`, `FName::Init(...)`, or `InitObjectArrayDecryption(lambda)` for XOR'd object pointers, as the README describes.

**UE4SS** (github.com/UE4SS-RE/RE-UE4SS, targets UE 4.7 to 5.x):
- Extract the release into `<Game>/Binaries/Win64/`. It loads through a `dwmapi.dll` proxy.
- Enable `GuiConsoleEnabled = 1` in `UE4SS-settings.ini`. The GUI has Console, Live View, Watches and Dumpers tabs. Use Live View to search a live object (for example your `PlayerController`) and confirm property values change as you play.
- Default keybinds come from `Mods/Keybinds/Scripts/main.lua`. Ctrl+J writes `UE4SS_ObjectDump.txt`, where property lines carry `[o: OFFSET]`. Ctrl+H writes C++ headers to `CXXHeaderDump/`, which include offsets and sizes when `[CXXHeaderGenerator] DumpOffsetsAndSizes = 1`. Ctrl+Numpad 6 writes a `.usmap`.
- If UE4SS can't find a global on a custom engine, supply your own AOB through `UE4SS_Signatures/GUObjectArray.lua`, `FName_ToString.lua` and similar files. Each defines `Register()` (returns the pattern) and `OnMatchFound(MatchAddress)`. See docs.ue4ss.com, "Fixing compatibility problems".

Choose Dumper-7 when you want global RVAs and a compilable SDK. Choose UE4SS when you want live inspection, Lua mods, or the dumper fails. Reading either dump is covered in [references/reading-dumps.md](references/reading-dumps.md).

Don't rely on remembered "magic strings" to locate globals. The string anchors verified in Dumper-7's own finder are `ByteProperty` (referenced in the `FNamePool` constructor, for GNames) and `Accessed None` (near ProcessEvent). Dumper-7 finds GObjects by scanning `.data` for a plausible array header, and GWorld by searching memory for a pointer to the live UWorld. Check any other string with `sigtool scan <exe> "<hex bytes>" --section .rdata` before building on it.

## 4. Collect the chain offsets

Open `Engine_classes.hpp` (or the UE4SS dump) and record these. Names are stable across UE4/5. Offsets are not.

| Hop | Field | Type |
|---|---|---|
| UWorld | `PersistentLevel` | `ULevel*` |
| UWorld | `GameState` | `AGameStateBase*` |
| UWorld | `OwningGameInstance` | `UGameInstance*` |
| UGameInstance | `LocalPlayers` | `TArray<ULocalPlayer*>` |
| UPlayer (base of ULocalPlayer) | `PlayerController` | `APlayerController*` |
| APlayerController | `AcknowledgedPawn` | `APawn*` |
| AActor | `RootComponent` | `USceneComponent*` |
| USceneComponent | `RelativeLocation` | `FVector` |
| AGameStateBase | `PlayerArray` | `TArray<APlayerState*>` |
| APawn | `PlayerState` | `APlayerState*` |

Notes:
- `ULevel::Actors` (the `TArray<AActor*>` of the level) is not a UPROPERTY. Dumpers show it as padding, so find it by looking for a TArray inside ULevel whose entries are AActor objects. It sits near the start of ULevel's native fields (commonly 0x98 in UE4, larger in UE5). Verify it rather than guess.
- `RelativeLocation` equals world location only when the root component has no attach parent, which holds for player pawns in most games. For attached actors, read `ComponentToWorld`, which is non-reflected and found the same way as Actors.
- In 4.24+, `RelativeLocation` became private with accessors. The offset is still in the dump.

## 5. Write the deliverable

Write `offsets.toml`, keeping the version and the dump source so the next update is easy to diff:

```toml
[meta]
game = "ExampleGame"
exe = "ExampleGame-Win64-Shipping.exe"
engine = "4.27"
source = "Dumper-7 CppSDK, 2026-10-26"
vector = "f32"          # "f64" on UE5

[globals]               # RVAs from Basic.hpp, re-resolved by signatures.toml
GObjects = 0x0
GNames   = 0x0
GWorld   = 0x0

[UWorld]
PersistentLevel    = 0x0
GameState          = 0x0
OwningGameInstance = 0x0
[UGameInstance]
LocalPlayers = 0x0
[UPlayer]
PlayerController = 0x0
[APlayerController]
AcknowledgedPawn = 0x0
[AActor]
RootComponent = 0x0
[USceneComponent]
RelativeLocation = 0x0
```

Fill every `0x0` from your dump. Never ship a value you didn't read from this build.

Sign the globals so they survive patches. For each global:
1. In x64dbg, IDA or Ghidra, list the references to the global's address (base + RVA). Pick an instruction that loads it RIP-relatively, for example `48 8B 1D ?? ?? ?? ??` (`mov rbx, [rip+X]`) or `48 8D 0D ?? ?? ?? ??` (`lea rcx, [rip+X]`). Prefer a reference in a small, rarely-changed function.
2. Run `sigtool suggest <exe> <instruction RVA> --rva`. It wildcards the rel32 for you.
3. Run `sigtool scan <exe> "<pattern>" --rel 3` and confirm exactly one match resolves to the RVA from Basic.hpp. Use `--rel N:K` when an immediate follows the displacement. If the reference points at `GUObjectArray` while Dumper-7 reported `ObjObjects`, write the 0x10 difference into a comment.

```toml
# signatures.toml
[GWorld]
pattern = "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01"   # replace with suggest output
rel = 3

[GObjects]
pattern = "48 8B 05 ?? ?? ?? ?? 48 8B 0C C8"   # placeholder, extend until unique; resolves to GUObjectArray+0x10
rel = 3

[GNames]
pattern = "48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ?? C6 05"       # lea rcx, NamePool
rel = 3
```

All three patterns are placeholders: replace them with your `suggest` output (sigtool rejects anything that isn't a hex byte or `??`, so don't leave `...` in a pattern). Then run `sigtool check signatures.toml <exe> [<old exe> ...]`. Every line must read `ok   <Name>  matches 1  rva ...  rel -> rva <global RVA> (...)`, and exit code 0 means every pattern matched exactly once in each build. Field offsets can be signed too, with `read = "N:u32"` on an instruction like `mov rax, [rcx+disp32]`. Re-dumping after an update is usually faster and safer.

## 6. Verify: GWorld to local player position

With the game running offline and the player standing still, walk the chain read-only:

```bash
sigtool chain --process ExampleGame-Win64-Shipping.exe --module ExampleGame-Win64-Shipping.exe \
  --base <GWorld RVA> \
  --offsets <OwningGameInstance>,<LocalPlayers>,0x0,<PlayerController>,<AcknowledgedPawn>,<RootComponent>,<RelativeLocation> \
  --type f32        # f64 on UE5
```

The `0x0` hop dereferences `LocalPlayers.Data` to get `LocalPlayers[0]`. sigtool prints a `start` line, one `[address] -> pointer  + offset = next` line per hop, then `address` and `value`; a null hop stops it with `chain broken: hop N: null pointer` and exit code 1. Check that:
- Every intermediate hop is a plausible heap pointer (non-zero, 8-byte aligned).
- The value is X. Read +4/+8 (UE4) or +8/+16 (UE5) for Y and Z. The values change as you walk and look like world units (centimetres, often hundreds to tens of thousands).
- Jumping changes Z.
- After a map load, the chain still resolves because you re-read GWorld.

If a hop returns 0, the pawn may not exist yet (main menu) or the field moved. Confirm the object in UE4SS Live View, or decode `UObject::NamePrivate` with GNames at each hop to check you're on a `World`, `GameInstance`, `LocalPlayer`, `PlayerController` and so on.

Report the offsets file, signatures.toml, the `sigtool check` result, and the chain output. To turn them into a standalone reader, continue with the `external-memory-reader` skill.

## Caveats

- **Packed/protected shipping builds.** If the `.text` on disk is encrypted, `sigtool check` on the exe finds nothing. Analyse a memory dump of the running offline game instead (`sigtool check signatures.toml dump.bin --mapped` for a raw module image; a rebuilt PE dump needs no flag), and say that patterns were checked against the dump. Don't remove, patch or redistribute DRM.
- **Custom engine forks** move fields, add members to UObject, reorder `TUObjectArray`, or change the FNameEntry header shift. Trust the dumper's detected values over the tables here, and never hard-code version tables without checking.
- **Encrypted FNames / obfuscated GObjects** exist mostly in online titles with anti-cheat, which are out of scope. For an offline title, use Dumper-7's `InitObjectArrayDecryption` or the `FName::Init` override (AppendString/ToString instead of GNames).
- **No PDB ships**, so don't expect symbol names. Reflection replaces them for UPROPERTY data. Native-only fields (Actors, ComponentToWorld) need manual confirmation.
- **Non-shipping builds** (Development/Test/DebugGame) can carry extra members such as STATS data and editor-only FName fields. Re-dump instead of reusing shipping offsets.
- For pattern craft and update resilience, follow the `aob-signatures` skill.

## Practice

`sigtool practice` writes a two-version, UE-like synthetic "game" (GWorld global, a store instruction with a `movss [rcx+0x1A8]`-style field offset, a rel32 caller, 5 KB, no game installed) plus an exercise README, so you can dry-run this skill's GWorld workflow — xref the global, sign the reader, extract the field offset, `check` across both versions — offline before doing it on the real Shipping exe.
