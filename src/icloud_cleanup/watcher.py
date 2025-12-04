"""File system watcher for iCloud conflict files using FSEvents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

    from .config import CleanupConfig
    from .detector import ConflictDetector


class ConflictEventHandler(FileSystemEventHandler):
    """Handles file system events for conflict detection."""

    def __init__(
        self,
        detector: ConflictDetector,
        callback: Callable[[Path], None],
        logger: logging.Logger,
    ) -> None:
        """Initialize the event handler.

        Args:
            detector: Conflict detector instance.
            callback: Function to call when conflict is detected.
            logger: Logger instance.

        """
        super().__init__()
        self.detector = detector
        self.callback = callback
        self.logger = logger

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events.

        Args:
            event: File system event.

        """
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            src_path = event.src_path if isinstance(event.src_path, str) else event.src_path.decode()
            self._check_path(Path(src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle file move events (iCloud often moves files).

        Args:
            event: File system event.

        """
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            dest_path = event.dest_path if isinstance(event.dest_path, str) else event.dest_path.decode()
            self._check_path(Path(dest_path))

    def _check_path(self, path: Path) -> None:
        """Check if the path is a conflict file.

        Args:
            path: Path to check.

        """
        if conflict := self.detector.is_conflict_file(path):
            self.logger.debug("Detected conflict file: %s", conflict.path.name)
            self.callback(path)


class FileWatcher:
    """Watches directories for iCloud conflict files using FSEvents."""

    def __init__(
        self,
        config: CleanupConfig,
        detector: ConflictDetector,
        logger: logging.Logger,
    ) -> None:
        """Initialize the file watcher.

        Args:
            config: Cleanup configuration.
            detector: Conflict detector instance.
            logger: Logger instance.

        """
        self.config = config
        self.detector = detector
        self.logger = logger
        self._observer: Any = None
        self._pending_conflicts: asyncio.Queue[Path] = asyncio.Queue()
        self._running = False

    def _on_conflict_detected(self, path: Path) -> None:
        """Handle detected conflict file.

        Args:
            path: Path to conflict file.

        """
        try:
            self._pending_conflicts.put_nowait(path)
        except asyncio.QueueFull:
            self.logger.warning("Conflict queue full, dropping: %s", path.name)

    def start(self) -> None:
        """Start watching configured directories."""
        if self._observer is not None:
            return

        self._observer = Observer()
        handler = ConflictEventHandler(
            self.detector,
            self._on_conflict_detected,
            self.logger,
        )

        for directory in self.config.watch_directories:
            if directory.exists():
                self._observer.schedule(handler, str(directory), recursive=True)
                self.logger.info("Watching directory: %s", directory)
            else:
                self.logger.warning("Watch directory does not exist: %s", directory)

        self._observer.start()
        self._running = True
        self.logger.info("File watcher started")

    def stop(self) -> None:
        """Stop watching directories."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
            self._running = False
            self.logger.info("File watcher stopped")

    @property
    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running

    async def get_pending_conflict(self) -> Path:
        """Get a pending conflict file from the queue.

        Returns:
            Path to conflict file.

        """
        return await self._pending_conflicts.get()

    def clear_pending(self) -> int:
        """Clear all pending conflicts.

        Returns:
            Number of conflicts cleared.

        """
        count = 0
        while not self._pending_conflicts.empty():
            try:
                self._pending_conflicts.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        return count
