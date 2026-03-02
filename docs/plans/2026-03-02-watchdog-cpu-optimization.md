# Watchdog CPU Optimization: Async Deferred Processing

**Date**: 2026-03-02
**Status**: Approved
**Problem**: Watchdog Observer thread consumes ~14% CPU idle

## Problem

After fixing scan frequency (commit `0d9fd68`), the daemon still uses ~14% CPU.
The bottleneck is the watchdog `Observer` thread processing FSEvents from iCloud Drive.

**Root cause chain:**

1. iCloud Drive generates hundreds of FSEvents/minute (sync, metadata, `.icloud` files)
2. Each event synchronously calls `is_target()` on all watch-capable modules
3. Each `is_target()` does `stat()` syscalls (`path.is_dir()`, `path.is_file()`, `path.exists()`)
4. No deduplication — same path checked dozens of times per minute
5. Modules check stat() *before* cheap string matching (wasted I/O)

## Architecture

### Current (sync I/O in watchdog thread)

```
FSEvent → watchdog thread → _check_path() → is_target() [stat!] → asyncio.Queue → daemon
```

### Proposed (zero I/O in watchdog thread)

```
FSEvent → watchdog thread → _enqueue_path() [set.add(), zero I/O]
                                     ↓
                              Lock-protected set[Path]
                                     ↓
            async loop ← drain every 1-2s ← deduplicated paths
                  ↓
           can_match(name) pre-filter [string only, no I/O]
                  ↓
           is_target(path) [stat] in chunks of ~50
                  ↓
           _pending_deletes
```

## Components

### 1. Watchdog handler: zero I/O

`ConflictEventHandler._check_path()` becomes `_enqueue_path()`:

- Adds `Path` to a `threading.Lock`-protected `set[Path]`
- Lock held for one pointer operation (microseconds)
- No `is_target()`, no stat(), no module iteration
- Handles both `on_created` and `on_moved` events

### 2. FileWatcher.drain_paths(): atomic swap

New method replaces `get_pending()` as the primary interface:

- Under lock: swap `self._paths` with empty `set()` (pointer swap, zero iteration)
- Returns the old set to the caller
- `get_pending()` and `asyncio.Queue` removed

### 3. CleanupModule.can_match(name): string pre-filter

New method in `CleanupModule` Protocol:

- Pure string/regex check on filename — no I/O
- Returns `bool` — "could this filename be a target?"
- Called *before* `is_target()` to skip stat() on obvious non-matches

Module implementations:

| Module | can_match logic |
|--------|----------------|
| ICloudConflictsModule | Regex match on `conflict_pattern` |
| EphemeralCachesModule | Name in `EPHEMERAL_PATTERNS` |
| CoverageArtifactsModule | `supports_watch=False`, not called |

### 4. Daemon drain loop: decoupled cadences

Two timers in the main loop:

- **Drain cadence** (1-2s): wake, drain paths, run `can_match` + `is_target`, process pending deletes
- **Full scan cadence** (scan_interval=300s): periodic `_scan_and_queue()` + recovery cleanup

```python
last_scan = loop.time()

while self._running:
    # Drain watcher buffer
    raw_paths = self.watcher.drain_paths()
    if raw_paths:
        await self._process_watcher_batch(raw_paths)

    await self._process_pending_deletes()

    # Periodic full scan
    if loop.time() - last_scan >= self.config.scan_interval:
        self._scan_and_queue()
        self.cleaner.cleanup_recovery_dir()
        last_scan = loop.time()

    await asyncio.sleep(self._drain_interval)
```

### 5. Batch processing with cooperative yield

```python
async def _process_watcher_batch(self, paths: set[Path]) -> None:
    batch_size = 50
    path_list = list(paths)

    for i in range(0, len(path_list), batch_size):
        batch = path_list[i : i + batch_size]
        for path in batch:
            self._check_and_enqueue(path)
        await asyncio.sleep(0)  # yield to event loop
```

`_check_and_enqueue(path)` runs `can_match()` first, then `is_target()` only on matches.

### 6. Remove legacy detector from watcher

`ConflictEventHandler` currently falls back to `ConflictDetector.is_conflict_file()`.
This is redundant — `ICloudConflictsModule.is_target()` covers the same logic with
an additional `original_path.exists()` check. The legacy path does extra stat() calls
to arrive at the same result (skip in `_process_conflict`).

Remove the legacy fallback from the watcher entirely. The `ConflictDetector` remains
for `_process_pending_deletes` backward compatibility (entries with `detected=None`),
but those should also be cleaned up.

### 7. Module is_target() reordering

Invert stat-then-regex to regex-then-stat inside modules:

**ICloudConflictsModule** (current):
```python
if not path.is_file():     # stat() — expensive
    return None
match = pattern.match(name) # regex — cheap
```

**ICloudConflictsModule** (proposed):
```python
match = pattern.match(name) # regex — cheap, early exit
if not match:
    return None
if not path.is_file():      # stat() — only if regex matched
    return None
```

Same for `EphemeralCachesModule`: check name against patterns before `path.is_dir()`.

## Config

New field in `CleanupConfig`:

```python
watcher_drain_interval: float = 1.0  # Seconds between watcher buffer drains
watcher_batch_size: int = 50         # Max paths per processing chunk
```

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| stat() calls/event | 2-3 | 0 (handler) + ~0.01 (after pre-filter) |
| Events deduplicated | No | Yes (set) |
| Idle CPU | ~14% | <1% |
| Event latency | instant | 1-2s |
| Watcher thread I/O | stat() per event | zero |

## Thread Safety

- Lock-protected `set[Path]` with atomic pointer swap — lock held for microseconds
- `drain_paths()` called only from async loop (single consumer)
- `_enqueue_path()` called from watchdog thread (single producer per observer)
- No contention risk at event rates of hundreds/minute

## Edge Cases

- **Thread lifecycle on stop**: After `observer.stop()`, drain remaining paths once
  (or discard in finally block)
- **EDEADLK**: Stat calls in `is_target()` can raise EDEADLK on iCloud paths —
  existing `except OSError` handling preserved, now runs in async context
- **Back-pressure**: Set is naturally bounded by distinct path count (max ~50K for
  typical iCloud Drive). Not a concern; add debug logging of set size for monitoring

## Files to Modify

| File | Changes |
|------|---------|
| `src/icloud_cleanup/modules/base.py` | Add `can_match(name: str) -> bool` to Protocol |
| `src/icloud_cleanup/modules/icloud_conflicts.py` | Add `can_match()`, reorder stat/regex in `is_target()` |
| `src/icloud_cleanup/modules/ephemeral_caches.py` | Add `can_match()`, reorder stat/pattern in `is_target()` |
| `src/icloud_cleanup/modules/coverage_artifacts.py` | Add `can_match()` (stub, `supports_watch=False`) |
| `src/icloud_cleanup/watcher.py` | Replace Queue with Lock+set, `drain_paths()`, remove legacy fallback |
| `src/icloud_cleanup/daemon.py` | New drain loop, `_process_watcher_batch()`, `_check_and_enqueue()` |
| `src/icloud_cleanup/config.py` | Add `watcher_drain_interval`, `watcher_batch_size` |
| `tests/test_watcher.py` | Update for new drain_paths API, remove Queue tests |
| `tests/test_daemon.py` | Update drain loop tests, add batch processing tests |
| `tests/test_modules_base.py` | Add `can_match` to mock module, protocol tests |
| `tests/test_detector.py` | Verify no regressions after legacy removal |
