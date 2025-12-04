"""File system watcher for iCloud conflict files using FSEvents."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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
            self._check_path(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle file move events (iCloud often moves files).

        Args:
            event: File system event.

        """
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            self._check_path(Path(event.dest_path))

    def _check_path(self, path: Path) -> None:
        """Check if path is a conflict file.

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
        self._observer: Observer | None = None
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
        """Check if watcher is running."""
        return self._running

    async def get_pending_conflict(self, timeout: float | None = None) -> Path | None:
        """Get a pending conflict file from the queue.

        Args:
            timeout: Maximum time to wait for a conflict.

        Returns:
            Path to conflict file, or None if timeout.

        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(
                    self._pending_conflicts.get(),
                    timeout=timeout,
                )
            else:
                return await self._pending_conflicts.get()
        except asyncio.TimeoutError:
            return None

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
