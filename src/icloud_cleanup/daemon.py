"""Main daemon for iCloud conflict cleanup."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

from .cleaner import Cleaner, CleanupResult
from .detector import ConflictDetector, ConflictFile
from .icloud_status import ICloudStatusChecker
from .modules import discover_modules
from .watcher import FileWatcher

if TYPE_CHECKING:
    from .config import CleanupConfig
    from .modules.base import CleanupModule, DetectedFile


@dataclass
class DaemonStats:
    """Statistics for the daemon."""

    start_time: datetime
    files_detected: int = 0
    files_deleted: int = 0
    files_recovered: int = 0
    files_skipped: int = 0
    errors: int = 0
    per_module: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))


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

        # Discover cleanup modules first (watcher needs them)
        self.modules: list[CleanupModule] = discover_modules(config)
        self.logger.info(
            "Loaded %d cleanup modules: %s",
            len(self.modules),
            ", ".join(m.name for m in self.modules),
        )

        # Initialize components
        self.detector = ConflictDetector(config)
        self.checker = ICloudStatusChecker(config)
        self.cleaner = Cleaner(config, self.logger)
        self.watcher = FileWatcher(config, self.detector, self.logger, modules=self.modules)

        # State
        self.stats = DaemonStats(start_time=datetime.now())
        self._running = False
        self._pending_deletes: dict[Path, tuple[float, DetectedFile | None]] = {}
        self._failed_deletes: dict[Path, tuple[int, float]] = {}  # (count, timestamp)

    def _setup_logging(self) -> logging.Logger:
        """Set up logging for the daemon.

        Returns:
            Configured logger instance.

        """
        logger = logging.getLogger("icloud-cleanup")
        logger.setLevel(getattr(logging, self.config.log_level))

        # Clear existing handlers to avoid duplicates if the daemon is recreated
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
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(file_handler)

        return logger

    async def _process_detected(self, detected: DetectedFile) -> CleanupResult | None:
        """Process a detected file from any module.

        Args:
            detected: Detected file to process.

        Returns:
            Cleanup result, or None if skipped.

        """
        path = detected.path
        current_time = asyncio.get_running_loop().time()

        should_skip, failure_count = self._check_cooldown_status(path, current_time)
        if should_skip:
            self.stats.files_skipped += 1
            return None

        if not path.exists():
            self.stats.files_skipped += 1
            return None

        # Wait for iCloud sync for files that need recovery (iCloud files)
        if detected.recovery_enabled:
            self.logger.debug("Waiting for iCloud sync: %s", path.name)
            if not await self.checker.wait_for_sync(path):
                self.logger.warning("Timeout waiting for sync: %s", path.name)
                self.stats.files_skipped += 1
                return None

        result = self.cleaner.delete_detected(detected)
        self._update_stats_after_delete(path, result, failure_count, current_time)

        # Track per-module stats
        if result.success:
            self.stats.per_module[detected.module_name] += 1

        return result

    async def _process_conflict(self, conflict: ConflictFile) -> CleanupResult | None:
        """Process a single conflict file (backward-compat wrapper).

        Args:
            conflict: Conflict file to process.

        Returns:
            Cleanup result, or None if skipped.

        """
        path = conflict.path
        current_time = asyncio.get_running_loop().time()

        # Check cooldown status
        should_skip, failure_count = self._check_cooldown_status(path, current_time)
        if should_skip:
            self.stats.files_skipped += 1
            return None

        # Check if the original exists
        if not conflict.original_path.exists():
            self.logger.warning(
                "Skipping %s - original file doesn't exist: %s",
                path.name,
                conflict.original_path.name,
            )
            self.stats.files_skipped += 1
            return None

        # Wait for iCloud sync to complete
        self.logger.debug("Waiting for iCloud sync: %s", path.name)
        if not await self.checker.wait_for_sync(path):
            self.logger.warning("Timeout waiting for sync: %s", path.name)
            self.stats.files_skipped += 1
            return None

        # Delete/recover the conflict
        result = self.cleaner.delete_conflict(conflict)

        # Update stats and failure tracking
        self._update_stats_after_delete(path, result, failure_count, current_time)

        return result

    def _check_cooldown_status(self, path: Path, current_time: float) -> tuple[bool, int]:
        """Check if a file is in cooldown and return its failure count.

        Args:
            path: Path to check.
            current_time: Current loop time.

        Returns:
            Tuple of (should_skip, failure_count).

        """
        if path not in self._failed_deletes:
            return False, 0

        failure_count, last_failure_time = self._failed_deletes[path]
        time_since_failure = current_time - last_failure_time

        if failure_count < self.config.max_delete_retries:
            return False, failure_count

        if time_since_failure < self.config.retry_cooldown:
            return True, failure_count

        # Cooldown expired - reset counter and try again
        self.logger.info(
            "Cooldown expired for %s, retrying (was %d failures)",
            path.name,
            failure_count,
        )
        del self._failed_deletes[path]
        return False, 0

    def _update_stats_after_delete(
        self, path: Path, result: CleanupResult, failure_count: int, current_time: float
    ) -> None:
        """Update stats and failure tracking after a deletion attempt.

        Args:
            path: Path that was processed.
            result: Result of the deletion attempt.
            failure_count: Number of prior failures for this path.
            current_time: Current loop time.

        """
        if result.success:
            if result.action == "deleted":
                self.stats.files_deleted += 1
            elif result.action == "recovered":
                self.stats.files_recovered += 1
            self._failed_deletes.pop(path, None)
            return

        self.stats.errors += 1
        new_count = failure_count + 1
        self._failed_deletes[path] = (new_count, current_time)

        if new_count >= self.config.max_delete_retries:
            self.logger.warning(
                "Failed to delete %s (%d/%d attempts), cooldown %ds",
                path.name,
                new_count,
                self.config.max_delete_retries,
                self.config.retry_cooldown,
            )
        else:
            self.logger.debug(
                "Failed to delete %s (attempt %d/%d)",
                path.name,
                new_count,
                self.config.max_delete_retries,
            )

    async def _process_pending_deletes(self) -> None:
        """Process files that have been pending long enough."""
        current_time = asyncio.get_running_loop().time()

        ready: list[tuple[Path, DetectedFile | None]] = []
        for path, (timestamp, detected) in self._pending_deletes.items():
            wait_time = 0 if (detected and not detected.recovery_enabled) else self.config.wait_before_delete
            if current_time - timestamp >= wait_time:
                ready.append((path, detected))

        for path, _ in ready:
            del self._pending_deletes[path]

        for path, detected in ready:
            if detected is not None:
                await self._process_detected(detected)
            elif conflict := self.detector.is_conflict_file(path):
                await self._process_conflict(conflict)

    def _scan_and_queue(self) -> None:
        """Scan all directories using all modules and queue files for deletion."""
        current_time = asyncio.get_running_loop().time()

        # Scan via all modules
        for module in self.modules:
            for detected in module.scan_all():
                if detected.path not in self._pending_deletes:
                    self._pending_deletes[detected.path] = (current_time, detected)
                    self.stats.files_detected += 1
                    self.logger.info(
                        "Queued [%s]: %s — %s",
                        detected.module_name,
                        detected.path.name,
                        detected.reason,
                    )

    async def run_once(self) -> list[CleanupResult]:
        """Run a single cleanup pass.

        Returns:
            List of cleanup results.

        """
        self.logger.info("Starting single cleanup pass...")
        results: list[CleanupResult] = []

        # Scan via all modules
        all_detected: list[DetectedFile] = []
        for module in self.modules:
            all_detected.extend(module.scan_all())

        self.logger.info("Found %d files to process across %d modules", len(all_detected), len(self.modules))

        for detected in all_detected:
            self.stats.files_detected += 1

            # Only delay for files that want recovery (iCloud conflicts)
            if detected.recovery_enabled:
                self.logger.info(
                    "Waiting %ds before processing: %s",
                    self.config.wait_before_delete,
                    detected.path.name,
                )
                await asyncio.sleep(self.config.wait_before_delete)

            if result := await self._process_detected(detected):
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

                # Check for new files from the watcher
                while True:
                    try:
                        async with asyncio.timeout(0.1):
                            path, detected = await self.watcher.get_pending()
                    except TimeoutError:
                        break
                    if path not in self._pending_deletes:
                        self._pending_deletes[path] = (asyncio.get_running_loop().time(), detected)
                        self.stats.files_detected += 1
                        label = f"[{detected.module_name}]" if detected else "conflict"
                        self.logger.info("Detected %s: %s", label, path.name)

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
                self.stats.files_detected,
                self.stats.files_deleted,
                self.stats.files_recovered,
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
