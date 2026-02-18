"""Tests for cleanup module base protocol and DetectedFile dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from icloud_cleanup.modules.base import CleanupModule, DetectedFile


class TestDetectedFile:
    """Tests for the DetectedFile frozen dataclass."""

    def test_creation_with_all_fields(self, tmp_path: Path) -> None:
        """Test creating a DetectedFile with all required fields."""
        file_path = tmp_path / "document 2.txt"
        detected = DetectedFile(
            path=file_path,
            module_name="icloud_conflicts",
            reason="Conflict file with number 2",
            recovery_enabled=True,
        )

        assert detected.path == file_path
        assert detected.module_name == "icloud_conflicts"
        assert detected.reason == "Conflict file with number 2"
        assert detected.recovery_enabled is True

    def test_frozen_prevents_attribute_mutation(self, tmp_path: Path) -> None:
        """Test that frozen dataclass rejects attribute assignment."""
        detected = DetectedFile(
            path=tmp_path / "file.txt",
            module_name="test_module",
            reason="test reason",
            recovery_enabled=False,
        )

        with pytest.raises(FrozenInstanceError):
            detected.path = tmp_path / "other.txt"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            detected.module_name = "changed"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            detected.reason = "changed"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            detected.recovery_enabled = True  # type: ignore[misc]

    def test_equality_same_values(self, tmp_path: Path) -> None:
        """Test that two DetectedFile instances with identical values are equal."""
        file_path = tmp_path / "document 2.txt"
        first = DetectedFile(
            path=file_path,
            module_name="mod",
            reason="reason",
            recovery_enabled=True,
        )
        second = DetectedFile(
            path=file_path,
            module_name="mod",
            reason="reason",
            recovery_enabled=True,
        )

        assert first == second

    def test_inequality_different_values(self, tmp_path: Path) -> None:
        """Test that DetectedFile instances with different values are not equal."""
        first = DetectedFile(
            path=tmp_path / "a.txt",
            module_name="mod",
            reason="reason",
            recovery_enabled=True,
        )
        second = DetectedFile(
            path=tmp_path / "b.txt",
            module_name="mod",
            reason="reason",
            recovery_enabled=True,
        )

        assert first != second

    @pytest.mark.parametrize(
        "field,value_a,value_b",
        [
            ("module_name", "module_a", "module_b"),
            ("reason", "reason one", "reason two"),
            ("recovery_enabled", True, False),
        ],
    )
    def test_inequality_per_field(self, tmp_path: Path, field: str, value_a: object, value_b: object) -> None:
        """Test that differing any single field produces inequality."""
        file_path = tmp_path / "file.txt"
        base_kwargs = {
            "path": file_path,
            "module_name": "mod",
            "reason": "reason",
            "recovery_enabled": True,
        }

        kwargs_a = {**base_kwargs, field: value_a}
        kwargs_b = {**base_kwargs, field: value_b}

        assert DetectedFile(**kwargs_a) != DetectedFile(**kwargs_b)

    def test_hash_consistency(self, tmp_path: Path) -> None:
        """Test that equal DetectedFile instances produce the same hash."""
        file_path = tmp_path / "doc.txt"
        first = DetectedFile(path=file_path, module_name="m", reason="r", recovery_enabled=False)
        second = DetectedFile(path=file_path, module_name="m", reason="r", recovery_enabled=False)

        assert hash(first) == hash(second)

    def test_usable_in_set(self, tmp_path: Path) -> None:
        """Test that frozen DetectedFile instances can be stored in a set."""
        file_path = tmp_path / "doc.txt"
        detected = DetectedFile(path=file_path, module_name="m", reason="r", recovery_enabled=True)
        duplicate = DetectedFile(path=file_path, module_name="m", reason="r", recovery_enabled=True)

        result = {detected, duplicate}

        assert len(result) == 1

    def test_repr_contains_field_values(self, tmp_path: Path) -> None:
        """Test that repr includes field values for debugging."""
        file_path = tmp_path / "file.txt"
        detected = DetectedFile(
            path=file_path,
            module_name="my_module",
            reason="some reason",
            recovery_enabled=True,
        )
        representation = repr(detected)

        assert "my_module" in representation
        assert "some reason" in representation
        assert "file.txt" in representation

    def test_recovery_enabled_false(self, tmp_path: Path) -> None:
        """Test creation with recovery disabled."""
        detected = DetectedFile(
            path=tmp_path / "file.txt",
            module_name="mod",
            reason="reason",
            recovery_enabled=False,
        )

        assert detected.recovery_enabled is False


class TestCleanupModuleProtocol:
    """Tests for the CleanupModule runtime-checkable protocol."""

    def test_conforming_class_passes_isinstance(self) -> None:
        """Test that a fully conforming class satisfies the protocol."""

        class ConformingModule:
            MODULE_ENABLED: bool = True
            name: str = "conforming"
            supports_watch: bool = True

            @staticmethod
            def is_target(_path: Path) -> DetectedFile | None:
                return None

            @staticmethod
            def scan_directory(_directory: Path) -> list[DetectedFile]:
                return []

            @staticmethod
            def scan_all() -> list[DetectedFile]:
                return []

        instance = ConformingModule()
        assert isinstance(instance, CleanupModule)

    def test_missing_method_fails_isinstance(self) -> None:
        """Test that a class missing a required method does not satisfy the protocol."""

        class MissingScanAll:
            MODULE_ENABLED: bool = True
            name: str = "incomplete"
            supports_watch: bool = False

            @staticmethod
            def is_target(_path: Path) -> DetectedFile | None:
                return None

            @staticmethod
            def scan_directory(_directory: Path) -> list[DetectedFile]:
                return []

            # scan_all intentionally omitted

        instance = MissingScanAll()
        assert not isinstance(instance, CleanupModule)

    def test_missing_attribute_fails_isinstance(self) -> None:
        """Test that a class missing a required attribute does not satisfy the protocol."""

        class MissingAttribute:
            # MODULE_ENABLED intentionally omitted
            name: str = "missing_attr"
            supports_watch: bool = True

            @staticmethod
            def is_target(_path: Path) -> DetectedFile | None:
                return None

            @staticmethod
            def scan_directory(_directory: Path) -> list[DetectedFile]:
                return []

            @staticmethod
            def scan_all() -> list[DetectedFile]:
                return []

        instance = MissingAttribute()
        assert not isinstance(instance, CleanupModule)

    def test_empty_class_fails_isinstance(self) -> None:
        """Test that an empty class does not satisfy the protocol."""

        class EmptyClass:
            pass

        instance = EmptyClass()
        assert not isinstance(instance, CleanupModule)

    def test_unrelated_object_fails_isinstance(self) -> None:
        """Test that unrelated built-in types do not satisfy the protocol."""
        assert not isinstance("a string", CleanupModule)
        assert not isinstance(42, CleanupModule)
        assert not isinstance([], CleanupModule)


class TestMinimalMockModule:
    """Tests using a minimal mock implementation to verify protocol conformance."""

    @staticmethod
    def _make_module() -> _MockCleanupModule:
        """Create a minimal mock module that satisfies CleanupModule."""
        return _MockCleanupModule()

    def test_mock_satisfies_protocol(self) -> None:
        """Test that the mock module passes isinstance check."""
        module = self._make_module()
        assert isinstance(module, CleanupModule)

    def test_is_target_returns_detected_file(self, tmp_path: Path) -> None:
        """Test that is_target returns a DetectedFile for matching paths."""
        module = self._make_module()
        target_file = tmp_path / "target.tmp"
        target_file.touch()

        result = module.is_target(target_file)

        assert result is not None
        assert isinstance(result, DetectedFile)
        assert result.path == target_file
        assert result.module_name == "mock_module"

    def test_is_target_returns_none_for_non_match(self, tmp_path: Path) -> None:
        """Test that is_target returns None for non-matching paths."""
        module = self._make_module()
        non_target = tmp_path / "document.txt"

        result = module.is_target(non_target)

        assert result is None

    def test_scan_directory(self, tmp_path: Path) -> None:
        """Test scanning a directory with mixed files."""
        module = self._make_module()

        (tmp_path / "a.tmp").touch()
        (tmp_path / "b.tmp").touch()
        (tmp_path / "keep.txt").touch()

        results = module.scan_directory(tmp_path)

        assert len(results) == 2
        result_names = {r.path.name for r in results}
        assert result_names == {"a.tmp", "b.tmp"}

    def test_scan_all_uses_configured_directories(self, tmp_path: Path) -> None:
        """Test that scan_all scans the configured watch directories."""
        module = _MockCleanupModule(watch_directories=[tmp_path])
        (tmp_path / "file.tmp").touch()
        (tmp_path / "other.txt").touch()

        results = module.scan_all()

        assert len(results) == 1
        assert results[0].path.name == "file.tmp"

    def test_module_attributes(self) -> None:
        """Test that module attributes are accessible and correct."""
        module = self._make_module()

        assert module.MODULE_ENABLED is True
        assert module.name == "mock_module"
        assert module.supports_watch is True


class _MockCleanupModule:
    """Minimal CleanupModule implementation for testing protocol conformance.

    Detects files with `.tmp` suffix as cleanup targets.
    """

    MODULE_ENABLED: bool = True
    name: str = "mock_module"
    supports_watch: bool = True

    def __init__(self, watch_directories: list[Path] | None = None) -> None:
        self._watch_directories = watch_directories or []

    def is_target(self, path: Path) -> DetectedFile | None:
        if path.suffix == ".tmp":
            return DetectedFile(
                path=path,
                module_name=self.name,
                reason="Temporary file detected",
                recovery_enabled=True,
            )
        return None

    def scan_directory(self, directory: Path) -> list[DetectedFile]:
        results: list[DetectedFile] = []
        for child in directory.iterdir():
            if child.is_file():
                detected = self.is_target(child)
                if detected is not None:
                    results.append(detected)
        return results

    def scan_all(self) -> list[DetectedFile]:
        all_detected: list[DetectedFile] = []
        for directory in self._watch_directories:
            all_detected.extend(self.scan_directory(directory))
        return all_detected
