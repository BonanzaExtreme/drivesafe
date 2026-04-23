"""Utilities for resolving paths in source and frozen executable modes."""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-built executable."""
    return getattr(sys, "frozen", False)


def bundle_root() -> str:
    """Directory that contains bundled resources."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def executable_dir() -> str:
    """Directory that contains the executable (or project root in source mode)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return bundle_root()


def resource_path(*parts: str) -> str:
    """Path to a bundled project resource directory or file."""
    return os.path.join(bundle_root(), *parts)


def runtime_path(*parts: str) -> str:
    """Path for runtime-generated files that should persist near the executable."""
    return os.path.join(executable_dir(), *parts)
