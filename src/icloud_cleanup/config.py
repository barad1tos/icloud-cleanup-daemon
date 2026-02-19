"""Configuration management for iCloud cleanup daemon."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def parse_bool(value: Any, default: bool) -> bool:
    """Coerce YAML string representations ('true', 'yes', 'on', '1') to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "on", "1")
    return bool(value)


@dataclass
class CleanupConfig:
    """YAML-backed settings for watch directories, recovery, and module toggles."""

    # Directories to monitor for iCloud conflicts
    watch_directories: list[Path] = field(default_factory=list)

    # File patterns to match as conflicts (regex)
    # Default: matches "filename 2.ext", "filename 3.ext", etc.
    # iCloud conflict numbers start at 2, not 1
    conflict_pattern: str = r"^(.+)\s+([2-9]|\d{2,})(\.[^.]+)?$"

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
    log_file: Path = field(default_factory=lambda: Path.home() / "Library/Logs/icloud-cleanup-daemon.log")
    log_level: str = "INFO"

    # Daemon settings
    scan_interval: int = 60  # Seconds between full scans (when not using FSEvents)
    max_delete_retries: int = 3  # Max attempts to delete a file before cooldown
    retry_cooldown: int = 3600  # Seconds to wait after max retries before trying again

    # Module settings
    modules_disabled: list[str] = field(default_factory=list)

    # Nosync settings
    nosync_auto_repair: bool = True
    nosync_valuable_patterns: list[str] = field(default_factory=list)
    nosync_ephemeral_patterns: list[str] = field(default_factory=list)

    @classmethod
    def get_config_path(cls) -> Path:
        """Return the platform-specific default config file path (macOS Application Support)."""
        return Path.home() / "Library/Application Support/icloud-cleanup/config.yaml"

    @classmethod
    def load(cls, config_path: Path | None = None) -> CleanupConfig:
        """Load configuration from a YAML file, falling back to defaults if absent."""
        if config_path is None:
            config_path = cls.get_config_path()

        if not config_path.exists():
            # Return the default config with iCloud Drive as the default watch directory
            config = cls()
            config.watch_directories = cls._get_default_watch_directories()
            return config

        try:
            with config_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            msg = f"Invalid YAML in {config_path}: {exc}"
            raise ValueError(msg) from exc

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> CleanupConfig:
        """Create config from a dictionary."""
        config = cls()

        # Watch directories
        watch_dirs = data.get("watch_directories")
        config.watch_directories = (
            [Path(os.path.expanduser(p)) for p in watch_dirs]
            if watch_dirs is not None
            else cls._get_default_watch_directories()
        )

        # Simple scalar fields
        config.conflict_pattern = data.get("conflict_pattern", config.conflict_pattern)
        config.wait_before_delete = int(data.get("wait_before_delete", config.wait_before_delete))
        config.icloud_poll_interval = int(data.get("icloud_poll_interval", config.icloud_poll_interval))
        config.max_icloud_wait = int(data.get("max_icloud_wait", config.max_icloud_wait))
        config.scan_interval = int(data.get("scan_interval", config.scan_interval))

        # Nested sections
        cls._apply_recovery_config(config, data.get("recovery", {}))
        cls._apply_logging_config(config, data.get("logging", {}))
        cls._apply_modules_config(config, data.get("modules", {}))
        cls._apply_nosync_config(config, data.get("nosync", {}))

        cls._validate(config)

        return config

    @staticmethod
    def _validate(config: CleanupConfig) -> None:
        """Guard against misconfigured intervals that cause infinite loops or hangs."""
        if config.scan_interval <= 0:
            msg = f"scan_interval must be positive, got {config.scan_interval}"
            raise ValueError(msg)
        if config.wait_before_delete < 0:
            msg = f"wait_before_delete must be non-negative, got {config.wait_before_delete}"
            raise ValueError(msg)
        if config.icloud_poll_interval <= 0:
            msg = f"icloud_poll_interval must be positive, got {config.icloud_poll_interval}"
            raise ValueError(msg)

    @classmethod
    def _apply_recovery_config(cls, config: CleanupConfig, recovery: dict[str, Any]) -> None:
        """Apply recovery settings from config dict."""
        config.enable_recovery = parse_bool(recovery.get("enabled"), config.enable_recovery)
        if "directory" in recovery:
            config.recovery_dir = Path(os.path.expanduser(recovery["directory"]))
        config.recovery_retention_days = int(recovery.get("retention_days", config.recovery_retention_days))

    @classmethod
    def _apply_logging_config(cls, config: CleanupConfig, logging_cfg: dict[str, Any]) -> None:
        """Apply logging settings from config dict."""
        if "file" in logging_cfg:
            config.log_file = Path(os.path.expanduser(logging_cfg["file"]))
        config.log_level = logging_cfg.get("level", config.log_level)

    @classmethod
    def _apply_modules_config(cls, config: CleanupConfig, modules_cfg: dict[str, Any]) -> None:
        """Apply modules settings from config dict."""
        disabled = modules_cfg.get("disabled", [])
        if isinstance(disabled, str):
            disabled = [disabled]
        if isinstance(disabled, list):
            config.modules_disabled = [str(name) for name in disabled]

    @classmethod
    def _apply_nosync_config(cls, config: CleanupConfig, nosync_cfg: dict[str, Any]) -> None:
        """Apply nosync settings from config dict."""
        config.nosync_auto_repair = parse_bool(nosync_cfg.get("auto_repair"), config.nosync_auto_repair)
        valuable = nosync_cfg.get("valuable_patterns", [])
        if isinstance(valuable, list):
            config.nosync_valuable_patterns = [str(p) for p in valuable]
        ephemeral = nosync_cfg.get("ephemeral_patterns", [])
        if isinstance(ephemeral, list):
            config.nosync_ephemeral_patterns = [str(p) for p in ephemeral]

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
        """Serialize current settings to a YAML file, creating parent directories as needed."""
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
            "modules": {
                "disabled": self.modules_disabled,
            },
            "nosync": {
                "auto_repair": self.nosync_auto_repair,
                "valuable_patterns": self.nosync_valuable_patterns,
                "ephemeral_patterns": self.nosync_ephemeral_patterns,
            },
        }

        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
