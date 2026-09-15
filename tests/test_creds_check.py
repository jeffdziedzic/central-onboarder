from unittest.mock import MagicMock

from central_onboarder.core import central, central_classic, creds_check


def test_normalize_base_url_adds_https_when_missing():
    assert creds_check.normalize_base_url("us1.api.central.arubanetworks.com") == "https://us1.api.central.arubanetworks.com"


def test_normalize_base_url_leaves_existing_scheme_alone():
    assert creds_check.normalize_base_url("http://example.test") == "http://example.test"
    assert creds_check.normalize_base_url("https://example.test") == "https://example.test"


def test_hints_cover_central_classic_ap_ssh_only():
    assert set(creds_check.HINTS.keys()) == {"central", "classic", "ap_ssh"}


def test_test_central_account_success(monkeypatch):
    tm = MagicMock()
    tm.get_token.return_value = "tok"
    monkeypatch.setattr(central, "TokenManager", lambda cid, secret: tm)
    ok, detail = creds_check.test_central_account({"client_id": "cid", "client_secret": "secret"})
    assert ok is True
    assert "GreenLake" in detail


def test_test_central_account_failure(monkeypatch):
    tm = MagicMock()
    tm.get_token.side_effect = central.CentralAuthError("nope")
    monkeypatch.setattr(central, "TokenManager", lambda cid, secret: tm)
    ok, detail = creds_check.test_central_account({"client_id": "cid", "client_secret": "secret"})
    assert ok is False
    assert "nope" in detail


def test_test_classic_account_success(monkeypatch):
    tm = MagicMock()
    tm.get_token.return_value = "tok"
    monkeypatch.setattr(central_classic, "ClassicTokenManager", lambda *a, **k: tm)
    ok, detail = creds_check.test_classic_account(
        "acct", {"base_url": "https://x", "client_id": "cid", "client_secret": "s", "refresh_token": "rt"}
    )
    assert ok is True
