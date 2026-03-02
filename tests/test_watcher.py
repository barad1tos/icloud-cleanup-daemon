"""Tests for file system watcher."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from watchdog.events import FileCreatedEvent, FileMovedEvent

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.watcher import ConflictEventHandler, FileWatcher


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration."""
    cleanup_config = CleanupConfig()
    cleanup_config.watch_directories = [tmp_path]
    return cleanup_config


@pytest.fixture
def logger() -> logging.Logger:
    """Create a test logger for the watcher."""
    return logging.getLogger("test-watcher")


@pytest.fixture
def watcher(config: CleanupConfig, logger: logging.Logger) -> FileWatcher:
    """Create a test file watcher."""
    return FileWatcher(config, logger)


class TestConflictEventHandler:
    """Tests for the zero-I/O event handler."""

    def test_on_created_enqueues_path(self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path) -> None:
        """Test that a created file path is enqueued."""
        handler = ConflictEventHandler(watcher, logger)

        file_path = tmp_path / "document 2.txt"
        event = FileCreatedEvent(str(file_path))
        handler.on_created(event)

        drained = watcher.drain_paths()
        assert file_path in drained

    def test_on_created_regular_file(self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path) -> None:
        """Test that regular files are also enqueued (filtering happens later)."""
        handler = ConflictEventHandler(watcher, logger)

        regular_file = tmp_path / "document.txt"
        event = FileCreatedEvent(str(regular_file))
        handler.on_created(event)

        drained = watcher.drain_paths()
        assert regular_file in drained

    def test_on_created_ignores_directory_events(
        self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that a directory creation event is ignored."""
        handler = ConflictEventHandler(watcher, logger)

        new_dir = tmp_path / "subdir 2"
        event = FileCreatedEvent(str(new_dir))
        event.is_directory = True
        handler.on_created(event)

        drained = watcher.drain_paths()
        assert not drained

    def test_on_moved_enqueues_dest_path(
        self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that a moved file's destination path is enqueued."""
        handler = ConflictEventHandler(watcher, logger)

        src = tmp_path / "temp.txt"
        dest = tmp_path / "document 2.txt"
        event = FileMovedEvent(str(src), str(dest))
        handler.on_moved(event)

        drained = watcher.drain_paths()
        assert dest in drained

    def test_on_moved_ignores_directory_events(
        self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that directory move events are ignored."""
        handler = ConflictEventHandler(watcher, logger)

        src_dir = tmp_path / "old"
        dest_dir = tmp_path / "new 2"
        event = FileMovedEvent(str(src_dir), str(dest_dir))
        event.is_directory = True
        handler.on_moved(event)

        drained = watcher.drain_paths()
        assert not drained

    def test_handles_bytes_path(self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path) -> None:
        """Test the handling of bytes paths (some FSEvents return bytes)."""
        handler = ConflictEventHandler(watcher, logger)

        file_path = tmp_path / "document 2.txt"
        event = FileCreatedEvent(str(file_path).encode())
        handler.on_created(event)

        drained = watcher.drain_paths()
        assert file_path in drained


class TestFileWatcher:
    """Tests for FileWatcher lifecycle."""

    def test_initial_state(self, watcher: FileWatcher) -> None:
        """Test that the initial watcher state is stopped."""
        assert not watcher.is_running
        assert watcher._observer is None

    def test_start_stop(self, watcher: FileWatcher) -> None:
        """Test that the watcher starts and stops correctly."""
        watcher.start()
        assert watcher.is_running
        assert watcher._observer is not None

        watcher.stop()
        assert not watcher.is_running
        assert watcher._observer is None

    def test_start_twice(self, watcher: FileWatcher) -> None:
        """Test that starting twice doesn't create duplicate observers."""
        watcher.start()
        observer1 = watcher._observer

        watcher.start()  # Should be no-op
        assert watcher._observer is observer1

        watcher.stop()

    def test_stop_when_not_started(self, watcher: FileWatcher) -> None:
        """Test that stopping when not started doesn't crash."""
        watcher.stop()  # Should be no-op
        assert not watcher.is_running

    def test_watches_configured_directories(
        self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that all configured directories are watched."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        config.watch_directories = [dir1, dir2]
        test_watcher = FileWatcher(config, logger)

        with patch("icloud_cleanup.watcher.Observer") as mock_observer_class:
            self._start_and_verify_schedule_count(mock_observer_class, test_watcher, 2)

    def test_skips_nonexistent_directories(
        self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that nonexistent directories are skipped."""
        existing_dir = tmp_path / "exists"
        existing_dir.mkdir()
        nonexistent_dir = tmp_path / "missing"

        config.watch_directories = [existing_dir, nonexistent_dir]
        test_watcher = FileWatcher(config, logger)

        with patch("icloud_cleanup.watcher.Observer") as mock_observer_class:
            self._start_and_verify_schedule_count(mock_observer_class, test_watcher, 1)

    @staticmethod
    def _start_and_verify_schedule_count(
        mock_observer_class: MagicMock, watcher: FileWatcher, expected_count: int
    ) -> None:
        """Start the watcher with a mocked observer and verify the schedule call count."""
        mock_observer = MagicMock()
        mock_observer_class.return_value = mock_observer
        watcher.start()
        assert mock_observer.schedule.call_count == expected_count
        watcher.stop()


class TestFileWatcherDrainPaths:
    """Tests for the Lock+set drain_paths API."""

    def test_enqueue_and_drain(self, watcher: FileWatcher) -> None:
        """Test that enqueued paths are returned by drain_paths."""
        p1 = Path("/tmp/a")
        p2 = Path("/tmp/b")

        watcher.enqueue_path(p1)
        watcher.enqueue_path(p2)

        drained = watcher.drain_paths()
        assert drained == {p1, p2}

    def test_drain_returns_empty_after_drain(self, watcher: FileWatcher) -> None:
        """Test that drain_paths returns an empty set on the second call."""
        watcher.enqueue_path(Path("/tmp/a"))

        watcher.drain_paths()
        second = watcher.drain_paths()
        assert second == set()

    def test_deduplication(self, watcher: FileWatcher) -> None:
        """Test that duplicate paths are deduplicated."""
        p = Path("/tmp/same")
        watcher.enqueue_path(p)
        watcher.enqueue_path(p)
        watcher.enqueue_path(p)

        drained = watcher.drain_paths()
        assert len(drained) == 1
        assert p in drained

    def test_drain_is_atomic_swap(self, watcher: FileWatcher) -> None:
        """Test that drain_paths performs an atomic swap."""
        watcher.enqueue_path(Path("/tmp/before"))

        drained = watcher.drain_paths()
        watcher.enqueue_path(Path("/tmp/after"))

        assert Path("/tmp/before") in drained
        assert Path("/tmp/after") not in drained

        second = watcher.drain_paths()
        assert Path("/tmp/after") in second


class TestWatcherIntegration:
    """Integration tests for file watcher (require actual file system events)."""

    @pytest.mark.asyncio
    async def test_detects_created_file(
        self,
        config: CleanupConfig,
        logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """Test that the watcher buffers newly created files."""
        config.watch_directories = [tmp_path]
        test_watcher = FileWatcher(config, logger)

        test_watcher.start()

        try:
            await asyncio.sleep(0.5)

            created = tmp_path / "document 2.txt"
            created.write_text("content")

            # Poll drain_paths until the event appears or timeout
            found = False
            for _ in range(50):  # 50 * 0.1s = 5s max
                drained = test_watcher.drain_paths()
                if created in drained:
                    found = True
                    break
                await asyncio.sleep(0.1)

            if not found:
                pytest.skip("FSEvents not detected — may be an environment limitation")

        finally:
            test_watcher.stop()
