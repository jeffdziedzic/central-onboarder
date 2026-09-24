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
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        result = api.save_central("acct", "us1.api.central.arubanetworks.com", "cid", "csecret")
        assert result["ok"] is True
        data = api.get_credentials()
    assert data["accounts"]["acct"]["base_url"] == "https://us1.api.central.arubanetworks.com"
    assert data["active"] == "acct"


def test_save_central_rejects_missing_fields(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        result = api.save_central("acct", "", "cid", "csecret")
    assert result["ok"] is False


def test_wipe_credentials_removes_one_category(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        api.save_central("acct", "https://x", "cid", "csecret")
        api.save_ap_ssh("acct", "admin", "hunter2")
        api.wipe_credentials("acct", "central")
        data = api.get_credentials()
    acct = data["accounts"]["acct"]
    assert "client_id" not in acct
    assert acct["ap_ssh_username"] == "admin"


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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "S1", "target_site": "Building 1", "device_type": "UXI"}])
        result = api.assign_site()
    assert result["unrecognized_types"] == ["UXI"]


def test_reset_to_default_clears_sheet_and_credentials(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("acct", "https://x", "cid", "csecret")
        api.add_devices_manual([{"serial": "S1"}])
        result = api.reset_to_default()
        assert result["ok"] is True
        assert workspace.get_sheet() is None
        assert cs.load() == {"accounts": {}}


# --- UXI --------------------------------------------------------------


def test_save_uxi_requires_application_id(tmp_path: Path):
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.save_uxi("acct", "")
    assert result["ok"] is False


def test_list_glcp_services_without_credentials_reports_error(tmp_path: Path):
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.list_glcp_services()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_save_and_get_uxi_application(tmp_path: Path):
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.save_uxi("acct", "app-1", "us-west")
        assert result["ok"] is True
        data = api.get_credentials()
    assert data["accounts"]["acct"]["uxi_application_id"] == "app-1"
    assert data["accounts"]["acct"]["uxi_region"] == "us-west"


def test_run_onboard_batch_splits_service_assignment_by_uxi_vs_central(tmp_path: Path):
    """UXI rows must get their own application_id (from credential_store's
    uxi entry), never Central's auto-discovered one - a real bug risk
    for a mixed AP+UXI batch, since restore_central_assignment's
    auto-discovery doesn't distinguish device types on its own (see
    api.py's run_onboard_batch docstring)."""
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        cs.set_central_account("acct", "https://x", "cid", "csecret", path=creds_path)
        cs.set_uxi_application("acct", "uxi-app-1", region="us-west", path=creds_path)
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
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
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=creds_path):
        result = api.check_full_status("SOMESERIAL")
    assert result["ok"] is True
    assert "New Central credentials" in result["glcp"]["skipped"]
    assert "Classic Central" in result["classic"]["skipped"]


# --- multi-account selection ----------------------------------------------


def test_api_calls_use_the_selected_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        api.save_central("cust_a", "https://a", "id-a", "sec-a")
        api.save_central("cust_b", "https://b", "id-b", "sec-b")
        assert api._central_creds() == ("https://a", "id-a", "sec-a")
        assert api.set_active_account("cust_b")["ok"] is True
        assert api._central_creds() == ("https://b", "id-b", "sec-b")
        assert api._glp_creds() == ("id-b", "sec-b")
        assert api.get_credentials()["active"] == "cust_b"


def test_classic_client_uses_selected_account_and_persists_rotation_there(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        api.save_classic("cust_a", "https://ag-a", "id-a", "sec-a", "rt-a")
        api.save_classic("cust_b", "https://ag-b", "id-b", "sec-b", "rt-b")
        api.set_active_account("cust_b")
        assert api._classic_creds()[4] == "cust_b"
        client, error = api._classic_client()
        assert error is None
        client._tm._on_rotated("rt-b2")  # what a real token refresh fires
        assert cs.get_classic_account("cust_a")["refresh_token"] == "rt-a"
        assert cs.get_classic_account("cust_b")["refresh_token"] == "rt-b2"


def test_set_active_account_unknown_reports_error(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        result = api.set_active_account("ghost")
    assert result["ok"] is False


def test_add_account_rejects_blank_and_duplicate(tmp_path: Path):
    path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(cs, "default_path", return_value=path):
        assert api.add_account("  ")["ok"] is False
        assert api.add_account("cust_a")["ok"] is True
        assert api.add_account("cust_a")["ok"] is False
        assert api.get_credentials()["active"] == "cust_a"


def test_uxi_service_uses_selected_accounts_application(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("cust_a", "https://a", "id-a", "sec-a")
        api.save_uxi("cust_a", "uxi-a")
        api.save_central("cust_b", "https://b", "id-b", "sec-b")
        api.save_uxi("cust_b", "uxi-b")
        api.set_active_account("cust_b")
        api.add_devices_manual([{"serial": "UXI1", "mac": "AA:BB:CC:DD:EE:FF", "device_type": "UXI"}])
        calls = []

        def fake_restore(client, identifiers, application_id, region):
            calls.append(application_id)
            return [central.UnassignResult(i, True) for i in identifiers]

        with patch.object(central, "add_devices_to_glcp", return_value=[central.UnassignResult("UXI1", True)]), \
             patch.object(central, "restore_central_assignment", side_effect=fake_restore):
            api.run_onboard_batch()
    assert calls == ["uxi-b"]


def test_get_credentials_migrates_legacy_json_once(tmp_path: Path):
    import json
    legacy = cs.legacy_path()
    legacy.write_text(json.dumps(
        {"central": {"old": {"base_url": "https://x", "client_id": "i", "client_secret": "s"}}}
    ), encoding="utf-8")
    api = Api()
    first = api.get_credentials()
    assert first["migrated"] == ["old"]
    assert first["active"] == "old"
    second = api.get_credentials()
    assert second["migrated"] == []
    assert second["legacy_file_present"] is True


def test_check_full_status_gateway_by_mac_uses_gateway_endpoint(tmp_path: Path):
    """Live bug 2026-09-24: switches/gateways always showed 'not seen'
    in Classic Central because only the AP endpoint was asked."""
    from central_onboarder.core import central_classic

    creds_path = tmp_path / "token.yaml"
    api = Api()
    glcp_device = central.GLPDeviceRecord(
        serial="GW1", assigned_state="ASSIGNED", subscription_tier="ADVANCE_70XX",
        subscription_end="2031-02-01", application_id="app", mac_address="20:4C:03:B6:E1:6A",
        raw={"deviceType": "GATEWAY"},
    )
    paths = []

    def fake_get(self, path, params=None):
        paths.append(path)
        if path == "monitoring/v1/gateways/GW1":
            return {"status": 200, "body": {"status": "Up", "group_name": "GW-Group", "site": "HQ"}}
        raise central_classic.ClassicAPIError("not found", status=404)

    with patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("acct", "https://x", "cid", "csecret")
        api.save_classic("acct", "https://ag", "acid", "acs", "rt")
        with patch.object(central, "list_glp_devices", return_value=[glcp_device]), \
             patch.object(central_classic.ClassicCentralClient, "get", fake_get):
            result = api.check_full_status("20:4c:03:b6:e1:6a")

    assert paths == ["monitoring/v1/gateways/GW1"]
    assert result["classic"] == {
        "checked_in": True, "device_type": "Gateway", "status": "Up", "group": "GW-Group", "site": "HQ",
    }


# --- Set Hostname (Post Onboard) --------------------------------------------


def test_run_set_hostname_uses_each_rows_hostname_and_marks(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()
    seen = []

    def fake_set(client, pairs):
        seen.extend(pairs)
        return [central.UnassignResult(s, s != "S1", None if s != "S1" else "not provisioned") for s, _h in pairs]

    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("acct", "https://nc", "cid", "csecret")
        api.add_devices_manual([
            {"serial": "A1", "device_type": "AP", "hostname": "AP-01"},
            {"serial": "S1", "device_type": "Switch", "hostname": "SW-01"},
            {"serial": "U1", "device_type": "UXI", "hostname": "UXI-01"},
            {"serial": "N1", "device_type": "AP"},
        ])
        with patch.object(central, "set_hostnames", side_effect=fake_set):
            result = api.run_set_hostname()
            rows = {r["serial"]: r for r in api.get_devices()["devices"]}
            again = api.run_set_hostname()

    assert seen[:2] == [("A1", "AP-01"), ("S1", "SW-01")]
    assert result["ok"] is False
    assert rows["A1"]["hostname_set"] == "Y"
    assert rows["S1"]["hostname_set"] is None
    assert [s for s, _ in seen[2:]] == ["S1"]  # rerun retries only the failed row
    assert again["results"][0]["serial"] == "S1"


def test_run_set_hostname_without_credentials(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.add_devices_manual([{"serial": "A1", "hostname": "AP-01"}])
        result = api.run_set_hostname()
    assert result["ok"] is False
    assert "New Central" in result["error"]


def test_set_hostname_manual_requires_paired_lists(tmp_path: Path):
    api = Api()
    assert api.set_hostname_manual(["A1", "A2"], ["X"])["ok"] is False
    assert api.set_hostname_manual([], [])["ok"] is False


def test_set_hostname_manual_marks_only_rows_with_matching_planned_hostname(tmp_path: Path):
    ws_path = tmp_path / "workspace.json"
    creds_path = tmp_path / "token.yaml"
    api = Api()

    def ok_all(client, pairs):
        return [central.UnassignResult(s, True) for s, _h in pairs]

    with patch.object(workspace, "default_path", return_value=ws_path), \
         patch.object(cs, "default_path", return_value=creds_path):
        api.save_central("acct", "https://nc", "cid", "csecret")
        api.add_devices_manual([
            {"serial": "A1", "hostname": "AP-01"},
            {"serial": "A2", "hostname": "AP-02"},
        ])
        with patch.object(central, "set_hostnames", side_effect=ok_all):
            result = api.set_hostname_manual(["A1", "A2"], ["AP-01", "SOMETHING-ELSE"])
        rows = {r["serial"]: r for r in api.get_devices()["devices"]}
    assert result["ok"] is True
    assert rows["A1"]["hostname_set"] == "Y"
    assert rows["A2"]["hostname_set"] is None


def test_working_sheet_in_old_layout_is_upgraded_on_open(tmp_path: Path):
    import openpyxl
    ws_path = tmp_path / "workspace.json"
    old = tmp_path / "old.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = sheet_module.DEVICES_SHEET
    wb.active.append(list(sheet_module._V1_DEVICES_HEADERS))
    wb.active.append(["S1", None, "AP", None, None, None, "Y", None, None, None, None, None])
    wb.save(old)
    api = Api()
    with patch.object(workspace, "default_path", return_value=ws_path):
        result = api.set_working_sheet(str(old))
        devices = api.get_devices()["devices"]
    assert result["ok"] is True
    assert result["schema_error"] is None
    assert devices[0]["added_to_glcp"] == "Y"
