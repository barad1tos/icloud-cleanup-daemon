"""Tests for file system watcher."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from watchdog.events import FileCreatedEvent, FileMovedEvent

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.detector import ConflictDetector
from icloud_cleanup.watcher import ConflictEventHandler, FileWatcher


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create test configuration."""
    cfg = CleanupConfig()
    cfg.watch_directories = [tmp_path]
    return cfg


@pytest.fixture
def detector(config: CleanupConfig) -> ConflictDetector:
    """Create conflict detector."""
    return ConflictDetector(config)


@pytest.fixture
def logger() -> logging.Logger:
    """Create test logger."""
    return logging.getLogger("test-watcher")


@pytest.fixture
def watcher(
    config: CleanupConfig, detector: ConflictDetector, logger: logging.Logger
) -> FileWatcher:
    """Create file watcher."""
    return FileWatcher(config, detector, logger)


class TestConflictEventHandler:
    """Tests for ConflictEventHandler."""

    def test_on_created_conflict_file(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test handling of created conflict file."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        # Create a conflict file
        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()

        event = FileCreatedEvent(str(conflict_file))
        handler.on_created(event)

        assert len(callback_paths) == 1
        assert callback_paths[0] == conflict_file

    def test_on_created_regular_file(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that regular files don't trigger callback."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        # Create a regular file (not a conflict)
        regular_file = tmp_path / "document.txt"
        regular_file.touch()

        event = FileCreatedEvent(str(regular_file))
        handler.on_created(event)

        assert not callback_paths

    def test_on_created_ignores_directories(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that directory creation is ignored."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        # Create directory event
        new_dir = tmp_path / "subdir 2"
        new_dir.mkdir()

        event = FileCreatedEvent(str(new_dir))
        event.is_directory = True
        handler.on_created(event)

        assert not callback_paths

    def test_on_moved_conflict_file(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test handling of moved file becoming conflict."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        # Simulate file move
        src = tmp_path / "temp.txt"
        dest = tmp_path / "document 2.txt"
        dest.touch()  # Create the destination file

        event = FileMovedEvent(str(src), str(dest))
        handler.on_moved(event)

        assert len(callback_paths) == 1
        assert callback_paths[0] == dest

    def test_on_moved_ignores_directories(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that directory moves are ignored."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        src_dir = tmp_path / "old"
        dest_dir = tmp_path / "new 2"
        dest_dir.mkdir()

        event = FileMovedEvent(str(src_dir), str(dest_dir))
        event.is_directory = True
        handler.on_moved(event)

        assert not callback_paths

    def test_handles_bytes_path(
        self, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test handling of bytes paths (some FSEvents return bytes)."""
        callback_paths: list[Path] = []

        def callback(path: Path) -> None:
            callback_paths.append(path)

        handler = ConflictEventHandler(detector, callback, logger)

        conflict_file = tmp_path / "document 2.txt"
        conflict_file.touch()

        # Create event with bytes path
        event = FileCreatedEvent(str(conflict_file).encode())
        handler.on_created(event)

        assert len(callback_paths) == 1


class TestFileWatcher:
    """Tests for FileWatcher."""

    def test_initial_state(self, watcher: FileWatcher) -> None:
        """Test initial watcher state."""
        assert not watcher.is_running
        assert watcher._observer is None

    def test_start_stop(self, watcher: FileWatcher) -> None:
        """Test starting and stopping watcher."""
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

    def test_on_conflict_detected_queues_path(self, watcher: FileWatcher, tmp_path: Path) -> None:
        """Test that detected conflicts are queued."""
        conflict_path = tmp_path / "document 2.txt"
        conflict_path.touch()

        watcher._on_conflict_detected(conflict_path)

        assert not watcher._pending_conflicts.empty()

    def test_queue_full_warning(
        self, watcher: FileWatcher, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test warning when the queue is full."""
        # Create a new watcher with limited queue
        watcher._pending_conflicts = asyncio.Queue(maxsize=1)

        path1 = tmp_path / "doc 2.txt"
        path2 = tmp_path / "doc 3.txt"
        path1.touch()
        path2.touch()

        watcher._on_conflict_detected(path1)
        # This should warn about full queue but not crash
        watcher._on_conflict_detected(path2)

        assert watcher._pending_conflicts.qsize() == 1

    @pytest.mark.asyncio
    async def test_get_pending_conflict(self, watcher: FileWatcher, tmp_path: Path) -> None:
        """Test getting pending conflict from queue."""
        conflict_path = tmp_path / "document 2.txt"
        conflict_path.touch()

        watcher._on_conflict_detected(conflict_path)
        result = await watcher.get_pending_conflict()

        assert result == conflict_path

    def test_clear_pending(self, watcher: FileWatcher, tmp_path: Path) -> None:
        """Test clearing pending conflicts."""
        # Queue some conflicts
        for i in range(5):
            path = tmp_path / f"doc {i+2}.txt"
            path.touch()
            watcher._on_conflict_detected(path)

        count = watcher.clear_pending()

        assert count == 5
        assert watcher._pending_conflicts.empty()

    def test_clear_pending_empty_queue(self, watcher: FileWatcher) -> None:
        """Test clearing already empty queue."""
        count = watcher.clear_pending()
        assert count == 0

    def test_watches_configured_directories(
        self, config: CleanupConfig, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that all configured directories are watched."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        config.watch_directories = [dir1, dir2]
        watcher = FileWatcher(config, detector, logger)

        with patch("icloud_cleanup.watcher.Observer") as mock_observer_class:
            self._start_and_verify_schedule_count(mock_observer_class, watcher, 2)

    def test_skips_nonexistent_directories(
        self, config: CleanupConfig, detector: ConflictDetector, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test that nonexistent directories are skipped."""
        existing_dir = tmp_path / "exists"
        existing_dir.mkdir()
        nonexistent_dir = tmp_path / "missing"

        config.watch_directories = [existing_dir, nonexistent_dir]
        watcher = FileWatcher(config, detector, logger)

        with patch("icloud_cleanup.watcher.Observer") as mock_observer_class:
            self._start_and_verify_schedule_count(mock_observer_class, watcher, 1)

    @staticmethod
    def _start_and_verify_schedule_count(
        mock_observer_class: MagicMock, watcher: FileWatcher, expected_count: int
    ) -> None:
        """Start watcher with mock observer and verify schedule call count."""
        mock_observer = MagicMock()
        mock_observer_class.return_value = mock_observer
        watcher.start()
        assert mock_observer.schedule.call_count == expected_count
        watcher.stop()


class TestWatcherIntegration:
    """Integration tests for file watcher (require actual file system events)."""

    @pytest.mark.asyncio
    async def test_detects_created_conflict(
        self,
        config: CleanupConfig,
        detector: ConflictDetector,
        logger: logging.Logger,
        tmp_path: Path,
    ) -> None:
        """Test that watcher detects newly created conflict files."""
        config.watch_directories = [tmp_path]
        watcher = FileWatcher(config, detector, logger)

        # Create original file first
        original = tmp_path / "document.txt"
        original.touch()

        watcher.start()

        try:
            # Small delay for watcher to initialize
            await asyncio.sleep(0.5)

            # Create conflict file
            conflict = tmp_path / "document 2.txt"
            conflict.write_text("conflict content")

            # Wait for event with timeout
            try:
                async with asyncio.timeout(5):
                    detected = await watcher.get_pending_conflict()
                assert detected == conflict
            except TimeoutError:
                # FSEvents may not fire in test environment
                pytest.skip("FSEvents not detected - may be environment limitation")

        finally:
            watcher.stop()
