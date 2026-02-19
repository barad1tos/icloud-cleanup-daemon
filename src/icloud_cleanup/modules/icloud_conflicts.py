"""iCloud conflict file cleanup module."""

from __future__ import annotations

import errno
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .base import DetectedFile

if TYPE_CHECKING:
    from ..config import CleanupConfig

logger = logging.getLogger(__name__)


@dataclass
class ConflictFile:
    """Parsed components of an iCloud conflict filename (original name, number, extension)."""

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
        """Match a path against the conflict pattern."""
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
        """Check if a path is an iCloud conflict file with an existing original."""
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

    def _check_single_path(self, path: Path) -> DetectedFile | None:
        """Check a single path, handling iCloud transient errors."""
        try:
            return self.is_target(path)
        except PermissionError:
            logger.debug("Permission denied checking: %s", path)
        except OSError as exc:
            if exc.errno == errno.EDEADLK:
                logger.warning("EDEADLK (iCloud transient) — skipping: %s", path)
            else:
                raise
        return None

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        """Scan a directory for conflict files."""
        if not directory.exists():
            return []

        detected: list[DetectedFile] = []
        try:
            for path in directory.rglob("*"):
                if result := self._check_single_path(path):
                    detected.append(result)
        except PermissionError:
            logger.warning("Permission denied scanning: %s", directory)
        except OSError as exc:
            if exc.errno == errno.EDEADLK:
                logger.warning("EDEADLK (iCloud transient) during rglob — aborting scan: %s", directory)
            else:
                raise

        return detected

    def scan_all(self) -> list[DetectedFile]:
        """Scan all configured watch directories."""
        all_detected: list[DetectedFile] = []

        for directory in self.config.watch_directories:
            all_detected.extend(self.scan_directory(directory))

        return all_detected

    def get_conflict_file(self, path: Path) -> ConflictFile | None:
        """Get ConflictFile for a path (for backward compatibility)."""
        return self._match_conflict(path)
