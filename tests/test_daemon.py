"""Tests for daemon retry limit and cooldown functionality."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from icloud_cleanup.cleaner import CleanupResult
from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.daemon import ICloudCleanupDaemon
from icloud_cleanup.detector import ConflictFile


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration."""
    cfg = CleanupConfig()
    cfg.watch_directories = [tmp_path]
    cfg.log_file = tmp_path / "test.log"
    cfg.max_delete_retries = 3
    cfg.retry_cooldown = 3600  # 1 hour
    return cfg


@pytest.fixture
def daemon(config: CleanupConfig) -> ICloudCleanupDaemon:
    """Create a daemon instance."""
    return ICloudCleanupDaemon(config)


def _make_conflict(path: Path) -> ConflictFile:
    """Create a ``ConflictFile`` object for testing."""
    return ConflictFile(
        path=path,
        original_name=path.stem.rsplit(" ", 1)[0],
        conflict_number=2,
        extension=path.suffix or None,
    )


class TestDaemonInit:
    """Tests for daemon initialization."""

    def test_failed_deletes_initialized(self, daemon: ICloudCleanupDaemon) -> None:
        """Test that _failed_deletes is initialized empty."""
        assert daemon._failed_deletes == {}

    def test_max_delete_retries_from_config(self, daemon: ICloudCleanupDaemon) -> None:
        """Test that max_delete_retries is read from config."""
        assert daemon.config.max_delete_retries == 3

    def test_retry_cooldown_from_config(self, daemon: ICloudCleanupDaemon) -> None:
        """Test that retry_cooldown is read from config."""
        assert daemon.config.retry_cooldown == 3600


class TestLogLevelValidation:
    """Tests for log_level validation in daemon init."""

    def test_invalid_log_level_raises(self, tmp_path: Path) -> None:
        """Test that an invalid log_level raises ValueError."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.log_file = tmp_path / "test.log"
        config.log_level = "INVALID"

        with pytest.raises(ValueError, match="Invalid log_level"):
            ICloudCleanupDaemon(config)


class TestRetryLimit:
    """Tests for retry limit functionality."""

    @pytest.mark.asyncio
    async def test_skips_during_cooldown(self, daemon: ICloudCleanupDaemon, tmp_path: Path) -> None:
        """Test that files are skipped during the cooldown period."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        # Simulate max retries reached recently (within cooldown)
        current_time = asyncio.get_running_loop().time()
        daemon._failed_deletes[conflict_file] = (3, current_time - 100)  # 100s ago

        result = await daemon._process_conflict(conflict)

        assert result is None
        assert daemon.stats.files_skipped == 1

    @pytest.mark.asyncio
    async def test_retries_after_cooldown_expires(self, daemon: ICloudCleanupDaemon, tmp_path: Path) -> None:
        """Test that files are retried after cooldown expires."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        # Simulate max retries reached long ago (cooldown expired)
        current_time = asyncio.get_running_loop().time()
        daemon._failed_deletes[conflict_file] = (3, current_time - 4000)

        success_result = CleanupResult(
            path=conflict_file,
            success=True,
            action="deleted",
        )

        with (
            patch.object(daemon.checker, "wait_for_sync", new=AsyncMock(return_value=True)),
            patch.object(daemon.cleaner, "delete_conflict", return_value=success_result),
        ):
            result = await daemon._process_conflict(conflict)

        assert result is not None
        assert result.success is True
        assert conflict_file not in daemon._failed_deletes

    @pytest.mark.asyncio
    async def test_increments_failure_count(self, daemon: ICloudCleanupDaemon, tmp_path: Path) -> None:
        """Test that failure count is incremented on failed deletion."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        failed_result = CleanupResult(
            path=conflict_file,
            success=False,
            action="error",
            error="Resource deadlock avoided",
        )

        with (
            patch.object(daemon.checker, "wait_for_sync", new=AsyncMock(return_value=True)),
            patch.object(daemon.cleaner, "delete_conflict", return_value=failed_result),
        ):
            await daemon._process_conflict(conflict)

        assert conflict_file in daemon._failed_deletes
        failure_count, _ = daemon._failed_deletes[conflict_file]
        assert failure_count == 1
        assert daemon.stats.errors == 1

    @pytest.mark.asyncio
    async def test_clears_failure_on_success(self, daemon: ICloudCleanupDaemon, tmp_path: Path) -> None:
        """Test that failure count is cleared on successful deletion."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        # Pre-populate failure count (not yet at max)
        current_time = asyncio.get_running_loop().time()
        daemon._failed_deletes[conflict_file] = (2, current_time - 10)

        success_result = CleanupResult(
            path=conflict_file,
            success=True,
            action="deleted",
        )

        with (
            patch.object(daemon.checker, "wait_for_sync", new=AsyncMock(return_value=True)),
            patch.object(daemon.cleaner, "delete_conflict", return_value=success_result),
        ):
            await daemon._process_conflict(conflict)

        assert conflict_file not in daemon._failed_deletes
        assert daemon.stats.files_deleted == 1

    @pytest.mark.asyncio
    async def test_allows_retries_under_limit(self, daemon: ICloudCleanupDaemon, tmp_path: Path) -> None:
        """Test that files under retry limit are still processed."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        # Set failure count below limit
        current_time = asyncio.get_running_loop().time()
        daemon._failed_deletes[conflict_file] = (2, current_time - 10)

        failed_result = CleanupResult(
            path=conflict_file,
            success=False,
            action="error",
            error="Resource deadlock avoided",
        )

        with (
            patch.object(daemon.checker, "wait_for_sync", new=AsyncMock(return_value=True)),
            patch.object(daemon.cleaner, "delete_conflict", return_value=failed_result),
        ):
            result = await daemon._process_conflict(conflict)

        assert result is not None
        assert result.success is False
        failure_count, _ = daemon._failed_deletes[conflict_file]
        assert failure_count == 3

    @pytest.mark.asyncio
    async def test_failure_resets_after_cooldown_then_fails_again(
        self, daemon: ICloudCleanupDaemon, tmp_path: Path
    ) -> None:
        """Test that counter resets after cooldown and tracks new failures."""
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()
        original = tmp_path / "document.txt"
        original.touch()
        conflict = _make_conflict(conflict_file)

        # Simulate max retries reached long ago (cooldown expired)
        current_time = asyncio.get_running_loop().time()
        daemon._failed_deletes[conflict_file] = (3, current_time - 4000)

        failed_result = CleanupResult(
            path=conflict_file,
            success=False,
            action="error",
            error="Resource deadlock avoided",
        )

        with (
            patch.object(daemon.checker, "wait_for_sync", new=AsyncMock(return_value=True)),
            patch.object(daemon.cleaner, "delete_conflict", return_value=failed_result),
        ):
            await daemon._process_conflict(conflict)

        # Counter should have reset and started from 1
        failure_count, _ = daemon._failed_deletes[conflict_file]
        assert failure_count == 1
