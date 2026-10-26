# Value scanning in depth

Read this when the basic exact or unknown-value scans in SKILL.md step 1 don't find the value, or find too many results.

## Scan settings that matter

- `Memory Scan Options`: the default range covers user-mode memory. Leave `Writable` checked. Set `Executable` and `CopyOnWrite` to "don't care" (the grey state), not checked, otherwise you skip heap memory.
- `Fast Scan` with `Alignment` 4 is right for `4 Bytes` and `Float`. Use 8 for `8 Bytes`/`Double` only if you're sure; an unaligned field is rare but possible in packed structs, so turn `Fast Scan` off if a value you're sure about isn't found.
- `Pause the game while scanning` keeps fast-changing values (timers, position while falling) consistent between the snapshot and the comparison.
- Float rounding: `Rounded (default)`, `Rounded (extreme)` and `Truncated` control how an exact float scan matches. A HUD showing `87` may be `87.4999`. Use `Value between` 86.5 to 87.5, or `Truncated`.
- `Undo Scan` reverts one Next Scan when you scanned with the wrong value. Use it instead of restarting.

## Choosing the value type

| Clue | Likely storage |
|---|---|
| Whole numbers that can reach millions (gold, XP) | `4 Bytes` (int32), sometimes `8 Bytes` |
| Health shown as a bar or with decimals | `Float` |
| Unreal Engine 5 positions and some timers | `Double` (UE5 uses double-precision vectors) |
| Unity, UE4, most engines' positions | `Float` |
| Tiny counters (lives, level 1 to 99) | `4 Bytes`, sometimes `2 Bytes`/`Byte` |
| Shown as 87, internally 8700 or 0.87 | scaled: scan `87*100`, `87*10`, or as float 0.87 |

`All (Byte to Double)` with `Exact value` is a decent first probe when you have no idea. It shows the type of each hit in the results list.

## Scaled and derived values

Games often store something related to what's displayed:
- Scaled: health `87` stored as `8700` (fixed point) or `0.87` (fraction of max).
- Inverted: "damage taken" instead of current health. It increases when health goes down.
- Max plus current: the HUD shows `current/max`, both stored. Scan each separately.
- Display copy: the UI keeps its own integer copy of a float. Editing it changes the HUD but not the game.

Use `Unknown initial value`, then only relative scans (`Increased value`, `Decreased value`, `Changed value`, `Unchanged value`). They work for any of these encodings as long as the direction is consistent.

## Encrypted or obfuscated values

Some single-player games XOR a value with a key or store it twice and compare. Signs: relative scans keep collapsing to zero results while the value clearly changes, or the found value fixes itself right after you edit it.

Approach:
1. Run `Unknown initial value` with `Changed value`/`Unchanged value` only. The ciphertext still changes when the value changes, but in no particular direction.
2. Once you have a few candidates, use `Find out what accesses this address` on them while the HUD updates. The instruction that decodes it (an `xor`, `sub`, or call into a small getter) tells you the encoding and where the key lives.
3. Build the chain to the encoded field, and document the decode step in the deliverable (for example `value = raw ^ [key_chain]`).

If the protection belongs to an anti-cheat in an online game, stop here (see Scope).

## Position vectors

1. Stand still: `Unknown initial value`, `Float`.
2. Walk forward or climb a ladder: `Changed value` (or `Increased value` if you know the axis direction). Stand still: `Unchanged value`. Repeat.
3. Jumping is a clean signal for the up axis (Y in Unity, Z in Unreal): increased while rising, decreased while falling.
4. Browse the memory region around a hit (`Browse this memory region`, display as float). The other two axes are usually right next to it, as `float x, y, z` (12 bytes) or `double x, y, z` (24 bytes).
5. Expect several matches: the physics body, the render transform, the camera target, network-interpolated copies. Freeze each one. The one that teleports the player (or snaps back immediately because physics owns it) is the real one. Writing to the physics or transform component usually works better than to a cached copy.

## Too many results that never go below a few hundred

- The value is in an array of identical objects (every enemy has health 100). Damage one enemy or yourself to separate them.
- You're scanning static data like config tables. Change the value with gameplay, not menus.
- Use `Value between` with a tight range once you know the approximate value.
