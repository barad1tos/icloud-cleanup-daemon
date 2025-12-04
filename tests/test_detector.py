"""Tests for conflict detection."""

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.detector import ConflictDetector


@pytest.fixture
def config() -> CleanupConfig:
    """Create test configuration."""
    return CleanupConfig()


@pytest.fixture
def detector(config: CleanupConfig) -> ConflictDetector:
    """Create conflict detector."""
    return ConflictDetector(config)


class TestConflictPattern:
    """Tests for conflict file pattern matching."""

    @pytest.mark.parametrize(
        "filename,expected_original,expected_num",
        [
            ("document 2.txt", "document", 2),
            ("document 3.txt", "document", 3),
            ("my file 2.csv", "my file", 2),
            ("pending_year_verification 5.csv", "pending_year_verification", 5),
            ("file.name 2.tar.gz", "file.name 2.tar", 2),  # handles complex extensions
        ],
    )
    def test_detects_conflict_files(
        self,
        detector: ConflictDetector,
        tmp_path: Path,
        filename: str,
        expected_original: str,
        expected_num: int,
    ) -> None:
        """Test that conflict files are detected correctly."""
        # Create test file
        test_file = tmp_path / filename
        test_file.touch()

        conflict = detector.is_conflict_file(test_file)

        assert conflict is not None
        assert conflict.original_name == expected_original
        assert conflict.conflict_number == expected_num

    @pytest.mark.parametrize(
        "filename",
        [
            "document.txt",
            "my file.csv",
            "file2.txt",  # no space before number
            "file 1.txt",  # 1 is not a conflict number
            "2 file.txt",  # number at start
        ],
    )
    def test_ignores_non_conflict_files(
        self,
        detector: ConflictDetector,
        tmp_path: Path,
        filename: str,
    ) -> None:
        """Test that regular files are not detected as conflicts."""
        test_file = tmp_path / filename
        test_file.touch()

        conflict = detector.is_conflict_file(test_file)

        assert conflict is None


class TestDirectoryScan:
    """Tests for directory scanning."""

    def test_scan_finds_conflicts(
        self,
        detector: ConflictDetector,
        tmp_path: Path,
    ) -> None:
        """Test that scan finds conflict files in directory."""
        # Create original and conflict files
        (tmp_path / "document.txt").touch()
        (tmp_path / "document 2.txt").touch()
        (tmp_path / "document 3.txt").touch()
        (tmp_path / "other.csv").touch()

        conflicts = detector.scan_directory(tmp_path)

        assert len(conflicts) == 2
        names = {c.path.name for c in conflicts}
        assert "document 2.txt" in names
        assert "document 3.txt" in names

    def test_scan_recursive(
        self,
        detector: ConflictDetector,
        tmp_path: Path,
    ) -> None:
        """Test that recursive scan finds nested conflicts."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "root 2.txt").touch()
        (subdir / "nested 2.txt").touch()

        conflicts = detector.scan_directory(tmp_path, recursive=True)

        assert len(conflicts) == 2

    def test_scan_non_recursive(
        self,
        detector: ConflictDetector,
        tmp_path: Path,
    ) -> None:
        """Test that non-recursive scan ignores nested files."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "root 2.txt").touch()
        (subdir / "nested 2.txt").touch()

        conflicts = detector.scan_directory(tmp_path, recursive=False)

        assert len(conflicts) == 1
        assert conflicts[0].path.name == "root 2.txt"
