"""File system watcher for iCloud conflict files using FSEvents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .modules.base import DetectedFile

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

    from .config import CleanupConfig
    from .detector import ConflictDetector
    from .modules.base import CleanupModule


class ConflictEventHandler(FileSystemEventHandler):
    """Handles file system events for conflict detection."""

    def __init__(
        self,
        detector: ConflictDetector,
        callback: Callable[[Path, DetectedFile | None], None],
        logger: logging.Logger,
        modules: list[CleanupModule] | None = None,
    ) -> None:
        """Initialize the event handler.

        Args:
            detector: Conflict detector instance.
            callback: Invoked with (path, DetectedFile) when a match occurs.
            logger: Logger instance.
            modules: Optional list of cleanup modules with supports_watch=True.

        """
        super().__init__()
        self.detector = detector
        self.callback = callback
        self.logger = logger
        self._watch_modules = [m for m in (modules or []) if m.supports_watch]

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
        """Check if the path matches any watch-capable module.

        Iterates all watch-capable modules first, then falls back to the
        legacy detector. The first match wins. DetectedFile context is
        passed through the callback, so the daemon preserves module info.

        Args:
            path: Path to check.

        """
        for module in self._watch_modules:
            if detected := module.is_target(path):
                self.logger.debug("Detected [%s]: %s", detected.module_name, path.name)
                self.callback(path, detected)
                return

        # Legacy detector fallback — wrap in a DetectedFile for the unified pipeline
        if self.detector.is_conflict_file(path):
            detected = DetectedFile(
                path=path,
                module_name="icloud_conflicts",
                reason="iCloud conflict (legacy detector)",
                recovery_enabled=True,
            )
            self.logger.debug("Detected [legacy]: %s", path.name)
            self.callback(path, detected)


class FileWatcher:
    """Watches directories for iCloud conflict files using FSEvents."""

    def __init__(
        self,
        config: CleanupConfig,
        detector: ConflictDetector,
        logger: logging.Logger,
        modules: list[CleanupModule] | None = None,
    ) -> None:
        """Initialize the file watcher.

        Args:
            config: Cleanup configuration.
            detector: Conflict detector instance.
            logger: Logger instance.
            modules: Optional list of cleanup modules for a multi-module watch.

        """
        self.config = config
        self.detector = detector
        self.logger = logger
        self._modules = modules or []
        self._observer: Any = None
        self._pending_queue: asyncio.Queue[tuple[Path, DetectedFile | None]] = asyncio.Queue()
        self._running = False

    def _on_file_detected(self, path: Path, detected: DetectedFile | None) -> None:
        """Handle a detected file from any module.

        Args:
            path: Path to the detected file.
            detected: DetectedFile with module context, or None for legacy matches.

        """
        try:
            self._pending_queue.put_nowait((path, detected))
        except asyncio.QueueFull:
            self.logger.warning("Watch queue full, dropping: %s", path.name)

    def start(self) -> None:
        """Start watching configured directories."""
        if self._observer is not None:
            return

        self._observer = Observer()
        handler = ConflictEventHandler(
            self.detector,
            self._on_file_detected,
            self.logger,
            modules=self._modules,
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

    async def get_pending(self) -> tuple[Path, DetectedFile | None]:
        """Get a pending detected file from the queue.

        Returns:
            Tuple of the path, and DetectedFile or None for legacy matches.

        """
        return await self._pending_queue.get()

    def clear_pending(self) -> int:
        """Clear all pending items.

        Returns:
            Number of items cleared.

        """
        count = 0
        while not self._pending_queue.empty():
            try:
                self._pending_queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        return count
