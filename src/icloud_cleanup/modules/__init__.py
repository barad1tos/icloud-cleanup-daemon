"""Modular cleanup system with auto-discovery."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from .base import CleanupModule

if TYPE_CHECKING:
    from ..config import CleanupConfig

logger = logging.getLogger("icloud-cleanup")


def discover_modules(config: CleanupConfig) -> list[CleanupModule]:
    """Discover and instantiate all enabled cleanup modules.

    Scans the modules package for classes with MODULE_ENABLED = True,
    instantiates them with the config, and filters out disabled modules.

    Args:
        config: Cleanup configuration.

    Returns:
        List of instantiated cleanup modules.

    """
    modules: list[CleanupModule] = []
    package = importlib.import_module(__package__ or "icloud_cleanup.modules")

    for _finder, modname, _is_pkg in pkgutil.iter_modules(package.__path__):
        if modname == "base":
            continue
        try:
            mod = importlib.import_module(f"{__package__}.{modname}")
        except ImportError:
            logger.warning("Failed to import module: %s", modname)
            continue

        modules.extend(_find_module_classes(mod, config))
    return modules


def _find_module_classes(mod: object, config: CleanupConfig) -> list[CleanupModule]:
    """Find and instantiate CleanupModule classes in a Python module.

    Args:
        mod: Imported Python module to inspect.
        config: Cleanup configuration.

    Returns:
        List of instantiated modules from this Python module.

    """
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
