"""Tests for EphemeralCachesModule.can_match string pre-filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.ephemeral_caches import EphemeralCachesModule


@pytest.fixture
def module(tmp_path: Path) -> EphemeralCachesModule:
    """Create a module with default config."""
    config = CleanupConfig()
    config.watch_directories = [tmp_path]
    return EphemeralCachesModule(config)


class TestCanMatch:
    """Tests for can_match string pre-filter."""

    def test_matches_builtin_patterns(self, module: EphemeralCachesModule) -> None:
        """Test that built-in ephemeral patterns pass."""
        assert module.can_match("__pycache__") is True
        assert module.can_match(".mypy_cache") is True
        assert module.can_match(".pytest_cache") is True
        assert module.can_match("build") is True
        assert module.can_match("dist") is True

    def test_rejects_non_ephemeral_names(self, module: EphemeralCachesModule) -> None:
        """Test that non-ephemeral names are rejected."""
        assert module.can_match("src") is False
        assert module.can_match("main.py") is False
        assert module.can_match(".venv") is False  # valuable, not ephemeral

    def test_rejects_nosync_suffix(self, module: EphemeralCachesModule) -> None:
        """Test that names with .nosync suffix are rejected."""
        assert module.can_match("__pycache__.nosync") is False

    def test_matches_wildcard_pattern(self, module: EphemeralCachesModule) -> None:
        """Test that wildcard patterns like *.egg-info match."""
        assert module.can_match("mypackage.egg-info") is True

    def test_matches_custom_extra_patterns(self, tmp_path: Path) -> None:
        """Test that user-configured extra patterns are matched."""
        config = CleanupConfig()
        config.watch_directories = [tmp_path]
        config.nosync_ephemeral_patterns = [".custom_cache"]
        module = EphemeralCachesModule(config)

        assert module.can_match(".custom_cache") is True
        assert module.can_match("other") is False
