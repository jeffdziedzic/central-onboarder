from pathlib import Path
from unittest.mock import patch

from central_onboarder.core import credential_store as cs
from central_onboarder.core import workspace
from central_onboarder.gui.api import Api


def test_bare_construction_does_not_touch_disk(tmp_path: Path):
    """Api(action_log=None) - the default - never writes an action log
    file, same guarantee core/action_log.py's own docstring documents."""
    api = Api()
    assert api._action_log is None


def test_get_version_returns_current_version():
    from central_onboarder.version import VERSION
    api = Api()
    assert api.get_version() == {"version": VERSION}


def test_save_and_get_central_credentials(tmp_path: Path):
    path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        result = api.save_central("acct", "us1.api.central.arubanetworks.com", "cid", "csecret")
        assert result["ok"] is True
        data = api.get_credentials()
    assert data["central"]["acct"]["base_url"] == "https://us1.api.central.arubanetworks.com"


def test_save_central_rejects_missing_fields(tmp_path: Path):
    path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        result = api.save_central("acct", "", "cid", "csecret")
    assert result["ok"] is False


def test_wipe_credentials_removes_one_category(tmp_path: Path):
    path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        api.save_central("acct", "https://x", "cid", "csecret")
        api.save_ap_ssh("acct", "admin", "hunter2")
        api.wipe_credentials("central")
        data = api.get_credentials()
    assert "central" not in data
    assert "ap_ssh" in data


def test_get_working_sheet_when_none_set(tmp_path: Path):
    path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=path):
        result = api.get_working_sheet()
    assert result == {"path": None, "summary": None, "schema_error": None}


def test_create_new_sheet_sets_working_sheet(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    sheet_path = tmp_path / "device-list.xlsx"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        result = api.create_new_sheet(str(sheet_path))
    assert result["ok"] is True
    assert sheet_path.exists()
    assert result["path"] == str(sheet_path)


def test_add_devices_manual_creates_sheet_when_none_set(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        result = api.add_devices_manual([{"serial": "S1", "device_type": "AP"}])
        assert result["ok"] is True
        assert result["rows_added"] == 1
        devices = api.get_devices()
    assert devices["ok"] is True
    assert devices["devices"][0]["serial"] == "S1"


def test_get_devices_without_working_sheet_returns_error(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        result = api.get_devices()
    assert result["ok"] is False


def test_preprovision_without_credentials_reports_error(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "target_group": "Building-1-APs"}])
        result = api.preprovision()
    assert result["ok"] is False
    assert "Classic Central" in result["error"]


def test_preprovision_noop_when_no_rows_need_it(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1"}])  # no target_group set
        result = api.preprovision()
    assert result == {"ok": True, "provisioned": 0, "failed": 0}


def test_assign_site_reports_unrecognized_device_type(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "target_site": "Building 1", "device_type": "UXI"}])
        result = api.assign_site()
    assert result["unrecognized_types"] == ["UXI"]


def test_reset_to_default_clears_sheet_and_credentials(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("acct", "https://x", "cid", "csecret")
        api.add_devices_manual([{"serial": "S1"}])
        result = api.reset_to_default()
        assert result["ok"] is True
        assert workspace.get_sheet() is None
        assert cs.load() == {}
