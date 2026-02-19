"""Tests for configuration loading and saving."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from icloud_cleanup.config import CleanupConfig, parse_bool


class TestParseBool:
    """Tests for boolean parsing helper."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("yes", True),
            ("Yes", True),
            ("on", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("no", False),
            ("off", False),
            ("0", False),
            ("random", False),  # Non-standard strings are False
            ("", False),
        ],
    )
    def test_parse_bool_values(self, value: bool | str, expected: bool) -> None:
        """Test parsing various boolean representations."""
        assert parse_bool(value, False) == expected

    def test_parse_bool_none_uses_default(self) -> None:
        """Test that None returns the default value."""
        assert parse_bool(None, True) is True
        assert parse_bool(None, False) is False

    def test_parse_bool_integer(self) -> None:
        """Test parsing integer values."""
        assert parse_bool(1, False) is True
        assert parse_bool(0, True) is False


class TestCleanupConfigDefaults:
    """Tests for default configuration values."""

    def test_default_values(self) -> None:
        """Test that defaults are sensible."""
        config = CleanupConfig()

        assert config.wait_before_delete == 180
        assert config.icloud_poll_interval == 10
        assert config.max_icloud_wait == 300
        assert config.enable_recovery is True
        assert config.recovery_retention_days == 7
        assert config.log_level == "INFO"
        assert config.scan_interval == 60

    def test_default_conflict_pattern(self) -> None:
        """Test the default conflict pattern matches expected files."""
        import re

        config = CleanupConfig()
        pattern = re.compile(config.conflict_pattern)

        # Should match
        assert pattern.match("document 2.txt")
        assert pattern.match("file 3.pdf")
        assert pattern.match("photo 10.jpg")
        assert pattern.match(".hidden 2")

        # Should NOT match
        assert pattern.match("document 1.txt") is None
        assert pattern.match("file.txt") is None
        assert pattern.match("2 file.txt") is None

    def test_default_recovery_dir(self) -> None:
        """Test default recovery directory location."""
        config = CleanupConfig()
        assert config.recovery_dir == Path.home() / ".icloud-cleanup-trash"

    def test_default_log_file(self) -> None:
        """Test default log file location."""
        config = CleanupConfig()
        expected = Path.home() / "Library/Logs/icloud-cleanup-daemon.log"
        assert config.log_file == expected


class TestConfigLoad:
    """Tests for loading configuration from file."""

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """Test loading returns defaults when file doesn't exist."""
        config_path = tmp_path / "nonexistent.yaml"
        config = CleanupConfig.load(config_path)

        assert config.wait_before_delete == 180
        assert config.enable_recovery is True

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading empty file returns defaults."""
        config_path = tmp_path / "empty.yaml"
        config_path.touch()

        config = CleanupConfig.load(config_path)

        assert config.wait_before_delete == 180

    def test_load_partial_config(self, tmp_path: Path) -> None:
        """Test loading partial config merges with defaults."""
        config = self._load_config_from_text(tmp_path, "partial.yaml", "wait_before_delete: 60\n")
        assert config.wait_before_delete == 60
        assert config.enable_recovery is True  # Default

    def test_load_full_config(self, tmp_path: Path) -> None:
        """Test loading full configuration."""
        config_path = tmp_path / "full.yaml"
        data = {
            "watch_directories": ["/tmp/watch1", "~/Documents"],
            "conflict_pattern": r"^(.+)\s+(\d+)\..*$",
            "wait_before_delete": 120,
            "icloud_poll_interval": 5,
            "max_icloud_wait": 600,
            "scan_interval": 30,
            "recovery": {
                "enabled": True,
                "directory": "~/.trash-recovery",
                "retention_days": 14,
            },
            "logging": {
                "file": "~/logs/cleanup.log",
                "level": "DEBUG",
            },
        }
        with config_path.open("w") as f:
            yaml.dump(data, f)

        config = CleanupConfig.load(config_path)

        assert len(config.watch_directories) == 2
        assert config.watch_directories[0] == Path("/tmp/watch1")
        assert config.wait_before_delete == 120
        assert config.icloud_poll_interval == 5
        assert config.max_icloud_wait == 600
        assert config.scan_interval == 30
        assert config.enable_recovery is True
        assert config.recovery_retention_days == 14
        assert config.log_level == "DEBUG"

    def test_load_expands_tilde(self, tmp_path: Path) -> None:
        """Test that ~ is expanded in paths."""
        config_path = tmp_path / "tilde.yaml"
        data = {
            "watch_directories": ["~/Documents"],
            "recovery": {"directory": "~/.recovery"},
            "logging": {"file": "~/logs/test.log"},
        }
        with config_path.open("w") as f:
            yaml.dump(data, f)

        config = CleanupConfig.load(config_path)

        assert str(config.watch_directories[0]).startswith(str(Path.home()))
        assert str(config.recovery_dir).startswith(str(Path.home()))
        assert str(config.log_file).startswith(str(Path.home()))

    def test_load_recovery_disabled(self, tmp_path: Path) -> None:
        """Test loading with recovery explicitly disabled."""
        config_path = tmp_path / "no_recovery.yaml"
        data = {"recovery": {"enabled": False}}
        with config_path.open("w") as f:
            yaml.dump(data, f)

        config = CleanupConfig.load(config_path)

        assert config.enable_recovery is False

    def test_load_recovery_string_bool(self, tmp_path: Path) -> None:
        """Test that string booleans are parsed correctly in YAML."""
        config = self._load_config_from_text(tmp_path, "string_bool.yaml", "recovery:\n  enabled: true\n")
        assert config.enable_recovery is True

    def test_load_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """Test that malformed YAML raises ValueError with context."""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("watch_directories: [\n  unclosed")

        with pytest.raises(ValueError, match="Invalid YAML"):
            CleanupConfig.load(config_path)

    def test_load_zero_scan_interval_raises(self, tmp_path: Path) -> None:
        """Test that a zero scan_interval raises ValueError."""
        config_path = tmp_path / "bad_interval.yaml"
        config_path.write_text("scan_interval: 0\n")

        with pytest.raises(ValueError, match="scan_interval must be positive"):
            CleanupConfig.load(config_path)

    def test_load_negative_poll_interval_raises(self, tmp_path: Path) -> None:
        """Test that a negative icloud_poll_interval raises ValueError."""
        config_path = tmp_path / "bad_poll.yaml"
        config_path.write_text("icloud_poll_interval: -1\n")

        with pytest.raises(ValueError, match="icloud_poll_interval must be positive"):
            CleanupConfig.load(config_path)

    @staticmethod
    def _load_config_from_text(tmp_path: Path, filename: str, content: str) -> CleanupConfig:
        """Create a config file with given content and load it."""
        config_path = tmp_path / filename
        config_path.write_text(content)
        return CleanupConfig.load(config_path)


class TestConfigSave:
    """Tests for saving configuration to file."""

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Test that save creates parent directories."""
        config_path = tmp_path / "subdir" / "config.yaml"
        config = CleanupConfig()

        config.save(config_path)

        assert config_path.exists()
        assert config_path.parent.exists()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Test that saved config can be loaded identically."""
        config_path = tmp_path / "roundtrip.yaml"

        original = CleanupConfig()
        original.wait_before_delete = 999
        original.enable_recovery = False
        original.recovery_retention_days = 30
        original.log_level = "DEBUG"
        original.watch_directories = [tmp_path / "dir1", tmp_path / "dir2"]

        original.save(config_path)
        loaded = CleanupConfig.load(config_path)

        assert loaded.wait_before_delete == 999
        assert loaded.enable_recovery is False
        assert loaded.recovery_retention_days == 30
        assert loaded.log_level == "DEBUG"
        assert len(loaded.watch_directories) == 2

    def test_save_format(self, tmp_path: Path) -> None:
        """Test that saved YAML has expected structure."""
        config_path = tmp_path / "format.yaml"
        config = CleanupConfig()
        config.save(config_path)

        with config_path.open() as f:
            data = yaml.safe_load(f)

        assert "watch_directories" in data
        assert "conflict_pattern" in data
        assert "wait_before_delete" in data
        assert "recovery" in data
        assert "logging" in data
        assert "enabled" in data["recovery"]
        assert "retention_days" in data["recovery"]


class TestConfigPath:
    """Tests for config path handling."""

    def test_get_config_path(self) -> None:
        """Test default config path location."""
        path = CleanupConfig.get_config_path()
        expected = Path.home() / "Library/Application Support/icloud-cleanup/config.yaml"
        assert path == expected

    def test_load_uses_default_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test that load() uses the default path when no path is specified."""
        # Create config at custom default path
        custom_default = tmp_path / "default_config.yaml"
        monkeypatch.setattr(CleanupConfig, "get_config_path", classmethod(lambda cls: custom_default))

        custom_default.write_text("wait_before_delete: 42\n")

        config = CleanupConfig.load()

        assert config.wait_before_delete == 42


class TestNosyncConfig:
    """Tests for nosync configuration section."""

    def test_default_nosync_auto_repair(self) -> None:
        config = CleanupConfig()
        assert config.nosync_auto_repair is True

    def test_default_nosync_patterns_empty(self) -> None:
        config = CleanupConfig()
        assert config.nosync_valuable_patterns == []
        assert config.nosync_ephemeral_patterns == []

    def test_load_nosync_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "nosync:\n"
            "  auto_repair: false\n"
            "  valuable_patterns:\n"
            "    - .venv\n"
            "  ephemeral_patterns:\n"
            "    - .mypy_cache\n"
        )
        config = CleanupConfig.load(config_file)
        assert config.nosync_auto_repair is False
        assert config.nosync_valuable_patterns == [".venv"]
        assert config.nosync_ephemeral_patterns == [".mypy_cache"]

    def test_nosync_config_missing_uses_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("scan_interval: 30\n")
        config = CleanupConfig.load(config_file)
        assert config.nosync_auto_repair is True
        assert config.nosync_valuable_patterns == []

    def test_nosync_config_saved(self, tmp_path: Path) -> None:
        config = CleanupConfig()
        config.nosync_auto_repair = False
        config.nosync_valuable_patterns = [".venv"]
        config_file = tmp_path / "config.yaml"
        config.save(config_file)

        loaded = CleanupConfig.load(config_file)
        assert loaded.nosync_auto_repair is False
        assert loaded.nosync_valuable_patterns == [".venv"]


class TestWatchDirectories:
    """Tests for watch directory handling."""

    def test_default_watch_directories_exist(self) -> None:
        """Test default watch directories detection."""
        # This test may pass or fail depending on system state
        # The important thing is it doesn't crash
        config = CleanupConfig()
        config.watch_directories = CleanupConfig._get_default_watch_directories()
        # Directories may or may not exist
        assert isinstance(config.watch_directories, list)

    def test_empty_watch_directories_if_no_icloud(self) -> None:
        """Test that method doesn't crash when iCloud directories don't exist."""
        # The method returns empty list if icloud_base doesn't exist
        # This depends on actual system state, just ensure no crash
        dirs = CleanupConfig._get_default_watch_directories()
        assert isinstance(dirs, list)
