"""Detect iCloud sync conflict files.

Backward-compatibility wrapper — delegates to modules.icloud_conflicts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .modules.icloud_conflicts import ConflictFile, ICloudConflictsModule

if TYPE_CHECKING:
    from pathlib import Path

    from .config import CleanupConfig

# Re-export ConflictFile for backward compatibility
__all__ = ["ConflictDetector", "ConflictFile"]

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Thin wrapper around ICloudConflictsModule for backward compatibility."""

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config
        self._module = ICloudConflictsModule(config)

    def is_conflict_file(self, path: Path) -> ConflictFile | None:
        """Check if a path is a conflict file."""
        return self._module.get_conflict_file(path)

    def scan_directory(self, directory: Path, *, recursive: bool = True) -> list[ConflictFile]:
        """Scan a directory for conflict files."""
        conflicts: list[ConflictFile] = []

        if not directory.exists():
            return conflicts

        try:
            files = directory.rglob("*") if recursive else directory.glob("*")
            for path in files:
                try:
                    conflict = self._module.get_conflict_file(path)
                except PermissionError:
                    logger.debug("Permission denied checking: %s", path)
                    continue
                if conflict:
                    conflicts.append(conflict)
        except PermissionError:
            logger.warning("Permission denied scanning: %s", directory)

        return conflicts

    def scan_all(self) -> list[ConflictFile]:
        """Scan all configured watch directories."""
        all_conflicts: list[ConflictFile] = []
        for directory in self.config.watch_directories:
            all_conflicts.extend(self.scan_directory(directory))
        return all_conflicts

    def find_related_conflicts(self, path: Path) -> list[ConflictFile]:
        """Find all conflict versions of a file sharing the same original."""
        conflict = self._module.get_conflict_file(path)
        original = conflict.original_path if conflict else path
        parent = original.parent
        stem = original.stem
        suffix = original.suffix

        conflicts: list[ConflictFile] = []
        try:
            for sibling in parent.iterdir():
                try:
                    sibling_conflict = self._module.get_conflict_file(sibling)
                except PermissionError:
                    continue
                if sibling_conflict is None:
                    continue
                ext_matches = sibling_conflict.extension == suffix
                ext_both_none = sibling_conflict.extension is None and not suffix
                if sibling_conflict.original_name == stem and (ext_matches or ext_both_none):
                    conflicts.append(sibling_conflict)
        except PermissionError:
            logger.warning("Permission denied listing: %s", parent)
        return sorted(conflicts, key=lambda conflict_file: conflict_file.conflict_number)
