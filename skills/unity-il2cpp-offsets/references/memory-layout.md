# IL2CPP memory layout (64-bit)

All offsets assume a 64-bit build (8-byte pointers). For 32-bit builds, re-derive them from the `il2cpp.h` the dumper writes. When this file and your `il2cpp.h` disagree, trust `il2cpp.h`: it's generated for the exact metadata version.

## Object header (Il2CppObject)

| Offset | Field | Notes |
|---|---|---|
| 0x00 | `Il2CppClass* klass` | The type of the object. `[klass+0x10]` is `const char* name`. |
| 0x08 | `MonitorData* monitor` | Lock state, usually 0. |
| 0x10 | first instance field | dump.cs offsets already include this header. |

Value types (structs) have no header when they're stored inline or in arrays. A boxed struct has one, so its data starts at 0x10.

## Il2CppClass

These offsets come from Il2CppDumper's generated headers. `byval_arg`/`this_arg` became embedded `Il2CppType` structs (0x10 each) in 24.1. `interopData` first appears in the v23-24.0 header, and 24.1 added `klass`.

| Field | v22 | v23-24.0 | v24.1 to v31 |
|---|---|---|---|
| `image` | 0x00 | 0x00 | 0x00 |
| `gc_desc` | 0x08 | 0x08 | 0x08 |
| `name` (const char*) | 0x10 | 0x10 | 0x10 |
| `namespaze` (const char*) | 0x18 | 0x18 | 0x18 |
| `byval_arg` | 0x20 (ptr) | 0x20 (ptr) | 0x20 (embedded) |
| `element_class` | 0x30 | 0x30 | 0x40 |
| `declaringType` | 0x40 | 0x40 | 0x50 |
| `parent` | 0x48 | 0x48 | 0x58 |
| `fields` (FieldInfo*) | 0x60 | 0x68 | 0x80 |
| `methods` (MethodInfo**) | 0x78 | 0x80 | 0x98 |
| `static_fields` | 0x98 | 0xA0 | 0xB8 |
| `rgctx_data` | 0xA0 | 0xA8 | 0xC0 |

- v24.1 to v31 covers Unity 2018.3 through Unity 6 up to 6000.2. That is almost every game you'll meet, so 0xB8 is the common answer. Confirm it anyway.
- Metadata v35 and later (Unity 6000.3+) are too new for this table. Get the layout from Il2CppInspectorRedux or Cpp2IL output, or from disassembly: find `mov reg, [reg+XX]` right after a `Class_TypeInfo` load in any static getter. `XX` is `static_fields`.
- After `rgctx_data`, the `Il2CppClass_2` part (`typeHierarchy`, cctor state, `instance_size`, counts, flags) shifts between versions. Read it from `il2cpp.h` rather than hard-coding it.
- The `vtable` is an array of `{methodPtr, MethodInfo*}` pairs at the end of the class.

## MethodInfo

| Field | up to v27.x | v29+ |
|---|---|---|
| `methodPointer` | 0x00 | 0x00 |
| `virtualMethodPointer` | none | 0x08 |
| `invoker_method` | 0x08 | 0x10 |
| `name` | 0x10 | 0x18 |
| `klass` / `declaring_type` | 0x18 | 0x20 |

`Method$...` globals in script.json point to MethodInfo* slots. Dereference twice and you get the code address.

## Static fields

- `[Il2CppClass+static_fields]` points to a heap block laid out like a struct, with dump.cs static offsets (`// 0x0`, `// 0x8`, ...). It's allocated when the class initialises, so it stays null before then.
- Thread-static fields (`// 0xFFFFFFFF` in dump.cs) aren't in this block. They live in per-thread storage reached through `thread_static_fields_offset`. Avoid them in external chains.
- Literals (`const`) aren't stored anywhere. Enum constants are `const`.

## System.String (Il2CppString)

| Offset | Field |
|---|---|
| 0x00 | klass |
| 0x08 | monitor |
| 0x10 | `int32 length`, counted in UTF-16 code units |
| 0x14 | `char16 chars[length]` (UTF-16LE, followed by a null terminator) |

Read `length` first, cap it (for example at 4096) to guard against garbage, then read `length*2` bytes from 0x14.

## Arrays (Il2CppArray, T[])

| Offset | Field |
|---|---|
| 0x00 | klass |
| 0x08 | monitor |
| 0x10 | `Il2CppArrayBounds* bounds`. It's null for single-dimensional `T[]`. |
| 0x18 | `il2cpp_array_size_t max_length`: pointer-sized (u64) on modern 64-bit builds. Il2CppDumper's v22 header types it as int32, so check `il2cpp.h` for very old games. |
| 0x20 | element data |

- Reference-type elements are pointers: element `i` is at `+0x20 + i*8`.
- Value-type elements are stored inline at `+0x20 + i*sizeof(T)` (`int` 4, `float` 4, `Vector3` 12, `Vector2Int` 8, `bool` 1).
- Multi-dimensional arrays (`T[,]`) have non-null `bounds`, which point to `{size_t length; int32 lower_bound;}` per dimension. The data is row-major from 0x20.

## List<T>

| Offset | Field |
|---|---|
| 0x10 | `T[] _items`, the backing array (capacity is `_items.max_length`) |
| 0x18 | `int32 _size`, the logical count. Iterate only to `_size`. |
| 0x1C | `int32 _version` |
| 0x20 | `object _syncRoot` (only in some class-library versions; verify in the dump) |

Element `i` of `List<RefType>` is at `[[list+0x10]+0x20+i*8]`. These offsets are the same for every `T`, because the fields are a pointer and two ints. Confirm them by searching dump.cs for `class List<T>` in `mscorlib`.

## Dictionary<TKey, TValue> (Unity's mscorlib, .NET Framework 4.x layout)

| Offset | Field |
|---|---|
| 0x10 | `int[] buckets` |
| 0x18 | `Entry[] entries` |
| 0x20 | `int count` |
| 0x24 | `int version` |
| 0x28 | `int freeList` |
| 0x2C | `int freeCount` |
| 0x30 | `IEqualityComparer<TKey> comparer` |
| 0x38 | `KeyCollection keys` |
| 0x40 | `ValueCollection values` |

Check dump.cs for `class Dictionary<TKey, TValue>`. Field names and order can differ between Unity versions, so trust the dump over this table. Newer Unity versions ship a corefx-derived class library whose `Dictionary` uses `_buckets`, `_entries`, `_count`, `_freeList`, `_freeCount`, `_version`, `_comparer`, ... in that order, so everything after `_count` moves.

`Entry` is a struct, stored inline in `entries` starting at `+0x20`:

```text
struct Entry { int hashCode; int next; TKey key; TValue value; }
```

| TKey, TValue | key | value | sizeof(Entry) |
|---|---|---|---|
| ref, ref (`string, Foo`) | 0x08 | 0x10 | 0x18 |
| int, ref | 0x08 | 0x10 | 0x18 (value aligned to 8) |
| int, int | 0x08 | 0x0C | 0x10 |
| int, float | 0x08 | 0x0C | 0x10 |
| ulong, ref | 0x08 | 0x10 | 0x18 |

Iterate `i` in `[0, count)` and skip free slots. In the .NET Framework layout they have `hashCode < 0`; corefx-derived versions mark them through `next` instead (`next < -1`), so check which one your dump.cs shows. Entry `i` is at `entries + 0x20 + i*sizeof(Entry)`. For other value types, compute alignment by the usual C rules, or read the `Entry` struct from `il2cpp.h`.

## HashSet<T>, Queue<T>, Stack<T>

These follow the same pattern: a backing array plus int counters. Take their offsets from dump.cs (`System.Core` or `mscorlib`/`System.Collections`) instead of guessing.

## Unity native objects

- `UnityEngine.Object` has one managed field: `IntPtr m_CachedPtr` at 0x10. Every `MonoBehaviour`, `Component`, `GameObject`, `Transform`, `ScriptableObject` inherits it, which is why user fields start at 0x18.
- `m_CachedPtr` points to the native C++ object inside UnityPlayer.dll (or `libunity.so`). Native layouts aren't in global-metadata.dat and they change with the Unity version.
- A Transform's world position isn't a plain field. It's computed through the native transform hierarchy. For external tools, prefer a managed field the game itself keeps (for example `Vector3 targetPos` on a component), or call `get_position` in-process (mod or Frida). If you must read native Transform data, reverse it per Unity version in UnityPlayer.dll and say so in the offsets file.
- `m_CachedPtr == 0` means the native object was destroyed (a "fake null" Unity object). Treat it as null.
