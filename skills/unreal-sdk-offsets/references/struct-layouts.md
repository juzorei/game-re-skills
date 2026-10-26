# Unreal core struct layouts (x64)

These are the stock-engine layouts for shipping builds. Custom forks and some titles change them. When a dumper reports a different value, the dumper wins. Offsets are hex.

## Version cut-overs

| Change | Version |
|---|---|
| `TUObjectArray` becomes chunked (`FChunkedFixedUObjectArray`) | around 4.20/4.21 (verify in the dump: chunked arrays have `NumChunks` and a pointer-to-pointers at +0x00) |
| `TNameEntryArray` replaced by `FNamePool` | 4.23 |
| `USceneComponent::RelativeLocation` made private (offset unchanged) | 4.24 |
| `FProperty` (FField) replaces `UProperty` (UObject). Properties leave GObjects | 4.25 |
| Large World Coordinates: `FVector`/`FRotator`/`FQuat`/`FTransform` use double | 5.0 |

Since 4.25, properties are no longer UObjects. If you walk the reflection yourself, follow `UStruct::ChildProperties` (an FField chain), not `Children`. Dumpers handle both.

## GObjects

`FUObjectArray` (global `GUObjectArray`):

```text
+0x00 int32  ObjFirstGCIndex
+0x04 int32  ObjLastNonGCIndex
+0x08 int32  MaxObjectsNotConsideredByGC
+0x0C bool   OpenForDisregardForGC
+0x10 TUObjectArray ObjObjects        <- Dumper-7 "Offsets::GObjects" points here
...   (critical section, delete listeners, etc.)
```

Chunked `TUObjectArray` (4.21+, `FChunkedFixedUObjectArray`):

```text
+0x00 FUObjectItem** Objects          array of chunk pointers
+0x08 FUObjectItem*  PreAllocatedObjects
+0x10 int32 MaxElements
+0x14 int32 NumElements
+0x18 int32 MaxChunks
+0x1C int32 NumChunks
NumElementsPerChunk = 64 * 1024 (0x10000)
```

Flat `TUObjectArray` (4.11 to 4.20, `FFixedUObjectArray`):

```text
+0x00 FUObjectItem* Objects
+0x08 int32 MaxElements
+0x0C int32 NumElements
```

`FUObjectItem`:

```text
+0x00 UObjectBase* Object
+0x08 int32 Flags            (UE5.x splits/merges this with a refcount in some versions)
+0x0C int32 ClusterRootIndex
+0x10 int32 SerialNumber
size  0x18 in most builds. Some titles pad it to 0x20 or more. Measure it.
```

Dumper-7 ships alternative chunked layouts for specific games (for example a UE5.8 development layout and reordered layouts for a few titles). If counts look wrong, check `FChunkedFixedUObjectArrayLayouts` in its `ObjectArray.cpp`.

Lookup by index:

```c
FUObjectItem* chunk = Objects[i / 0x10000];
UObject* obj = *(UObject**)((u8*)chunk + (i % 0x10000) * ItemSize);
```

## UObjectBase / UObject

```text
+0x00 void**  VTable
+0x08 int32   ObjectFlags (EObjectFlags)
+0x0C int32   InternalIndex      index into GObjects
+0x10 UClass* ClassPrivate
+0x18 FName   NamePrivate        8 bytes in shipping
+0x20 UObject* OuterPrivate
size 0x28
```

To get a full name, decode `NamePrivate`, then follow `OuterPrivate` until it's null and join the names with `.`. The class name comes from `ClassPrivate->NamePrivate`.

## FName

```text
+0x00 int32 ComparisonIndex   (FNameEntryId)
+0x04 int32 Number            0 = no suffix, N = "_<N-1>"
```

Builds with `WITH_CASE_PRESERVING_NAME` (editor, some dev builds) add `DisplayIndex` and grow FName to 0xC. Shipping game builds normally don't.

## GNames before 4.23: TNameEntryArray

`GNames` is a pointer to the array: `TNameEntryArray* GNames`.

```text
TNameEntryArray (TStaticIndirectArrayThreadSafeRead<FNameEntry, 2*1024*1024, 16384>)
+0x000 FNameEntry** Chunks[128]
+0x400 int32 NumElements
+0x404 int32 NumChunks
ElementsPerChunk = 0x4000

FNameEntry (stock 4.x shipping, typical)
+0x00 int32 Index            bit 0 = bIsWide, index = Index >> 1
+0x08 FNameEntry* HashNext   (after 4 bytes of padding)
+0x10 char  AnsiName[] / wchar_t WideName[]   (null-terminated)
```

The string offset varies between versions and forks (0x10 is the common stock value, some builds differ). Verify it in the dump: Dumper-7 detects it, and entry 0 must read `None`.

```c
FNameEntry* e = (*GNames)->Chunks[id / 0x4000][id % 0x4000];
```

## GNames 4.23+: FNamePool

```text
FNamePool
+0x00 FNameEntryAllocator Entries
        +0x00 FRWLock Lock            (8 bytes on Windows)
        +0x08 uint32  CurrentBlock
        +0x0C uint32  CurrentByteCursor
        +0x10 uint8*  Blocks[8192]    FNameMaxBlocks = 1 << 13
...   hash shards follow
```

`FNameEntryHandle` from the ComparisonIndex:

```c
u32 block  = id >> 16;                 // FNameBlockOffsetBits = 16
u32 offset = id & 0xFFFF;
u8* entry  = Blocks[block] + offset * Stride;   // Stride = alignof(FNameEntry), normally 2
```

`FNameEntry`:

```text
+0x00 uint16 Header   bIsWide:1 | LowercaseProbeHash:5 | Len:10   (Len = Header >> 6)
+0x02 char / wchar_t Name[Len]          NOT null-terminated
```

Variants seen in the wild:
- Stride 4 with a 4-byte header (some builds carry an extra field). Dumper-7 sets the stride from the header size.
- Different length shift (Len not at bit 6). Dumper-7 computes the shift from the `ByteProperty` entry (length 12).
- A title that hashes or encrypts entries. Then names decode as garbage while indices still look sane. Fall back to calling the game's own `FName::ToString`/`AppendString` (`FName::Init` override in Dumper-7, `FName_ToString.lua` in UE4SS) in offline titles.

Sanity check: entry 0 must decode to `None`, and `/Script/CoreUObject` appears in block 0.

## Containers and strings

```text
TArray<T>    +0x00 T* Data  +0x08 int32 Num  +0x0C int32 Max      size 0x10
FString      TArray<TCHAR>, TCHAR = UTF-16 on Windows, Num includes '\0'
TMap/TSet    TSparseArray (Data, Num, Max, allocation-flag bit array, FirstFreeIndex, NumFreeIndices),
             then the hash (inline bucket + pointer) and HashSize: 0x50 total with the default allocators.
             Elements are {Value (TPair<Key, Value> for TMap), HashNextId, HashIndex}. Prefer the dumper's typed view.
FText        pointer to ITextData. Don't read it raw. Use FString fields instead.
```

## Math types

| Type | UE4 | UE5 (LWC) |
|---|---|---|
| FVector | 3 x f32, size 0xC | 3 x f64, size 0x18 |
| FVector2D | 2 x f32 | 2 x f64 |
| FRotator | Pitch, Yaw, Roll f32, size 0xC | f64, size 0x18 |
| FQuat | 4 x f32, size 0x10 | 4 x f64, size 0x20 |
| FTransform | Rotation(Quat) +0x0, Translation +0x10, Scale3D +0x20, size 0x30 | +0x0, +0x20, +0x40, size 0x60 |

`FVector3f`/`FRotator3f` keep float precision in UE5. Some rendering and network structs use them, so check the member type in the dump.

## UWorldProxy (GWorld)

```text
+0x00 UWorld* World
```

`GWorld` changes on map travel. Re-read it every frame or tick instead of caching the UWorld pointer.

## Native (non-reflected) fields you'll want

Dumpers don't name these because they aren't UPROPERTYs. They show up as `Pad_XXX` in Dumper-7 output.

- `ULevel::Actors` (`TArray<AActor*>`). To confirm it, find a TArray in ULevel whose entries are objects of AActor subclasses, and check that one entry is your pawn.
- `USceneComponent::ComponentToWorld` (`FTransform`, private native). Find a 0x30-byte (UE4) or 0x60-byte (UE5) block whose translation equals `RelativeLocation` for an unparented root, with Scale3D = (1,1,1).
