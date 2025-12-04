"""Configuration management for iCloud cleanup daemon."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CleanupConfig:
    """Configuration for the iCloud cleanup daemon."""

    # Directories to monitor for iCloud conflicts
    watch_directories: list[Path] = field(default_factory=list)

    # File patterns to match as conflicts (regex)
    # Default: matches "filename 2.ext", "filename 3.ext", etc.
    conflict_pattern: str = r"^(.+)\s+(\d+)(\.[^.]+)?$"

    # Wait time before deleting (seconds) - allows iCloud to finish syncing
    wait_before_delete: int = 180  # 3 minutes

    # Polling interval for iCloud sync status (seconds)
    icloud_poll_interval: int = 10

    # Maximum wait time for iCloud sync (seconds)
    max_icloud_wait: int = 300  # 5 minutes

    # Recovery settings
    enable_recovery: bool = True
    recovery_dir: Path = field(default_factory=lambda: Path.home() / ".icloud-cleanup-trash")
    recovery_retention_days: int = 7

    # Logging
    log_file: Path = field(
        default_factory=lambda: Path.home() / "Library/Logs/icloud-cleanup-daemon.log"
    )
    log_level: str = "INFO"

    # Daemon settings
    scan_interval: int = 60  # Seconds between full scans (when not using FSEvents)

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the default configuration file path."""
        return Path.home() / "Library/Application Support/icloud-cleanup/config.yaml"

    @classmethod
    def load(cls, config_path: Path | None = None) -> CleanupConfig:
        """Load configuration from YAML file.

        Args:
            config_path: Path to config file. Uses default if None.

        Returns:
            Loaded configuration.

        """
        if config_path is None:
            config_path = cls.get_config_path()

        if not config_path.exists():
            # Return default config with iCloud Drive as default watch directory
            config = cls()
            config.watch_directories = cls._get_default_watch_directories()
            return config

        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> CleanupConfig:
        """Create config from dictionary."""
        config = cls()

        # Watch directories
        if "watch_directories" in data:
            config.watch_directories = [
                Path(os.path.expanduser(p)) for p in data["watch_directories"]
            ]
        else:
            config.watch_directories = cls._get_default_watch_directories()

        # Simple fields
        if "conflict_pattern" in data:
            config.conflict_pattern = data["conflict_pattern"]
        if "wait_before_delete" in data:
            config.wait_before_delete = int(data["wait_before_delete"])
        if "icloud_poll_interval" in data:
            config.icloud_poll_interval = int(data["icloud_poll_interval"])
        if "max_icloud_wait" in data:
            config.max_icloud_wait = int(data["max_icloud_wait"])
        if "scan_interval" in data:
            config.scan_interval = int(data["scan_interval"])

        # Recovery settings
        if "recovery" in data:
            recovery = data["recovery"]
            if "enabled" in recovery:
                config.enable_recovery = bool(recovery["enabled"])
            if "directory" in recovery:
                config.recovery_dir = Path(os.path.expanduser(recovery["directory"]))
            if "retention_days" in recovery:
                config.recovery_retention_days = int(recovery["retention_days"])

        # Logging
        if "logging" in data:
            logging_cfg = data["logging"]
            if "file" in logging_cfg:
                config.log_file = Path(os.path.expanduser(logging_cfg["file"]))
            if "level" in logging_cfg:
                config.log_level = logging_cfg["level"]

        return config

    @classmethod
    def _get_default_watch_directories(cls) -> list[Path]:
        """Get default iCloud directories to watch."""
        icloud_base = Path.home() / "Library/Mobile Documents"
        directories: list[Path] = []

        if icloud_base.exists():
            # Add iCloud Drive
            icloud_drive = icloud_base / "com~apple~CloudDocs"
            if icloud_drive.exists():
                directories.append(icloud_drive)

        return directories

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to YAML file.

        Args:
            config_path: Path to save config. Uses default if None.

        """
        if config_path is None:
            config_path = self.get_config_path()

        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "watch_directories": [str(p) for p in self.watch_directories],
            "conflict_pattern": self.conflict_pattern,
            "wait_before_delete": self.wait_before_delete,
            "icloud_poll_interval": self.icloud_poll_interval,
            "max_icloud_wait": self.max_icloud_wait,
            "scan_interval": self.scan_interval,
            "recovery": {
                "enabled": self.enable_recovery,
                "directory": str(self.recovery_dir),
                "retention_days": self.recovery_retention_days,
            },
            "logging": {
                "file": str(self.log_file),
                "level": self.log_level,
            },
        }

        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
