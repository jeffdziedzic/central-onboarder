"""Entry point for the Central Onboarder GUI. Opens one pywebview
window over static/index.html, with Api (see api.py) exposed as the
JS-callable bridge. Version string lives in central_onboarder/version.py
(single source of truth), not defined here.

Ported from the sibling AOS8-to-AOS10 Conversion Tool project's own
gui/app.py - see that module's docstring for the frozen-path caveats
(genuinely untested for either macOS/py2app or Windows/PyInstaller as
of this tool's first scaffold; packaging is deferred, see the repo's
README/CHANGELOG)."""

from __future__ import annotations

import sys
from pathlib import Path

import webview

from central_onboarder.core.action_log import ActionLog
from central_onboarder.version import VERSION

from .api import Api


def _static_dir() -> Path:
    """Unfrozen (plain `python -m central_onboarder.gui.app`): static/
    sits right next to this file. Frozen (PyInstaller, once a real spec
    exists): sys._MEIPASS is the extraction/resource root a .spec's
    `datas` entries get unpacked under - untested here, ported from the
    sibling project's own same-shaped function."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path(sys.executable).parent.parent / "Resources" / "central_onboarder" / "gui" / "static"
        meipass = getattr(sys, "_MEIPASS", None)
        base = Path(meipass) if meipass else Path(sys.executable).parent
        return base / "central_onboarder" / "gui" / "static"
    return Path(__file__).resolve().parent / "static"


_STATIC_DIR = _static_dir()


def main() -> None:
    webview.create_window(
        f"Central Onboarder v{VERSION}",
        url=str(_STATIC_DIR / "index.html"),
        js_api=Api(action_log=ActionLog()),
        width=1100,
        height=720,
        min_size=(800, 560),
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
