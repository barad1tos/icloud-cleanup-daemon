"""Main daemon for iCloud conflict cleanup."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

from .cleaner import Cleaner, CleanupResult
from .detector import ConflictDetector, ConflictFile
from .icloud_status import ICloudStatusChecker
from .watcher import FileWatcher

if TYPE_CHECKING:
    from .config import CleanupConfig


@dataclass
class DaemonStats:
    """Statistics for the daemon."""

    start_time: datetime
    conflicts_detected: int = 0
    conflicts_deleted: int = 0
    conflicts_recovered: int = 0
    conflicts_skipped: int = 0
    errors: int = 0


class ICloudCleanupDaemon:
    """Main daemon for cleaning up iCloud sync conflicts."""

    def __init__(self, config: CleanupConfig) -> None:
        """Initialize the daemon.

        Args:
            config: Cleanup configuration.

        """
        self.config = config
        self.logger = self._setup_logging()
        self.console = Console()

        # Initialize components
        self.detector = ConflictDetector(config)
        self.checker = ICloudStatusChecker(config)
        self.cleaner = Cleaner(config, self.logger)
        self.watcher = FileWatcher(config, self.detector, self.logger)

        # State
        self.stats = DaemonStats(start_time=datetime.now())
        self._running = False
        self._pending_deletes: dict[Path, float] = {}  # path -> timestamp when detected

    def _setup_logging(self) -> logging.Logger:
        """Set up logging for the daemon.

        Returns:
            Configured logger instance.

        """
        logger = logging.getLogger("icloud-cleanup")
        logger.setLevel(getattr(logging, self.config.log_level))

        # Clear existing handlers to avoid duplicates if daemon is recreated
        if logger.handlers:
            logger.handlers.clear()

        # Console handler with Rich
        console_handler = RichHandler(
            console=Console(),
            show_time=True,
            show_path=False,
        )
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        # File handler
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(self.config.log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        )
        logger.addHandler(file_handler)

        return logger

    async def _process_conflict(self, conflict: ConflictFile) -> CleanupResult | None:
        """Process a single conflict file.

        Args:
            conflict: Conflict file to process.

        Returns:
            Cleanup result, or None if skipped.

        """
        path = conflict.path

        # Check if the original exists
        if not conflict.original_path.exists():
            self.logger.warning(
                "Skipping %s - original file doesn't exist: %s",
                path.name,
                conflict.original_path.name,
            )
            self.stats.conflicts_skipped += 1
            return None

        # Wait for iCloud sync to complete
        self.logger.debug("Waiting for iCloud sync: %s", path.name)
        if not await self.checker.wait_for_sync(path):
            self.logger.warning("Timeout waiting for sync: %s", path.name)
            self.stats.conflicts_skipped += 1
            return None

        # Delete/recover the conflict
        result = self.cleaner.delete_conflict(conflict)

        # Update stats
        if result.success:
            if result.action == "deleted":
                self.stats.conflicts_deleted += 1
            elif result.action == "recovered":
                self.stats.conflicts_recovered += 1
        else:
            self.stats.errors += 1

        return result

    async def _process_pending_deletes(self) -> None:
        """Process files that have been pending long enough."""
        current_time = asyncio.get_running_loop().time()

        paths_to_process = [
            path
            for path, timestamp in self._pending_deletes.items()
            if current_time - timestamp >= self.config.wait_before_delete
        ]
        for path in paths_to_process:
            del self._pending_deletes[path]

        for path in paths_to_process:
            if conflict := self.detector.is_conflict_file(path):
                await self._process_conflict(conflict)

    def _scan_and_queue(self) -> None:
        """Scan all directories and queue conflicts for deletion."""
        conflicts = self.detector.scan_all()
        current_time = asyncio.get_running_loop().time()

        for conflict in conflicts:
            # Only queue if the original file exists (otherwise it's not a real conflict)
            if not conflict.original_path.exists():
                continue
            if conflict.path not in self._pending_deletes:
                self._pending_deletes[conflict.path] = current_time
                self.stats.conflicts_detected += 1
                self.logger.info("Queued for deletion: %s", conflict.path.name)

    async def run_once(self) -> list[CleanupResult]:
        """Run a single cleanup pass.

        Returns:
            List of cleanup results.

        """
        self.logger.info("Starting single cleanup pass...")
        results: list[CleanupResult] = []

        all_conflicts = self.detector.scan_all()
        # Filter to only real conflicts (where the original exists)
        conflicts = [c for c in all_conflicts if c.original_path.exists()]
        if false_positives := len(all_conflicts) - len(conflicts):
            self.logger.debug(
                "Filtered out %d files where original doesn't exist",
                false_positives,
            )
        self.logger.info("Found %d conflict files", len(conflicts))

        for conflict in conflicts:
            self.stats.conflicts_detected += 1

            # Wait a specified time
            self.logger.info(
                "Waiting %ds before processing: %s",
                self.config.wait_before_delete,
                conflict.path.name,
            )
            await asyncio.sleep(self.config.wait_before_delete)

            if result := await self._process_conflict(conflict):
                results.append(result)

        if cleaned := self.cleaner.cleanup_recovery_dir():
            self.logger.info("Cleaned %d expired recovery directories", cleaned)

        return results

    async def run_daemon(self) -> None:
        """Run the daemon continuously."""
        self._running = True
        self.logger.info("Starting iCloud cleanup daemon...")

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start file watcher
        self.watcher.start()

        # Initial scan
        self._scan_and_queue()

        try:
            while self._running:
                # Process any pending deletes
                await self._process_pending_deletes()

                # Check for new conflicts from watcher
                while True:
                    try:
                        async with asyncio.timeout(0.1):
                            path = await self.watcher.get_pending_conflict()
                    except TimeoutError:
                        break
                    if path not in self._pending_deletes:
                        self._pending_deletes[path] = asyncio.get_running_loop().time()
                        self.stats.conflicts_detected += 1
                        self.logger.info("Detected new conflict: %s", path.name)

                # Periodic full scan
                await asyncio.sleep(self.config.scan_interval)
                self._scan_and_queue()

                # Periodic recovery cleanup
                self.cleaner.cleanup_recovery_dir()

        except asyncio.CancelledError:
            self.logger.info("Daemon cancelled")
            raise
        finally:
            self.watcher.stop()
            self.logger.info(
                "Daemon stopped. Stats: detected=%d, deleted=%d, recovered=%d, errors=%d",
                self.stats.conflicts_detected,
                self.stats.conflicts_deleted,
                self.stats.conflicts_recovered,
                self.stats.errors,
            )

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        self.logger.info("Shutdown signal received")
        self._running = False

    def stop(self) -> None:
        """Stop the daemon."""
        self._running = False
        self.watcher.stop()
