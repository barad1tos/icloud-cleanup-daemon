"""Tests for nosync directory management."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.nosync import (
    DEFAULT_EXCLUDE_PATTERNS,
    EPHEMERAL_PATTERNS,
    VALUABLE_PATTERNS,
    NosyncManager,
    NosyncResult,
)


@pytest.fixture
def config(tmp_path: Path) -> CleanupConfig:
    """Create a test configuration."""
    cleanup_config = CleanupConfig()
    cleanup_config.watch_directories = [tmp_path]
    return cleanup_config


@pytest.fixture
def logger() -> logging.Logger:
    """Create a test logger."""
    return logging.getLogger("test-nosync")


@pytest.fixture
def manager(config: CleanupConfig, logger: logging.Logger) -> NosyncManager:
    """Create a nosync manager."""
    return NosyncManager(config, logger)


class TestDefaultExcludePatterns:
    """Tests for default exclusion patterns."""

    def test_contains_expected_patterns(self) -> None:
        """Test that common patterns are included."""
        expected = [
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "dist",
            "build",
        ]
        for pattern in expected:
            assert pattern in DEFAULT_EXCLUDE_PATTERNS

    def test_contains_wildcard_patterns(self) -> None:
        """Test that wildcard patterns are included."""
        assert "*.egg-info" in DEFAULT_EXCLUDE_PATTERNS


class TestNosyncResult:
    """Tests for NosyncResult dataclass."""

    def test_success_result(self, tmp_path: Path) -> None:
        """Test a successful nosync result."""
        result = NosyncResult(
            path=tmp_path / "venv",
            success=True,
            action="converted",
            nosync_path=tmp_path / "venv.nosync",
        )
        assert result.success
        assert result.action == "converted"
        assert result.error is None

    def test_error_result(self, tmp_path: Path) -> None:
        """Test an error nosync result."""
        result = NosyncResult(
            path=tmp_path / "venv",
            success=False,
            action="error",
            error="Permission denied",
        )
        assert not result.success
        assert result.error == "Permission denied"


class TestIsNosyncCandidate:
    """Tests for is_nosync_candidate static method."""

    @staticmethod
    def _assert_is_candidate(tmp_path: Path, dirname: str) -> None:
        """Create a directory and assert it is a nosync candidate."""
        directory = tmp_path / dirname
        directory.mkdir(parents=True)
        assert NosyncManager.is_nosync_candidate(directory)

    def test_venv_is_candidate(self, tmp_path: Path) -> None:
        """Test that venv directories are candidates."""
        self._assert_is_candidate(tmp_path, ".venv")
        self._assert_is_candidate(tmp_path / "sub1", "venv")

    def test_node_modules_is_candidate(self, tmp_path: Path) -> None:
        """Test that node_modules is a candidate."""
        self._assert_is_candidate(tmp_path, "node_modules")

    def test_pycache_is_candidate(self, tmp_path: Path) -> None:
        """Test that __pycache__ is a candidate."""
        self._assert_is_candidate(tmp_path, "__pycache__")

    def test_egg_info_is_candidate(self, tmp_path: Path) -> None:
        """Test that *.egg-info directories are candidates."""
        self._assert_is_candidate(tmp_path, "mypackage.egg-info")

    def test_regular_directory_not_candidate(self, tmp_path: Path) -> None:
        """Test that regular directories are not candidates."""
        src = tmp_path / "src"
        src.mkdir()
        assert not NosyncManager.is_nosync_candidate(src)

    def test_file_not_candidate(self, tmp_path: Path) -> None:
        """Test that files are not candidates."""
        file_path = tmp_path / "node_modules"  # Same name but file
        file_path.touch()
        assert not NosyncManager.is_nosync_candidate(file_path)

    def test_already_nosync_not_candidate(self, tmp_path: Path) -> None:
        """Test that .nosync directories are not candidates."""
        nosync = tmp_path / "venv.nosync"
        nosync.mkdir()
        assert not NosyncManager.is_nosync_candidate(nosync)

    def test_pytest_cache_is_candidate(self, tmp_path: Path) -> None:
        """Test that .pytest_cache is a candidate."""
        self._assert_is_candidate(tmp_path, ".pytest_cache")

    def test_mypy_cache_is_candidate(self, tmp_path: Path) -> None:
        """Test that .mypy_cache is a candidate."""
        self._assert_is_candidate(tmp_path, ".mypy_cache")


class TestConvertToNosync:
    """Tests for convert_to_nosync method."""

    @staticmethod
    def _assert_convert_fails(manager: NosyncManager, path: Path, expected_error: str) -> None:
        """Assert that conversion fails with the expected error message."""
        result = manager.convert_to_nosync(path)
        assert not result.success
        assert result.action == "skipped"
        assert result.error is not None
        assert expected_error in result.error.lower()

    def test_convert_directory(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test converting a directory to the .nosync format."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "bin").mkdir()
        (venv / "lib").mkdir()

        result = manager.convert_to_nosync(venv)

        assert result.success
        assert result.action == "converted"
        assert result.nosync_path == tmp_path / ".venv.nosync"

        # The original path should now be a symlink
        assert venv.is_symlink()
        assert venv.resolve() == (tmp_path / ".venv.nosync").resolve()

        # .nosync directory should exist with contents
        assert (tmp_path / ".venv.nosync").exists()
        assert (tmp_path / ".venv.nosync" / "bin").exists()

    def test_convert_nonexistent_path(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test converting a nonexistent path fails."""
        missing = tmp_path / "missing"
        self._assert_convert_fails(manager, missing, "does not exist")

    def test_convert_file_fails(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that converting a file fails."""
        file_path = tmp_path / "file.txt"
        file_path.touch()
        self._assert_convert_fails(manager, file_path, "not a directory")

    def test_convert_symlink_fails(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that converting a symlink fails."""
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target)
        self._assert_convert_fails(manager, link, "symlink")

    def test_convert_when_nosync_exists(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test converting when .nosync already exists fails."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        venv_nosync = tmp_path / ".venv.nosync"
        venv_nosync.mkdir()
        self._assert_convert_fails(manager, venv, "already exists")

    def test_convert_preserves_contents(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that conversion preserves directory contents."""
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "file.txt").write_text("content")
        subdir = venv / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested")

        result = manager.convert_to_nosync(venv)

        assert result.success
        nosync_path = tmp_path / "venv.nosync"
        assert (nosync_path / "file.txt").read_text() == "content"
        assert (nosync_path / "subdir" / "nested.txt").read_text() == "nested"


class TestScanForCandidates:
    """Tests for the scan_for_candidates method."""

    def test_scan_finds_candidates(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test scanning finds nosync candidates."""
        # Create candidate directories
        (tmp_path / ".venv").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "__pycache__").mkdir()

        # Create non-candidate directories
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        candidates = manager.scan_for_candidates(tmp_path)

        assert len(candidates) == 3
        names = {c.name for c in candidates}
        assert ".venv" in names
        assert "node_modules" in names
        assert "__pycache__" in names

    def test_scan_recursive(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that scanning is recursive."""
        # Create nested structure
        project = tmp_path / "project"
        project.mkdir()
        (project / ".venv").mkdir()
        (project / "src").mkdir()
        (project / "src" / "__pycache__").mkdir()

        candidates = manager.scan_for_candidates(tmp_path)

        assert len(candidates) == 2
        paths = {str(c) for c in candidates}
        assert str(project / ".venv") in paths
        assert str(project / "src" / "__pycache__") in paths

    def test_scan_nonexistent_directory(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that scanning a nonexistent directory returns empty."""
        missing = tmp_path / "missing"

        candidates = manager.scan_for_candidates(missing)

        assert candidates == []

    def test_scan_sorted_results(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that results are sorted."""
        (tmp_path / "zzz_pycache").mkdir()  # Won't match but tests sorting
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".venv").mkdir()

        candidates = manager.scan_for_candidates(tmp_path)

        # Should be sorted by path
        assert candidates == sorted(candidates)

    def test_scan_skips_nested_inside_candidates(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that scan skips directories nested inside found candidates."""
        project = tmp_path / "project"
        project.mkdir()
        venv = project / ".venv"
        venv.mkdir()
        # Directories nested inside .venv should not be reported
        (venv / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
        (venv / "lib" / "python3.13" / "site-packages" / "__pycache__").mkdir()
        (venv / "lib" / "python3.13" / "site-packages" / "pkg" / "dist").mkdir(
            parents=True,
        )
        # A "typeshed" stubs directory named "venv" inside .venv
        (venv / "lib" / "typeshed" / "stdlib" / "venv").mkdir(parents=True)  # cspell:ignore typeshed

        candidates = manager.scan_for_candidates(tmp_path)

        assert candidates == [venv]

    def test_scan_skips_inside_existing_nosync(self, manager: NosyncManager, tmp_path: Path) -> None:
        """Test that scan skips content inside already-converted .nosync dirs."""
        project = tmp_path / "project"
        project.mkdir()
        # Simulate an already-converted directory
        nosync_dir = project / ".venv.nosync"
        nosync_dir.mkdir()
        (nosync_dir / "lib" / "__pycache__").mkdir(parents=True)
        (nosync_dir / "lib" / "dist").mkdir()

        candidates = manager.scan_for_candidates(tmp_path)

        assert candidates == []


class TestScanAll:
    """Tests for the scan_all method."""

    def test_scan_all_watch_directories(self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path) -> None:
        """Test scanning all watch directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / ".venv").mkdir()
        (dir2 / "node_modules").mkdir()

        config.watch_directories = [dir1, dir2]
        manager = NosyncManager(config, logger)

        candidates = manager.scan_all()

        assert len(candidates) == 2

    def test_scan_all_empty_directories(self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path) -> None:
        """Test scanning empty watch directories."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        config.watch_directories = [empty_dir]
        manager = NosyncManager(config, logger)

        candidates = manager.scan_all()

        assert candidates == []

    def test_scan_all_with_nonexistent_directories(
        self, config: CleanupConfig, logger: logging.Logger, tmp_path: Path
    ) -> None:
        """Test scan_all skips nonexistent directories without error."""
        existing_dir = tmp_path / "existing"
        nonexistent_dir = tmp_path / "missing"
        existing_dir.mkdir()
        # nonexistent_dir is deliberately not created

        (existing_dir / ".venv").mkdir()

        config.watch_directories = [existing_dir, nonexistent_dir]
        manager = NosyncManager(config, logger)

        # Should not raise, should only return candidates from existing dir
        candidates = manager.scan_all()

        assert len(candidates) == 1
        assert candidates[0].name == ".venv"


class TestWildcardPatterns:
    """Tests for wildcard pattern matching."""

    def test_egg_info_wildcard(self, tmp_path: Path) -> None:
        """Test *.egg-info pattern matching."""
        # Various egg-info directories
        dirs = [
            "mypackage.egg-info",
            "another_pkg.egg-info",
            "pkg-1.0.0.egg-info",
        ]
        for d in dirs:
            (tmp_path / d).mkdir()

        for d in dirs:
            assert NosyncManager.is_nosync_candidate(tmp_path / d)

    def test_non_matching_suffix(self, tmp_path: Path) -> None:
        """Test that similar but non-matching suffixes don't match."""
        # These should NOT match *.egg-info
        non_matches = ["mypackage.egg", "data.egg-info.bak"]
        for name in non_matches:
            path = tmp_path / name
            path.mkdir()
            assert not NosyncManager.is_nosync_candidate(path)


class TestPatternCategories:
    """Tests for valuable vs ephemeral pattern split."""

    def test_valuable_patterns_exist(self) -> None:
        expected = {".venv", "venv", "node_modules", ".env"}
        assert expected == VALUABLE_PATTERNS

    def test_ephemeral_patterns_exist(self) -> None:
        expected = {
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "__pycache__",
            ".tox",
            ".nox",
            "*.egg-info",
            ".eggs",
            ".build",
            "build",
            "dist",
            ".cache",
        }
        assert expected == EPHEMERAL_PATTERNS

    def test_no_overlap_between_categories(self) -> None:
        assert VALUABLE_PATTERNS.isdisjoint(EPHEMERAL_PATTERNS)

    def test_default_patterns_is_union(self) -> None:
        assert DEFAULT_EXCLUDE_PATTERNS == VALUABLE_PATTERNS | EPHEMERAL_PATTERNS

    def test_is_valuable_candidate(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        assert NosyncManager.is_valuable_candidate(venv)

    def test_is_ephemeral_candidate(self, tmp_path: Path) -> None:
        cache = tmp_path / ".mypy_cache"
        cache.mkdir()
        assert NosyncManager.is_ephemeral_candidate(cache)

    def test_valuable_not_ephemeral(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        assert not NosyncManager.is_ephemeral_candidate(venv)

    def test_ephemeral_not_valuable(self, tmp_path: Path) -> None:
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        assert not NosyncManager.is_valuable_candidate(cache)


class TestVerifyAndRepair:
    """Tests for symlink guardian (verify_and_repair)."""

    def test_healthy_symlink_no_action(self, manager: NosyncManager, tmp_path: Path) -> None:
        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()
        link = tmp_path / ".venv"
        link.symlink_to(nosync.name)
        results = manager.verify_and_repair(tmp_path)
        assert results == []

    def test_missing_symlink_recreated(self, manager: NosyncManager, tmp_path: Path) -> None:
        from icloud_cleanup.nosync import RepairResult

        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()
        results = manager.verify_and_repair(tmp_path)
        assert len(results) == 1
        assert isinstance(results[0], RepairResult)
        assert results[0].action == "repaired"
        link = tmp_path / ".venv"
        assert link.is_symlink()
        assert link.resolve() == nosync.resolve()

    def test_conflict_2_symlink_replaced(self, manager: NosyncManager, tmp_path: Path) -> None:
        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()
        broken = tmp_path / ".venv 2"
        broken.symlink_to(nosync.name)
        results = manager.verify_and_repair(tmp_path)
        assert len(results) == 1
        assert results[0].action == "repaired"
        assert not broken.exists()
        link = tmp_path / ".venv"
        assert link.is_symlink()

    def test_real_directory_at_original_name_warning(self, manager: NosyncManager, tmp_path: Path) -> None:
        nosync = tmp_path / ".venv.nosync"
        nosync.mkdir()
        real = tmp_path / ".venv"
        real.mkdir()
        results = manager.verify_and_repair(tmp_path)
        assert len(results) == 1
        assert results[0].action == "warning"
        assert real.is_dir()
        assert not real.is_symlink()

    def test_only_processes_valuable_nosync_dirs(self, manager: NosyncManager, tmp_path: Path) -> None:
        nosync = tmp_path / ".mypy_cache.nosync"
        nosync.mkdir()
        results = manager.verify_and_repair(tmp_path)
        assert results == []

    def test_repair_multiple_directories(self, manager: NosyncManager, tmp_path: Path) -> None:
        for name in [".venv", "node_modules"]:
            (tmp_path / f"{name}.nosync").mkdir()
        results = manager.verify_and_repair(tmp_path)
        assert len(results) == 2

    def test_nonexistent_directory(self, manager: NosyncManager, tmp_path: Path) -> None:
        results = manager.verify_and_repair(tmp_path / "missing")
        assert results == []
