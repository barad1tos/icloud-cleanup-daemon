# iCloud Cleanup Daemon

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/macOS-13+-black.svg)](https://www.apple.com/macos/)

> **Platform:** macOS only. Uses macOS-specific APIs (`FSEvents`, `launchd`, `brctl`). Linux is not supported (no iCloud). Windows support is not yet implemented (different conflict patterns require service adaptation).

Automatically cleans up iCloud sync conflict files (e.g., `file 2.csv`, `file 3.csv`) on macOS.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Running as a Service](#running-as-a-service)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Safety](#safety)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Modular Cleanup** — Plugin-based architecture: iCloud conflicts, stale `.coverage` artifacts, and more
- **Real-time Monitoring** — Detects new conflict files using macOS FSEvents
- **iCloud Aware** — Waits for iCloud to finish syncing before deletion
- **Smart Detection** — Only deletes true conflicts (verifies original file exists)
- **Safe by Default** — 7-day recovery period, protected system paths, dry-run mode
- **Unicode Support** — Works with filenames in any language
- **Low Resource Usage** — Runs as a background daemon with minimal impact
- **Makefile Workflow** — Simple commands for common operations

## Installation

### Requirements

- macOS 13+ (Ventura or later)
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install

```bash
# Clone the repository
git clone https://github.com/barad1tos/icloud-cleanup-daemon.git
cd icloud-cleanup-daemon

# Install dependencies
make setup
```

<details>
<summary>Alternative: Install with pip</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```
</details>

## Quick Start

```bash
# 1. Preview what would be deleted (safe, no changes)
make dry-run

# 2. Run cleanup once
make once

# 3. Install as auto-starting service
make install
make start
```

## Usage

### Using Make (Recommended)

```bash
make help          # Show all commands

# Development
make dry-run       # Preview deletions (no changes)
make scan          # Scan for conflicts
make once          # Run cleanup once
make run           # Run in foreground

# Service Management
make install       # Install launchd service
make start         # Start service
make stop          # Stop service
make status        # Check service status
make logs          # Tail logs
```

### Using CLI Directly

```bash
# Scan for conflicts
icloud-cleanup scan
icloud-cleanup scan --dir ~/Documents

# Run cleanup
icloud-cleanup run --dry-run    # Preview only
icloud-cleanup run --once       # Run once
icloud-cleanup run              # Run as daemon

# Configuration
icloud-cleanup config --init    # Create config
icloud-cleanup config --show    # Show config

# Recovery
icloud-cleanup recovery --list
icloud-cleanup recovery --restore /path/to/file
```

## Running as a Service

The daemon can run automatically on login using macOS launchd:

```bash
# Install and start
make install
make start

# Check status
make status

# View logs
make logs

# Stop and uninstall
make stop
make uninstall
```

## Configuration

Configuration file: `~/Library/Application Support/icloud-cleanup/config.yaml`

```bash
# Create default config
make config-init

# View current config
make config
```

### Options

| Option                    | Default      | Description                     |
|---------------------------|--------------|---------------------------------|
| `watch_directories`       | iCloud Drive | Directories to monitor          |
| `wait_before_delete`      | 180s         | Wait time before deleting       |
| `recovery.enabled`        | true         | Move to trash instead of delete |
| `recovery.retention_days` | 7            | Days to keep deleted files      |
| `scan_interval`           | 60s          | Interval between full scans     |
| `modules.disabled`        | []           | List of module names to disable |

## How It Works

```
1. Discovery   →  Auto-discover enabled cleanup modules
2. Detection   →  Each module scans for its file patterns
3. Watching    →  FSEvents monitor triggers modules in real-time
4. Verification →  Module-specific checks (e.g., original exists)
5. Safety Check →  Ensure file is not in protected directory
6. Sync Check  →  Wait for iCloud sync (if recovery enabled)
7. Cleanup     →  Delete or move to recovery directory
8. Retention   →  Auto-delete recovered files after 7 days
```

### Cleanup Modules

| Module | Detects | Recovery |
|--------|---------|----------|
| `icloud_conflicts` | `filename 2.ext` when `filename.ext` exists | Yes |
| `coverage_artifacts` | `.coverage.host.pidN.hash` when `.coverage` exists | No |

New modules are auto-discovered — drop a file in `src/icloud_cleanup/modules/` and it works.

### What IS a Conflict

| File             | Original              | Conflict? |
|------------------|-----------------------|-----------|
| `document 2.txt` | `document.txt` exists | ✅ Yes    |
| `photo 3.jpg`    | `photo.jpg` exists    | ✅ Yes    |

### What is NOT a Conflict

| File             | Why Not                                  |
|------------------|------------------------------------------|
| `April 2025.pdf` | No `April.pdf` exists — it's a date      |
| `vSphere 6.pdf`  | No `vSphere.pdf` exists — it's a version |
| `Том 2.fb2`      | No `Том.fb2` exists — it's a book volume |

## Safety

Multiple safety mechanisms protect your files:

| Safety Feature      | Description                                                   |
|---------------------|---------------------------------------------------------------|
| **Recovery Mode**   | Files moved to `~/.icloud-cleanup-trash/` (not deleted)       |
| **7-Day Retention** | Recover accidentally deleted files                            |
| **Original Check**  | Only delete when original file exists                         |
| **Protected Paths** | System directories blocked (`/System`, `/Applications`, etc.) |
| **Dry-Run Mode**    | Preview changes with `--dry-run`                              |
| **iCloud Sync**     | Wait for sync completion before deletion                      |

### Why Not macOS Trash?

Files are moved to `~/.icloud-cleanup-trash/` instead of the system Trash (`~/.Trash`) by design:

1. **Full control** — We manage retention periods and automatic cleanup (7 days by default)
2. **Date organization** — Files are grouped by deletion date (`2025-12-04/`) for easy browsing
3. **No Trash clutter** — Keeps your system Trash clean for manual deletions
4. **Programmatic reliability** — Moving files to `~/.Trash` programmatically doesn't integrate properly with Finder (files won't appear in Trash UI without using private APIs)

To restore a file:
```bash
icloud-cleanup recovery --list      # See all recoverable files
icloud-cleanup recovery --restore /path/to/file
```

### Logs

```bash
# View all logs
make logs

# View errors only
make logs-error
```

Log locations:
- `~/Library/Logs/icloud-cleanup-daemon.log`
- `~/Library/Logs/icloud-cleanup-daemon-stdout.log`
- `~/Library/Logs/icloud-cleanup-daemon-stderr.log`

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

```bash
# Development setup
make setup
make test

# Before submitting PR
make check  # Runs lint + typecheck + tests
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---
<p align="center">
*Made with some hate to iCloud sync conflicts.* ❤️
</p>
