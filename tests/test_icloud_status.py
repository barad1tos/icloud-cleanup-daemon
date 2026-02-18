"""Tests for iCloud sync status checking."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.icloud_status import (
    FileStatus,
    ICloudStatusChecker,
    SyncStatus,
)


@pytest.fixture
def config() -> CleanupConfig:
    """Create test configuration."""
    cfg = CleanupConfig()
    cfg.icloud_poll_interval = 1  # Fast polling for tests
    cfg.max_icloud_wait = 5  # Short timeout for tests
    return cfg


@pytest.fixture
def checker(config: CleanupConfig) -> ICloudStatusChecker:
    """Create iCloud status checker."""
    return ICloudStatusChecker(config)


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_status_values(self) -> None:
        """Test that all expected status values exist."""
        assert SyncStatus.SYNCED.value == "synced"
        assert SyncStatus.UPLOADING.value == "uploading"
        assert SyncStatus.DOWNLOADING.value == "downloading"
        assert SyncStatus.WAITING.value == "waiting"
        assert SyncStatus.ERROR.value == "error"
        assert SyncStatus.UNKNOWN.value == "unknown"


class TestFileStatus:
    """Tests for FileStatus dataclass."""

    def test_file_status_creation(self, tmp_path: Path) -> None:
        """Test creating FileStatus instance."""
        status = FileStatus(
            path=tmp_path / "file.txt",
            status=SyncStatus.SYNCED,
            is_placeholder=False,
            is_uploaded=True,
        )
        assert status.status == SyncStatus.SYNCED
        assert not status.is_placeholder
        assert status.is_uploaded


class TestGetFileStatus:
    """Tests for get_file_status method."""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test status of nonexistent file."""
        missing = tmp_path / "missing.txt"
        status = ICloudStatusChecker.get_file_status(missing)

        assert status.status == SyncStatus.UNKNOWN
        assert not status.is_placeholder
        assert not status.is_uploaded

    def test_icloud_placeholder_file(self, tmp_path: Path) -> None:
        """Test detection of .icloud placeholder files."""
        # iCloud creates files like ".filename.icloud" for not-downloaded files
        placeholder = tmp_path / ".document.txt.icloud"
        placeholder.touch()

        status = ICloudStatusChecker.get_file_status(placeholder)

        assert status.status == SyncStatus.DOWNLOADING
        assert status.is_placeholder
        assert status.is_uploaded

    def test_regular_file_synced(self, tmp_path: Path) -> None:
        """Test regular file without iCloud attributes is synced."""
        regular_file = tmp_path / "document.txt"
        regular_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=b"",  # No iCloud attributes
                returncode=0,
            )
            status = ICloudStatusChecker.get_file_status(regular_file)

        assert status.status == SyncStatus.SYNCED
        assert not status.is_placeholder

    def test_file_uploading(self, tmp_path: Path) -> None:
        """Test detection of file being uploaded."""
        uploading_file = tmp_path / "uploading.txt"
        uploading_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=b"com.apple.icloud.itemUploadPending: some_value",
                returncode=0,
            )
            status = ICloudStatusChecker.get_file_status(uploading_file)

        assert status.status == SyncStatus.UPLOADING
        assert not status.is_uploaded

    def test_file_download_pending(self, tmp_path: Path) -> None:
        """Test detection of file pending download."""
        pending_file = tmp_path / "pending.txt"
        pending_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=b"com.apple.icloud.itemDownloadPending: some_value",
                returncode=0,
            )
            status = ICloudStatusChecker.get_file_status(pending_file)

        assert status.status == SyncStatus.DOWNLOADING
        assert status.is_placeholder

    def test_xattr_binary_output_handled(self, tmp_path: Path) -> None:
        """Test that binary xattr output is handled properly."""
        test_file = tmp_path / "binary.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            # Simulate binary output that isn't valid UTF-8
            mock_run.return_value = MagicMock(
                stdout=b"\x80\x81\x82 invalid utf8 com.apple.icloud.itemUploadPending",
                returncode=0,
            )
            status = ICloudStatusChecker.get_file_status(test_file)

        # Should not crash, and should detect the attribute
        assert status.status == SyncStatus.UPLOADING

    def test_subprocess_error_handled(self, tmp_path: Path) -> None:
        """Test that subprocess errors return UNKNOWN status."""
        test_file = tmp_path / "error.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("xattr failed")
            status = ICloudStatusChecker.get_file_status(test_file)

        assert status.status == SyncStatus.UNKNOWN

    def test_oserror_handled(self, tmp_path: Path) -> None:
        """Test that OS errors return UNKNOWN status."""
        test_file = tmp_path / "oserror.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            status = ICloudStatusChecker.get_file_status(test_file)

        assert status.status == SyncStatus.UNKNOWN


class TestIsSynced:
    """Tests for is_synced method."""

    def test_synced_file(self, checker: ICloudStatusChecker, tmp_path: Path) -> None:
        """Test is_synced returns True for synced file."""
        test_file = tmp_path / "synced.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=b"", returncode=0)
            assert checker.is_synced(test_file) is True

    def test_uploading_file_not_synced(self, checker: ICloudStatusChecker, tmp_path: Path) -> None:
        """Test is_synced returns False for uploading file."""
        test_file = tmp_path / "uploading.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=b"com.apple.icloud.itemUploadPending: data",
                returncode=0,
            )
            assert checker.is_synced(test_file) is False


class TestWaitForSync:
    """Tests for wait_for_sync async method."""

    @pytest.mark.asyncio
    async def test_already_synced(self, checker: ICloudStatusChecker, tmp_path: Path) -> None:
        """Test wait_for_sync returns immediately if already synced."""
        test_file = tmp_path / "synced.txt"
        test_file.write_text("content")

        with patch.object(checker, "is_synced", return_value=True):
            result = await checker.wait_for_sync(test_file)

        assert result is True

    @pytest.mark.asyncio
    async def test_timeout_on_not_synced(self, config: CleanupConfig, tmp_path: Path) -> None:
        """Test wait_for_sync returns False on timeout."""
        config.max_icloud_wait = 2
        config.icloud_poll_interval = 1
        checker = ICloudStatusChecker(config)

        test_file = tmp_path / "not_synced.txt"
        test_file.write_text("content")

        with patch.object(checker, "is_synced", return_value=False):
            result = await checker.wait_for_sync(test_file)

        assert result is False

    @pytest.mark.asyncio
    async def test_becomes_synced(self, config: CleanupConfig, tmp_path: Path) -> None:
        """Test wait_for_sync succeeds when a file becomes synced."""
        config.max_icloud_wait = 10
        config.icloud_poll_interval = 1
        checker = ICloudStatusChecker(config)

        test_file = tmp_path / "becoming_synced.txt"
        test_file.write_text("content")

        # First call returns False, second returns True
        sync_states = iter([False, True])

        with patch.object(checker, "is_synced", side_effect=lambda p: next(sync_states)):
            result = await checker.wait_for_sync(test_file)

        assert result is True

    @pytest.mark.asyncio
    async def test_minimum_poll_interval(self, config: CleanupConfig, tmp_path: Path) -> None:
        """Test that poll interval is at least 1 second."""
        config.icloud_poll_interval = 0  # Would cause infinite loop without check
        config.max_icloud_wait = 2
        checker = ICloudStatusChecker(config)

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        with patch.object(checker, "is_synced", return_value=False):
            # Should not hang - the code enforces minimum 1 second interval
            result = await checker.wait_for_sync(test_file)

        assert result is False


class TestGetICloudDriveStatus:
    """Tests for get_icloud_drive_status method."""

    def test_parse_brctl_output(self) -> None:
        """Test parsing brctl status output."""
        mock_output = """account: user@example.com
status: idle
uploads: 0
downloads: 0"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=mock_output,
                returncode=0,
            )
            status = ICloudStatusChecker.get_icloud_drive_status()

        assert "account" in status
        assert status["account"] == "user@example.com"
        assert status["status"] == "idle"

    def test_brctl_not_available(self) -> None:
        """Test handling when brctl is not available."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("brctl not found")
            status = ICloudStatusChecker.get_icloud_drive_status()

        assert status == {"status": "unknown"}

    def test_brctl_oserror(self) -> None:
        """Test handling OS errors from brctl."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            status = ICloudStatusChecker.get_icloud_drive_status()

        assert status == {"status": "unknown"}


class TestIsICloudIdle:
    """Tests for is_icloud_idle method."""

    def test_icloud_idle(self, checker: ICloudStatusChecker) -> None:
        """Test detection of idle iCloud."""
        with patch.object(
            checker,
            "get_icloud_drive_status",
            return_value={"status": "idle", "uploads": "0", "downloads": "0"},
        ):
            assert checker.is_icloud_idle() is True

    def test_icloud_uploading(self, checker: ICloudStatusChecker) -> None:
        """Test detection of uploading state."""
        with patch.object(
            checker,
            "get_icloud_drive_status",
            return_value={"status": "uploading", "uploads": "5"},
        ):
            assert checker.is_icloud_idle() is False

    def test_icloud_downloading(self, checker: ICloudStatusChecker) -> None:
        """Test detection of downloading state."""
        with patch.object(
            checker,
            "get_icloud_drive_status",
            return_value={"status": "downloading", "downloads": "3"},
        ):
            assert checker.is_icloud_idle() is False

    def test_unknown_status_treated_as_idle(self, checker: ICloudStatusChecker) -> None:
        """Test that unknown status is treated as idle."""
        with patch.object(
            checker,
            "get_icloud_drive_status",
            return_value={"status": "unknown"},
        ):
            assert checker.is_icloud_idle() is True


class TestSubprocessTimeout:
    """Tests for subprocess timeout handling."""

    def test_xattr_timeout_returns_unknown(self, tmp_path: Path) -> None:
        """Test that an xattr timeout returns UNKNOWN status."""
        test_file = tmp_path / "slow.txt"
        test_file.write_text("content")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="xattr", timeout=10)
            status = ICloudStatusChecker.get_file_status(test_file)

        assert status.status == SyncStatus.UNKNOWN
