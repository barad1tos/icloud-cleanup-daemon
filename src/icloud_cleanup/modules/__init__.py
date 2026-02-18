"""Modular cleanup system with auto-discovery."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import types
from typing import TYPE_CHECKING

from .base import CleanupModule

if TYPE_CHECKING:
    from ..config import CleanupConfig

logger = logging.getLogger("icloud-cleanup")


def discover_modules(config: CleanupConfig) -> list[CleanupModule]:
    """Discover and instantiate all enabled cleanup modules.

    Scans the modules package for classes with MODULE_ENABLED = True,
    instantiates them with the config, and filters out disabled modules.
    """
    modules: list[CleanupModule] = []
    package = importlib.import_module(__package__ or "icloud_cleanup.modules")

    for _finder, module_name, _is_pkg in pkgutil.iter_modules(package.__path__):
        if module_name == "base":
            continue
        try:
            mod = importlib.import_module(f"{__package__}.{module_name}")
        except ImportError:
            logger.warning("Failed to import module: %s", module_name)
            continue

        modules.extend(_find_module_classes(mod, config))
    return modules


def _find_module_classes(mod: types.ModuleType, config: CleanupConfig) -> list[CleanupModule]:
    """Instantiate all CleanupModule classes found in the given Python module."""
    found: list[CleanupModule] = []

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if not (
            isinstance(attr, type) and getattr(attr, "MODULE_ENABLED", False) is True and attr_name != "CleanupModule"
        ):
            continue

        try:
            instance = attr(config)
        except (TypeError, ValueError):
            logger.warning("Failed to instantiate module: %s", attr_name, exc_info=True)
            continue

        if instance.name in config.modules_disabled:
            logger.info("Module disabled by config: %s", instance.name)
            continue

        found.append(instance)
        logger.debug("Loaded module: %s", instance.name)

    return found
