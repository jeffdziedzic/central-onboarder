"""Local 'current working device list' pointer - a convenience, not a
secret, so it lives in its own small file (workspace.json, gitignored
the same way credentials.json is) rather than inside credential_store.py's
secrets-only scope. Ported as-is from the sibling AOS8-to-AOS10
Conversion Tool project's own workspace.py.

Set via the GUI's Device List screen, read by every action that would
otherwise need a sheet path passed in explicitly - the operator picks
the workbook once per session, not once per action."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_path() -> Path:
    """Same frozen-vs-dev-checkout reasoning as credential_store.py's
    default_path() - see that function's docstring."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "workspace.json"
    return _PROJECT_ROOT / "workspace.json"


def get_sheet(path: Path | None = None) -> Path | None:
    p = path or default_path()
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    sheet = data.get("sheet")
    return Path(sheet) if sheet else None


def set_sheet(sheet_path: Path, path: Path | None = None) -> None:
    p = path or default_path()
    p.write_text(json.dumps({"sheet": str(sheet_path)}, indent=2), encoding="utf-8")


def clear_sheet(path: Path | None = None) -> None:
    """Unsets the working sheet pointer. Only removes the pointer, never
    the actual .xlsx file on disk. A no-op if workspace.json doesn't
    exist yet."""
    p = path or default_path()
    if p.exists():
        p.write_text(json.dumps({"sheet": None}, indent=2), encoding="utf-8")
