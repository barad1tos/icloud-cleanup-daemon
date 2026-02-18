"""Coverage artifact cleanup module.

Detects stale .coverage.<host>.pid<N>.<hash> files left by parallel
coverage.py runs when the merged .coverage database exists.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .base import DetectedFile

if TYPE_CHECKING:
    from ..config import CleanupConfig

_PATTERN = re.compile(r"^\.coverage\..+\.pid\d+\..+$")
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", ".tox", "__pycache__"})


class CoverageArtifactsModule:
    """Detects and cleans up stale coverage.py parallel artifacts."""

    MODULE_ENABLED: bool = True
    name: str = "coverage_artifacts"
    supports_watch: bool = False

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config

    def is_target(self, path: Path) -> DetectedFile | None:
        """Check if a file is a stale coverage artifact.

        A file matches when:
        1. Its name matches .coverage.<host>.pid<N>.<hash>
        2. A merged .coverage file exists in the same directory

        Args:
            path: Path to check.

        Returns:
            DetectedFile if the file is a stale artifact, None otherwise.

        """
        if not path.is_file():
            return None

        if not _PATTERN.match(path.name):
            return None

        merged = path.parent / ".coverage"
        if not merged.is_file():
            return None

        return DetectedFile(
            path=path,
            module_name=self.name,
            reason="Stale coverage artifact (merged .coverage exists)",
            recovery_enabled=False,
        )

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        """Scan a directory for stale coverage artifacts.

        Args:
            directory: Directory to scan.

        Returns:
            List of detected coverage artifacts.

        """
        detected: list[DetectedFile] = []

        if not directory.exists():
            return detected

        with contextlib.suppress(PermissionError):
            for path in directory.rglob(".*"):
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                if result := self.is_target(path):
                    detected.append(result)

        return detected

    def scan_all(self) -> list[DetectedFile]:
        """Scan all configured watch directories.

        Returns:
            List of all detected coverage artifacts.

        """
        all_detected: list[DetectedFile] = []

        for directory in self.config.watch_directories:
            all_detected.extend(self.scan_directory(directory))

        return all_detected
