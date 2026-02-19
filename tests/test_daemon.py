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


class TestSymlinkGuardianIntegration:
    """Tests for symlink guardian in daemon."""

    @pytest.mark.asyncio
    async def test_scan_calls_verify_and_repair(self, tmp_path: Path) -> None:
        """Verify that _scan_and_queue repairs broken symlinks when auto_repair is on."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = True
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()

        daemon._scan_and_queue()

        link = tmp_path / ".venv"
        assert link.is_symlink()

    @pytest.mark.asyncio
    async def test_scan_skips_repair_when_disabled(self, tmp_path: Path) -> None:
        """Verify that _scan_and_queue skips symlink repair when auto_repair is off."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = False
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()

        daemon._scan_and_queue()

        link = tmp_path / ".venv"
        assert not link.exists()

    @pytest.mark.asyncio
    async def test_scan_recurses_into_subdirectories(self, tmp_path: Path) -> None:
        """Verify that the guardian walks subdirectories for broken symlinks."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = True
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        subdir = tmp_path / "project"
        subdir.mkdir()
        nosync = subdir / "node_modules.nosync"
        nosync.mkdir()

        daemon._scan_and_queue()

        link = subdir / "node_modules"
        assert link.is_symlink()

    @pytest.mark.asyncio
    async def test_scan_skips_nosync_directories(self, tmp_path: Path) -> None:
        """Verify that the guardian does not recurse into .nosync directories."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = True
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        # Create a .nosync dir with a nested .nosync inside (should not be visited)
        outer = tmp_path / "libs.nosync"
        outer.mkdir()
        inner = outer / ".venv.nosync"
        inner.mkdir()

        daemon._scan_and_queue()

        # The inner .venv symlink should NOT be created (we skip .nosync dirs)
        inner_link = outer / ".venv"
        assert not inner_link.exists()

    @pytest.mark.asyncio
    async def test_scan_skips_symlink_directories(self, tmp_path: Path) -> None:
        """Verify that the guardian does not follow symlinks when recursing."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = True
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        # Create a symlink to a directory
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        nosync_inside = real_dir / ".venv.nosync"
        nosync_inside.mkdir()

        sym_dir = tmp_path / "sym_project"
        sym_dir.symlink_to(real_dir)

        daemon._scan_and_queue()

        # The .venv symlink should be created in real_project (direct child)
        assert (real_dir / ".venv").is_symlink()
        # But NOT via the symlink path (we skip symlink dirs)
        # The real_project one is created via direct recursion, not via sym_project

    @pytest.mark.asyncio
    async def test_scan_handles_permission_error(self, tmp_path: Path) -> None:
        """Verify that PermissionError during guardian walk is caught."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_auto_repair = True
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        # Should not raise even if directory listing fails
        with patch.object(daemon.nosync_manager, "verify_and_repair", side_effect=PermissionError("denied")):
            daemon._scan_and_queue()  # must not raise

    def test_nosync_manager_initialized(self, daemon: ICloudCleanupDaemon) -> None:
        """Verify that the daemon initializes a NosyncManager."""
        assert hasattr(daemon, "nosync_manager")
        from icloud_cleanup.nosync import NosyncManager

        assert isinstance(daemon.nosync_manager, NosyncManager)


class TestEDEADLKRetry:
    """Tests for EDEADLK not counting as a failure."""

    def test_edeadlk_not_counted(self, tmp_path: Path) -> None:
        """Verify EDEADLK errors are treated as transient and not counted."""
        import errno as errno_mod

        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        path = tmp_path / "test.txt"
        edeadlk_result = CleanupResult(
            path=path,
            success=False,
            action="error",
            error=f"[Errno {errno_mod.EDEADLK}] Resource deadlock avoided",
        )

        daemon._update_stats_after_delete(path, edeadlk_result, 0, 100.0)

        assert path not in daemon._failed_deletes
        assert daemon.stats.errors == 0

    def test_non_edeadlk_error_still_counted(self, tmp_path: Path) -> None:
        """Verify that non-EDEADLK errors are still counted normally."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        path = tmp_path / "test.txt"
        other_error_result = CleanupResult(
            path=path,
            success=False,
            action="error",
            error="[Errno 13] Permission denied",
        )

        daemon._update_stats_after_delete(path, other_error_result, 0, 100.0)

        assert path in daemon._failed_deletes
        assert daemon.stats.errors == 1

    def test_edeadlk_does_not_reset_existing_failures(self, tmp_path: Path) -> None:
        """Verify EDEADLK does not alter pre-existing failure tracking for the path."""
        import errno as errno_mod

        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.log_file = tmp_path / "test.log"
        config.recovery_dir = tmp_path / "recovery"
        daemon = ICloudCleanupDaemon(config)

        path = tmp_path / "test.txt"
        # Pre-populate a prior failure
        daemon._failed_deletes[path] = (1, 50.0)

        edeadlk_result = CleanupResult(
            path=path,
            success=False,
            action="error",
            error=f"[Errno {errno_mod.EDEADLK}] Resource deadlock avoided",
        )

        daemon._update_stats_after_delete(path, edeadlk_result, 1, 100.0)

        # Should not increment — still at the old value
        failure_count, timestamp = daemon._failed_deletes[path]
        assert failure_count == 1
        assert timestamp == 50.0
        assert daemon.stats.errors == 0
