from pathlib import Path
from unittest.mock import patch

from central_onboarder.core import central
from central_onboarder.core import credential_store as cs
from central_onboarder.core import sheet as sheet_module
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


# --- sheet-driven run_X() steps (each Manual card's "Pull from Device
# List" checkbox, 2026-09-15) -------------------------------------------


def test_run_add_to_glcp_without_credentials_reports_error(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "mac": "11:22:33:44:55:66"}])
        result = api.run_add_to_glcp()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_run_add_to_glcp_noop_when_nothing_pending(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1", "mac": "11:22:33:44:55:66"}])
        sheet_module.mark_added_to_glcp(workspace.get_sheet(), ["S1"])
        result = api.run_add_to_glcp()
    assert result == {"ok": True, "results": [], "missing_mac": []}


def test_run_add_to_glcp_reports_missing_mac_without_touching_network(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1"}])  # no MAC set
        result = api.run_add_to_glcp()
    assert result == {"ok": True, "results": [], "missing_mac": ["S1"]}


def test_run_assign_service_without_credentials_reports_error(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1"}])
        result = api.run_assign_service()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_run_assign_service_noop_when_nothing_pending(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1"}])
        sheet_module.mark_service_assigned(workspace.get_sheet(), ["S1"])
        result = api.run_assign_service()
    assert result == {"ok": True, "results": []}


def test_run_assign_subscription_without_credentials_reports_error(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "subscription_key": "KEY-1"}])
        result = api.run_assign_subscription()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_run_assign_subscription_noop_when_no_key_set(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1"}])  # no subscription_key
        result = api.run_assign_subscription()
    assert result == {"ok": True, "results": []}


def test_run_onboard_batch_skips_preprovision_without_classic_creds(tmp_path: Path):
    """run_onboard_batch's pre-provision step (folded in per the merged
    Onboard screen, 2026-09-15) must not fail the whole batch just
    because Classic Central creds aren't stored - GLCP-side onboarding
    shouldn't be blocked on a platform this workspace may not use yet."""
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "target_group": "Building-1-APs"}])
        sheet_path = workspace.get_sheet()
        # mark every GLCP-side step done so only pre-provision is left pending
        sheet_module.mark_added_to_glcp(sheet_path, ["S1"])
        sheet_module.mark_service_assigned(sheet_path, ["S1"])
        result = api.run_onboard_batch()
    assert result["ok"] is True
    assert result["preprovision"]["ok"] is True
    assert "Classic Central" in result["preprovision"]["skipped"]


def test_run_onboard_batch_noop_when_no_rows_need_anything(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        api.add_devices_manual([{"serial": "S1"}])  # no target_group/subscription_key set
        sheet_path = workspace.get_sheet()
        sheet_module.mark_added_to_glcp(sheet_path, ["S1"])
        sheet_module.mark_service_assigned(sheet_path, ["S1"])  # nothing left pending for any step
        result = api.run_onboard_batch()
    assert result["ok"] is True
    assert result["preprovision"] == {"ok": True, "provisioned": 0, "failed": 0}


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


# --- UXI --------------------------------------------------------------


def test_save_uxi_requires_application_id(tmp_path: Path):
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.save_uxi("")
    assert result["ok"] is False


def test_list_glcp_services_without_credentials_reports_error(tmp_path: Path):
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.list_glcp_services()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_save_and_get_uxi_application(tmp_path: Path):
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.save_uxi("app-1", "us-west")
        assert result["ok"] is True
        data = api.get_credentials()
    assert data["uxi"] == {"application_id": "app-1", "region": "us-west"}


def test_run_onboard_batch_splits_service_assignment_by_uxi_vs_central(tmp_path: Path):
    """UXI rows must get their own application_id (from credential_store's
    uxi entry), never Central's auto-discovered one - a real bug risk
    for a mixed AP+UXI batch, since restore_central_assignment's
    auto-discovery doesn't distinguish device types on its own (see
    api.py's run_onboard_batch docstring)."""
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        cs.set_central_account("acct", "https://x", "cid", "csecret", path=creds_path)
        cs.set_uxi_application("uxi-app-1", region="us-west", path=creds_path)
        api.add_devices_manual([
            {"serial": "AP1", "mac": "11:22:33:44:55:66", "device_type": "AP"},
            {"serial": "UXI1", "mac": "AA:BB:CC:DD:EE:FF", "device_type": "UXI"},
        ])

        calls = []

        def fake_restore(client, identifiers, application_id, region):
            calls.append((tuple(identifiers), application_id, region))
            return [central.UnassignResult(i, True) for i in identifiers]

        with patch.object(
                central, "add_devices_to_glcp",
                return_value=[central.UnassignResult("AP1", True), central.UnassignResult("UXI1", True)]
        ), patch.object(central, "restore_central_assignment", side_effect=fake_restore):
            result = api.run_onboard_batch()

    assert result["ok"] is True
    assert (("AP1",), None, None) in calls
    assert (("UXI1",), "uxi-app-1", "us-west") in calls


def test_run_onboard_batch_uxi_service_fails_cleanly_without_stored_application(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        cs.set_central_account("acct", "https://x", "cid", "csecret", path=creds_path)
        api.add_devices_manual([{"serial": "UXI1", "mac": "AA:BB:CC:DD:EE:FF", "device_type": "UXI"}])
        with patch.object(central, "add_devices_to_glcp", return_value=[central.UnassignResult("UXI1", True)]):
            result = api.run_onboard_batch()

    assert result["ok"] is True
    assert result["service"]["ok"] is False
    assert "UXI application_id" in result["service"]["results"][0]["detail"]


# --- new manual cards ---------------------------------------------------


def test_remove_service_without_credentials_reports_error(tmp_path: Path):
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.remove_service(["S1"])
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_assign_site_manual_requires_identifiers_and_site():
    api = Api()
    assert api.assign_site_manual([], "AP", "")["ok"] is False


def test_assign_site_manual_rejects_unrecognized_device_type():
    api = Api()
    result = api.assign_site_manual(["S1"], "UXI", "Site A")
    assert result["ok"] is False
    assert "Unrecognized device type" in result["error"]


def test_preprovision_manual_requires_identifiers_and_group():
    api = Api()
    assert api.preprovision_manual([], "")["ok"] is False


def test_check_full_status_requires_identifier():
    api = Api()
    assert api.check_full_status("  ")["ok"] is False


def test_check_full_status_skips_both_sections_without_credentials(tmp_path: Path):
    creds_path = tmp_path / "credentials.json"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.check_full_status("SOMESERIAL")
    assert result["ok"] is True
    assert "No New Central credentials" in result["glcp"]["skipped"]
    assert "Classic Central" in result["classic"]["skipped"]
