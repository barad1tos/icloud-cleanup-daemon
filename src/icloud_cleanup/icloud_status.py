"""Check iCloud sync status using brctl and xattr."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CleanupConfig


class SyncStatus(Enum):
    """iCloud sync status for a file."""

    SYNCED = "synced"  # Fully synced
    UPLOADING = "uploading"  # Being uploaded to iCloud
    DOWNLOADING = "downloading"  # Being downloaded from iCloud
    WAITING = "waiting"  # Waiting to sync
    ERROR = "error"  # Sync error
    UNKNOWN = "unknown"  # Cannot determine status


@dataclass
class FileStatus:
    """Status of a file in iCloud."""

    path: Path
    status: SyncStatus
    is_placeholder: bool  # True if file is not downloaded locally
    is_uploaded: bool  # True if file exists in iCloud


class ICloudStatusChecker:
    """Check iCloud sync status for files."""

    def __init__(self, config: CleanupConfig) -> None:
        """Initialize the checker.

        Args:
            config: Cleanup configuration.

        """
        self.config = config

    def get_file_status(self, path: Path) -> FileStatus:
        """Get the sync status of a file.

        Uses xattr to check iCloud extended attributes.

        Args:
            path: Path to check.

        Returns:
            FileStatus with sync information.

        """
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

            # Use xattr to check com.apple.icloud attributes
            result = subprocess.run(
                ["xattr", "-l", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )

            xattrs = result.stdout

            # Check for various iCloud attributes
            is_placeholder = "com.apple.icloud.itemDownloadPending" in xattrs
            is_uploading = "com.apple.icloud.itemUploadPending" in xattrs

            if is_uploading:
                status = SyncStatus.UPLOADING
            elif is_placeholder:
                status = SyncStatus.DOWNLOADING
            else:
                status = SyncStatus.SYNCED

            return FileStatus(
                path=path,
                status=status,
                is_placeholder=is_placeholder,
                is_uploaded=not is_uploading,
            )

        except (subprocess.SubprocessError, OSError):
            return FileStatus(
                path=path,
                status=SyncStatus.UNKNOWN,
                is_placeholder=False,
                is_uploaded=False,
            )

    def is_synced(self, path: Path) -> bool:
        """Check if a file is fully synced.

        Args:
            path: Path to check.

        Returns:
            True if the file is fully synced and safe to delete.

        """
        status = self.get_file_status(path)
        return status.status == SyncStatus.SYNCED

    async def wait_for_sync(self, path: Path) -> bool:
        """Wait for a file to finish syncing.

        Args:
            path: Path to wait for.

        Returns:
            True if file is synced, False if timeout exceeded.

        """
        elapsed = 0

        while elapsed < self.config.max_icloud_wait:
            if self.is_synced(path):
                return True

            await asyncio.sleep(self.config.icloud_poll_interval)
            elapsed += self.config.icloud_poll_interval

        return False

    def get_icloud_drive_status(self) -> dict[str, str]:
        """Get overall iCloud Drive sync status using brctl.

        Returns:
            Dictionary with status information.

        """
        try:
            result = subprocess.run(
                ["brctl", "status"],
                capture_output=True,
                text=True,
                check=False,
            )

            status_info: dict[str, str] = {}

            for line in result.stdout.split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    status_info[key.strip()] = value.strip()

            return status_info

        except (subprocess.SubprocessError, OSError):
            return {"status": "unknown"}

    def is_icloud_idle(self) -> bool:
        """Check if iCloud Drive is idle (not syncing anything).

        Returns:
            True if iCloud appears to be idle.

        """
        status = self.get_icloud_drive_status()
        # brctl status output varies, check for common indicators
        status_text = str(status).lower()
        return "uploading" not in status_text and "downloading" not in status_text
