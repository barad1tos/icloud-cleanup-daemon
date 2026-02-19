"""Tests for a module auto-discovery system."""

from __future__ import annotations

import pytest

from icloud_cleanup.config import CleanupConfig
from icloud_cleanup.modules import discover_modules
from icloud_cleanup.modules.base import CleanupModule

BUILTIN_MODULE_NAMES = {"icloud_conflicts", "coverage_artifacts", "ephemeral_caches"}


@pytest.fixture
def config() -> CleanupConfig:
    """Create the default test configuration."""
    return CleanupConfig()


class TestDiscoverModules:
    """Tests for discover_modules auto-discovery."""

    def test_discovers_all_builtin_modules(self, config: CleanupConfig) -> None:
        """All built-in modules are returned with the default config."""
        modules = discover_modules(config)

        assert len(modules) >= 2
        names = {m.name for m in modules}
        assert BUILTIN_MODULE_NAMES.issubset(names)

    def test_module_names_match_expected(self, config: CleanupConfig) -> None:
        """Returned module names contain both icloud_conflicts and coverage_artifacts."""
        modules = discover_modules(config)
        names = {m.name for m in modules}

        assert "icloud_conflicts" in names
        assert "coverage_artifacts" in names

    def test_disabled_module_excluded(self) -> None:
        """A module listed in modules_disabled is not returned."""
        config = CleanupConfig()
        config.modules_disabled = ["coverage_artifacts"]

        modules = discover_modules(config)
        names = {m.name for m in modules}

        assert "icloud_conflicts" in names
        assert "coverage_artifacts" not in names

    def test_disable_all_modules_returns_empty(self) -> None:
        """Disabling all known modules yields an empty list."""
        config = CleanupConfig()
        config.modules_disabled = list(BUILTIN_MODULE_NAMES)

        modules = discover_modules(config)

        assert modules == []

    def test_all_modules_have_required_attributes(self, config: CleanupConfig) -> None:
        """Every discovered module exposes name, supports_watch, and MODULE_ENABLED."""
        modules = discover_modules(config)

        for module in modules:
            assert hasattr(module, "name"), f"Module {module!r} missing 'name'"
            assert hasattr(module, "supports_watch"), f"Module {module.name} missing 'supports_watch'"
            assert hasattr(module, "MODULE_ENABLED"), f"Module {module.name} missing 'MODULE_ENABLED'"
            assert module.MODULE_ENABLED is True

    def test_all_modules_are_cleanup_module_instances(self, config: CleanupConfig) -> None:
        """Every discovered module satisfies the CleanupModule protocol."""
        modules = discover_modules(config)

        assert len(modules) > 0, "Expected at least one module"
        for module in modules:
            assert isinstance(module, CleanupModule), f"{module.name} does not satisfy CleanupModule protocol"
