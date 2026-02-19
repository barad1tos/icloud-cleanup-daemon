"""Tests for ephemeral cache directory cleanup module."""

from __future__ import annotations

from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules.base import DetectedFile
from icloud_cleanup.modules.ephemeral_caches import EphemeralCachesModule


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration with tmp_path as a watch directory."""
    cleanup_config = CleanupConfig()
    cleanup_config.watch_directories = [tmp_path]
    return cleanup_config


@pytest.fixture
def module(config: CleanupConfig) -> EphemeralCachesModule:
    """Create ephemeral caches module instance."""
    return EphemeralCachesModule(config)


def _make_cache_dir(parent: Path, name: str) -> Path:
    """Create a cache directory and return its path."""
    cache = parent / name
    cache.mkdir(parents=True, exist_ok=True)
    return cache


class TestModuleAttributes:
    """Tests for class-level module attributes."""

    def test_module_enabled(self) -> None:
        """MODULE_ENABLED is True."""
        assert EphemeralCachesModule.MODULE_ENABLED is True

    def test_module_name(self, module: EphemeralCachesModule) -> None:
        """The module name is 'ephemeral_caches'."""
        assert module.name == "ephemeral_caches"

    def test_supports_watch(self, module: EphemeralCachesModule) -> None:
        """supports_watch is True for real-time FSEvents monitoring."""
        assert module.supports_watch is True


class TestIsTarget:
    """Tests for is_target detection of ephemeral cache directories."""

    def test_detects_mypy_cache(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects .mypy_cache as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, ".mypy_cache")

        result = module.is_target(cache)

        assert result is not None
        assert isinstance(result, DetectedFile)
        assert result.path == cache
        assert result.module_name == "ephemeral_caches"
        assert result.recovery_enabled is False

    def test_detects_pycache(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects __pycache__ as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, "__pycache__")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_detects_ruff_cache(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects .ruff_cache as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, ".ruff_cache")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_detects_pytest_cache(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects .pytest_cache as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, ".pytest_cache")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_detects_egg_info(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects *.egg-info wildcard pattern (e.g. mypackage.egg-info)."""
        cache = _make_cache_dir(tmp_path, "mypackage.egg-info")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_detects_build_dir(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects build/ as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, "build")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_detects_dist_dir(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Detects dist/ as an ephemeral cache directory."""
        cache = _make_cache_dir(tmp_path, "dist")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_ignores_venv(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Ignores .venv — valuable, not ephemeral (slow to rebuild)."""
        venv = _make_cache_dir(tmp_path, ".venv")

        result = module.is_target(venv)

        assert result is None

    def test_ignores_node_modules(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Ignores node_modules — valuable, not ephemeral (slow to rebuild)."""
        node_modules = _make_cache_dir(tmp_path, "node_modules")

        result = module.is_target(node_modules)

        assert result is None

    def test_ignores_files(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Ignores regular files, even if their name matches a pattern."""
        cache_file = tmp_path / "__pycache__"
        cache_file.touch()

        result = module.is_target(cache_file)

        assert result is None

    def test_ignores_regular_directory(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Ignores directories that do not match any ephemeral pattern."""
        src = _make_cache_dir(tmp_path, "src")

        result = module.is_target(src)

        assert result is None

    def test_ignores_nosync_directory(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Ignores directories already converted to .nosync suffix."""
        nosync = _make_cache_dir(tmp_path, ".mypy_cache.nosync")

        result = module.is_target(nosync)

        assert result is None


class TestScanDirectory:
    """Tests for directory scanning."""

    def test_finds_caches_in_directory(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Finds ephemeral cache directories at the top level."""
        _make_cache_dir(tmp_path, ".mypy_cache")
        _make_cache_dir(tmp_path, "__pycache__")
        _make_cache_dir(tmp_path, ".pytest_cache")
        # Non-cache directory should not be detected
        _make_cache_dir(tmp_path, "src")

        detected = module.scan_directory(tmp_path)

        found_names = {d.path.name for d in detected}
        assert found_names == {".mypy_cache", "__pycache__", ".pytest_cache"}

    def test_finds_nested_caches(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Finds ephemeral caches nested inside project subdirectories."""
        project_src = tmp_path / "project" / "src"
        project_src.mkdir(parents=True)
        _make_cache_dir(project_src, "__pycache__")

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 1
        assert detected[0].path == project_src / "__pycache__"

    def test_skips_caches_inside_nosync(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Skips caches found inside .nosync directories (already excluded from iCloud)."""
        venv_nosync = _make_cache_dir(tmp_path, ".venv.nosync")
        _make_cache_dir(venv_nosync / "lib", "__pycache__")

        detected = module.scan_directory(tmp_path)

        assert detected == []

    def test_skips_subtrees_of_found_caches(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Only reports the top-level cache, not nested caches within it.

        Example: build/lib/__pycache__ should not be reported separately
        when build/ is already detected.
        """
        build = _make_cache_dir(tmp_path, "build")
        _make_cache_dir(build / "lib", "__pycache__")

        detected = module.scan_directory(tmp_path)

        assert len(detected) == 1
        assert detected[0].path == build

    def test_nonexistent_directory(self, module: EphemeralCachesModule, tmp_path: Path) -> None:
        """Scanning a nonexistent directory returns an empty list."""
        nonexistent = tmp_path / "does_not_exist"

        detected = module.scan_directory(nonexistent)

        assert detected == []


class TestScanAll:
    """Tests for scanning all configured watch directories."""

    def test_scans_all_watch_dirs(self, tmp_path: Path) -> None:
        """Caches across multiple watch directories are all found."""
        dir_a = tmp_path / "project_a"
        dir_b = tmp_path / "project_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _make_cache_dir(dir_a, ".mypy_cache")
        _make_cache_dir(dir_b, "__pycache__")
        _make_cache_dir(dir_b, ".pytest_cache")

        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = [dir_a, dir_b]
        module = EphemeralCachesModule(cleanup_config)

        detected = module.scan_all()

        assert len(detected) == 3
        found_names = {d.path.name for d in detected}
        assert found_names == {".mypy_cache", "__pycache__", ".pytest_cache"}


class TestConfigOverrides:
    """Tests for user-defined ephemeral pattern overrides."""

    def test_custom_ephemeral_patterns(self, tmp_path: Path) -> None:
        """Custom patterns from config detect non-default cache directories."""
        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = [tmp_path]
        cleanup_config.nosync_ephemeral_patterns = [".custom_cache"]
        module = EphemeralCachesModule(cleanup_config)

        cache = _make_cache_dir(tmp_path, ".custom_cache")

        result = module.is_target(cache)

        assert result is not None
        assert result.path == cache

    def test_custom_patterns_extend_defaults(self, tmp_path: Path) -> None:
        """Custom patterns extend (not replace) the default ephemeral set."""
        cleanup_config = CleanupConfig()
        cleanup_config.watch_directories = [tmp_path]
        cleanup_config.nosync_ephemeral_patterns = [".custom_cache"]
        module = EphemeralCachesModule(cleanup_config)

        custom = _make_cache_dir(tmp_path, ".custom_cache")
        pycache = _make_cache_dir(tmp_path, "__pycache__")

        result_custom = module.is_target(custom)
        result_pycache = module.is_target(pycache)

        assert result_custom is not None
        assert result_pycache is not None
