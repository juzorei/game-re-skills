# Engine containers

Layouts below are the common x64 ones. They change between engine versions and with custom engine builds, so confirm against the dump produced by `unreal-sdk-offsets` or `unity-il2cpp-offsets` for the exact game before relying on them. Every helper must bound counts and validate pointers.

## Unreal Engine

### TArray<T>

```text
+0x00  T*     Data
+0x08  int32  Num
+0x0C  int32  Max
```

Read the 16-byte header in one call, check `0 <= Num <= Max` and a sane upper bound, then read `Num * sizeof(T)` from `Data` in one call. For `TArray<UObject*>`, each element is a pointer to validate before use.

```python
data, num, cap = struct.unpack("<Qii", mem.read(addr, 16))
if not 0 <= num <= cap <= 1_000_000:
    raise ReadError(f"bad TArray num={num} max={cap}")
items = read_counted_array(mem, data, num, stride=8)
```

### FString

A `TArray<TCHAR>`; on Windows TCHAR is UTF-16. `Num` includes the terminating null.

```python
data, num, cap = struct.unpack("<Qii", mem.read(addr, 16))
text = read_utf16(mem, data, num)   # helper strips the trailing null
```

### FName

An index into the global name pool, not a string. `FName` is usually `{int32 ComparisonIndex; int32 Number}` (8 bytes; some builds add a display index).

- UE 4.23+ / UE5: `FNamePool`. Split `ComparisonIndex` into block = index >> 16 and offset = (index & 0xFFFF) * stride (stride is 2 in common builds). The entry starts with a 2-byte header holding a wide flag and the length; the exact bit layout varies, take it from `unreal-sdk-offsets`.
- Older UE4: `TNameEntryArray` (GNames) in chunks of 16384 entries.
- If `Number > 0`, the display name is `f"{name}_{Number - 1}"`.

Resolve `GNames`/`FNamePool` with a signature at startup like any global, and cache decoded names per index; names don't change during a session, and this removes most reads from object-list walks.

### UObject basics

Name, class and outer offsets (`NamePrivate`, `ClassPrivate`, `OuterPrivate`) depend on the version. Take them from the SDK dump and keep them in `offsets.toml`.

## Unity il2cpp

Every managed object starts with an `Il2CppObject` header: `klass` at `+0x00`, `monitor` at `+0x08`, fields start at `+0x10`.

### System.String

```text
+0x10  int32   length (UTF-16 code units)
+0x14  char16  chars[length]
```

```python
length = read_type(mem, s + 0x10, "i")
text = read_utf16(mem, s + 0x14, length)   # pass the address directly: s is a validated pointer
```

### Arrays (T[])

```text
+0x10  Il2CppArrayBounds*  bounds (null for one-dimensional arrays)
+0x18  size_t              max_length
+0x20  T                   items[...]
```

Elements are inline for value types (stride = sizeof(T)) and pointers for reference types (stride 8).

### List<T>

```text
+0x10  T[]    _items
+0x18  int32  _size
```

Read `_items` and `_size`, then read `_size` elements from `_items + 0x20`. `_size` can be smaller than `max_length`; never read past `_size`.

### Dictionary<K,V>

Entries array of `{int32 hashCode; int32 next; K key; V value}` with padding per K/V alignment, plus a count. Compute the stride from the dumped types; skip entries with `hashCode < 0` (free slots).

### Statics

Static fields live behind `klass->static_fields`; the `static_fields` offset inside `Il2CppClass` changes between Unity versions. Get it from `unity-il2cpp-offsets`.

### Mono (not il2cpp)

Mono builds use different headers and string layouts. Don't reuse il2cpp offsets on a Mono game.

## Sanity checks that catch most layout mistakes

- Strings decode to printable text of plausible length.
- Counts are non-negative and below a limit you choose per container.
- A UObject's class pointer points to an object whose own class is `Class`.
- An il2cpp object's `klass` pointer is stable across ticks.
