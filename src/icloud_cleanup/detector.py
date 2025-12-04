"""Detect iCloud sync conflict files."""


from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CleanupConfig


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


class ConflictDetector:
    """Detects iCloud sync conflict files."""

    def __init__(self, config: CleanupConfig) -> None:
        """Initialize the detector.

        Args:
            config: Cleanup configuration.

        """
        self.config = config
        self._pattern = re.compile(config.conflict_pattern)

    def is_conflict_file(self, path: Path) -> ConflictFile | None:
        """Check if a path is a conflict file.

        Args:
            path: Path to check.

        Returns:
            ConflictFile if it's a conflict, None otherwise.

        """
        if not path.is_file():
            return None

        filename = path.name
        match = self._pattern.match(filename)

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

    def scan_directory(self, directory: Path, *, recursive: bool = True) -> list[ConflictFile]:
        """Scan a directory for conflict files.

        Args:
            directory: Directory to scan.
            recursive: Whether to scan subdirectories.

        Returns:
            List of conflict files found.

        """
        conflicts: list[ConflictFile] = []

        if not directory.exists():
            return conflicts

        with contextlib.suppress(PermissionError):
            files = directory.rglob("*") if recursive else directory.glob("*")
            for path in files:
                if conflict := self.is_conflict_file(path):
                    conflicts.append(conflict)

        return conflicts

    def scan_all(self) -> list[ConflictFile]:
        """Scan all configured watch directories.

        Returns:
            List of all conflict files found.

        """
        all_conflicts: list[ConflictFile] = []

        for directory in self.config.watch_directories:
            conflicts = self.scan_directory(directory)
            all_conflicts.extend(conflicts)

        return all_conflicts

    def find_related_conflicts(self, path: Path) -> list[ConflictFile]:
        """Find all conflict versions of a file.

        Args:
            path: Path to check (can be original or conflict).

        Returns:
            List of conflict files for the same original.

        """
        # First check if this path itself is a conflict
        conflict = self.is_conflict_file(path)
        original = conflict.original_path if conflict else path
        # Find all conflicts in the same directory
        parent = original.parent
        stem = original.stem
        suffix = original.suffix

        conflicts: list[ConflictFile] = []
        with contextlib.suppress(PermissionError):
            for sibling in parent.iterdir():
                if sibling_conflict := self.is_conflict_file(sibling):
                    # Check if it's for the same original file
                    expected_original = f"{stem}"
                    ext_matches = sibling_conflict.extension == suffix
                    ext_both_none = sibling_conflict.extension is None and not suffix
                    if sibling_conflict.original_name == expected_original and (ext_matches or ext_both_none):
                        conflicts.append(sibling_conflict)
        return sorted(conflicts, key=lambda c: c.conflict_number)
