"""Tests for the iCloud conflicts cleanup module."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.base import DetectedFile
from icloud_cleanup.modules.icloud_conflicts import ConflictFile, ICloudConflictsModule


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration with tmp_path as a watch directory."""
    cleanup_config = CleanupConfig()
    cleanup_config.watch_directories = [tmp_path]
    return cleanup_config


@pytest.fixture
def module(config: CleanupConfig) -> ICloudConflictsModule:
    """Create iCloud conflicts module instance."""
    return ICloudConflictsModule(config)


class TestModuleAttributes:
    """Tests for module class-level attributes."""

    def test_module_enabled(self, module: ICloudConflictsModule) -> None:
        """Module should be enabled by default."""
        assert module.MODULE_ENABLED is True

    def test_module_name(self, module: ICloudConflictsModule) -> None:
        """The module name should be 'icloud_conflicts'."""
        assert module.name == "icloud_conflicts"

    def test_supports_watch(self, module: ICloudConflictsModule) -> None:
        """Module should support file system watching."""
        assert module.supports_watch is True


class TestIsTarget:
    """Tests for is_target conflict detection with the original file check."""

    def test_conflict_with_original_present(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """A conflict file with an existing original returns DetectedFile."""
        (tmp_path / "document.txt").touch()
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert isinstance(result, DetectedFile)
        assert result.recovery_enabled is True

    def test_conflict_without_original(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """A conflict file without an existing original returns None."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is None

    def test_non_conflict_filename(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """A regular file that does not match the conflict pattern returns None."""
        regular_file = tmp_path / "regular.txt"
        regular_file.touch()

        result = module.is_target(regular_file)

        assert result is None

    def test_directory_not_detected(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Directory matching conflict name pattern returns None."""
        directory = tmp_path / "dir 2"
        directory.mkdir()

        result = module.is_target(directory)

        assert result is None


class TestDetectedFileFields:
    """Tests for DetectedFile fields returned by is_target."""

    def test_module_name_field(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """DetectedFile module_name matches the module's name."""
        (tmp_path / "notes.txt").touch()
        conflict_file = tmp_path / "notes 2.txt"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert result.module_name == "icloud_conflicts"

    def test_reason_includes_conflict_number(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Reason string includes the conflict number."""
        (tmp_path / "report.pdf").touch()
        conflict_file = tmp_path / "report 5.pdf"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert "#5" in result.reason

    def test_reason_includes_original_filename(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Reason string references the original file name."""
        (tmp_path / "report.pdf").touch()
        conflict_file = tmp_path / "report 3.pdf"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert "report.pdf" in result.reason

    def test_recovery_enabled(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """DetectedFile always has recovery_enabled=True."""
        (tmp_path / "data.csv").touch()
        conflict_file = tmp_path / "data 2.csv"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert result.recovery_enabled is True

    def test_path_field(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """DetectedFile path matches the conflict file path."""
        (tmp_path / "image.png").touch()
        conflict_file = tmp_path / "image 2.png"
        conflict_file.touch()

        result = module.is_target(conflict_file)

        assert result is not None
        assert result.path == conflict_file


class TestScanDirectory:
    """Tests for scan_directory recursive scanning."""

    def test_finds_conflicts_in_directory(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Scan finds all conflict files that have matching originals."""
        (tmp_path / "document.txt").touch()
        (tmp_path / "document 2.txt").touch()
        (tmp_path / "document 3.txt").touch()
        (tmp_path / "other.csv").touch()

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 2
        names = {d.path.name for d in detected}
        assert names == {"document 2.txt", "document 3.txt"}

    def test_finds_conflicts_in_nested_subdirs(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Scan descends into subdirectories via rglob."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        deep_dir = subdir / "deep"
        deep_dir.mkdir()

        # Root-level conflict
        (tmp_path / "root.txt").touch()
        (tmp_path / "root 2.txt").touch()

        # Nested conflict
        (subdir / "nested.txt").touch()
        (subdir / "nested 2.txt").touch()

        # Deeply nested conflict
        (deep_dir / "deep.txt").touch()
        (deep_dir / "deep 2.txt").touch()

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 3
        names = {d.path.name for d in detected}
        assert names == {"root 2.txt", "nested 2.txt", "deep 2.txt"}

    def test_nonexistent_directory_returns_empty(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Scanning a nonexistent directory returns an empty list."""
        nonexistent = tmp_path / "does_not_exist"

        detected = module.scan_directory(nonexistent)

        assert detected == []

    def test_skips_conflicts_without_original(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Scan skips conflict-patterned files whose originals are missing."""
        (tmp_path / "orphan 2.txt").touch()

        detected = module.scan_directory(tmp_path)

        assert detected == []


class TestScanAll:
    """Tests for scan_all across configured watch directories."""

    def test_scans_all_watch_directories(self, tmp_path: Path) -> None:
        """scan_all aggregates results from all configured watch directories."""
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "alpha.txt").touch()
        (dir_a / "alpha 2.txt").touch()
        (dir_b / "beta.txt").touch()
        (dir_b / "beta 2.txt").touch()

        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = [dir_a, dir_b]
        module = ICloudConflictsModule(cleanup_config)

        detected = module.scan_all()

        assert len(detected) == 2
        names = {d.path.name for d in detected}
        assert names == {"alpha 2.txt", "beta 2.txt"}

    def test_empty_watch_directories(self) -> None:
        """scan_all with no watch directories returns an empty list."""
        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = []
        module = ICloudConflictsModule(cleanup_config)

        detected = module.scan_all()

        assert detected == []


class TestGetConflictFile:
    """Tests for get_conflict_file backward compatibility helper."""

    def test_returns_conflict_file_for_match(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Returns ConflictFile with correct fields for a matching file."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()

        result = module.get_conflict_file(conflict_file)

        assert result is not None
        assert isinstance(result, ConflictFile)
        assert result.path == conflict_file
        assert result.original_name == "document"
        assert result.conflict_number == 2
        assert result.extension == ".txt"

    def test_returns_none_for_non_conflict(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Returns None for a file that does not match the conflict pattern."""
        regular_file = tmp_path / "regular.txt"
        regular_file.touch()

        result = module.get_conflict_file(regular_file)

        assert result is None

    def test_file_without_extension(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """Returns ConflictFile with None extension for extensionless files."""
        conflict_file = tmp_path / ".coverage 2"
        conflict_file.touch()

        result = module.get_conflict_file(conflict_file)

        assert result is not None
        assert result.original_name == ".coverage"
        assert result.conflict_number == 2
        assert result.extension is None

    def test_does_not_require_original(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """get_conflict_file does not check for original file existence."""
        conflict_file = tmp_path / "orphan 3.txt"
        conflict_file.touch()

        result = module.get_conflict_file(conflict_file)

        assert result is not None
        assert result.conflict_number == 3


class TestConflictFileOriginalPath:
    """Tests for ConflictFile.original_path property."""

    def test_original_path_with_extension(self, tmp_path: Path) -> None:
        """Constructs the correct original path when an extension is present."""
        conflict = ConflictFile(
            path=tmp_path / "document 2.txt",
            original_name="document",
            conflict_number=2,
            extension=".txt",
        )

        assert conflict.original_path == tmp_path / "document.txt"

    def test_original_path_without_extension(self, tmp_path: Path) -> None:
        """Constructs the correct original path when the extension is None."""
        conflict = ConflictFile(
            path=tmp_path / ".coverage 2",
            original_name=".coverage",
            conflict_number=2,
            extension=None,
        )

        assert conflict.original_path == tmp_path / ".coverage"

    def test_original_path_preserves_parent(self, tmp_path: Path) -> None:
        """The original path is in the same parent directory as the conflict."""
        subdir = tmp_path / "nested" / "deep"
        conflict = ConflictFile(
            path=subdir / "notes 3.md",
            original_name="notes",
            conflict_number=3,
            extension=".md",
        )

        assert conflict.original_path == subdir / "notes.md"
        assert conflict.original_path.parent == conflict.path.parent

    def test_str_representation(self, tmp_path: Path) -> None:
        """ConflictFile __str__ shows mapping from conflict to original."""
        conflict = ConflictFile(
            path=tmp_path / "report 2.pdf",
            original_name="report",
            conflict_number=2,
            extension=".pdf",
        )

        result = str(conflict)

        assert "report 2.pdf" in result
        assert "report.pdf" in result


class TestEDEADLKHandling:
    """Tests for EDEADLK (errno 11) transient error handling in scan_directory."""

    def test_edeadlk_skipped_gracefully(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """EDEADLK errors should be logged as a warning and skipped."""
        import errno
        from unittest.mock import patch

        (tmp_path / "document.txt").write_text("original")
        (tmp_path / "document 2.txt").write_text("conflict")

        edeadlk = OSError(errno.EDEADLK, "Resource deadlock avoided")
        with patch.object(module, "is_target", side_effect=edeadlk):
            detected = module.scan_directory(tmp_path)

        assert detected == []

    def test_edeadlk_does_not_stop_scan(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """EDEADLK on one file should not prevent scanning subsequent files."""
        import errno
        from unittest.mock import patch

        (tmp_path / "doc1.txt").write_text("a")
        (tmp_path / "doc1 2.txt").write_text("b")

        (tmp_path / "doc2.txt").write_text("c")
        (tmp_path / "doc2 2.txt").write_text("d")

        original_is_target = module.is_target

        def side_effect(path: Path) -> DetectedFile | None:
            if path.name == "doc1 2.txt":
                raise OSError(errno.EDEADLK, "Resource deadlock avoided")
            return original_is_target(path)

        with patch.object(module, "is_target", side_effect=side_effect):
            detected = module.scan_directory(tmp_path)

        assert len(detected) == 1
        assert detected[0].path.name == "doc2 2.txt"

    def test_non_edeadlk_oserror_propagates(self, module: ICloudConflictsModule, tmp_path: Path) -> None:
        """OSError with a different errno should still propagate."""
        import errno
        from unittest.mock import patch

        (tmp_path / "document.txt").write_text("original")
        (tmp_path / "document 2.txt").write_text("conflict")

        eio = OSError(errno.EIO, "Input/output error")
        with patch.object(module, "is_target", side_effect=eio), pytest.raises(OSError, match="Input/output error"):
            module.scan_directory(tmp_path)
