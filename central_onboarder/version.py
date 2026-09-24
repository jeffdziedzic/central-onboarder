"""Single source of truth for this app's version string. Mirrors
pyproject.toml's `version` field by convention, not import - this
module may run frozen (PyInstaller), outside the source tree
pyproject.toml lives in. gui/app.py and gui/api.py both import VERSION
from here instead of each defining their own copy - same convention
carried over from the sibling aos10ct project's version.py.

Bump this (and pyproject.toml's `version`, by hand, to match) alongside
a new dated entry in central_onboarder/assets/CHANGELOG.md."""

VERSION = "0.4.0"
