"""File system watcher for iCloud Drive using FSEvents."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

# watchdog.observers.Observer is a dynamic ObserverType, not valid in type annotations
_ObserverType = Any

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

    from .config import CleanupConfig


class ConflictEventHandler(FileSystemEventHandler):
    """Zero-I/O handler: enqueues raw paths without stat() calls."""

    def __init__(
        self,
        watcher: FileWatcher,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self._watcher = watcher
        self.logger = logger

    def on_created(self, event: FileSystemEvent) -> None:
        """Enqueue the source path of non-directory creation events."""
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            src_path = event.src_path if isinstance(event.src_path, str) else event.src_path.decode()
            self._watcher.enqueue_path(Path(src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        """Enqueue the destination path of non-directory move events."""
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            dest_path = event.dest_path if isinstance(event.dest_path, str) else event.dest_path.decode()
            self._watcher.enqueue_path(Path(dest_path))


class FileWatcher:
    """Watches directories using FSEvents with zero-I/O buffering.

    Paths are collected in a Lock-protected set for deduplication.
    The daemon drains the set periodically via drain_paths().
    """

    def __init__(
        self,
        config: CleanupConfig,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.logger = logger
        self._observer: _ObserverType | None = None
        self._lock = threading.Lock()
        self._paths: set[Path] = set()
        self._running = False

    def enqueue_path(self, path: Path) -> None:
        """Add a path to the buffer (called from watchdog thread)."""
        with self._lock:
            self._paths.add(path)

    def drain_paths(self) -> set[Path]:
        """Atomically swap the buffer and return all buffered paths."""
        with self._lock:
            paths = self._paths
            self._paths = set()
        return paths

    def start(self) -> None:
        """Start watching configured directories."""
        if self._observer is not None:
            return

        self._observer = Observer()
        handler = ConflictEventHandler(self, self.logger)

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
        return self._running
