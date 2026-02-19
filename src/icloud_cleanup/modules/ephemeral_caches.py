"""Ephemeral cache directory cleanup module.

Detects and deletes regenerable cache directories (.mypy_cache, __pycache__,
.pytest_cache, etc.) that waste iCloud sync bandwidth without providing value.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..nosync import NOSYNC_SUFFIX, NosyncManager
from .base import DetectedFile

if TYPE_CHECKING:
    from ..config import CleanupConfig

logger = logging.getLogger(__name__)


class EphemeralCachesModule:
    """Detects ephemeral cache directories for deletion."""

    MODULE_ENABLED: bool = True
    name: str = "ephemeral_caches"
    supports_watch: bool = True

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config
        self._extra_patterns: frozenset[str] = frozenset(config.nosync_ephemeral_patterns)

    def is_target(self, path: Path) -> DetectedFile | None:
        """Check if a path is an ephemeral cache directory.

        A path matches when it is a directory whose name matches a known
        ephemeral pattern (built-in or user-configured) and does not
        already have a .nosync suffix.
        """
        if NosyncManager.is_ephemeral_candidate(path):
            return DetectedFile(
                path=path,
                module_name=self.name,
                reason=f"Ephemeral cache directory: {path.name}",
                recovery_enabled=False,
            )

        # Check user-configured extra patterns
        if (
            self._extra_patterns
            and path.is_dir()
            and not path.name.endswith(NOSYNC_SUFFIX)
            and NosyncManager.matches_patterns(path.name, self._extra_patterns)
        ):
            return DetectedFile(
                path=path,
                module_name=self.name,
                reason=f"Ephemeral cache directory (custom pattern): {path.name}",
                recovery_enabled=False,
            )

        return None

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        """Scan a directory tree for ephemeral cache directories.

        Skips .nosync subtrees and subtrees of already-found candidates
        to avoid reporting nested caches (e.g. build/lib/__pycache__
        when build/ is already detected).
        """
        detected: list[DetectedFile] = []

        if not directory.exists():
            return detected

        skip_prefixes: list[str] = []

        try:
            for item in directory.rglob("*"):
                item_str = str(item)

                if any(item_str.startswith(prefix) for prefix in skip_prefixes):
                    continue

                # Skip .nosync subtrees
                if item.is_dir() and item.name.endswith(NOSYNC_SUFFIX):
                    skip_prefixes.append(f"{item_str}/")
                    continue

                try:
                    result = self.is_target(item)
                except PermissionError:
                    logger.debug("Permission denied checking: %s", item)
                    continue

                if result:
                    detected.append(result)
                    skip_prefixes.append(f"{item_str}/")
        except PermissionError:
            logger.warning("Permission denied scanning: %s", directory)

        return detected

    def scan_all(self) -> list[DetectedFile]:
        """Scan all configured watch directories."""
        all_detected: list[DetectedFile] = []

        for directory in self.config.watch_directories:
            all_detected.extend(self.scan_directory(directory))

        return all_detected
