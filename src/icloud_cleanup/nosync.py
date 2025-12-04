"""Exclude directories from iCloud sync using .nosync suffix."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CleanupConfig


# Common directories that should not be synced
DEFAULT_EXCLUDE_PATTERNS: frozenset[str] = frozenset({
    ".venv",
    "venv",
    ".env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    ".build",
    "build",
    "dist",
    ".cache",
})


@dataclass
class NosyncResult:
    """Result of a nosync operation."""

    path: Path
    success: bool
    action: str  # "converted", "skipped", "error"
    nosync_path: Path | None = None
    error: str | None = None


class NosyncManager:
    """Manages .nosync exclusions for iCloud directories."""

    def __init__(self, config: CleanupConfig, logger: logging.Logger) -> None:
        """Initialize the manager.

        Args:
            config: Cleanup configuration.
            logger: Logger instance.

        """
        self.config = config
        self.logger = logger

    @staticmethod
    def is_nosync_candidate(path: Path) -> bool:
        """Check if a directory should be excluded from iCloud sync.

        Args:
            path: Path to check.

        Returns:
            True if directory matches exclusion patterns.

        """
        if not path.is_dir():
            return False

        name = path.name

        # Already a .nosync directory
        if name.endswith(".nosync"):
            return False

        # Check against patterns
        for pattern in DEFAULT_EXCLUDE_PATTERNS:
            if pattern.startswith("*"):
                # Wildcard pattern (e.g., *.egg-info)
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True

        return False

    def convert_to_nosync(self, path: Path) -> NosyncResult:
        """Convert a directory to .nosync format.

        Renames directory to .nosync suffix and creates symlink.

        Args:
            path: Directory to convert.

        Returns:
            NosyncResult with operation details.

        """
        if not path.exists():
            return NosyncResult(
                path=path,
                success=False,
                action="skipped",
                error="Path does not exist",
            )

        if not path.is_dir():
            return NosyncResult(
                path=path,
                success=False,
                action="skipped",
                error="Not a directory",
            )

        if path.is_symlink():
            return NosyncResult(
                path=path,
                success=False,
                action="skipped",
                error="Already a symlink",
            )

        nosync_path = path.parent / f"{path.name}.nosync"

        if nosync_path.exists():
            return NosyncResult(
                path=path,
                success=False,
                action="skipped",
                error=f"{nosync_path.name} already exists",
            )

        try:
            # Rename directory to .nosync
            path.rename(nosync_path)

            # Create symlink from original name to .nosync
            path.symlink_to(nosync_path.name)

            self.logger.info(
                "Converted to nosync: %s -> %s",
                path.name,
                nosync_path.name,
            )

            return NosyncResult(
                path=path,
                success=True,
                action="converted",
                nosync_path=nosync_path,
            )

        except PermissionError as e:
            self.logger.error("Permission denied: %s", e)
            return NosyncResult(
                path=path,
                success=False,
                action="error",
                error=f"Permission denied: {e}",
            )
        except OSError as e:
            self.logger.error("Error converting %s: %s", path, e)
            return NosyncResult(
                path=path,
                success=False,
                action="error",
                error=str(e),
            )

    def scan_for_candidates(self, directory: Path) -> list[Path]:
        """Scan the directory for nosync candidates.

        Args:
            directory: Directory to scan.

        Returns:
            List of directories that should be converted.

        """
        candidates: list[Path] = []

        if not directory.exists():
            return candidates

        try:
            candidates.extend(
                item
                for item in directory.rglob("*")
                if self.is_nosync_candidate(item)
            )
        except PermissionError:
            self.logger.warning("Permission denied scanning: %s", directory)

        return sorted(candidates)

    def scan_all(self) -> list[Path]:
        """Scan all watch directories for nosync candidates.

        Returns:
            List of all directories that should be converted.

        """
        all_candidates: list[Path] = []

        for directory in self.config.watch_directories:
            candidates = self.scan_for_candidates(directory)
            all_candidates.extend(candidates)

        return all_candidates
