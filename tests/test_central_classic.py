from unittest.mock import MagicMock

import pytest

from central_onboarder.core import central_classic as cc


def _client():
    tm = MagicMock()
    tm.get_token.return_value = "tok"
    return cc.ClassicCentralClient("https://example.test", tm)


def test_preprovision_device_to_group_posts_expected_body():
    c = _client()
    c.post = MagicMock(return_value={"status": 200, "body": {"ok": True}})
    result = cc.preprovision_device_to_group(c, "Building-1-APs", ["S1", "S2"])
    c.post.assert_called_once_with(
        "configuration/v1/devices/move", body={"group": "Building-1-APs", "serials": ["S1", "S2"]}
    )
    assert result == {"ok": True}


def test_preprovision_device_to_group_rejects_too_many_serials():
    c = _client()
    c.post = MagicMock()
    with pytest.raises(ValueError):
        cc.preprovision_device_to_group(c, "group", [f"S{i}" for i in range(51)])
    c.post.assert_not_called()


def test_get_device_group_returns_group_name():
    c = _client()
    c.get = MagicMock(return_value={"status": 200, "body": {"group": "Building-1-APs"}})
    assert cc.get_device_group(c, "S1") == "Building-1-APs"


def test_get_device_group_returns_none_when_absent():
    c = _client()
    c.get = MagicMock(return_value={"status": 200, "body": {}})
    assert cc.get_device_group(c, "S1") is None


def test_get_ap_status_seen():
    c = _client()
    c.get = MagicMock(return_value={"status": 200, "body": {
        "status": "Up", "group_name": "g1", "site_name": "s1", "firmware_version": "10.5",
    }})
    status = cc.get_ap_status(c, "S1")
    assert status.seen is True
    assert status.status == "Up"
    assert status.site_name == "s1"


def test_get_ap_status_404_means_not_seen():
    c = _client()
    c.get = MagicMock(side_effect=cc.ClassicAPIError("not found", status=404))
    status = cc.get_ap_status(c, "S1")
    assert status.seen is False
    assert status.status is None


def test_get_ap_status_reraises_non_404():
    c = _client()
    c.get = MagicMock(side_effect=cc.ClassicAPIError("server error", status=500))
    with pytest.raises(cc.ClassicAPIError):
        cc.get_ap_status(c, "S1")


def _get_by_path(responses: dict):
    """Fake client.get: path -> body, anything else 404s."""
    calls = []

    def fake_get(path, params=None):
        calls.append(path)
        if path in responses:
            return {"status": 200, "body": responses[path]}
        raise cc.ClassicAPIError("not found", status=404)

    return fake_get, calls


def test_get_device_status_finds_switch_after_ap_404():
    c = _client()
    c.get, calls = _get_by_path({"monitoring/v1/switches/SW1": {"status": "Up", "group_name": "g", "site": "HQ"}})
    status = cc.get_device_status(c, "SW1")
    assert status.seen is True
    assert status.device_type == "Switch"
    assert status.site_name == "HQ"
    assert calls == ["monitoring/v1/aps/SW1", "monitoring/v1/switches/SW1"]


def test_get_device_status_finds_gateway():
    c = _client()
    c.get, _ = _get_by_path({"monitoring/v1/gateways/GW1": {"status": "Up", "group_name": "g"}})
    status = cc.get_device_status(c, "GW1")
    assert status.device_type == "Gateway"
    assert status.status == "Up"


def test_get_device_status_tries_hinted_type_first():
    c = _client()
    c.get, calls = _get_by_path({"monitoring/v1/gateways/GW1": {"status": "Up"}})
    cc.get_device_status(c, "GW1", "Gateway")
    assert calls == ["monitoring/v1/gateways/GW1"]


def test_get_device_status_wrong_hint_still_falls_back():
    c = _client()
    c.get, calls = _get_by_path({"monitoring/v1/aps/AP1": {"status": "Up", "site_name": "s"}})
    status = cc.get_device_status(c, "AP1", "Switch")
    assert status.device_type == "AP"
    assert calls[0] == "monitoring/v1/switches/AP1"


def test_get_device_status_all_404_means_not_seen():
    c = _client()
    c.get, calls = _get_by_path({})
    status = cc.get_device_status(c, "X")
    assert status.seen is False
    assert len(calls) == 3


def test_get_device_status_reraises_non_404():
    c = _client()
    c.get = MagicMock(side_effect=cc.ClassicAPIError("server error", status=500))
    with pytest.raises(cc.ClassicAPIError):
        cc.get_device_status(c, "S1")


def test_list_sites_single_short_page():
    c = _client()
    c.get = MagicMock(return_value={
        "status": 200, "body": {"sites": [{"site_name": "Site A", "site_id": 1}], "total": 1},
    })
    assert cc.list_sites(c) == {"Site A": 1}


def test_list_sites_paginates_across_full_pages():
    # list_sites' own stop condition is "page shorter than the 100-item
    # page size" (no cursor field to key off) - so a first page must be
    # a FULL 100 items to continue to a second, shorter page.
    c = _client()
    full_page = [{"site_name": f"Site {i}", "site_id": i} for i in range(100)]
    responses = iter([
        {"status": 200, "body": {"sites": full_page, "total": 101}},
        {"status": 200, "body": {"sites": [{"site_name": "Site 100", "site_id": 100}], "total": 101}},
    ])
    c.get = MagicMock(side_effect=lambda *a, **k: next(responses))
    sites = cc.list_sites(c)
    assert len(sites) == 101
    assert sites["Site 100"] == 100


def test_associate_devices_to_site_posts_expected_body():
    c = _client()
    c.post = MagicMock(return_value={"status": 200, "body": {"ok": True}})
    cc.associate_devices_to_site(c, 42, cc.DEVICE_TYPE_SWITCH, ["S1"])
    c.post.assert_called_once_with(
        "central/v2/sites/associations",
        body={"site_id": 42, "device_type": "SWITCH", "device_ids": ["S1"]},
    )


def test_device_type_constants_cover_ap_switch_gateway():
    assert cc.DEVICE_TYPE_AP == "IAP"
    assert cc.DEVICE_TYPE_SWITCH == "SWITCH"
    # DEVICE_TYPE_GATEWAY is this project's own addition (not present in
    # the sibling conversion project, which only ever handled APs) -
    # confirmed by the user 2026-09-15, not a guess.
    assert cc.DEVICE_TYPE_GATEWAY == "GATEWAY"


def test_token_manager_sends_refresh_token_grant():
    tm = cc.ClassicTokenManager("https://example.test", "cid", "csecret", "rt-old")
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": "tok", "expires_in": 7200}
    session.post.return_value = resp
    tm._session = session

    token = tm.get_token()
    assert token == "tok"
    args, kwargs = session.post.call_args
    assert args[0] == "https://example.test/oauth2/token"
    assert kwargs["params"]["grant_type"] == "refresh_token"
    assert kwargs["params"]["refresh_token"] == "rt-old"


def test_token_manager_rotates_refresh_token_and_calls_back():
    rotated = []
    tm = cc.ClassicTokenManager(
        "https://example.test", "cid", "csecret", "rt-old",
        on_refresh_token_rotated=lambda new_rt: rotated.append(new_rt),
    )
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": "tok", "expires_in": 7200, "refresh_token": "rt-new"}
    session.post.return_value = resp
    tm._session = session

    tm.get_token()
    assert rotated == ["rt-new"]


def test_token_manager_raises_on_non_200():
    tm = cc.ClassicTokenManager("https://example.test", "cid", "csecret", "rt-old")
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 401
    session.post.return_value = resp
    tm._session = session

    with pytest.raises(cc.ClassicAuthError):
        tm.get_token()


# --- set_hostname (Classic Central) ------------------------------------------
# Request/response shapes live-confirmed 2026-09-24 (AP, AOS-CX switch and
# AOS10 gateway on a real workspace).

def _classic_hostname_client(found: dict, caas_body=None, template=None):
    """found: monitoring path -> body; anything else under monitoring 404s.
    template: {"Wired": bool, "Wireless": bool} for every group (default
    both False = UI group)."""
    c = _client()
    calls = []

    def fake_call(method, path, params=None, body=None):
        calls.append((method, path, params, body))
        if path.startswith("monitoring/"):
            if path in found:
                return {"status": 200, "body": found[path]}
            raise cc.ClassicAPIError("not found", status=404)
        if path == "configuration/v2/groups/template_info":
            return {"status": 200, "body": {"data": [
                {"group": params["groups"], "template_details": template or {"Wired": False, "Wireless": False}}
            ]}}
        if path.startswith("configuration/v2/ap_settings/") and method == "GET":
            return {"status": 200, "body": {"hostname": "OLD", "ip_address": "0.0.0.0", "zonename": "_#ALL#_"}}
        if path == "caasapi/v1/exec/cmd":
            return {"status": 200, "body": caas_body or {
                "_global_result": {"status": 0, "status_str": "Success"},
                "cli_cmds_result": [{body["cli_cmds"][0]: {"status": 0, "status_str": ""}}],
            }}
        return {"status": 200, "body": "Success"}

    c._call = fake_call
    c.get = lambda path, params=None: fake_call("GET", path, params)
    c.post = lambda path, body=None: fake_call("POST", path, None, body)
    c.patch = lambda path, body=None: fake_call("PATCH", path, None, body)
    return c, calls


def test_classic_set_hostname_ap_posts_full_settings_with_new_hostname():
    c, calls = _classic_hostname_client({"monitoring/v1/aps/AP1": {"status": "Up", "group_name": "G"}})
    result = cc.set_hostname(c, "AP1", "NEW-AP", "AP")
    assert result.ok is True
    method, path, _params, body = calls[-1]
    assert (method, path) == ("POST", "configuration/v2/ap_settings/AP1")
    assert body == {"hostname": "NEW-AP", "ip_address": "0.0.0.0", "zonename": "_#ALL#_"}


def test_classic_set_hostname_switch_patches_sys_hostname_variable():
    c, calls = _classic_hostname_client({"monitoring/v1/switches/SW1": {"status": "Down", "group_name": "Switches"}})
    result = cc.set_hostname(c, "SW1", "NEW-SW")
    assert result.ok is True
    assert calls[-1] == ("PATCH", "configuration/v1/devices/SW1/template_variables", None,
                         {"variables": {"_sys_hostname": "NEW-SW"}})


def test_classic_set_hostname_gateway_uses_caasapi_device_node():
    c, calls = _classic_hostname_client({"monitoring/v1/gateways/GW1": {
        "status": "Up", "group_name": "Branch - New", "macaddr": "20:4c:03:b6:e1:6a"}})
    result = cc.set_hostname(c, "GW1", "NEW-GW", "Gateway")
    assert result.ok is True
    method, path, params, body = calls[-1]
    assert (method, path) == ("POST", "caasapi/v1/exec/cmd")
    assert params == {"group_name": "Branch - New/20:4C:03:B6:E1:6A"}
    assert body == {"cli_cmds": ["hostname NEW-GW"]}


def test_classic_set_hostname_gateway_caasapi_failure_inside_200():
    bad = {"_global_result": {"status": 1, "status_str": "Invalid node"}, "cli_cmds_result": []}
    c, _calls = _classic_hostname_client({"monitoring/v1/gateways/GW1": {
        "status": "Up", "group_name": "G", "macaddr": "aa:bb:cc:dd:ee:ff"}}, caas_body=bad)
    result = cc.set_hostname(c, "GW1", "X", "Gateway")
    assert result.ok is False
    assert "Invalid node" in result.detail


def test_classic_set_hostname_unknown_device():
    c, calls = _classic_hostname_client({})
    result = cc.set_hostname(c, "NOPE", "X")
    assert result.ok is False
    assert "not found in Classic Central" in result.detail
    assert all(call[1].startswith("monitoring/") for call in calls)


def test_classic_set_hostname_blank():
    c, calls = _classic_hostname_client({})
    assert cc.set_hostname(c, "AP1", " ").ok is False
    assert calls == []


@pytest.mark.parametrize("found,hint,template", [
    ({"monitoring/v1/switches/D1": {"status": "Up", "group_name": "TG"}}, "Switch", {"Wired": True, "Wireless": False}),
    ({"monitoring/v1/aps/D1": {"status": "Up", "group_name": "TG"}}, "AP", {"Wired": False, "Wireless": True}),
    ({"monitoring/v1/gateways/D1": {"status": "Up", "group_name": "TG", "macaddr": "aa:bb:cc:dd:ee:ff"}},
     "Gateway", {"Wired": False, "Wireless": True}),
])
def test_classic_set_hostname_refuses_template_groups_without_writing(found, hint, template):
    c, calls = _classic_hostname_client(found, template=template)
    result = cc.set_hostname(c, "D1", "X", hint)
    assert result.ok is False
    assert "template group" in result.detail
    assert all(method == "GET" for method, *_ in calls)


def test_classic_set_hostname_switch_allowed_when_only_wireless_is_templated():
    c, calls = _classic_hostname_client(
        {"monitoring/v1/switches/SW1": {"status": "Up", "group_name": "Mixed"}},
        template={"Wired": False, "Wireless": True},
    )
    assert cc.set_hostname(c, "SW1", "SW-NEW", "Switch").ok is True
    assert calls[-1][0] == "PATCH"
