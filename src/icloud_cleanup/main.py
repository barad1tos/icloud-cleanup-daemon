"""Main entry point for iCloud cleanup daemon."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import CleanupConfig
from .daemon import ICloudCleanupDaemon


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments.

    """
    parser = argparse.ArgumentParser(
        prog="icloud-cleanup",
        description="Daemon for cleaning up iCloud sync conflict files",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Path to configuration file",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command (default)
    run_parser = subparsers.add_parser("run", help="Run the daemon")
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit instead of continuous daemon mode",
    )

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan for conflicts without deleting")
    scan_parser.add_argument(
        "--dir",
        "-d",
        type=Path,
        default=None,
        help="Specific directory to scan",
    )

    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_parser.add_argument(
        "--init",
        action="store_true",
        help="Create default configuration file",
    )
    config_parser.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration",
    )

    # Recovery command
    recovery_parser = subparsers.add_parser("recovery", help="Manage recovered files")
    recovery_parser.add_argument(
        "--list",
        action="store_true",
        dest="list_files",
        help="List recoverable files",
    )
    recovery_parser.add_argument(
        "--restore",
        type=Path,
        default=None,
        help="Restore a specific file",
    )
    recovery_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up expired recovery files",
    )

    return parser.parse_args()


def cmd_scan(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute scan command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    from .detector import ConflictDetector

    console = Console()
    detector = ConflictDetector(config)

    if args.dir:
        conflicts = detector.scan_directory(args.dir)
    else:
        conflicts = detector.scan_all()

    if not conflicts:
        console.print("[green]No conflict files found[/green]")
        return 0

    table = Table(title=f"Found {len(conflicts)} conflict files")
    table.add_column("Conflict File", style="red")
    table.add_column("Original", style="green")
    table.add_column("Location", style="dim")

    for conflict in conflicts:
        table.add_row(
            conflict.path.name,
            conflict.original_path.name,
            str(conflict.path.parent),
        )

    console.print(table)
    return 0


def cmd_config(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute config command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    console = Console()

    if args.init:
        config_path = CleanupConfig.get_config_path()
        if config_path.exists():
            console.print(f"[yellow]Config already exists: {config_path}[/yellow]")
            return 1
        config.save()
        console.print(f"[green]Created config: {config_path}[/green]")
        return 0

    if args.show:
        table = Table(title="Current Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Watch directories", "\n".join(str(d) for d in config.watch_directories))
        table.add_row("Wait before delete", f"{config.wait_before_delete}s")
        table.add_row("Recovery enabled", str(config.enable_recovery))
        table.add_row("Recovery directory", str(config.recovery_dir))
        table.add_row("Retention days", str(config.recovery_retention_days))
        table.add_row("Log file", str(config.log_file))
        table.add_row("Log level", config.log_level)

        console.print(table)
        return 0

    console.print("[yellow]Use --init or --show[/yellow]")
    return 1


def cmd_recovery(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute recovery command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    import logging

    from .cleaner import Cleaner

    console = Console()
    logger = logging.getLogger("icloud-cleanup")
    cleaner = Cleaner(config, logger)

    if args.list_files:
        files = cleaner.list_recoverable_files()
        if not files:
            console.print("[green]No recoverable files[/green]")
            return 0

        table = Table(title=f"Recoverable files ({len(files)})")
        table.add_column("File", style="cyan")
        table.add_column("Deleted", style="dim")
        table.add_column("Path", style="dim")

        for path, date in files:
            table.add_row(
                path.name,
                date.strftime("%Y-%m-%d"),
                str(path),
            )

        console.print(table)
        return 0

    if args.restore:
        if cleaner.restore_file(args.restore):
            console.print(f"[green]Restored: {args.restore.name}[/green]")
            return 0
        console.print("[red]Restoration failed[/red]")
        return 1

    if args.cleanup:
        cleaned = cleaner.cleanup_recovery_dir()
        console.print(f"[green]Cleaned {cleaned} expired directories[/green]")
        return 0

    console.print("[yellow]Use --list, --restore, or --cleanup[/yellow]")
    return 1


def cmd_run(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute run command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    daemon = ICloudCleanupDaemon(config)

    if args.once:
        results = asyncio.run(daemon.run_once())
        success = sum(1 for r in results if r.success)
        print(f"Processed {len(results)} conflicts, {success} successful")
        return 0

    asyncio.run(daemon.run_daemon())
    return 0


def main() -> int:
    """Main entry point.

    Returns:
        Exit code.

    """
    args = parse_args()
    config = CleanupConfig.load(args.config)

    # Default to run command
    command = args.command or "run"

    if command == "scan":
        return cmd_scan(config, args)
    elif command == "config":
        return cmd_config(config, args)
    elif command == "recovery":
        return cmd_recovery(config, args)
    elif command == "run":
        return cmd_run(config, args)
    else:
        print(f"Unknown command: {command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
