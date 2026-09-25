from unittest.mock import MagicMock

import pytest

from central_onboarder.core import central


def _client():
    return central.CentralClient("https://example.test", "cid", "csecret")


@pytest.mark.parametrize("raw,expected", [
    ("AC:A3:1E:C7:7C:DA", "AC:A3:1E:C7:7C:DA"),
    ("ac-a3-1e-c7-7c-da", "AC:A3:1E:C7:7C:DA"),
    ("ACA31EC77CDA", "AC:A3:1E:C7:7C:DA"),
    ("aca3.1ec7.7cda", "AC:A3:1E:C7:7C:DA"),
])
def test_normalize_mac_accepts_common_separator_styles(raw, expected):
    assert central.normalize_mac(raw) == expected


def test_normalize_mac_rejects_non_mac_strings():
    assert central.normalize_mac("not-a-mac") is None
    assert central.normalize_mac("AA:BB") is None


def test_paginate_stops_when_items_empty():
    c = _client()
    c.get = MagicMock(return_value={"status": 200, "body": {"items": [], "total": 0}})
    assert list(central._paginate(c, "some/path", {})) == []


def test_paginate_follows_offset_style_next_cursor():
    c = _client()
    responses = iter([
        {"status": 200, "body": {"items": [{"id": 1}], "next": 1, "total": 2}},
        {"status": 200, "body": {"items": [{"id": 2}], "total": 2}},
    ])
    c.get = MagicMock(side_effect=lambda *a, **k: next(responses))
    items = list(central._paginate(c, "some/path", {}))
    assert items == [{"id": 1}, {"id": 2}]


def test_list_service_managers_returns_raw_items():
    c = _client()
    c.get = MagicMock(return_value={
        "status": 200,
        "body": {"items": [{"id": "svc-1", "name": "HPE Aruba Networking UXI"}], "total": 1},
    })
    assert central.list_service_managers(c) == [{"id": "svc-1", "name": "HPE Aruba Networking UXI"}]
    c.get.assert_called_once_with("service-catalog/v1/service-managers", params={"limit": 100})


def test_list_device_groups_maps_name_to_scope_id():
    c = _client()
    c.get = MagicMock(return_value={
        "status": 200,
        "body": {"items": [{"scopeName": "Building-1-APs", "scopeId": "s1"}], "total": 1},
    })
    assert central.list_device_groups(c) == {"Building-1-APs": "s1"}


def test_list_sites_maps_name_to_id():
    c = _client()
    c.get = MagicMock(return_value={
        "status": 200,
        "body": {"items": [{"siteName": "Building 1", "id": "site-1"}], "total": 1},
    })
    assert central.list_sites(c) == {"Building 1": "site-1"}


def test_add_devices_to_glcp_sends_serial_and_mac():
    c = _client()
    c.post = MagicMock(return_value={"status": 202, "body": {"transactionId": "tx1"}, "headers": {}})
    c.get = MagicMock(return_value={"status": 200, "body": {"status": "SUCCEEDED"}})

    results = central.add_devices_to_glcp(c, [("S1", "11:22:33:44:aa:bb")])

    body = c.post.call_args.kwargs["body"]
    assert body["network"] == [{"serialNumber": "S1", "macAddress": "11:22:33:44:AA:BB"}]
    assert body["compute"] == []
    assert body["storage"] == []
    assert results == [central.UnassignResult("S1", True, None)]


def test_add_devices_to_glcp_rejects_invalid_mac_without_calling_api():
    c = _client()
    c.post = MagicMock()
    results = central.add_devices_to_glcp(c, [("S1", "not-a-mac")])
    c.post.assert_not_called()
    assert results == [central.UnassignResult("S1", False, "'not-a-mac' is not a valid MAC address")]


def _glp_device(serial, dev_id, application_id=None, region=None, mac=None):
    return {
        "serialNumber": serial, "id": dev_id, "assignedState": "ASSIGNED",
        "application": {"id": application_id} if application_id else {},
        "region": region, "macAddress": mac,
    }


def _devices_and_poll_get(devices_body, sub_lookup_body=None):
    """A c.get side_effect that dispatches on path - list_glp_devices'
    devices/v1/devices, the poll loop's devices/v1/async-operations/*,
    and (if given) get_subscription_id_by_key's subscriptions/v1/
    subscriptions - so a test exercising a real call chain (list ->
    patch -> poll) doesn't have the poll's status check see the wrong
    body and spin for real wall-clock time waiting on a status that
    never arrives."""

    def _get(path, params=None):
        if "async-operations" in path:
            return {"status": 200, "body": {"status": "SUCCEEDED"}}
        if "subscriptions" in path and sub_lookup_body is not None:
            return {"status": 200, "body": sub_lookup_body}
        return {"status": 200, "body": devices_body}

    return _get


def test_restore_central_assignment_auto_discovers_application_id():
    c = _client()
    devices_body = {
        "items": [
            _glp_device("S1", "id1"),
            _glp_device("S2", "id2", application_id="app-123", region="us-west"),
        ],
        "total": 2,
    }
    c.get = MagicMock(side_effect=_devices_and_poll_get(devices_body))
    c.patch = MagicMock(return_value={"status": 202, "body": {"transactionId": "tx1"}})

    results = central.restore_central_assignment(c, ["S1"])

    body = c.patch.call_args.kwargs["body"]
    assert body == {"application": {"id": "app-123"}, "region": "us-west"}
    assert results[0].ok is True


def test_restore_central_assignment_fails_clearly_when_nothing_to_discover_from():
    c = _client()
    devices_body = {"items": [_glp_device("S1", "id1")], "total": 1}
    c.get = MagicMock(side_effect=_devices_and_poll_get(devices_body))
    c.patch = MagicMock()

    results = central.restore_central_assignment(c, ["S1"])

    c.patch.assert_not_called()
    assert results[0].ok is False
    assert "no application_id given" in results[0].detail


def test_assign_subscription_resolves_key_then_patches():
    c = _client()
    devices_body = {"items": [_glp_device("S1", "id1")], "total": 1}
    c.get = MagicMock(side_effect=_devices_and_poll_get(devices_body, sub_lookup_body={"items": [{"id": "sub-1"}]}))
    c.patch = MagicMock(return_value={"status": 202, "body": {"transactionId": "tx1"}})

    central.assign_subscription(c, ["S1"], "PAYHAH3YJE6THY")

    body = c.patch.call_args.kwargs["body"]
    assert body == {"subscription": [{"id": "sub-1"}]}


def test_assign_subscription_key_not_found_reports_per_identifier():
    c = _client()
    c.get = MagicMock(return_value={"status": 200, "body": {"items": []}})
    c.patch = MagicMock()

    results = central.assign_subscription(c, ["S1", "S2"], "NOPE")

    c.patch.assert_not_called()
    assert all(not r.ok for r in results)
    assert "not found in this workspace" in results[0].detail


def test_patch_device_dedupes_serial_and_mac_of_same_device():
    c = _client()
    devices_body = {"items": [_glp_device("S1", "id1", mac="AA:BB:CC:DD:EE:FF")], "total": 1}
    c.get = MagicMock(side_effect=_devices_and_poll_get(devices_body))
    c.patch = MagicMock(return_value={"status": 202, "body": {"transactionId": "tx1"}})

    results = central.remove_subscription_key(c, ["S1", "aa:bb:cc:dd:ee:ff"])

    assert c.patch.call_count == 1
    assert c.patch.call_args.kwargs["params"]["id"] == ["id1"]
    assert len(results) == 1


# --- set_hostname (System Information local profile) ------------------------
# Response shapes below are copied from live calls against a real tenant
# (2026-09-24).

_INVENTORY_AP = {
    "count": 1, "next": None, "total": 1,
    "items": [{
        "serialNumber": "VNLCK9Y0NS", "scopeId": "370578829", "deviceName": "CNX-555",
        "deviceType": "ACCESS_POINT", "deviceFunction": "Campus Access Point", "isProvisioned": "Yes",
    }],
}


def _hostname_client(inventory, local_profile):
    c = _client()
    calls = []

    def fake_get(path, params=None):
        calls.append(("GET", path, dict(params or {})))
        if path == "network-monitoring/v1/device-inventory":
            return {"status": 200, "body": inventory}
        return {"status": 200, "body": local_profile}

    def fake_write(method):
        def _w(path, params=None, body=None):
            calls.append((method, path, dict(params or {}), body))
            return {"status": 200, "body": {"errorCode": "SUCC_001", "httpStatusCode": 200, "message": "success"}}
        return _w

    c.get = fake_get
    c.post = fake_write("POST")
    c.patch = fake_write("PATCH")
    return c, calls


def test_set_hostname_patches_when_local_profile_exists():
    c, calls = _hostname_client(_INVENTORY_AP, {"name": "sys-system-info-profile", "hostname": "OLD"})
    result = central.set_hostname(c, "VNLCK9Y0NS", "NEW-NAME")
    assert result.ok is True
    method, path, params, body = calls[-1]
    assert method == "PATCH"
    assert path == central.SYSTEM_INFO_PROFILE_PATH
    assert params == {"object_type": "LOCAL", "scope_id": "370578829", "persona": "CAMPUS_AP"}
    assert body == {"hostname": "NEW-NAME"}
    get_profile = calls[1]
    assert get_profile[2]["view_type"] == "LOCAL"


def test_set_hostname_posts_when_no_local_profile():
    """Live: a device with no local profile answers GET with 200 {} (not 404)."""
    c, calls = _hostname_client(_INVENTORY_AP, {})
    assert central.set_hostname(c, "VNLCK9Y0NS", "NEW-NAME").ok is True
    assert calls[-1][0] == "POST"
    assert calls[-1][3] == {"hostname": "NEW-NAME"}


@pytest.mark.parametrize("function,persona", [
    ("Access Switch", "ACCESS_SWITCH"),
    ("Mobility Gateway", "MOBILITY_GW"),
    ("Campus AP", "CAMPUS_AP"),
])
def test_set_hostname_persona_per_device_function(function, persona):
    inv = {"items": [{**_INVENTORY_AP["items"][0], "deviceFunction": function}]}
    c, calls = _hostname_client(inv, {})
    central.set_hostname(c, "VNLCK9Y0NS", "X")
    assert calls[-1][2]["persona"] == persona


def test_set_hostname_refuses_unprovisioned_device_without_writing():
    inv = {"items": [{**_INVENTORY_AP["items"][0], "deviceFunction": "-", "isProvisioned": "No"}]}
    c, calls = _hostname_client(inv, {})
    result = central.set_hostname(c, "VNLCK9Y0NS", "X")
    assert result.ok is False
    assert "not provisioned" in result.detail
    assert all(call[0] == "GET" for call in calls)


def test_set_hostname_device_not_in_inventory():
    c, calls = _hostname_client({"items": []}, {})
    result = central.set_hostname(c, "NOPE", "X")
    assert result.ok is False
    assert "inventory" in result.detail


def test_set_hostname_unknown_device_function():
    inv = {"items": [{**_INVENTORY_AP["items"][0], "deviceFunction": "Space Laser"}]}
    c, calls = _hostname_client(inv, {})
    result = central.set_hostname(c, "VNLCK9Y0NS", "X")
    assert result.ok is False
    assert "Space Laser" in result.detail


def test_set_hostname_reports_api_error_message():
    c, calls = _hostname_client(_INVENTORY_AP, {"hostname": "OLD"})

    def bad_patch(path, params=None, body=None):
        raise central.CentralAPIError("PATCH failed", 400, {"message": "hostname invalid"})

    c.patch = bad_patch
    result = central.set_hostname(c, "VNLCK9Y0NS", "bad name!")
    assert result.ok is False
    assert result.detail == "hostname invalid"


def test_set_hostname_blank_hostname():
    c, calls = _hostname_client(_INVENTORY_AP, {})
    assert central.set_hostname(c, "VNLCK9Y0NS", "  ").ok is False
    assert calls == []


# --- list_subscriptions ------------------------------------------------------
# Item shape copied from a live GET subscriptions/v1/subscriptions
# (2026-09-24) - note quantity/availableQuantity are strings.

def _sub_item(key, sub_type, tier, desc, qty, avail, end, status="STARTED", is_eval=False):
    return {
        "id": f"id-{key}", "type": "subscriptions/subscription", "key": key,
        "subscriptionType": sub_type, "tier": tier, "tierDescription": desc,
        "quantity": str(qty), "availableQuantity": str(avail), "isEval": is_eval,
        "skuDescription": "sku", "endTime": end, "subscriptionStatus": status, "productType": "DEVICE",
    }


def test_list_subscriptions_parses_and_paginates():
    c = _client()
    page1 = {"items": [_sub_item("K1", "CENTRAL_AP", "ADVANCED_AP", "Advanced AP", 10, 5, "2031-02-01T14:37:16.000Z")],
             "count": 1, "offset": 0, "total": 2}
    page2 = {"items": [_sub_item("K2", "CENTRAL_SWITCH", "FOUNDATION_SWITCH_6100", "Foundation-Switch-Class-1",
                                 2, 0, "2030-10-05T00:00:00.000Z")],
             "count": 1, "offset": 1, "total": 2}
    pages = iter([{"status": 200, "body": page1}, {"status": 200, "body": page2}])
    c.get = MagicMock(side_effect=lambda *a, **k: next(pages))
    subs = central.list_subscriptions(c)
    assert [s.key for s in subs] == ["K1", "K2"]
    assert (subs[0].quantity, subs[0].available) == (10, 5)
    assert c.get.call_args_list[0].args[0] == "subscriptions/v1/subscriptions"
    assert c.get.call_args_list[1].kwargs["params"]["offset"] == 1


@pytest.mark.parametrize("sub_type,tier,category,level", [
    ("CENTRAL_AP", "ADVANCED_AP", "AP", "Advanced"),
    ("CENTRAL_SWITCH", "FOUNDATION_SWITCH_6100", "Switch", "Foundation"),
    ("CENTRAL_GW", "ADVANCE_70XX", "Gateway", "Advanced"),
    ("CENTRAL_GW", "VGW_500M", "Gateway", None),
    ("UXI_SENSOR_CLOUD", "FOUNDATION_SENSOR_CLOUD", "UXI", "Foundation"),
    ("SERVICE", "ANALYTICS", "Service", None),
])
def test_subscription_category_and_level(sub_type, tier, category, level):
    s = central.Subscription("K", sub_type, tier, "", 1, 1, None, "STARTED", False, None)
    assert s.category == category
    assert s.level == level


def test_subscription_expiry():
    from datetime import datetime, timezone
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    mk = lambda end, status="STARTED": central.Subscription("K", "CENTRAL_AP", "ADVANCED_AP", "", 1, 1, end, status, False, None)
    assert mk("2031-02-01T14:37:16.000Z").is_expired(now) is False
    assert mk("2025-02-10T00:00:00.000Z", "NONE").is_expired(now) is True
    assert mk("2031-02-01T14:37:16.000Z", "ENDED").is_expired(now) is True
    assert mk(None).is_expired(now) is False
