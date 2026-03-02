"""Tests for CoverageArtifactsModule.can_match string pre-filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.coverage_artifacts import CoverageArtifactsModule


@pytest.fixture
def module(tmp_path: Path) -> CoverageArtifactsModule:
    """Create a module with default config."""
    config = CleanupConfig()
    config.watch_directories = [tmp_path]
    return CoverageArtifactsModule(config)


class TestCanMatch:
    """Tests for can_match regex pre-filter."""

    def test_matches_coverage_artifact_pattern(self, module: CoverageArtifactsModule) -> None:
        """Test that coverage artifact filenames pass the pre-filter."""
        assert module.can_match(".coverage.hostname.pid123.abc") is True
        assert module.can_match(".coverage.myhost.pid999.deadbeef") is True

    def test_rejects_non_coverage_names(self, module: CoverageArtifactsModule) -> None:
        """Test that non-matching filenames are rejected."""
        assert module.can_match("anything") is False
        assert module.can_match(".coverage") is False
        assert module.can_match("main.py") is False

    def test_supports_watch_is_false(self, module: CoverageArtifactsModule) -> None:
        """Verify supports_watch is False (can_match not called by watcher in practice)."""
        assert module.supports_watch is False
