# iCloud Cleanup Daemon

Automatically cleans up iCloud sync conflict files (e.g., `file 2.csv`, `file 3.csv`).

## Features

- **FSEvents Monitoring**: Real-time detection of new conflict files using macOS FSEvents
- **iCloud Sync Awareness**: Waits for iCloud to finish syncing before deleting
- **7-Day Recovery**: Deleted files are moved to trash with 7-day retention
- **Configurable Whitelist**: Choose which directories to monitor
- **Low Resource Usage**: Runs as a background daemon with minimal CPU/IO impact

## Installation

```bash
cd /Users/cloud/Developer/icloud-cleanup-daemon

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Or with uv
uv sync
```

## Usage

### Quick Scan (No Deletion)

```bash
# Scan all iCloud directories
icloud-cleanup scan

# Scan specific directory
icloud-cleanup scan --dir ~/Library/Mobile\ Documents/com~apple~CloudDocs/
```

### One-Time Cleanup

```bash
# Run once and exit
icloud-cleanup run --once
```

### Run as Daemon

```bash
# Run continuously
icloud-cleanup run
```

### Configuration

```bash
# Create default config
icloud-cleanup config --init

# Show current config
icloud-cleanup config --show
```

Configuration file location: `~/Library/Application Support/icloud-cleanup/config.yaml`

### Recovery

```bash
# List recoverable files
icloud-cleanup recovery --list

# Restore a file
icloud-cleanup recovery --restore /path/to/recovery/file

# Clean up expired recoveries
icloud-cleanup recovery --cleanup
```

## Install as launchd Service

```bash
# Copy plist to LaunchAgents
cp launchd/com.cloud.icloud-cleanup.plist ~/Library/LaunchAgents/

# Load the daemon
launchctl load ~/Library/LaunchAgents/com.cloud.icloud-cleanup.plist

# Check status
launchctl list | grep icloud-cleanup

# View logs
tail -f ~/Library/Logs/icloud-cleanup-daemon.log
```

### Uninstall

```bash
# Unload daemon
launchctl unload ~/Library/LaunchAgents/com.cloud.icloud-cleanup.plist

# Remove plist
rm ~/Library/LaunchAgents/com.cloud.icloud-cleanup.plist
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `watch_directories` | iCloud Drive | Directories to monitor |
| `wait_before_delete` | 180s | Wait time before deleting (allows iCloud to sync) |
| `recovery.enabled` | true | Move to trash instead of permanent delete |
| `recovery.retention_days` | 7 | Days to keep deleted files |
| `scan_interval` | 60s | Interval between full directory scans |

## How It Works

1. **Detection**: Monitors configured directories for files matching pattern `filename N.ext` where N is a number ≥ 2
2. **Verification**: Checks if the original file (`filename.ext`) exists
3. **Sync Check**: Waits for iCloud to finish syncing the file
4. **Cleanup**: Moves conflict to recovery directory (or deletes if recovery disabled)
5. **Recovery Cleanup**: Automatically removes recovered files older than retention period

## Logs

- **Daemon log**: `~/Library/Logs/icloud-cleanup-daemon.log`
- **stdout/stderr**: `~/Library/Logs/icloud-cleanup-daemon-{stdout,stderr}.log`

## License

MIT
