"""Cleanup logic for iCloud conflict files with recovery support."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CleanupConfig
    from .detector import ConflictFile


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    path: Path
    success: bool
    action: str  # "deleted", "recovered", "skipped", "error"
    recovery_path: Path | None = None
    error: str | None = None


class Cleaner:
    """Cleans up iCloud conflict files with optional recovery."""

    def __init__(self, config: CleanupConfig, logger: logging.Logger) -> None:
        """Initialize the cleaner.

        Args:
            config: Cleanup configuration.
            logger: Logger instance.

        """
        self.config = config
        self.logger = logger
        self._ensure_recovery_dir()

    def _ensure_recovery_dir(self) -> None:
        """Ensure the recovery directory exists."""
        if self.config.enable_recovery:
            self.config.recovery_dir.mkdir(parents=True, exist_ok=True)

    def _get_recovery_path(self, conflict: ConflictFile) -> Path:
        """Generate a unique recovery path for a conflict file.

        Args:
            conflict: Conflict file to recover.

        Returns:
            Path where the file will be stored for recovery.

        """
        # Create date-based subdirectory
        date_dir = datetime.now(UTC).strftime("%Y-%m-%d")
        recovery_subdir = self.config.recovery_dir / date_dir
        recovery_subdir.mkdir(parents=True, exist_ok=True)

        # Include parent directory info to avoid collisions
        parent_hash = hex(hash(str(conflict.path.parent)))[-6:]
        filename = f"{parent_hash}_{conflict.path.name}"

        return recovery_subdir / filename

    def delete_conflict(self, conflict: ConflictFile, *, force: bool = False) -> CleanupResult:
        """Delete a conflict file, optionally moving to recovery.

        Args:
            conflict: Conflict file to delete.
            force: If True, skip recovery and delete immediately.

        Returns:
            CleanupResult with operation details.

        """
        path = conflict.path

        if not path.exists():
            return CleanupResult(
                path=path,
                success=False,
                action="skipped",
                error="File no longer exists",
            )

        try:
            if self.config.enable_recovery and not force:
                # Move to recovery directory
                recovery_path = self._get_recovery_path(conflict)
                shutil.move(str(path), str(recovery_path))

                self.logger.info(
                    "Moved conflict to recovery: %s -> %s",
                    path.name,
                    recovery_path,
                )

                return CleanupResult(
                    path=path,
                    success=True,
                    action="recovered",
                    recovery_path=recovery_path,
                )
            else:
                # Delete immediately
                path.unlink()

                self.logger.info("Deleted conflict file: %s", path)

                return CleanupResult(
                    path=path,
                    success=True,
                    action="deleted",
                )

        except PermissionError as e:
            self.logger.error("Permission denied deleting %s: %s", path, e)
            return CleanupResult(
                path=path,
                success=False,
                action="error",
                error=f"Permission denied: {e}",
            )
        except OSError as e:
            self.logger.error("Error deleting %s: %s", path, e)
            return CleanupResult(
                path=path,
                success=False,
                action="error",
                error=str(e),
            )

    def cleanup_recovery_dir(self) -> int:
        """Remove files older than retention period from recovery directory.

        Returns:
            Number of files cleaned up.

        """
        if not self.config.enable_recovery:
            return 0

        if not self.config.recovery_dir.exists():
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=self.config.recovery_retention_days)
        cleaned = 0

        try:
            for date_dir in self.config.recovery_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                # Parse date from directory name
                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
                except ValueError:
                    continue

                if dir_date < cutoff:
                    # Remove entire directory
                    shutil.rmtree(date_dir)
                    self.logger.info("Removed expired recovery directory: %s", date_dir.name)
                    cleaned += 1

        except OSError as e:
            self.logger.error("Error cleaning recovery directory: %s", e)

        return cleaned

    def restore_file(self, recovery_path: Path, destination: Path | None = None) -> bool:
        """Restore a file from recovery.

        Args:
            recovery_path: Path to file in recovery directory.
            destination: Where to restore. If None, attempts to restore to original location.

        Returns:
            True if restoration successful.

        """
        if not recovery_path.exists():
            self.logger.error("Recovery file not found: %s", recovery_path)
            return False

        if destination is None:
            # Extract original filename (remove hash prefix)
            parts = recovery_path.name.split("_", 1)
            if len(parts) > 1:
                original_name = parts[1]
            else:
                original_name = recovery_path.name

            # Default to home directory
            destination = Path.home() / "Desktop" / "Restored" / original_name

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(recovery_path), str(destination))
            self.logger.info("Restored file: %s -> %s", recovery_path.name, destination)
            return True
        except OSError as e:
            self.logger.error("Error restoring file: %s", e)
            return False

    def list_recoverable_files(self) -> list[tuple[Path, datetime]]:
        """List all files in recovery directory.

        Returns:
            List of (path, date) tuples for recoverable files.

        """
        files: list[tuple[Path, datetime]] = []

        if not self.config.recovery_dir.exists():
            return files

        try:
            for date_dir in self.config.recovery_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
                except ValueError:
                    continue

                for file_path in date_dir.iterdir():
                    if file_path.is_file():
                        files.append((file_path, dir_date))

        except OSError:
            pass

        return sorted(files, key=lambda x: x[1], reverse=True)
