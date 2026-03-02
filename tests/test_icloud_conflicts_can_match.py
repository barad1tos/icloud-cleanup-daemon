"""Tests for ICloudConflictsModule.can_match string pre-filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.icloud_conflicts import ICloudConflictsModule


@pytest.fixture
def module(tmp_path: Path) -> ICloudConflictsModule:
    """Create a module with default config."""
    config = CleanupConfig()
    config.watch_directories = [tmp_path]
    return ICloudConflictsModule(config)


class TestCanMatch:
    """Tests for can_match string pre-filter."""

    def test_matches_conflict_pattern(self, module: ICloudConflictsModule) -> None:
        """Test that conflict filenames pass the pre-filter."""
        assert module.can_match("document 2.txt") is True
        assert module.can_match("file 3.pdf") is True
        assert module.can_match("photo 10.jpg") is True

    def test_rejects_non_conflict_names(self, module: ICloudConflictsModule) -> None:
        """Test that normal filenames are rejected."""
        assert module.can_match("document.txt") is False
        assert module.can_match("file.txt") is False
        assert module.can_match("2 file.txt") is False

    def test_rejects_number_one(self, module: ICloudConflictsModule) -> None:
        """Test that filenames with number 1 are rejected (iCloud starts at 2)."""
        assert module.can_match("document 1.txt") is False

    def test_matches_hidden_files(self, module: ICloudConflictsModule) -> None:
        """Test that hidden conflict files pass."""
        assert module.can_match(".hidden 2") is True

    def test_no_io_performed(self, module: ICloudConflictsModule) -> None:
        """Test that can_match works on pure strings without filesystem access."""
        assert module.can_match("nonexistent 2.xyz") is True


class TestIsTargetReordering:
    """Tests verifying regex is checked before stat."""

    def test_non_matching_name_returns_none(
        self, module: ICloudConflictsModule, tmp_path: Path
    ) -> None:
        """Test that non-matching names return None without stat calls."""
        regular = tmp_path / "document.txt"
        regular.touch()
        assert module.is_target(regular) is None

    def test_matching_conflict_detected(
        self, module: ICloudConflictsModule, tmp_path: Path
    ) -> None:
        """Test that matching conflicts are still detected after reordering."""
        original = tmp_path / "document.txt"
        original.touch()
        conflict = tmp_path / "document 2.txt"
        conflict.touch()
        result = module.is_target(conflict)
        assert result is not None
        assert result.module_name == "icloud_conflicts"

    def test_missing_original_returns_none(
        self, module: ICloudConflictsModule, tmp_path: Path
    ) -> None:
        """Test that a conflict without its original returns None."""
        conflict = tmp_path / "document 2.txt"
        conflict.touch()
        assert module.is_target(conflict) is None
