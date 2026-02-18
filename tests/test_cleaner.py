"""Tests for file cleanup with recovery support."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from icloud_cleanup.cleaner import Cleaner, CleanupResult
from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.detector import ConflictFile


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration with a temp recovery directory."""
    cfg = CleanupConfig()
    cfg.recovery_dir = tmp_path / "recovery"
    cfg.enable_recovery = True
    cfg.recovery_retention_days = 7
    return cfg


@pytest.fixture
def logger() -> logging.Logger:
    """Create a test logger."""
    return logging.getLogger("test-cleaner")


@pytest.fixture
def cleaner(config: CleanupConfig, logger: logging.Logger) -> Cleaner:
    """Create a cleaner instance."""
    return Cleaner(config, logger)


def _make_conflict(path: Path) -> ConflictFile:
    """Create a ``ConflictFile`` object for testing."""
    return ConflictFile(
        path=path,
        original_name=path.stem.rsplit(" ", 1)[0],
        conflict_number=2,
        extension=path.suffix or None,
    )


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_success_result(self, tmp_path: Path) -> None:
        """Test a successful cleanup result."""
        result = CleanupResult(
            path=tmp_path / "file.txt",
            success=True,
            action="deleted",
        )
        assert result.success
        assert result.action == "deleted"
        assert result.error is None

    def test_error_result(self, tmp_path: Path) -> None:
        """Test an error cleanup result."""
        result = CleanupResult(
            path=tmp_path / "file.txt",
            success=False,
            action="error",
            error="Permission denied",
        )
        assert not result.success
        assert result.error == "Permission denied"


class TestProtectedPaths:
    """Tests for protected path detection."""

    def test_system_path_protected(self, cleaner: Cleaner) -> None:
        """Test that system paths are protected."""
        assert cleaner.is_path_protected(Path("/System/Library/file.txt"))
        assert cleaner.is_path_protected(Path("/Applications/App.app"))
        assert cleaner.is_path_protected(Path("/Library/Preferences/file.plist"))
        assert cleaner.is_path_protected(Path("/usr/bin/python"))
        assert cleaner.is_path_protected(Path("/var/log/system.log"))

    def test_home_directory_not_protected(self, cleaner: Cleaner) -> None:
        """Test that home directory files are not protected."""
        home = Path.home()
        assert not cleaner.is_path_protected(home / "Documents/file.txt")
        assert not cleaner.is_path_protected(home / "Downloads/file.pdf")
        assert not cleaner.is_path_protected(home / "Library/file.plist")

    def test_regular_path_not_protected(self, cleaner: Cleaner) -> None:
        """Test that regular paths under home are not protected."""
        # Use a path under the home directory which is explicitly allowed
        home = Path.home()
        test_path = home / "some_test_dir" / "document 2.txt"
        # Don't need to create the file - is_path_protected checks path string, not existence
        assert not cleaner.is_path_protected(test_path)

    def test_root_path_protected(self, cleaner: Cleaner) -> None:
        """Test that the root itself is protected."""
        assert cleaner.is_path_protected(Path("/"))


class TestDeleteConflict:
    """Tests for conflict file deletion.

    Note: We patch is_path_protected because pytest's tmp_path resolves to
    /private/var/folders/... on macOS, which is considered a protected system path.
    """

    def test_delete_nonexistent_file(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test deleting a file that doesn't exist."""
        conflict = _make_conflict(tmp_path / "missing 2.txt")
        result = cleaner.delete_conflict(conflict)

        assert not result.success
        assert result.action == "skipped"
        assert result.error is not None
        assert "no longer exists" in result.error.lower()

    def test_delete_with_recovery(self, cleaner: Cleaner, config: CleanupConfig, tmp_path: Path) -> None:
        """Test that deletion with recovery enabled moves the file."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.write_text("test content")
        conflict = _make_conflict(conflict_file)

        result = self._delete_and_verify_action(cleaner, conflict, "recovered")
        assert result.recovery_path is not None
        assert result.recovery_path.exists()
        assert not conflict_file.exists()
        assert result.recovery_path.read_text() == "test content"

    def test_delete_without_recovery(self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path) -> None:
        """Test that deletion with recovery disabled permanently deletes the file."""
        config.enable_recovery = False
        config.recovery_dir = tmp_path / "recovery"
        cleaner = Cleaner(config, logger)

        conflict_file = tmp_path / "document 2.txt"
        conflict_file.write_text("test content")
        conflict = _make_conflict(conflict_file)

        result = self._delete_and_verify_action(cleaner, conflict, "deleted")
        assert result.recovery_path is None
        assert not conflict_file.exists()

    @staticmethod
    def _delete_and_verify_action(cleaner: Cleaner, conflict: ConflictFile, expected_action: str) -> CleanupResult:
        """Delete a conflict with protection bypassed and verify the action."""
        with patch.object(cleaner, "is_path_protected", return_value=False):
            result = cleaner.delete_conflict(conflict)
        assert result.success
        assert result.action == expected_action
        return result

    def test_recovery_path_collision(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test handling of recovery path collisions."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        file1 = dir1 / "document 2.txt"
        file2 = dir2 / "document 2.txt"
        file1.write_text("content 1")
        file2.write_text("content 2")

        conflict1 = _make_conflict(file1)
        conflict2 = _make_conflict(file2)

        with patch.object(cleaner, "is_path_protected", return_value=False):
            result1 = cleaner.delete_conflict(conflict1)
            result2 = cleaner.delete_conflict(conflict2)

        assert result1.success
        assert result2.success
        # Both should have different recovery paths
        assert result1.recovery_path is not None
        assert result2.recovery_path is not None
        assert result1.recovery_path != result2.recovery_path
        assert result1.recovery_path.exists()
        assert result2.recovery_path.exists()

    def test_delete_preserves_file_content(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that recovery preserves file content."""
        conflict_file = tmp_path / "binary 2.bin"
        binary_content = bytes(range(256))
        conflict_file.write_bytes(binary_content)
        conflict = _make_conflict(conflict_file)

        with patch.object(cleaner, "is_path_protected", return_value=False):
            result = cleaner.delete_conflict(conflict)

        assert result.success
        assert result.recovery_path is not None
        assert result.recovery_path.read_bytes() == binary_content

    def test_delete_with_force(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that force=True bypasses recovery."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.write_text("test content")
        conflict = _make_conflict(conflict_file)
        with patch.object(cleaner, "is_path_protected", return_value=False):
            result = cleaner.delete_conflict(conflict, force=True)
        assert result.success
        assert result.action == "deleted"
        assert not conflict_file.exists()

    def test_delete_protected_path_blocked(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that deletion of protected paths is blocked."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.write_text("test content")
        conflict = _make_conflict(conflict_file)

        # Simulate a protected path
        with patch.object(cleaner, "is_path_protected", return_value=True):
            result = cleaner.delete_conflict(conflict)

        assert not result.success
        assert result.action == "skipped"
        assert result.error is not None
        assert "protected" in result.error.lower()
        assert conflict_file.exists()  # File should NOT be deleted


class TestRecoveryCleanup:
    """Tests for recovery directory cleanup."""

    def test_cleanup_old_directories(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test that old recovery directories are cleaned up."""
        old_dir = self._create_dated_recovery_dir(config, days_ago=10, filename="old_file.txt")
        recent_dir = self._create_dated_recovery_dir(config, days_ago=3, filename="recent_file.txt")

        cleaned = cleaner.cleanup_recovery_dir()

        assert cleaned == 1
        assert not old_dir.exists()
        assert recent_dir.exists()

    def test_cleanup_retention_zero_days(self, config: CleanupConfig, logger: logging.Logger) -> None:
        """When retention is 0, all dated recovery directories should be removed."""
        config.recovery_retention_days = 0
        cleaner = Cleaner(config, logger)

        old_dir = self._create_dated_recovery_dir(config, days_ago=10, filename="old.txt")
        recent_dir = self._create_dated_recovery_dir(config, days_ago=1, filename="recent.txt")

        cleaned = cleaner.cleanup_recovery_dir()

        assert cleaned == 2
        assert not old_dir.exists()
        assert not recent_dir.exists()

    def test_cleanup_retention_one_day_boundary(self, config: CleanupConfig, logger: logging.Logger) -> None:
        """Validate 1-day retention boundary (dirs >= retention_days old are removed)."""
        config.recovery_retention_days = 1
        cleaner = Cleaner(config, logger)

        old_dir = self._create_dated_recovery_dir(config, days_ago=2, filename="old.txt")
        boundary_dir = self._create_dated_recovery_dir(config, days_ago=1, filename="boundary.txt")
        new_dir = self._create_dated_recovery_dir(config, days_ago=0, filename="new.txt")

        cleaned = cleaner.cleanup_recovery_dir()

        # Dirs >= 1 day old are removed (old=2d, boundary=1d), today's dir survives
        assert cleaned == 2
        assert not old_dir.exists()
        assert not boundary_dir.exists()
        assert new_dir.exists()

    @staticmethod
    def _create_dated_recovery_dir(config: CleanupConfig, days_ago: int, filename: str) -> Path:
        """Create a dated recovery directory with a test file inside."""
        date = datetime.now(UTC) - timedelta(days=days_ago)
        date_dir = config.recovery_dir / date.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True)
        (date_dir / filename).touch()
        return date_dir

    def test_cleanup_with_recovery_disabled(
        self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test cleanup does nothing when recovery is disabled."""
        config.enable_recovery = False
        config.recovery_dir = tmp_path / "recovery"
        cleaner = Cleaner(config, logger)

        cleaned = cleaner.cleanup_recovery_dir()
        assert cleaned == 0

    def test_cleanup_nonexistent_recovery_dir(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test cleanup handles nonexistent recovery directory."""
        # Ensure recovery dir doesn't exist
        if config.recovery_dir.exists():
            import shutil

            shutil.rmtree(config.recovery_dir)

        cleaned = cleaner.cleanup_recovery_dir()
        assert cleaned == 0

    def test_cleanup_ignores_invalid_date_dirs(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test cleanup ignores directories with invalid names."""
        # Create an invalid directory
        invalid_dir = config.recovery_dir / "not-a-date"
        invalid_dir.mkdir(parents=True)
        (invalid_dir / "file.txt").touch()

        # Create old valid directory
        old_date = datetime.now(UTC) - timedelta(days=10)
        old_dir = config.recovery_dir / old_date.strftime("%Y-%m-%d")
        old_dir.mkdir(parents=True)
        (old_dir / "file.txt").touch()

        cleaned = cleaner.cleanup_recovery_dir()

        assert cleaned == 1
        assert invalid_dir.exists()  # Should not be touched
        assert not old_dir.exists()


class TestRestoreFile:
    """Tests for file restoration."""

    def test_restore_to_destination(self, cleaner: Cleaner, config: CleanupConfig, tmp_path: Path) -> None:
        """Test restoring a file to a specific destination."""
        # Create a file in recovery
        date_dir = config.recovery_dir / datetime.now(UTC).strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True)
        recovery_file = date_dir / "abc123_document 2.txt"
        recovery_file.write_text("restored content")

        destination = tmp_path / "restored" / "document.txt"
        success = cleaner.restore_file(recovery_file, destination)

        assert success
        assert destination.exists()
        assert destination.read_text() == "restored content"

    def test_restore_nonexistent_file(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that restoring a nonexistent file fails."""
        missing = tmp_path / "missing.txt"
        success = cleaner.restore_file(missing)
        assert not success

    def test_restore_to_default_location(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test restoring a file to the default location."""
        # Create a file in recovery with hash prefix
        date_dir = config.recovery_dir / datetime.now(UTC).strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True)
        recovery_file = date_dir / "abc123_document.txt"
        recovery_file.write_text("content")

        success = cleaner.restore_file(recovery_file)

        assert success
        # Default is ~/Desktop/Restored/original_name
        expected = Path.home() / "Desktop" / "Restored" / "document.txt"
        assert expected.exists()
        # Cleanup
        expected.unlink()
        expected.parent.rmdir()


class TestListRecoverableFiles:
    """Tests for listing recoverable files."""

    def test_list_empty_recovery(self, cleaner: Cleaner) -> None:
        """Test listing an empty recovery directory."""
        files = cleaner.list_recoverable_files()
        assert files == []

    def test_list_files_sorted_by_date(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test that files are sorted by date (newest first)."""
        # Create files on different dates
        old_date = datetime.now(UTC) - timedelta(days=5)
        new_date = datetime.now(UTC) - timedelta(days=1)

        old_dir = config.recovery_dir / old_date.strftime("%Y-%m-%d")
        new_dir = config.recovery_dir / new_date.strftime("%Y-%m-%d")
        old_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)

        (old_dir / "old.txt").touch()
        (new_dir / "new.txt").touch()

        files = cleaner.list_recoverable_files()

        assert len(files) == 2
        # Newest should be first
        assert "new.txt" in files[0][0].name
        assert "old.txt" in files[1][0].name

    def test_list_ignores_invalid_dirs(self, cleaner: Cleaner, config: CleanupConfig) -> None:
        """Test that listing ignores invalid date directories."""
        # Create an invalid directory
        invalid_dir = config.recovery_dir / "invalid"
        invalid_dir.mkdir(parents=True)
        (invalid_dir / "file.txt").touch()

        # Create a valid directory
        valid_dir = config.recovery_dir / datetime.now(UTC).strftime("%Y-%m-%d")
        valid_dir.mkdir(parents=True)
        (valid_dir / "valid.txt").touch()

        files = cleaner.list_recoverable_files()

        assert len(files) == 1
        assert "valid.txt" in files[0][0].name


class TestDeleteDetected:
    """Tests for delete_detected — the module-system entry point."""

    def test_delete_with_recovery_enabled(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that recovery_enabled=True moves the file to recovery."""
        from icloud_cleanup.modules.base import DetectedFile

        target = tmp_path / "conflict 2.txt"
        target.write_text("content")
        detected = DetectedFile(
            path=target,
            module_name="icloud_conflicts",
            reason="test conflict",
            recovery_enabled=True,
        )

        with patch.object(cleaner, "is_path_protected", return_value=False):
            result = cleaner.delete_detected(detected)

        assert result.success
        assert result.action == "recovered"
        assert result.recovery_path is not None
        assert result.recovery_path.exists()
        assert not target.exists()

    def test_delete_with_recovery_disabled(self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path) -> None:
        """Test that recovery_enabled=False permanently deletes the file."""
        from icloud_cleanup.modules.base import DetectedFile

        config.enable_recovery = True  # global recovery on, but file opts out
        cleaner = Cleaner(config, logger)

        target = tmp_path / ".coverage.host.pid1.abc"
        target.write_text("stale")
        detected = DetectedFile(
            path=target,
            module_name="coverage_artifacts",
            reason="stale artifact",
            recovery_enabled=False,
        )

        with patch.object(cleaner, "is_path_protected", return_value=False):
            result = cleaner.delete_detected(detected)

        assert result.success
        assert result.action == "deleted"
        assert result.recovery_path is None
        assert not target.exists()

    def test_delete_nonexistent_detected(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test deleting a detected file that no longer exists."""
        from icloud_cleanup.modules.base import DetectedFile

        missing = tmp_path / "gone 2.txt"
        detected = DetectedFile(
            path=missing,
            module_name="icloud_conflicts",
            reason="test",
            recovery_enabled=True,
        )

        result = cleaner.delete_detected(detected)

        assert not result.success
        assert result.action == "skipped"

    def test_delete_protected_detected(self, cleaner: Cleaner, tmp_path: Path) -> None:
        """Test that protected paths are blocked for detected files."""
        from icloud_cleanup.modules.base import DetectedFile

        target = tmp_path / "system 2.txt"
        target.write_text("protected")
        detected = DetectedFile(
            path=target,
            module_name="icloud_conflicts",
            reason="test",
            recovery_enabled=True,
        )

        with patch.object(cleaner, "is_path_protected", return_value=True):
            result = cleaner.delete_detected(detected)

        assert not result.success
        assert result.action == "skipped"
        assert target.exists()
