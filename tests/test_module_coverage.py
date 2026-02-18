"""Tests for coverage artifact cleanup module."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.base import DetectedFile
from icloud_cleanup.modules.coverage_artifacts import CoverageArtifactsModule


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration with tmp_path as a watch directory."""
    cleanup_config = CleanupConfig()
    cleanup_config.watch_directories = [tmp_path]
    return cleanup_config


@pytest.fixture
def module(config: CleanupConfig) -> CoverageArtifactsModule:
    """Create coverage artifacts module instance."""
    return CoverageArtifactsModule(config)


def _create_artifact(directory: Path, name: str, *, with_merged: bool = True) -> Path:
    """Create a coverage artifact file and optionally the merged .coverage.

    Args:
        directory: Directory to create files in.
        name: Artifact filename.
        with_merged: Whether to also create the merged .coverage file.

    Returns:
        Path to the created artifact file.
    """
    artifact = directory / name
    artifact.touch()
    if with_merged:
        merged = directory / ".coverage"
        if not merged.exists():
            merged.touch()
    return artifact


class TestPatternMatching:
    """Tests for coverage artifact filename pattern matching."""

    @pytest.mark.parametrize(
        "name",
        [
            ".coverage.MacBookPro.pid1234.abc123",
            ".coverage.host.pid99.xyz",
            ".coverage.my-host.pid1.a",
            ".coverage.server01.pid55555.deadbeef",
            ".coverage.localhost.pid1.abcdef0123456789",
        ],
    )
    def test_valid_artifact_names_detected(self, module: CoverageArtifactsModule, tmp_path: Path, name: str) -> None:
        """Valid .coverage.<host>.pid<N>.<hash> names are detected."""
        _create_artifact(tmp_path, name)

        result = module.is_target(tmp_path / name)

        assert result is not None
        assert isinstance(result, DetectedFile)
        assert result.path == tmp_path / name
        assert result.module_name == "coverage_artifacts"
        assert result.recovery_enabled is False

    @pytest.mark.parametrize(
        "name",
        [
            ".coverage",
            ".coverage.host",
            ".coverage.host.pid.abc",
            "regular.txt",
            ".coveragerc",
            ".coverage.",
            ".coverage.host.pid99",
            "coverage.host.pid1.abc",
        ],
    )
    def test_invalid_names_rejected(self, module: CoverageArtifactsModule, tmp_path: Path, name: str) -> None:
        """Non-matching filenames return None."""
        _create_artifact(tmp_path, name)

        result = module.is_target(tmp_path / name)

        assert result is None


class TestMergedCoverageRequired:
    """Tests for the merged .coverage prerequisite."""

    def test_artifact_without_merged_returns_none(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Artifact file exists but no merged .coverage in the same directory."""
        _create_artifact(tmp_path, ".coverage.host.pid42.abc", with_merged=False)

        result = module.is_target(tmp_path / ".coverage.host.pid42.abc")

        assert result is None

    def test_artifact_with_merged_returns_detected(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Artifact plus merged .coverage returns a DetectedFile."""
        _create_artifact(tmp_path, ".coverage.host.pid42.abc", with_merged=True)

        result = module.is_target(tmp_path / ".coverage.host.pid42.abc")

        assert result is not None
        assert result.reason == "Stale coverage artifact (merged .coverage exists)"


class TestNonFileTarget:
    """Tests for non-file targets."""

    def test_directory_matching_pattern_returns_none(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """A directory whose name matches the pattern is not a target."""
        (tmp_path / ".coverage").touch()
        directory = tmp_path / ".coverage.host.pid1.abc"
        directory.mkdir()

        result = module.is_target(directory)

        assert result is None

    def test_nonexistent_path_returns_none(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """A path that does not exist returns None."""
        result = module.is_target(tmp_path / ".coverage.host.pid1.abc")

        assert result is None


class TestScanDirectory:
    """Tests for directory scanning."""

    def test_finds_all_artifacts(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Multiple artifacts with a merged .coverage are all found."""
        (tmp_path / ".coverage").touch()
        _create_artifact(tmp_path, ".coverage.host.pid1.aaa")
        _create_artifact(tmp_path, ".coverage.host.pid2.bbb")
        _create_artifact(tmp_path, ".coverage.host.pid3.ccc")

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 3
        found_names = {d.path.name for d in detected}
        assert found_names == {
            ".coverage.host.pid1.aaa",
            ".coverage.host.pid2.bbb",
            ".coverage.host.pid3.ccc",
        }

    def test_recursive_finds_nested_artifacts(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Rglob scan finds artifacts in subdirectories."""
        subdir = tmp_path / "project" / "tests"
        subdir.mkdir(parents=True)
        (subdir / ".coverage").touch()
        _create_artifact(subdir, ".coverage.host.pid1.abc")

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 1
        assert detected[0].path == subdir / ".coverage.host.pid1.abc"

    def test_nonexistent_directory_returns_empty(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Scanning a directory that does not exist returns an empty list."""
        nonexistent = tmp_path / "does_not_exist"

        detected = module.scan_directory(nonexistent)

        assert detected == []

    def test_ignores_non_matching_hidden_files(self, module: CoverageArtifactsModule, tmp_path: Path) -> None:
        """Hidden files that don't match the pattern are not detected."""
        (tmp_path / ".coverage").touch()
        (tmp_path / ".coveragerc").touch()
        (tmp_path / ".gitignore").touch()
        _create_artifact(tmp_path, ".coverage.host.pid1.abc")

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 1


class TestScanAll:
    """Tests for scanning all configured watch directories."""

    def test_scans_all_watch_directories(self, tmp_path: Path) -> None:
        """Artifacts across multiple watch directories are all found."""
        dir_a = tmp_path / "project_a"
        dir_b = tmp_path / "project_b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / ".coverage").touch()
        _create_artifact(dir_a, ".coverage.host.pid1.aaa")

        (dir_b / ".coverage").touch()
        _create_artifact(dir_b, ".coverage.host.pid2.bbb")
        _create_artifact(dir_b, ".coverage.host.pid3.ccc")

        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = [dir_a, dir_b]
        module = CoverageArtifactsModule(cleanup_config)

        detected = module.scan_all()

        assert len(detected) == 3

    def test_empty_watch_directories(self) -> None:
        """No watch directories configured returns an empty list."""
        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = []
        module = CoverageArtifactsModule(cleanup_config)

        detected = module.scan_all()

        assert detected == []


class TestModuleAttributes:
    """Tests for class-level module attributes."""

    def test_module_enabled(self) -> None:
        """MODULE_ENABLED is True by default."""
        assert CoverageArtifactsModule.MODULE_ENABLED is True

    def test_module_name(self, module: CoverageArtifactsModule) -> None:
        """The module name is 'coverage_artifacts'."""
        assert module.name == "coverage_artifacts"

    def test_supports_watch_disabled(self, module: CoverageArtifactsModule) -> None:
        """supports_watch is False (no real-time FSEvents monitoring)."""
        assert module.supports_watch is False

    def test_stores_config(self, module: CoverageArtifactsModule, config: CleanupConfig) -> None:
        """Module stores the provided config."""
        assert module.config is config
