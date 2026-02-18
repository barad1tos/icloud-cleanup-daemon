"""iCloud conflict file cleanup module."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .base import DetectedFile

if TYPE_CHECKING:
    from ..config import CleanupConfig


@dataclass
class ConflictFile:
    """Represents an iCloud sync conflict file."""

    path: Path
    original_name: str
    conflict_number: int
    extension: str | None

    @property
    def original_path(self) -> Path:
        """Get the path to the original (non-conflict) file."""
        original_filename = f"{self.original_name}{self.extension}" if self.extension else self.original_name
        return self.path.parent / original_filename

    def __str__(self) -> str:
        return f"ConflictFile({self.path.name} -> {self.original_path.name})"


class ICloudConflictsModule:
    """Detects and manages iCloud sync conflict files."""

    MODULE_ENABLED: bool = True
    name: str = "icloud_conflicts"
    supports_watch: bool = True

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config
        self._pattern = re.compile(config.conflict_pattern)

    def _match_conflict(self, path: Path) -> ConflictFile | None:
        """Match a path against the conflict pattern.

        Args:
            path: Path to check.

        Returns:
            ConflictFile if it matches, None otherwise.

        """
        if not path.is_file():
            return None

        match = self._pattern.match(path.name)
        if not match:
            return None

        original_name = match.group(1).rstrip()
        conflict_number = int(match.group(2))
        extension = match.group(3) if match.lastindex and match.lastindex >= 3 else None

        return ConflictFile(
            path=path,
            original_name=original_name,
            conflict_number=conflict_number,
            extension=extension,
        )

    def is_target(self, path: Path) -> DetectedFile | None:
        """Check if a path is an iCloud conflict file with an existing original.

        Args:
            path: Path to check.

        Returns:
            DetectedFile if it's a valid conflict, None otherwise.

        """
        conflict = self._match_conflict(path)
        if conflict is None:
            return None

        if not conflict.original_path.exists():
            return None

        return DetectedFile(
            path=path,
            module_name=self.name,
            reason=f"iCloud conflict #{conflict.conflict_number} of {conflict.original_path.name}",
            recovery_enabled=True,
        )

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        """Scan a directory for conflict files.

        Args:
            directory: Directory to scan.

        Returns:
            List of detected conflict files.

        """
        detected: list[DetectedFile] = []

        if not directory.exists():
            return detected

        with contextlib.suppress(PermissionError):
            for path in directory.rglob("*"):
                if result := self.is_target(path):
                    detected.append(result)

        return detected

    def scan_all(self) -> list[DetectedFile]:
        """Scan all configured watch directories.

        Returns:
            List of all detected conflict files.

        """
        all_detected: list[DetectedFile] = []

        for directory in self.config.watch_directories:
            all_detected.extend(self.scan_directory(directory))

        return all_detected

    # Backward-compat helpers for code that still uses ConflictFile

    def get_conflict_file(self, path: Path) -> ConflictFile | None:
        """Get ConflictFile for a path (for backward compatibility).

        Args:
            path: Path to check.

        Returns:
            ConflictFile if it matches the pattern, None otherwise.

        """
        return self._match_conflict(path)
