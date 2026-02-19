"""Exclude directories from iCloud sync using .nosync suffix."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import CleanupConfig

NosyncAction = Literal["converted", "skipped", "error"]

# Valuable directories: slow to rebuild, keep nosync+symlink approach
VALUABLE_PATTERNS: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        ".env",
        "node_modules",
    }
)

# Ephemeral caches: fast to regenerate, can be deleted outright
EPHEMERAL_PATTERNS: frozenset[str] = frozenset(
    {
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
    }
)

# Union of both categories — backward compatible
DEFAULT_EXCLUDE_PATTERNS: frozenset[str] = VALUABLE_PATTERNS | EPHEMERAL_PATTERNS


@dataclass
class NosyncResult:
    """Result of a nosync operation."""

    path: Path
    success: bool
    action: NosyncAction
    nosync_path: Path | None = None
    error: str | None = None


class NosyncManager:
    """Manages .nosync exclusions for iCloud directories."""

    def __init__(self, config: CleanupConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    @staticmethod
    def is_nosync_candidate(path: Path) -> bool:
        """Check if a directory should be excluded from iCloud sync."""
        if not path.is_dir():
            return False
        if path.name.endswith(".nosync"):
            return False
        return NosyncManager._matches_patterns(path.name, DEFAULT_EXCLUDE_PATTERNS)

    @staticmethod
    def is_valuable_candidate(path: Path) -> bool:
        """Check if a directory is a valuable nosync candidate (slow to rebuild)."""
        if not path.is_dir() or path.name.endswith(".nosync"):
            return False
        return NosyncManager._matches_patterns(path.name, VALUABLE_PATTERNS)

    @staticmethod
    def is_ephemeral_candidate(path: Path) -> bool:
        """Check if a directory is an ephemeral cache (fast to regenerate)."""
        if not path.is_dir() or path.name.endswith(".nosync"):
            return False
        return NosyncManager._matches_patterns(path.name, EPHEMERAL_PATTERNS)

    @staticmethod
    def _matches_patterns(name: str, patterns: frozenset[str]) -> bool:
        """Check a directory name against a set of patterns (exact or wildcard)."""
        for pattern in patterns:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    def convert_to_nosync(self, path: Path) -> NosyncResult:
        """Rename the directory to .nosync suffix and create a symlink at the original path."""
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

            # Create symlink from the original name to .nosync
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

        except PermissionError as error:
            self.logger.error("Permission denied: %s", error)
            return NosyncResult(
                path=path,
                success=False,
                action="error",
                error=f"Permission denied: {error}",
            )
        except OSError as error:
            self.logger.error("OS error converting %s: %s", path, error)
            return NosyncResult(
                path=path,
                success=False,
                action="error",
                error=f"OS error: {error}",
            )

    def scan_for_candidates(self, directory: Path) -> list[Path]:
        """Scan the directory tree, skipping subtrees of found candidates and .nosync dirs."""
        candidates: list[Path] = []

        if not directory.exists():
            return candidates

        skip_prefixes: list[str] = []

        try:
            for item in directory.rglob("*"):
                item_str = str(item)

                if any(item_str.startswith(prefix) for prefix in skip_prefixes):
                    continue

                try:
                    is_candidate = self.is_nosync_candidate(item)
                except PermissionError:
                    self.logger.warning(
                        "Permission denied checking: %s",
                        item,
                    )
                    continue

                if is_candidate:
                    candidates.append(item)
                    skip_prefixes.append(f"{item_str}/")
                elif item.is_dir() and item.name.endswith(".nosync"):
                    skip_prefixes.append(f"{item_str}/")
        except PermissionError:
            self.logger.warning("Permission denied scanning: %s", directory)

        return sorted(candidates)

    def scan_all(self) -> list[Path]:
        """Scan all watch directories for nosync candidates."""
        all_candidates: list[Path] = []

        for directory in self.config.watch_directories:
            candidates = self.scan_for_candidates(directory)
            all_candidates.extend(candidates)

        return all_candidates
