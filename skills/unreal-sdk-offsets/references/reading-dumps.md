# Reading Dumper-7 and UE4SS output

## Dumper-7 output tree

```text
C:/Dumper-7/<GameVersion>-<GameName>/
  CppSDK/
    SDK.hpp
    SDK/Basic.hpp                 globals in namespace Offsets, core types (TArray, FString, FName)
    SDK/Basic.cpp
    SDK/CoreUObject_classes.hpp   UObject, UClass, UStruct, ...
    SDK/CoreUObject_structs.hpp   FVector, FRotator, FTransform, ...
    SDK/Engine_classes.hpp        UWorld, ULevel, UGameInstance, APlayerController, AActor, ...
    SDK/Engine_structs.hpp
    SDK/<Package>_classes.hpp     game modules, e.g. MyGame_classes.hpp
    SDK/<Package>_parameters.hpp  UFunction parameter structs
  Mappings/<GameVersion>-<GameName>.usmap
  IDAMappings/<GameVersion>-<GameName>.idmap
  Dumpspace/                      JSON for the Dumpspace web viewer
  GObjects-Dump.txt
```

### Globals

`Basic.hpp` contains:

```cpp
namespace Offsets
{
	constexpr int32 GObjects          = 0x0XXXXXXX;
	constexpr int32 AppendString      = 0x0XXXXXXX;
	constexpr int32 GNames            = 0x0XXXXXXX;
	constexpr int32 GWorld            = 0x0XXXXXXX;
	constexpr int32 ProcessEvent      = 0x0XXXXXXX;
	constexpr int32 ProcessEventIdx   = 0x000000XX;
	...
}
```

- All values are offsets from the main module base (RVAs). Absolute address = module base + value.
- `GObjects` points to `TUObjectArray` (`GUObjectArray.ObjObjects`).
- `GNames` is 0 when Dumper-7 used `AppendString` instead of locating the name table. In that case, find the table yourself. Its `FNamePool` is the `lea rcx/r8, [rip+X]` target inside `AppendString`'s lazy init on many builds, or the argument passed to the `FNamePool` constructor that references `ByteProperty`.
- `ProcessEventIdx` is a vtable index (slot), not an RVA.

### Member lines

```cpp
// Class Engine.GameInstance
// 0x00XX (0x0XXX - 0x00XX)
class UGameInstance : public UObject
{
public:
	uint8                          Pad_28[0x10];          // 0x0028(0x0010)(Fixing Size After Last Property [ Dumper-7 ])
	TArray<class ULocalPlayer*>    LocalPlayers;          // 0x0038(0x0010)(ZeroConstructor, NativeAccessSpecifierPrivate)
	...
};
```

- Read the first hex value in the trailing comment: `0xOFFSET(0xSIZE)(flags)`. The header comment gives the class size and where it starts (the parent's size).
- Inherited members are not repeated. `RootComponent` is in `AActor`, not `APawn`. Find the declaring class by searching for `Name;` in `Engine_classes.hpp`.
- `Pad_XXX` blocks are native or unknown data. Non-reflected fields such as `ULevel::Actors` live inside them.
- Bit fields are shown with a `BitIndex` comment. Read the byte at the offset and mask it.
- The example values above are illustrative only. Take offsets from your own dump.

### GObjects-Dump.txt

Each line lists an object's index, address and full name. Use it to:
- confirm a class exists (`Class Engine.PlayerController`, game subclasses like `BP_MyController_C`),
- find the default object (`Default__...`) or a live instance address to test hops.

## UE4SS output

All files are written to the UE4SS working directory (next to `UE4SS.dll`, or the game-specific subfolder).

| Key (default) | Output | Use |
|---|---|---|
| Ctrl+J | `UE4SS_ObjectDump.txt` | Every loaded object with addresses. Property lines include `[o: OFFSET]` |
| Ctrl+H | `CXXHeaderDump/` | C++ headers. Offsets and sizes are included when `[CXXHeaderGenerator] DumpOffsetsAndSizes = 1` |
| Ctrl+Numpad 9 | UHT-compatible headers | Rebuilding a mirror .uproject for modding |
| Ctrl+Numpad 6 | `.usmap` | Asset tools that need unversioned property mappings |
| Ctrl+Numpad 7 | actor dump | Level contents for UMAP recreation |

Keybinds are defined in `Mods/Keybinds/Scripts/main.lua`. The same actions are on the GUI Dumpers tab.

`[CXXHeaderGenerator] KeepMemoryLayout` is documented in the shipped settings file as not producing accurate layouts. Take offsets from the `[o: ...]` / offset comments, not from struct padding.

`[ObjectDumper] UseModuleOffsets = 1` prints function addresses as module offsets, which are easier to diff between runs.

### Live View workflow

1. Open the GUI (`GuiConsoleEnabled = 1`, toggle key `ToggleGuiKey`, default O) and go to the Live View tab.
2. Search for `PlayerController` and select the non-`Default__` instance.
3. Expand `AcknowledgedPawn`, then `RootComponent`, then `RelativeLocation`. Walk in game and confirm the values update. Add them to Watches to log changes.
4. Use the offsets shown for each property to fill `offsets.toml`. The Live View confirms you have the live instance and not the CDO.

## Converting to offsets.toml

1. Copy `GObjects`, `GNames` and `GWorld` from `Basic.hpp` into `[globals]`.
2. For each hop in the chain, record `Class.Member = offset` from its declaring class.
3. Record `engine` and `vector = "f32" | "f64"` from the dump (`FVector` in `CoreUObject_structs.hpp` shows `float X` or `double X`).
4. Commit the dump's GameVersion string next to the offsets. After an update, re-dump and diff the two `Engine_classes.hpp` files. Changed members show up as changed offset comments.

A quick extraction from Git Bash:

```bash
grep -nE '^\s.*\b(OwningGameInstance|PersistentLevel|GameState|LocalPlayers|PlayerController|AcknowledgedPawn|RootComponent|RelativeLocation|PlayerArray);' \
  CppSDK/SDK/Engine_classes.hpp
```

This prints each member with its `// 0xOFFSET(0xSIZE)` comment. Check the enclosing `class` line for the declaring type, since `PlayerController` also appears as a member name in other classes.
