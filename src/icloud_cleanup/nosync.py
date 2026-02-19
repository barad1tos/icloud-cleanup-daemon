"""Exclude directories from iCloud sync using .nosync suffix."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import CleanupConfig

NosyncAction = Literal["converted", "skipped", "error"]

NOSYNC_SUFFIX: str = ".nosync"

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
class RepairResult:
    """Result of a symlink repair operation."""

    nosync_path: Path
    original_name: str
    action: Literal["repaired", "warning", "error"]
    detail: str


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
        if path.name.endswith(NOSYNC_SUFFIX):
            return False
        return NosyncManager.matches_patterns(path.name, DEFAULT_EXCLUDE_PATTERNS)

    @staticmethod
    def is_valuable_candidate(path: Path) -> bool:
        """Check if a directory is a valuable nosync candidate (slow to rebuild)."""
        if not path.is_dir() or path.name.endswith(NOSYNC_SUFFIX):
            return False
        return NosyncManager.matches_patterns(path.name, VALUABLE_PATTERNS)

    @staticmethod
    def is_ephemeral_candidate(path: Path) -> bool:
        """Check if a directory is an ephemeral cache (fast to regenerate)."""
        if not path.is_dir() or path.name.endswith(NOSYNC_SUFFIX):
            return False
        return NosyncManager.matches_patterns(path.name, EPHEMERAL_PATTERNS)

    @staticmethod
    def matches_patterns(name: str, patterns: frozenset[str]) -> bool:
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

        nosync_path = path.parent / f"{path.name}{NOSYNC_SUFFIX}"

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
                elif item.is_dir() and item.name.endswith(NOSYNC_SUFFIX):
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

    def _get_valuable_patterns(self) -> frozenset[str]:
        """Return built-in valuable patterns extended by user config."""
        if self.config.nosync_valuable_patterns:
            return VALUABLE_PATTERNS | frozenset(self.config.nosync_valuable_patterns)
        return VALUABLE_PATTERNS

    def verify_and_repair(self, directory: Path) -> list[RepairResult]:
        """Check .nosync directories for broken symlinks and repair them.

        Only processes valuable patterns (e.g. .venv, node_modules) since
        ephemeral caches don't need symlink preservation. User-configured
        valuable patterns from ``nosync.valuable_patterns`` are also included.

        Args:
            directory: Parent directory to scan for .nosync children.

        Returns:
            List of repair actions taken. Empty if everything is healthy.
        """
        if not directory.exists():
            return []

        results: list[RepairResult] = []
        valuable = self._get_valuable_patterns()

        try:
            children = sorted(directory.iterdir())
        except PermissionError:
            self.logger.warning("Permission denied listing: %s", directory)
            return []

        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if not child.name.endswith(NOSYNC_SUFFIX):
                continue

            original_name = child.name.removesuffix(NOSYNC_SUFFIX)
            if not self.matches_patterns(original_name, valuable):
                continue

            result = self._repair_symlink(directory, child, original_name)
            if result is not None:
                results.append(result)

        return results

    def _remove_conflict_symlinks(self, parent: Path, original_name: str) -> None:
        """Remove all iCloud conflict symlinks for a given name (e.g. '.venv 2', '.venv 3')."""
        try:
            children = parent.iterdir()
        except PermissionError:
            return

        conflict_re = re.compile(rf"^{re.escape(original_name)}\s+([2-9]|\d{{2,}})$")
        for child in children:
            if child.is_symlink() and conflict_re.match(child.name):
                try:
                    child.unlink()
                    self.logger.info("Removed conflict symlink: %s", child.name)
                except OSError as error:
                    self.logger.warning("Failed to remove conflict symlink %s: %s", child.name, error)

    def _repair_symlink(
        self,
        parent: Path,
        nosync_path: Path,
        original_name: str,
    ) -> RepairResult | None:
        """Ensure a correct symlink exists for a .nosync directory.

        Handles iCloud conflict symlinks (e.g. '.venv 2', '.venv 3')
        by removing them and recreating the proper symlink at the original name.

        Args:
            parent: Directory containing the .nosync dir and symlink.
            nosync_path: The .nosync directory path.
            original_name: Expected symlink name (without .nosync suffix).

        Returns:
            RepairResult if an action was taken, None if the symlink is healthy.
        """
        # Clean up all iCloud conflict symlinks (e.g. ".venv 2", ".venv 3", etc.)
        self._remove_conflict_symlinks(parent, original_name)

        symlink_path = parent / original_name

        # Healthy: valid symlink pointing to the correct target
        if symlink_path.is_symlink():
            target = symlink_path.readlink()
            if target == Path(nosync_path.name):
                return None

            # Wrong target -- fix it
            try:
                symlink_path.unlink()
                symlink_path.symlink_to(nosync_path.name)
                self.logger.info(
                    "Repaired symlink target: %s -> %s",
                    original_name,
                    nosync_path.name,
                )
                return RepairResult(
                    nosync_path=nosync_path,
                    original_name=original_name,
                    action="repaired",
                    detail=f"Fixed symlink target from {target} to {nosync_path.name}",
                )
            except OSError as error:
                return RepairResult(
                    nosync_path=nosync_path,
                    original_name=original_name,
                    action="error",
                    detail=f"Failed to fix symlink target: {error}",
                )

        # Real directory at the original name -- don't touch it
        if symlink_path.exists():
            self.logger.warning(
                "Real directory exists at symlink location: %s",
                symlink_path,
            )
            return RepairResult(
                nosync_path=nosync_path,
                original_name=original_name,
                action="warning",
                detail=f"Real directory exists at {original_name}, cannot create symlink",
            )

        # No symlink exists -- create one
        try:
            symlink_path.symlink_to(nosync_path.name)
            self.logger.info(
                "Created missing symlink: %s -> %s",
                original_name,
                nosync_path.name,
            )
            return RepairResult(
                nosync_path=nosync_path,
                original_name=original_name,
                action="repaired",
                detail=f"Created symlink {original_name} -> {nosync_path.name}",
            )
        except OSError as error:
            return RepairResult(
                nosync_path=nosync_path,
                original_name=original_name,
                action="error",
                detail=f"Failed to create symlink: {error}",
            )
