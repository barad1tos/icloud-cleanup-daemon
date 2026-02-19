"""Cleanup logic for iCloud conflict files with recovery support."""

from __future__ import annotations

import contextlib
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import CleanupConfig
    from .detector import ConflictFile
    from .modules.base import DetectedFile

CleanupAction = Literal["deleted", "recovered", "skipped", "error"]


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    path: Path
    success: bool
    action: CleanupAction
    recovery_path: Path | None = None
    error: str | None = None


class Cleaner:
    """Cleans up iCloud conflict files with optional recovery."""

    # Directories that should never be cleaned
    PROTECTED_PATHS: frozenset[str] = frozenset(
        {
            "/",
            "/System",
            "/Applications",
            "/Library",
            "/usr",
            "/bin",
            "/sbin",
            "/var",
            "/private",
        }
    )

    def __init__(self, config: CleanupConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._ensure_recovery_dir()

    def is_path_protected(self, path: Path) -> bool:
        """Guard against accidental deletion of macOS system directories."""
        resolved = path.resolve()
        resolved_str = str(resolved)
        home_str = str(Path.home())

        return next(
            (
                not resolved_str.startswith(home_str)
                for protected in self.PROTECTED_PATHS
                if resolved_str.startswith(f"{protected}/") or resolved_str == protected
            ),
            False,
        )

    def _ensure_recovery_dir(self) -> None:
        if self.config.enable_recovery:
            self.config.recovery_dir.mkdir(parents=True, exist_ok=True)

    def _get_recovery_path(self, file_path: Path) -> Path:
        """Generate a unique recovery path under ``recovery_dir/YYYY-MM-DD/``."""
        date_dir = datetime.now(UTC).strftime("%Y-%m-%d")
        recovery_subdir = self.config.recovery_dir / date_dir
        recovery_subdir.mkdir(parents=True, exist_ok=True)

        parent_hash = hex(hash(str(file_path.parent)))[-6:]
        base_filename = f"{parent_hash}_{file_path.name}"
        recovery_path = recovery_subdir / base_filename

        counter = 1
        while recovery_path.exists():
            recovery_path = recovery_subdir / f"{parent_hash}_{file_path.stem}_{counter}{file_path.suffix}"
            counter += 1

        return recovery_path

    def delete_detected(self, detected: DetectedFile) -> CleanupResult:
        """Delete a detected file, respecting its recovery_enabled flag."""
        path = detected.path
        use_recovery = detected.recovery_enabled and self.config.enable_recovery
        return self._delete_path(path, use_recovery=use_recovery)

    def delete_conflict(self, conflict: ConflictFile, *, force: bool = False) -> CleanupResult:
        """Delete a conflict file, optionally moving to recovery.

        Args:
            conflict: Conflict file to delete.
            force: If True, skip recovery and delete immediately.

        """
        use_recovery = self.config.enable_recovery and not force
        return self._delete_path(conflict.path, use_recovery=use_recovery)

    def _delete_path(self, path: Path, *, use_recovery: bool) -> CleanupResult:
        if not path.exists():
            return CleanupResult(
                path=path,
                success=False,
                action="skipped",
                error="File no longer exists",
            )

        if self.is_path_protected(path):
            self.logger.warning("Refusing to delete protected path: %s", path)
            return CleanupResult(
                path=path,
                success=False,
                action="skipped",
                error="Path is in protected directory",
            )

        try:
            if use_recovery:
                recovery_path = self._get_recovery_path(path)
                shutil.move(str(path), str(recovery_path))
                self.logger.info("Moved to recovery: %s -> %s", path.name, recovery_path)
                return CleanupResult(
                    path=path,
                    success=True,
                    action="recovered",
                    recovery_path=recovery_path,
                )

            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
                self.logger.info("Deleted directory: %s", path)
            else:
                path.unlink()
                self.logger.info("Deleted file: %s", path)
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
        """Remove date-directories older than the retention period.

        Returns:
            Number of expired directories removed.

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
                    # Remove the entire directory
                    shutil.rmtree(date_dir)
                    self.logger.info("Removed expired recovery directory: %s", date_dir.name)
                    cleaned += 1

        except OSError as e:
            self.logger.error("Error cleaning recovery directory: %s", e)

        return cleaned

    def restore_file(self, recovery_path: Path, destination: Path | None = None) -> bool:
        """Copy a file from recovery to *destination* (default: ``~/Desktop/Restored/``)."""
        if not recovery_path.exists():
            self.logger.error("Recovery file not found: %s", recovery_path)
            return False

        if destination is None:
            # Extract the original filename (remove hash prefix)
            parts = recovery_path.name.split("_", 1)
            original_name = parts[1] if len(parts) > 1 else recovery_path.name

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
        """List all files in the recovery directory, newest first."""
        files: list[tuple[Path, datetime]] = []

        if not self.config.recovery_dir.exists():
            return files

        with contextlib.suppress(OSError):
            for date_dir in self.config.recovery_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                try:
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
                except ValueError:
                    continue

                files.extend((file_path, dir_date) for file_path in date_dir.iterdir() if file_path.is_file())
        return sorted(files, key=lambda entry: entry[1], reverse=True)
