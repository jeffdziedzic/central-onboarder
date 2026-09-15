"""Packaged data files - the device-list Excel template, the GUI user
guide, and the changelog - resolved via importlib.resources so this
works identically in a dev checkout, a real pip install, and a frozen
build. core/sheet.py has its own private _template_path() for the
.xlsx template (predates this module, left as-is, same convention as
the sibling AOS8-to-AOS10 Conversion Tool project)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def gui_guide_path() -> Path:
    return resources.files(__package__) / "USER_GUIDE.md"


def gui_changelog_path() -> Path:
    return resources.files(__package__) / "CHANGELOG.md"
