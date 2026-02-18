"""Detect iCloud sync conflict files.

Backward-compatibility wrapper — delegates to modules.icloud_conflicts.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from .modules.icloud_conflicts import ConflictFile, ICloudConflictsModule

if TYPE_CHECKING:
    from pathlib import Path

    from .config import CleanupConfig

# Re-export ConflictFile for backward compatibility
__all__ = ["ConflictDetector", "ConflictFile"]


class ConflictDetector:
    """Detects iCloud sync conflict files.

    Thin wrapper around ICloudConflictsModule for backward compatibility.
    """

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config
        self._module = ICloudConflictsModule(config)

    def is_conflict_file(self, path: Path) -> ConflictFile | None:
        """Check if a path is a conflict file.

        Args:
            path: Path to check.

        Returns:
            ConflictFile if it's a conflict, None otherwise.

        """
        return self._module.get_conflict_file(path)

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
                if conflict := self._module.get_conflict_file(path):
                    conflicts.append(conflict)

        return conflicts

    def scan_all(self) -> list[ConflictFile]:
        """Scan all configured watch directories.

        Returns:
            List of all conflict files found.

        """
        all_conflicts: list[ConflictFile] = []
        for directory in self.config.watch_directories:
            all_conflicts.extend(self.scan_directory(directory))
        return all_conflicts

    def find_related_conflicts(self, path: Path) -> list[ConflictFile]:
        """Find all conflict versions of a file.

        Args:
            path: Path to check (can be original or conflict).

        Returns:
            List of conflict files for the same original.

        """
        conflict = self._module.get_conflict_file(path)
        original = conflict.original_path if conflict else path
        parent = original.parent
        stem = original.stem
        suffix = original.suffix

        conflicts: list[ConflictFile] = []
        with contextlib.suppress(PermissionError):
            for sibling in parent.iterdir():
                if sibling_conflict := self._module.get_conflict_file(sibling):
                    expected_original = f"{stem}"
                    ext_matches = sibling_conflict.extension == suffix
                    ext_both_none = sibling_conflict.extension is None and not suffix
                    if sibling_conflict.original_name == expected_original and (ext_matches or ext_both_none):
                        conflicts.append(sibling_conflict)
        return sorted(conflicts, key=lambda c: c.conflict_number)
