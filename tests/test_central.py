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
