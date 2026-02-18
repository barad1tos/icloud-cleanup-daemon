# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with code in this repository.

## Build Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Type checking
uv run ty check src/

# Linting
uv run ruff check src/ tests/

# Run the CLI
uv run icloud-cleanup --help
```

## Architecture

```
src/icloud_cleanup/
├── main.py          # CLI entry point (argparse, subcommands)
├── daemon.py        # Main daemon loop (asyncio, signal handling)
├── detector.py      # Backward-compat wrapper (delegates to modules)
├── cleaner.py       # File deletion with recovery support
├── watcher.py       # FSEvents-based file system monitoring (watchdog)
├── icloud_status.py # iCloud sync status checking
├── config.py        # YAML configuration loading/saving
├── nosync.py        # .nosync directory management for iCloud exclusion
└── modules/
    ├── __init__.py          # Auto-discovery: discover_modules(config)
    ├── base.py              # CleanupModule Protocol, DetectedFile dataclass
    ├── icloud_conflicts.py  # iCloud conflict files (filename 2.ext)
    └── coverage_artifacts.py # Stale .coverage.host.pidN.hash files
```

**Data flow:**
1. `discover_modules(config)` auto-discovers all enabled `CleanupModule` implementations
2. Each module's `scan_all()` finds files to clean — returns `DetectedFile` objects
3. `FileWatcher` monitors directories in real-time; modules with `supports_watch=True` get checked on events
4. `ICloudStatusChecker` waits for iCloud sync (only for files with `recovery_enabled=True`)
5. `Cleaner.delete_detected()` handles deletion — recovery or direct unlink per `DetectedFile.recovery_enabled`

### Module System

Each cleanup module implements `CleanupModule` Protocol from `modules/base.py`:
- `is_target(path)` — check a single file, return `DetectedFile` or `None`
- `scan_directory(directory)` — scan one directory
- `scan_all()` — scan all configured watch directories
- `supports_watch` — whether this module can handle real-time FSEvents
- `recovery_enabled` — set per-file in `DetectedFile` (iCloud conflicts use recovery, coverage artifacts don't)

**Adding a new module:**
1. Create `src/icloud_cleanup/modules/your_module.py`
2. Implement a class with `MODULE_ENABLED = True` and `CleanupModule` methods
3. Accept `config: CleanupConfig` in `__init__`
4. Auto-discovery will pick it up — no registration needed
5. Users can disable via `modules.disabled` list in config YAML

## Key Patterns

### Conflict File Detection
iCloud creates conflict files as `filename 2.ext`, `filename 3.ext`, etc. Pattern in `config.py`:
```python
conflict_pattern: str = r"^(.+)\s+([2-9]|\d{2,})(\.[^.]+)?$"
```
- Matches numbers >= 2 (iCloud starts at 2, not 1)
- Supports hidden files (`.coverage 2`)
- Supports files without extension
- Supports Unicode filenames (Cyrillic, accented characters, etc.)

**Critical**: Pattern match alone is NOT enough! Must also verify original file exists:
- ✅ `document 2.txt` when `document.txt` exists → real conflict
- ❌ `April 2025.pdf` when `April.pdf` doesn't exist → NOT a conflict (just a filename with year)

### Safety Features
- **Protected paths**: `/System`, `/Applications`, `/Library`, etc. are blocked from deletion
- **Recovery mode**: Files moved to `~/.icloud-cleanup-trash/YYYY-MM-DD/` instead of permanent delete
- **Dry-run mode**: `--dry-run` flag shows what would be deleted without taking action
- **Home directory exception**: Paths under `$HOME` are allowed even if under protected system paths

### Async Patterns
- Daemon uses `asyncio` event loop with signal handlers
- Timeout handling via `asyncio.timeout()` context manager
- `CancelledError` is always re-raised after cleanup

## Testing

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_detector.py
```

Tests use `tmp_path` fixture for isolated file system operations.

## Common Pitfalls

When modifying this codebase, watch out for:

1. **xattr binary output**: `xattr -l` can return binary data. Never use `text=True` in subprocess — decode manually with `errors="replace"`

2. **False positive conflicts**: Always check `conflict.original_path.exists()` before queueing for deletion

3. **YAML boolean parsing**: `bool("false")` = `True`! Use explicit parsing for config values

4. **Logger handler duplication**: Clear existing handlers before adding new ones if daemon can be recreated

5. **Infinite loop risk**: Always validate poll intervals are > 0 before using in while loops

6. **Dict mutation during iteration**: Never `del` from a dict while iterating over it — collect keys first, then delete in a separate loop. See `daemon.py:_process_pending_deletes` for the correct pattern.

7. **JetBrains MCP `get_file_problems`**: The `errorsOnly` parameter defaults to `true`. Always pass `errorsOnly: false` to get warnings. Note: Grazie (grammar), Sourcery, and SonarLint diagnostics are NOT exposed — only PyCharm's built-in Python inspections and Pyright.

8. **IDE warnings are action items**: When the user shares IDE diagnostics, LanguageTool warnings, or any code quality feedback — always fix them immediately. Do not dismiss them as cosmetic or non-blocking. The project maintains clean grammar in docstrings and comments.

## Configuration

Default config location: `~/Library/Application Support/icloud-cleanup/config.yaml`

Key settings:
- `watch_directories`: Directories to monitor (default: iCloud Drive)
- `wait_before_delete`: Seconds to wait before deleting (default: 180)
- `recovery.enabled`: Move to trash instead of delete (default: true)
- `recovery.retention_days`: Days to keep deleted files (default: 7)
- `modules.disabled`: List of module names to disable (default: empty)

## Git Workflow

### Commit Rules

1. **No Claude attribution** — Do NOT add "Generated with Claude Code" or "Co-Authored-By: Claude" lines to commits
2. **Conventional commits** — Use prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
3. **Concise messages** — First line under 72 chars, explain "why" not "what"

### Before Committing

```bash
# Always run before commit
make check  # or: uv run pytest && uv run ty check src/ && uv run ruff check src/ tests/
```

### Commit Message Format

```
type: short description

- Detail 1
- Detail 2
```

Good:
```
fix: prevent false positive conflict detection

- Check original file exists before queueing
- Filter out files like "Report 2025.pdf"
```

Bad:
```
Updated daemon.py  # No type prefix, doesn't explain why
```

### Branch Strategy

- `main` — stable, always passing tests
- Feature branches — `feat/feature-name` or `fix/issue-name`

### What NOT to Commit

- `.DS_Store` files
- `__pycache__/` directories
- `.env` files with secrets
- IDE settings (`.idea/`, `.vscode/` unless shared configs)
- Build artifacts (`dist/`, `*.egg-info/`)

### GitHub Workflow

```bash
# Push existing code
git remote add origin git@github.com:username/repo-name.git
git push -u origin main

# Create PR (use full path to bypass 1Password alias)
/opt/homebrew/bin/gh pr create --base main --title "feat: description" --body "PR body"
```

Note: Use full path `/opt/homebrew/bin/gh` — the `gh` alias routes through 1Password which requires interactive terminal
