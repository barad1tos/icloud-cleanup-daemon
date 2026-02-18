"""Main entry point for iCloud cleanup daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from .config import CleanupConfig
from .daemon import ICloudCleanupDaemon

if TYPE_CHECKING:
    from .cleaner import Cleaner
    from .modules.base import DetectedFile


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
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
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

    # Nosync command
    nosync_parser = subparsers.add_parser(
        "nosync",
        help="Exclude directories from iCloud sync (.venv, node_modules, etc.)",
    )
    nosync_parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan for directories that should be excluded",
    )
    nosync_parser.add_argument(
        "--apply",
        action="store_true",
        help="Convert directories to .nosync format",
    )
    nosync_parser.add_argument(
        "--dir",
        "-d",
        type=Path,
        default=None,
        help="Specific directory to process",
    )

    return parser.parse_args()


def cmd_scan(config: CleanupConfig, args: argparse.Namespace) -> int:  # NOSONAR
    """Execute scan command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    from .modules import discover_modules

    console = Console()
    modules = discover_modules(config)

    all_detected: list[DetectedFile] = []
    for module in modules:
        if args.dir:
            all_detected.extend(module.scan_directory(args.dir))
        else:
            all_detected.extend(module.scan_all())

    if not all_detected:
        console.print("[green]No files to clean up[/green]")
        return 0

    table = Table(title=f"Found {len(all_detected)} files to clean up")
    table.add_column("Module", style="cyan")
    table.add_column("File", style="red")
    table.add_column("Reason", style="green")
    table.add_column("Location", style="dim")

    for detected in all_detected:
        table.add_row(
            detected.module_name,
            detected.path.name,
            detected.reason,
            str(detected.path.parent),
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
        return _print_config(config, console)

    console.print("[yellow]Use --init or --show[/yellow]")
    return 1


def _print_config(config: CleanupConfig, console: Console) -> int:  # NOSONAR
    """Print the current configuration as a table."""
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
    table.add_row("Disabled modules", ", ".join(config.modules_disabled) or "none")

    console.print(table)
    return 0


def cmd_recovery(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute recovery command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    from .cleaner import Cleaner

    console = Console()
    logger = logging.getLogger("icloud-cleanup")
    cleaner = Cleaner(config, logger)

    if args.list_files:
        return _list_recovery_files(cleaner, console)
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


def _list_recovery_files(cleaner: Cleaner, console: Console) -> int:  # NOSONAR
    """List recoverable files as a table."""
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


def cmd_run(config: CleanupConfig, args: argparse.Namespace) -> int:  # NOSONAR
    """Execute the run command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    # Handle dry-run mode
    if getattr(args, "dry_run", False):
        return _dry_run(config)

    daemon = ICloudCleanupDaemon(config)

    if args.once:
        results = asyncio.run(daemon.run_once())
        success = sum(bool(r.success) for r in results)
        print(f"Processed {len(results)} conflicts, {success} successful")
        return 0

    asyncio.run(daemon.run_daemon())
    return 0


def _dry_run(config: CleanupConfig) -> int:
    """Show what would be deleted. Returns 1 if files are found, 0 if clean."""
    from .modules import discover_modules

    console = Console()
    modules = discover_modules(config)

    console.print("\n[bold yellow]DRY RUN MODE - No files will be deleted[/bold yellow]\n")
    console.print(f"[dim]Watch directories: {', '.join(str(d) for d in config.watch_directories)}[/dim]")
    console.print(f"[dim]Recovery enabled: {config.enable_recovery}[/dim]")
    console.print(f"[dim]Loaded modules: {', '.join(m.name for m in modules)}[/dim]\n")

    all_detected: list[DetectedFile] = []
    for module in modules:
        all_detected.extend(module.scan_all())

    if not all_detected:
        console.print("[green]No files to clean up[/green]")
        return 0

    table = Table(title=f"Would process {len(all_detected)} files")
    table.add_column("Action", style="yellow")
    table.add_column("Module", style="cyan")
    table.add_column("File", style="red")
    table.add_column("Reason", style="green")

    for detected in all_detected:
        action = "MOVE to recovery" if detected.recovery_enabled and config.enable_recovery else "DELETE"
        table.add_row(
            action,
            detected.module_name,
            detected.path.name,
            detected.reason,
        )

    console.print(table)
    console.print("\n[bold]To actually run, remove --dry-run flag[/bold]")
    return 1


def cmd_nosync(config: CleanupConfig, args: argparse.Namespace) -> int:
    """Execute nosync command.

    Args:
        config: Cleanup configuration.
        args: Parsed arguments.

    Returns:
        Exit code.

    """
    from .nosync import NosyncManager

    console = Console()
    logger = logging.getLogger("icloud-cleanup")
    manager = NosyncManager(config, logger)

    # Determine directories to scan
    candidates = manager.scan_for_candidates(args.dir) if args.dir else manager.scan_all()

    if not candidates:
        console.print("[green]No directories need to be excluded from iCloud sync[/green]")
        return 0

    if args.scan or not args.apply:
        return _print_nosync_candidates(candidates, console, args)
    console.print(f"\n[bold]Converting {len(candidates)} directories to .nosync...[/bold]\n")

    success_count = 0
    for path in candidates:
        result = manager.convert_to_nosync(path)
        if result.success:
            console.print(f"[green]✓[/green] {path.name} -> {path.name}.nosync")
            success_count += 1
        else:
            console.print(f"[red]✗[/red] {path.name}: {result.error}")

    console.print(f"\n[bold]Converted {success_count}/{len(candidates)} directories[/bold]")
    return 0


def _print_nosync_candidates(candidates: list[Path], console: Console, args: argparse.Namespace) -> int:
    """Print table of nosync candidates."""
    table = Table(title=f"Found {len(candidates)} directories to exclude")
    table.add_column("Directory", style="yellow")
    table.add_column("Location", style="dim")

    for path in candidates:
        table.add_row(path.name, str(path.parent))

    console.print(table)

    if not args.apply:
        console.print("\n[bold]To convert, run with --apply flag[/bold]")
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
    elif command == "nosync":
        return cmd_nosync(config, args)
    elif command == "run":
        return cmd_run(config, args)
    else:
        print(f"Unknown command: {command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
