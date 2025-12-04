# Contributing to iCloud Cleanup Daemon

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates.

When creating a bug report, include:
- macOS version
- Python version (`python3 --version`)
- Steps to reproduce the issue
- Expected vs actual behavior
- Relevant log output (`make logs-error`)

### Suggesting Features

Feature requests are welcome! Please:
- Check if the feature has already been requested
- Describe the use case and expected behavior
- Explain why this feature would be useful

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and checks (`make check`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/icloud-cleanup-daemon.git
cd icloud-cleanup-daemon

# Install dependencies
make setup

# Run tests to verify setup
make test
```

## Development Workflow

### Running Tests

```bash
# Run all tests
make test

# Run all checks (lint, typecheck, test)
make check
```

### Code Style

We use:
- **ruff** for linting
- **mypy** for type checking
- **pytest** for testing

Run before committing:
```bash
make lint      # Check code style
make typecheck # Check types
```

### Testing Changes

```bash
# Preview what would be deleted (safe)
make dry-run

# Scan for conflicts without deleting
make scan

# Run daemon in foreground for testing
make run
```

## Architecture Overview

```
src/icloud_cleanup/
├── main.py          # CLI entry point
├── daemon.py        # Main daemon loop
├── detector.py      # Conflict file detection
├── cleaner.py       # File deletion with recovery
├── watcher.py       # FSEvents file monitoring
├── icloud_status.py # iCloud sync status
├── config.py        # Configuration management
└── nosync.py        # .nosync directory management
```

### Key Concepts

1. **Conflict Detection**: Files matching `filename N.ext` (N >= 2) where `filename.ext` exists
2. **Safety First**: Protected paths, recovery mode, dry-run
3. **iCloud Awareness**: Wait for sync completion before deletion

## Commit Messages

Use clear, descriptive commit messages:
- `feat: add support for custom conflict patterns`
- `fix: handle unicode filenames correctly`
- `docs: update installation instructions`
- `test: add tests for edge cases`
- `refactor: simplify conflict detection logic`

## Questions?

Feel free to open an issue for any questions about contributing.
