"""Check iCloud sync status using brctl and xattr."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CleanupConfig

SUBPROCESS_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Possible states of a file's iCloud sync lifecycle."""

    SYNCED = "synced"
    UPLOADING = "uploading"
    DOWNLOADING = "downloading"
    WAITING = "waiting"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class FileStatus:
    """Snapshot of a file's sync state, placeholder presence, and upload status."""

    path: Path
    status: SyncStatus
    is_placeholder: bool
    is_uploaded: bool


class ICloudStatusChecker:
    """Check iCloud sync status for files."""

    def __init__(self, config: CleanupConfig) -> None:
        self.config = config

    @staticmethod
    def get_file_status(path: Path) -> FileStatus:
        """Inspect xattr to determine whether a file is synced, uploading, or downloading."""
        if not path.exists():
            return FileStatus(
                path=path,
                status=SyncStatus.UNKNOWN,
                is_placeholder=False,
                is_uploaded=False,
            )

        try:
            # Check for iCloud placeholder (.icloud file)
            if path.name.startswith(".") and path.name.endswith(".icloud"):
                return FileStatus(
                    path=path,
                    status=SyncStatus.DOWNLOADING,
                    is_placeholder=True,
                    is_uploaded=True,
                )

            # Note: Don't use text=True because xattr output may contain
            # binary data that isn't valid UTF-8
            result = subprocess.run(
                ["xattr", "-l", str(path)],
                capture_output=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )

            xattrs = result.stdout.decode("utf-8", errors="replace")

            is_placeholder = "com.apple.icloud.itemDownloadPending" in xattrs
            is_uploading = "com.apple.icloud.itemUploadPending" in xattrs

            if is_uploading:
                sync_status = SyncStatus.UPLOADING
            elif is_placeholder:
                sync_status = SyncStatus.DOWNLOADING
            else:
                sync_status = SyncStatus.SYNCED

            return FileStatus(
                path=path,
                status=sync_status,
                is_placeholder=is_placeholder,
                is_uploaded=not is_uploading,
            )

        except subprocess.TimeoutExpired:
            logger.debug("xattr timed out for: %s", path)
            return FileStatus(
                path=path,
                status=SyncStatus.UNKNOWN,
                is_placeholder=False,
                is_uploaded=False,
            )
        except (subprocess.SubprocessError, OSError):
            logger.debug("Failed to read xattr for: %s", path, exc_info=True)
            return FileStatus(
                path=path,
                status=SyncStatus.UNKNOWN,
                is_placeholder=False,
                is_uploaded=False,
            )

    def is_synced(self, path: Path) -> bool:
        """Return True when no pending iCloud upload or download attributes are present."""
        file_status = self.get_file_status(path)
        return file_status.status == SyncStatus.SYNCED

    async def wait_for_sync(self, path: Path) -> bool:
        """Poll xattr until iCloud sync completes or timeout is reached."""
        elapsed = 0
        # Ensure minimum poll interval to prevent infinite loop
        poll_interval = max(self.config.icloud_poll_interval, 1)

        while elapsed < self.config.max_icloud_wait:
            synced = await asyncio.to_thread(self.is_synced, path)
            if synced:
                return True

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return False

    @staticmethod
    def get_icloud_drive_status() -> dict[str, str]:
        """Parse brctl status output into a key-value dictionary."""
        try:
            result = subprocess.run(
                ["brctl", "status"],
                capture_output=True,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )

            status_info: dict[str, str] = {}

            for line in result.stdout.split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    status_info[key.strip()] = value.strip()

            return status_info

        except subprocess.TimeoutExpired:
            logger.debug("brctl status timed out")
            return {"status": "unknown"}
        except (subprocess.SubprocessError, OSError):
            logger.debug("Failed to get brctl status", exc_info=True)
            return {"status": "unknown"}

    def is_icloud_idle(self) -> bool:
        """Return True when brctl reports no active uploads or downloads."""
        drive_status = self.get_icloud_drive_status()
        drive_status_text = str(drive_status).lower()
        return (
            "uploading" not in drive_status_text
            and "downloading" not in drive_status_text
        )
