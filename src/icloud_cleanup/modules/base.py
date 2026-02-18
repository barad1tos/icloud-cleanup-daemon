"""Base protocol and types for cleanup modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DetectedFile:
    """Immutable record of a file flagged for cleanup, with module provenance."""

    path: Path
    module_name: str
    reason: str
    recovery_enabled: bool


@runtime_checkable
class CleanupModule(Protocol):
    """Interface for pluggable file-detection strategies."""

    MODULE_ENABLED: bool
    name: str
    supports_watch: bool

    def is_target(self, path: Path) -> DetectedFile | None:
        """Check if a single file is a target for this module.

        Args:
            path: Path to check.

        Returns:
            DetectedFile if the file should be cleaned, None otherwise.

        """
        ...

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        """Scan a directory for files to clean.

        Args:
            directory: Directory to scan.

        Returns:
            List of detected files.

        """
        ...

    def scan_all(self) -> list[DetectedFile]:
        """Scan all configured directories.

        Returns:
            List of all detected files.

        """
        ...
