---
name: unity-il2cpp-offsets
description: Get from a Unity game build to class field offsets, method RVAs and static instance pointers. Covers telling Mono from IL2CPP, reading the global-metadata.dat version, dumping GameAssembly.dll or libil2cpp.so with Il2CppDumper or Cpp2IL, reading dump.cs, naming functions in IDA or Ghidra with script.json, IL2CPP memory layout (object header, Il2CppClass static_fields, System.String, arrays, List, Dictionary), and finding singletons like GameManager.Instance through TypeInfo globals with a sigtool-verified signature. Use it when the user says "dump il2cpp", "global-metadata.dat", "GameAssembly.dll", "libil2cpp.so", "Unity offsets", "Il2CppDumper", "Cpp2IL", "Il2CppInspector", "dump.cs", "find the TypeInfo", "static field offset", "Unity game update broke my offsets", "MelonLoader/BepInEx IL2CPP mod", or "frida-il2cpp-bridge". Also use it for Unity games where the user just wants to find a field or a singleton.
---

# Unity IL2CPP offsets

## Scope
Use this for single-player or offline games, modding, interoperability, and private servers the user runs. Don't help bypass or hide from anti-cheat (EAC, BattlEye, Vanguard, VAC) or cheat in online multiplayer; say so plainly and offer the offline part if there is one.

## What you produce

1. `offsets/<Class>.md` (or `.h` / `.json`, whatever the user's tool reads), holding the build identity, field offsets, method RVAs and the static-instance chain.
2. A `signatures.toml` entry that resolves the class's TypeInfo global, so the chain still works after an update.
3. A verification record: `sigtool check` output, plus a `sigtool chain` read against the running game.

Install sigtool if it's missing:

```bash
pip install game-re-sigtool
```

Detailed tables are in [references/memory-layout.md](references/memory-layout.md). Tool notes, flags and version support are in [references/tools.md](references/tools.md).

## 1. Identify the backend

Look in the game folder before you pick a tool. The backend decides the whole workflow.

| You see | Backend | What to do |
|---|---|---|
| `<Game>_Data/Managed/Assembly-CSharp.dll` with real IL (it opens in dnSpy or ILSpy with method bodies) | Mono | No dump needed. Read the classes in dnSpy or ILSpy. Mono field offsets are computed at runtime, so get them from Mono's API or a Mono-aware tool. This skill doesn't cover Mono. |
| `GameAssembly.dll` next to the exe, plus `<Game>_Data/il2cpp_data/Metadata/global-metadata.dat` | IL2CPP (Windows) | Continue here. |
| `lib/arm64-v8a/libil2cpp.so` in the APK, plus `assets/bin/Data/Managed/Metadata/global-metadata.dat` | IL2CPP (Android) | Continue here. `sigtool scan` treats a `.so` as raw bytes (whole file, file offsets only, no `--section`), so it can still count pattern matches. `--rel` assumes x86 rel32, which ARM64 doesn't use (globals are reached through `ADRP`+`ADD`/`LDR` pairs), so resolve ARM64 targets in the disassembler. |
| `GameAssembly.dylib` (macOS), or `UnityFramework` with `Data/Managed/Metadata` (iOS) | IL2CPP | Continue here. |

If `Managed/` exists in an IL2CPP build, it contains only stubs or nothing at all. Don't treat it as source.

## 2. Pin the Unity and metadata versions

Record both versions in the offsets file. The dumper's parser and the runtime struct layouts follow them.

- Unity version (Windows): read the file version of `UnityPlayer.dll`, using `(Get-Item UnityPlayer.dll).VersionInfo.FileVersion` in PowerShell. You can also find the version string near the start of `<Game>_Data/globalgamemanagers` with `strings`. On Android, search `libunity.so` for a `20xx.x.xf1` or `6000.x.xf1` pattern.
- Metadata version: global-metadata.dat starts with the magic `AF 1B B1 FA` (0xFAB11BAF little-endian), followed by an int32 version.

```bash
python -c "import struct,sys;m,v=struct.unpack('<Ii',open(sys.argv[1],'rb').read(8));print(hex(m),v)" global-metadata.dat
# 0xfab11baf 29
```

Map the two numbers: 24.x = 2017.1 to 2020.1, 27.x = 2020.2 to 2021.1, 29 or 29.1 = 2021.2 to early 2022.3, 31 = 2022.3.33+ and Unity 6 up to 6000.2, 35+ = 6000.3 and later. The header holds only the major number. Sub-versions such as 24.2 versus 24.4 or 29 versus 29.1 are inferred by the tools, and you can force them when a dump fails.

If the magic is wrong, the metadata is encrypted or obfuscated. Go to section 8 before you try any dumper.

## 3. Dump

Use Il2CppDumper by default. It's the only dumper that writes the offset-annotated `dump.cs` and the `script.json`/`il2cpp.h` pair that disassemblers read. Its latest release supports metadata up to v31. For v35 and newer, or when Il2CppDumper fails, use Il2CppInspectorRedux or Cpp2IL (see [references/tools.md](references/tools.md)).

```bash
# Il2CppDumper CLI: <executable-file> <global-metadata> <output-directory>
Il2CppDumper.exe GameAssembly.dll "Game_Data/il2cpp_data/Metadata/global-metadata.dat" dump_out
Il2CppDumper.exe libil2cpp.so global-metadata.dat dump_out          # Android
```

The output directory contains:
- `dump.cs`: every type with field offsets and method RVAs. This is your primary source.
- `script.json`: method names, string literals and metadata globals (TypeInfo, MethodInfo, FieldInfo), all keyed by RVA.
- `il2cpp.h`: C structs for every type (`<Type>_o` instance, `<Type>_c` class, `<Type>_StaticFields`), matched to the metadata version.
- `stringliteral.json` and `DummyDll/` (stub assemblies for dnSpy or ILSpy that carry `[FieldOffset]`/`[Address]` attributes).

Configure it with `config.json` next to the exe. Keep `DumpFieldOffset` and `DumpMethodOffset` on. Set `RequireAnyKey: false` for unattended runs. Use `ForceIl2CppVersion`/`ForceVersion` only when the binary parser misdetects the version.

Use Cpp2IL to cross-check, to handle very new Unity versions, or to diff two builds:

```bash
Cpp2IL --game-path "C:/Games/MyGame" --output-as diffable-cs --output-to cpp2il_out
Cpp2IL --list-output-formats      # check what this build actually supports
```

`diffable-cs` writes `//Field offset: 0x..` and hides method addresses so that diffs stay clean. Use `dll_default` (alias `dummydll`) for stub DLLs. Cpp2IL doesn't write IDA or Ghidra naming scripts.

## 4. Read dump.cs

```csharp
// Namespace: Game.Core
public class GameManager : MonoBehaviour // TypeDefIndex: 4821
{
	// Fields
	private static GameManager <Instance>k__BackingField; // 0x0
	public PlayerController player; // 0x18
	public float timeScale; // 0x20
	private List<Enemy> enemies; // 0x28
	[ThreadStatic] private static int counter; // 0xFFFFFFFF
	public const int MaxEnemies = 64;

	// Methods
	// RVA: 0x5A1B30 Offset: 0x5A0730 VA: 0x1805A1B30
	public static GameManager get_Instance() { }
	// RVA: 0x5A1C80 Offset: 0x5A0880 VA: 0x1805A1C80
	private void Update() { }
}
```

- An instance field's `// 0x..` value is its offset from the object pointer. It already counts the 0x10 header (klass and monitor) and inherited fields. `MonoBehaviour` subclasses start at 0x18, because `UnityEngine.Object.m_CachedPtr` sits at 0x10.
- A static field's offset is relative to the class's `static_fields` block, not to an object.
- Offsets inside a struct (value type) are given for the unboxed data, starting at 0x0. When a struct is embedded in a class, add the struct field's offset to the class field's offset.
- `0xFFFFFFFF` marks a thread-static field. It lives in per-thread storage, so don't chain to it. `const` fields have no storage.
- In method lines, `RVA` is relative to the module base (use it with `GameAssembly.dll+RVA` and sigtool). `Offset` is the file offset. `VA` uses the binary's preferred image base, so ignore it at runtime. `RVA: -1` means the method has no compiled body, usually because it's abstract or a generic that was never instantiated.
- Generic instantiations list their RVAs under `/* GenericInstMethod :` blocks. `List<T>` over a reference type shares one `__Canon` body.
- Properties compile to `get_X`/`set_X` methods. An auto-property's data lives in `<X>k__BackingField`.

Search `dump.cs` for the class name or for an obvious field type. Then read the base class chain upward, because inherited fields take up the low offsets.

## 5. Name the binary in IDA or Ghidra

Load `GameAssembly.dll` (or `libil2cpp.so`), let auto-analysis finish, then run a script from the Il2CppDumper release folder:

- IDA: `ida_with_struct_py3.py`. It asks for `script.json`, then `il2cpp.h`, and applies names and struct types. Use `ida_py3.py` for names only. On old IDA without Python 3, use `ida.py` or `ida_with_struct.py`.
- Ghidra: `ghidra_with_struct.py`, or `ghidra.py` for names only. If Ghidra's script runner rejects it, check the Il2CppDumper README for the current Ghidra/Python setup. For large headers, `il2cpp_header_to_ghidra.py` preprocesses `il2cpp.h` for Ghidra's C parser.
- Binary Ninja: use the `Il2CppBinaryNinja` plugin. Il2CppInspectorRedux also writes scripts for IDA, Ghidra and Binary Ninja.

After the script runs, functions are named `Class$$Method`. Data globals are named `Class_TypeInfo` (an `Il2CppClass*`, typed `Class_c*`), `Method$Class.Method()`, `Field$...`, and `StringLiteral_N`. The `Class_TypeInfo` global is the anchor you need for static fields. Other tools name it differently (Il2CppInspector writes `GameManager__TypeInfo`, and some tutorials say `Class$`), but it's the same pointer. Search script.json's `ScriptMetadata` for `GameManager_TypeInfo` to get its RVA.

## 6. Find the static instance via TypeInfo

A C# static (`GameManager.Instance`, `<Instance>k__BackingField`) lives in the `static_fields` block of the class's `Il2CppClass`. The chain is:

```text
[GameAssembly.dll + TypeInfoRVA]      -> Il2CppClass*       (global set by IL2CPP metadata init)
[Il2CppClass + 0xB8]                  -> static_fields      (64-bit, metadata v24.1 through 31; check older or newer builds)
[static_fields + <static offset>]     -> GameManager object (offset from dump.cs, here 0x0)
[object + 0x20]                       -> timeScale (f32)
```

Take the `0xB8` from your own `il2cpp.h` (`struct Il2CppClass { Il2CppClass_1 _1; void* static_fields; ...}`) or from [references/memory-layout.md](references/memory-layout.md). Don't assume it.

The TypeInfo RVA changes on every build, so sign the code that reads it. Open `GameManager$$get_Instance`, or better, a larger and more distinctive caller such as `GameManager$$Update`, and find the read:

```asm
48 8B 05 ?? ?? ?? ??     mov rax, [rip+GameManager_TypeInfo]
48 8B 80 B8 00 00 00     mov rax, [rax+0B8h]        ; static_fields
48 8B 00                 mov rax, [rax]             ; <Instance>k__BackingField
```

Generate and check the pattern:

```bash
sigtool suggest GameAssembly.dll 0x5A1C93 --rva      # RVA of the mov rax,[rip+..] instruction
sigtool scan GameAssembly.dll "48 8B 05 ?? ?? ?? ?? 48 8B 80 B8 00 00 00 48 8B 00 48 85 C0" --rel 3
```

The match line ends in `rel -> rva 0x... (va 0x..., offset ...)`. That `rva` must equal the `GameManager_TypeInfo` RVA from script.json (script.json addresses are RVAs too). Tiny getters often compile to the same bytes in every class, so if `scan` reports more than one match, extend the pattern into neighbouring unique code (a call or a field offset you know) until it matches exactly once. Many methods start with a lazy-init check (`cmp byte ptr [rip+x], 0` plus a call into the runtime's metadata or class-init helper) before the read. You can include those instructions as long as their displacements are wildcarded.

The TypeInfo global stays null until the class is first used, and `static_fields` is valid only after the class constructor runs. Read the chain only once the game is in a state where the class has been touched.

For strings, arrays, `List<T>`, `Dictionary<K,V>` and Unity native objects, follow the layouts in [references/memory-layout.md](references/memory-layout.md). The essentials on 64-bit: `System.String` has its length at 0x10 and UTF-16 chars at 0x14. An array has `max_length` at 0x18 and its data at 0x20. `List<T>` has `_items` at 0x10 and `_size` at 0x18.

## 7. Runtime alternatives

- Mods: MelonLoader or BepInEx 6 (IL2CPP builds) generate interop assemblies with Il2CppInterop, so C# mods can call `GameManager.Instance` directly with no offsets at all. Prefer this when the user wants a mod rather than an external reader.
- Research: frida-il2cpp-bridge walks the live runtime (domain, assemblies, classes, fields with offsets, methods with addresses) without needing global-metadata.dat, and can dump, trace and hook. It's useful to confirm an offset, or when the metadata on disk is unusable. Check its README for the current CLI and API.
- Inside the process, the exported IL2CPP API (`il2cpp_domain_get`, `il2cpp_class_from_name`, `il2cpp_class_get_field_from_name`, `il2cpp_field_get_offset`, `il2cpp_field_static_get_value`) returns the same numbers at runtime. Some games rename or strip these exports.

## 8. Encrypted metadata and obfuscated names

- Bad magic or garbage strings in global-metadata.dat means the file is encrypted or packed, and the game decrypts it at load time. The usual research approach is to take the decrypted metadata from memory after the game has loaded it, or to read the live runtime with frida-il2cpp-bridge. Il2CppDumper's `ForceDump` handles binaries dumped from memory, and Il2CppInspector can write out the decrypted metadata it has loaded. Describe this at the conceptual level only. If the protection is part of an anti-cheat or DRM product, stop: that's out of scope.
- Version mismatch: games ship modified metadata headers or non-standard versions. If a dumper reports an unsupported version, cross-check the Unity version from section 2, try another dumper, then try `ForceIl2CppVersion`. Don't trust offsets from a dump that only half succeeded.
- Obfuscated names (BeeByte/Beebyte, Mfuscator and similar) turn `GameManager` into `ABCDEFGHIJK`. Identify classes by structure instead: field types and counts, string literals used in their methods (`stringliteral.json`, `StringLiteral_N` xrefs), Unity message methods (`Update`, `Awake`) whose names can't be obfuscated, and base classes. Record both the obfuscated name and your label in the offsets file. Obfuscated names can change on every build, so key your signatures to code, not names.

## 9. Deliverable

Write `offsets/GameManager.md` (adapt the format to the user's tool):

```text
Build: MyGame 1.4.2, Unity 2022.3.21f1, metadata v29, GameAssembly.dll size 0x4A31200 (PE timestamp 0x6650A1B2)
Class: Game.Core.GameManager : MonoBehaviour   (TypeDefIndex 4821)
TypeInfo RVA:   0x2F4E8A0  (GameManager_TypeInfo; resolved by signature GameManager_TypeInfo)
static_fields:  Il2CppClass+0xB8
  0x0   GameManager <Instance>k__BackingField
Instance fields:
  0x18  PlayerController player
  0x20  float timeScale
  0x28  List<Enemy> enemies          -> _items 0x10, _size 0x18; element i at _items+0x20+i*8
Methods:
  get_Instance  RVA 0x5A1B30
  Update        RVA 0x5A1C80
Chain: [[[GameAssembly.dll+TypeInfo]+0xB8]+0x0]+0x20 = timeScale (f32)
```

Add the signature to `signatures.toml`. The bytes below are illustrative. Use the pattern that `sigtool suggest` gave you for your build.

```toml
[GameManager_TypeInfo]
# GameManager$$Update: mov rax,[rip+GameManager_TypeInfo]; mov rax,[rax+0B8h]; mov rax,[rax]
pattern = "48 8B 05 ?? ?? ?? ?? 48 8B 80 B8 00 00 00 48 8B 00 48 85 C0 74 ?? F3 0F 10 40 20"
rel = 3

[GameManager_timeScale]
# same function: movss xmm0,[rax+20h]; read the disp8 field offset
pattern = "48 8B 05 ?? ?? ?? ?? 48 8B 80 B8 00 00 00 48 8B 00 48 85 C0 74 ?? F3 0F 10 40 ??"
read = "26:u8"
```

## 10. Verify before claiming success

1. `sigtool check signatures.toml GameAssembly.dll` must print `ok` and `matches 1` for every entry and end with `N/N passed` (exit code 0). The `rel -> rva` of `GameManager_TypeInfo` must equal script.json's address, and `GameManager_timeScale` must show `read = 0x20 (32)`. If you have an older build, run check against both files too. If you only have a raw memory dump of GameAssembly.dll (encrypted on disk), add `--mapped`.
2. With the game running and the class initialised (in-game, not at the main menu if it's created later):

```bash
sigtool chain --process MyGame.exe --module GameAssembly.dll --base 0x2F4E8A0 --offsets 0xB8,0x0,0x20 --type f32
```

   sigtool prints one `[address] -> pointer  + offset = next` line per hop, then `address` and `value`. Every hop should be a plausible heap pointer, and the final value should match what the game shows. A `chain broken: hop 0: null pointer` message (exit code 1) usually means the class isn't initialised yet. Change it in-game and read it again.
3. Sanity-check the object: `[[object]+0x10]` (klass to `Il2CppClass.name`) is a pointer to the ASCII string `GameManager`. This confirms you landed on the right type.
4. Cross-check one offset with a second source (Cpp2IL `diffable-cs`, Il2CppInspector, or frida-il2cpp-bridge's `field.offset`).

## Pitfalls

- `VA` from dump.cs with a live module base. Use the RVA.
- Static offsets read from the object instead of `static_fields`, or instance offsets used on `static_fields`.
- 32-bit builds (ARMv7, old x86): the header is 0x8, a String's length sits at 0x8 and its chars at 0xC, an array's `max_length` at 0xC and its data at 0x10, and the Il2CppClass offsets differ. `sigtool chain` detects a 32-bit (WOW64) process and reads 4-byte pointers (`--ptr-size 4` forces it). Re-derive everything from `il2cpp.h`.
- Value-type fields (`Vector3 pos; // 0x30`) are stored inline: `pos.y` is at 0x34, not behind a pointer.
- Holding a native pointer (`m_CachedPtr`) after a scene change. Unity destroys native objects while the managed wrapper survives with `m_CachedPtr == 0`.
- After an update: re-dump, run `sigtool check`, and diff Cpp2IL `diffable-cs` output between builds to see which field offsets moved.

## Practice

`sigtool practice` writes a two-version, UE-like synthetic "game" (5 KB, no game installed) with a global, a field-offset store instruction and a README of exercises: xref the global, sign the code that reads it, pull the field offset with `scan --read`, and regression-check both versions. It models the same static-global-plus-field-offset pattern this skill lands on (e.g. `GameManager_TypeInfo`), so it's a quick way to try the steps offline; for real IL2CPP targets, re-dump.
