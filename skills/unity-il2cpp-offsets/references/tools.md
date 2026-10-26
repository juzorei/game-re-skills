# IL2CPP tools: status, inputs, outputs

These notes were checked against each project's README and releases in October 2026. Tools change fast, so check the README before you rely on a flag. If a listed flag doesn't exist, run the tool's `--help`.

## Metadata version to Unity version

| Metadata | Unity |
|---|---|
| 16 to 23 | 5.3 to 5.6 |
| 24 | 2017.1 to 2018.2 |
| 24.1 | 2018.3 to 2018.4 |
| 24.2 to 24.5 | 2019.x, 2020.1 |
| 27, 27.1 | 2020.2 to 2020.3 |
| 27.2 | 2021.1 |
| 29, 29.1 | 2021.2 to 2022.3 (before 2022.3.33) |
| 31 | 2022.3.33+ and 6000.0 to 6000.2 |
| 35, 38, 39 | 6000.3 alpha and beta |
| 104 to 110 | 6000.5 to 6000.7 alphas |

The table comes from Il2CppInspectorRedux's README. For changes between versions, see the nneonneo/Il2CppVersions repo. The header stores only the integer version, and the tools detect sub-versions heuristically.

## Il2CppDumper (Perfare/Il2CppDumper)

- Status: the latest release is v6.7.46. Metadata v31 support arrived in v6.7.45. The README advertises Unity 5.3 to 2022.2, but v31 support extends it in practice to 2022.3 and early Unity 6. Expect failures on v35+.
- Inputs: PE (`GameAssembly.dll`), ELF/ELF64 (`libil2cpp.so`), Mach-O, NSO, WASM, plus `global-metadata.dat`.
- CLI: `Il2CppDumper.exe <executable-file> <global-metadata> <output-directory>`. Running it without arguments opens file pickers.
- Outputs: `dump.cs`, `script.json`, `il2cpp.h`, `stringliteral.json`, `DummyDll/`.
- `config.json` keys: `DumpMethod`, `DumpField`, `DumpProperty`, `DumpAttribute`, `DumpFieldOffset`, `DumpMethodOffset`, `DumpTypeDefIndex`, `GenerateDummyDll`, `GenerateStruct`, `DummyDllAddToken`, `RequireAnyKey`, `ForceIl2CppVersion`, `ForceVersion`, `ForceDump`, `NoRedirectedPointer`.
  - `ForceIl2CppVersion` + `ForceVersion` override only the binary parser version. The metadata parser is unaffected.
  - `ForceDump` treats the input as a memory dump. `NoRedirectedPointer` covers memory dumps whose pointers weren't redirected.
- Disassembler scripts shipped in the release: `ida.py`, `ida_py3.py`, `ida_with_struct.py`, `ida_with_struct_py3.py`, `ghidra.py`, `ghidra_with_struct.py`, `ghidra_wasm.py`, `hopper-py3.py`, `il2cpp_header_to_ghidra.py`, `il2cpp_header_to_binja.py`, and the `Il2CppBinaryNinja` plugin.
- `script.json` keys: `ScriptMethod` (`Address`, `Name`, `Signature`), `ScriptString` (`Address`, `Value`), `ScriptMetadata` (`Address`, `Name`, `Signature`: names like `Foo_TypeInfo`, `Foo_var`, `Field$...`), `ScriptMetadataMethod` (`Address`, `Name` = `Method$...`, `MethodAddress`), and `Addresses` (function boundaries). Every address is an RVA.
- The author doesn't support deobfuscating global-metadata.dat. For Android protections, the README points to dumping libil2cpp.so from memory, or to Zygisk-Il2CppDumper on rooted devices.

## Cpp2IL (SamboyCoding/Cpp2IL)

- Status: active. Releases are `2022.1.0-pre-release.N` builds (pre-release 21 is the latest at the time of writing), and CI builds come from the `development` branch. Recent releases add metadata v31 fixes and v35/38/39/104-106 support up to Unity 6000.5 alphas. It runs on .NET 9 and ships builds for Windows, Linux and macOS (x64 and arm64).
- Inputs: a game directory, or a single APK (since 2021.4.0). It auto-detects the binary, metadata and Unity version.
- Flags: `--game-path` (required), `--exe-name`, `--output-as <format>`, `--output-to <dir>` (default `cpp2il_out`), `--use-processor <id>` (repeatable), `--processor-config key=value`, `--list-output-formats`, `--list-processors`, `--wasm-framework-file`, `--verbose`, `--low-memory-mode`. Old flags like `--analysis-level` and `--skip-analysis` are gone.
- Output formats (one per run): `dummydll`/`dll_default`, `dll_empty`, `dll_throw_null`, `dll_il_recovery`, `diffable-cs`, `isil`, `wasm_name_section`, plus plugin formats (control-flow graph `.dot` files, PDB).
- `diffable-cs` prints `//Field offset: 0x..` per field and hides addresses, so it's ideal for diffing two builds. It doesn't write IDA or Ghidra naming scripts, so use Il2CppDumper or Il2CppInspectorRedux for those.
- Processors include attribute injection, call analysis and native method detection. Run `--list-processors` to see the exact IDs.

## Il2CppInspector and Il2CppInspectorRedux

- `djkaty/Il2CppInspector`: development has halted. It supports metadata up to 27.1 (Unity 2020.3), with partial 27.2. Use it only for old games.
- `LukeFZ/Il2CppInspectorRedux`: the maintained fork (README "2025.1"). It supports metadata 16 through 31 and the 35-110 Unity 6 alphas.
- Outputs: C# stubs, .NET shim DLLs, C++ scaffolding (an injectable DLL project with typed structs and function pointers), JSON address map, disassembler scripts (IDA 7.6+, Ghidra 11.3+ through PyGhidra, Binary Ninja), and decrypted metadata/binary written back to disk.
- Original CLI: `Il2CppInspector.exe -i GameAssembly.dll -m global-metadata.dat`, `--select-outputs` with `-c` (C#), `-p` (py script) `-t IDA|Ghidra`, `-h` (C++), `-o` (JSON), `-d` (DLLs), `--metadata-out`, `--binary-out`, `--image-base` (ELF memory dumps). Redux keeps a similar interface, but its README warns that the docs still describe the original. Check `--help`.
- It names TypeInfo globals `Foo__TypeInfo`. The C++ scaffolding is handy when the user wants an in-process mod in C++.

## Runtime tools

- frida-il2cpp-bridge (`vfsfitvnm/frida-il2cpp-bridge`, npm package `frida-il2cpp-bridge`, MIT): dumps, traces and hooks IL2CPP at runtime without global-metadata.dat. It supports Unity 5.3.0 to 6000.3.x and is tested on Android and Linux. The CLI wrapper is `npm exec frida-il2cpp-bridge -- -f <package> dump --out-dir dumps`. For the scripting API (`Il2Cpp.perform`, `Il2Cpp.domain.assembly(...).image.class(...)`, `field.offset`, method hooking), see the project wiki.
- MelonLoader and BepInEx 6 (IL2CPP builds) use Il2CppInterop (`BepInEx/Il2CppInterop`) to generate managed proxy assemblies from the game. Mods then access game types by name, so offsets are only needed for raw pointer work. Check each loader's compatibility notes for the game's Unity version.
- The exported IL2CPP C API (`il2cpp_domain_get`, `il2cpp_domain_get_assemblies`, `il2cpp_assembly_get_image`, `il2cpp_class_from_name`, `il2cpp_class_get_field_from_name`, `il2cpp_field_get_offset`, `il2cpp_field_static_get_value`, `il2cpp_string_new`) works from injected code. Protected games sometimes rename these exports.

## Mono quick reference (not this skill)

If the game ships `Managed/Assembly-CSharp.dll` with real IL, open it in dnSpyEx or ILSpy. Field offsets come from the Mono runtime (`mono_field_get_offset`), and tools such as Cheat Engine's Mono features can resolve them. There's no global-metadata.dat and no GameAssembly.dll.
