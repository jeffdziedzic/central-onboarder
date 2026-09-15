from pathlib import Path

from central_onboarder.core import workspace


def test_get_sheet_missing_file_returns_none(tmp_path: Path):
    assert workspace.get_sheet(tmp_path / "workspace.json") is None


def test_set_and_get_sheet(tmp_path: Path):
    path = tmp_path / "workspace.json"
    sheet = tmp_path / "device-list.xlsx"
    workspace.set_sheet(sheet, path=path)
    assert workspace.get_sheet(path=path) == sheet


def test_clear_sheet(tmp_path: Path):
    path = tmp_path / "workspace.json"
    sheet = tmp_path / "device-list.xlsx"
    workspace.set_sheet(sheet, path=path)
    workspace.clear_sheet(path=path)
    assert workspace.get_sheet(path=path) is None


def test_clear_sheet_noop_when_file_missing(tmp_path: Path):
    path = tmp_path / "workspace.json"
    workspace.clear_sheet(path=path)
    assert not path.exists()
