import json
from pathlib import Path

import yaml

from central_onboarder.core import credential_store as cs

_REAL_APP_DIR = cs._app_dir  # captured before conftest's per-test patch


def test_default_path_is_next_to_the_exe_when_frozen(tmp_path: Path, monkeypatch):
    import sys
    monkeypatch.setattr(cs, "_app_dir", _REAL_APP_DIR)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Central Onboarder.exe"))
    assert cs.default_path() == tmp_path.resolve() / "token.yaml"
    assert cs.legacy_path() == tmp_path.resolve() / "credentials.json"


def test_load_missing_file_returns_empty_accounts(tmp_path: Path):
    assert cs.load(tmp_path / "does-not-exist.yaml") == {"accounts": {}}


def test_default_path_is_token_yaml():
    assert cs.default_path().name == "token.yaml"


def test_set_and_get_central_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("acct", "https://us1.api.central.arubanetworks.com", "cid", "csecret", path=path)
    entry = cs.get_central_account("acct", path=path)
    assert entry == {
        "base_url": "https://us1.api.central.arubanetworks.com",
        "client_id": "cid",
        "client_secret": "csecret",
    }


def test_get_central_account_missing_returns_none(tmp_path: Path):
    assert cs.get_central_account("nope", path=tmp_path / "token.yaml") is None


def test_central_and_classic_share_one_account_block(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("acct", "url-new", "cid-new", "secret-new", path=path)
    cs.set_classic_account("acct", "url-classic", "cid-classic", "secret-classic", "rt", path=path)
    assert cs.get_central_account("acct", path=path)["base_url"] == "url-new"
    assert cs.get_classic_account("acct", path=path)["base_url"] == "url-classic"
    assert cs.list_accounts(path=path) == ["acct"]


def test_file_uses_aruba_central_token_yaml_key_names(tmp_path: Path):
    """An account block must be copy-pasteable to/from the sibling
    aruba_central project's token.yaml."""
    path = tmp_path / "token.yaml"
    cs.set_central_account("home", "https://nc", "cid", "cs", path=path)
    cs.set_classic_account("home", "https://apigw", "acid", "acs", "rt", path=path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw == {
        "accounts": {
            "home": {
                "base_url": "https://nc", "client_id": "cid", "client_secret": "cs",
                "apigw_base_url": "https://apigw", "apigw_client_id": "acid",
                "apigw_client_secret": "acs", "apigw_refresh_token": "rt",
            }
        },
        "default": "home",
    }


def test_reads_hand_written_aruba_central_style_file(tmp_path: Path):
    path = tmp_path / "token.yaml"
    path.write_text(
        "accounts:\n"
        "  customer_A:\n"
        "    base_url: https://a\n    client_id: ida\n    client_secret: sa\n"
        "  home:\n"
        "    base_url: https://h\n    client_id: idh\n    client_secret: sh\n"
        "    apigw_base_url: https://ag\n    apigw_client_id: agid\n"
        "    apigw_client_secret: ags\n    apigw_refresh_token: agrt\n"
        "default: home\n",
        encoding="utf-8",
    )
    assert cs.list_accounts(path=path) == ["customer_A", "home"]
    assert cs.get_active_account(path=path) == "home"
    assert cs.get_classic_account("customer_A", path=path) is None
    assert cs.get_classic_account("home", path=path)["refresh_token"] == "agrt"


def test_partial_central_credentials_count_as_missing(tmp_path: Path):
    path = tmp_path / "token.yaml"
    path.write_text("accounts:\n  a:\n    base_url: https://a\n", encoding="utf-8")
    assert cs.get_central_account("a", path=path) is None


# --- active account --------------------------------------------------------


def test_first_saved_account_becomes_active(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("first", "u", "i", "s", path=path)
    cs.set_central_account("second", "u", "i", "s", path=path)
    assert cs.get_active_account(path=path) == "first"


def test_set_active_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("first", "u", "i", "s", path=path)
    cs.set_central_account("second", "u", "i", "s", path=path)
    cs.set_active_account("second", path=path)
    assert cs.get_active_account(path=path) == "second"


def test_set_active_account_unknown_raises(tmp_path: Path):
    path = tmp_path / "token.yaml"
    try:
        cs.set_active_account("ghost", path=path)
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_stale_default_falls_back_to_first_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    path.write_text("accounts:\n  a: {}\n  b: {}\ndefault: gone\n", encoding="utf-8")
    assert cs.get_active_account(path=path) == "a"


def test_no_accounts_means_no_active(tmp_path: Path):
    assert cs.get_active_account(path=tmp_path / "token.yaml") is None


def test_add_account_creates_empty_and_selects_it(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("a", "u", "i", "s", path=path)
    cs.add_account("b", path=path)
    assert cs.list_accounts(path=path) == ["a", "b"]
    assert cs.get_active_account(path=path) == "b"
    assert cs.get_account("b", path=path) == {}


def test_delete_active_account_moves_default(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.add_account("a", path=path)
    cs.add_account("b", path=path)
    cs.delete_account("b", path=path)
    assert cs.list_accounts(path=path) == ["a"]
    assert cs.get_active_account(path=path) == "a"
    cs.delete_account("a", path=path)
    assert cs.load(path) == {"accounts": {}}


# --- refresh token rotation ------------------------------------------------


def test_update_classic_refresh_token_rotates_existing_entry(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_classic_account("acct", "url", "id", "secret", "rt-old", path=path)
    cs.update_classic_refresh_token("acct", "rt-new", path=path)
    entry = cs.get_classic_account("acct", path=path)
    assert entry["refresh_token"] == "rt-new"
    assert entry["client_id"] == "id"


def test_update_classic_refresh_token_only_touches_that_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_classic_account("a", "url", "id", "secret", "rt-a", path=path)
    cs.set_classic_account("b", "url", "id", "secret", "rt-b", path=path)
    cs.update_classic_refresh_token("b", "rt-b2", path=path)
    assert cs.get_classic_account("a", path=path)["refresh_token"] == "rt-a"
    assert cs.get_classic_account("b", path=path)["refresh_token"] == "rt-b2"


def test_update_classic_refresh_token_noop_when_account_not_stored(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.update_classic_refresh_token("never-stored", "rt-new", path=path)
    assert not path.exists()


def test_update_classic_refresh_token_noop_for_central_only_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("acct", "u", "i", "s", path=path)
    cs.update_classic_refresh_token("acct", "rt-new", path=path)
    assert "apigw_refresh_token" not in cs.get_account("acct", path=path)


# --- ap_ssh / uxi ------------------------------------------------------------


def test_set_and_get_ap_ssh_credential(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_ap_ssh_credential("acct", "admin", "hunter2", ap_ip="192.0.2.1", path=path)
    entry = cs.get_ap_ssh_credential("acct", path=path)
    assert entry == {"username": "admin", "password": "hunter2", "ap_ip": "192.0.2.1"}


def test_set_ap_ssh_credential_excludes_creds_when_omitted(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_ap_ssh_credential("acct", "admin", "hunter2", path=path)
    cs.set_ap_ssh_credential("acct", ap_ip="192.0.2.1", path=path)
    entry = cs.get_ap_ssh_credential("acct", path=path)
    assert entry == {"ap_ip": "192.0.2.1"}


def test_uxi_application_is_per_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    assert cs.get_uxi_application("a", path=path) is None
    cs.set_uxi_application("a", "app-a", region="us-west", path=path)
    cs.set_uxi_application("b", "app-b", path=path)
    assert cs.get_uxi_application("a", path=path) == {"application_id": "app-a", "region": "us-west"}
    assert cs.get_uxi_application("b", path=path) == {"application_id": "app-b", "region": None}


# --- clearing ----------------------------------------------------------------


def test_clear_category_removes_only_that_category_of_that_account(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("a", "url", "id", "secret", path=path)
    cs.set_classic_account("a", "url", "id", "secret", "rt", path=path)
    cs.set_central_account("b", "url", "id", "secret", path=path)
    cs.clear_category("a", "central", path=path)
    assert cs.get_central_account("a", path=path) is None
    assert cs.get_classic_account("a", path=path) is not None
    assert cs.get_central_account("b", path=path) is not None


def test_clear_category_noop_when_never_set(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.clear_category("acct", "central", path=path)
    assert not path.exists()


def test_clear_all(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("acct", "url", "id", "secret", path=path)
    cs.set_ap_ssh_credential("acct", "u", "p", path=path)
    cs.clear_all(path=path)
    assert cs.load(path) == {"accounts": {}}


def test_save_leaves_no_temp_file(tmp_path: Path):
    path = tmp_path / "token.yaml"
    cs.set_central_account("acct", "url", "id", "secret", path=path)
    assert [p.name for p in tmp_path.iterdir()] == ["token.yaml"]


# --- legacy credentials.json migration -----------------------------------------


def _write_legacy(path: Path) -> None:
    path.write_text(json.dumps({
        "central": {"acct": {"base_url": "https://nc", "client_id": "cid", "client_secret": "cs"}},
        "classic": {"acct": {"base_url": "https://ag", "client_id": "acid", "client_secret": "acs",
                             "refresh_token": "rt"}},
        "ap_ssh": {"acct": {"username": "admin", "password": "pw"}},
        "uxi": {"application_id": "uxi-1", "region": "us-west"},
    }), encoding="utf-8")


def test_migrate_legacy_json_merges_categories_by_account(tmp_path: Path):
    legacy = tmp_path / "credentials.json"
    path = tmp_path / "token.yaml"
    _write_legacy(legacy)
    assert cs.migrate_legacy_json(legacy, path) == ["acct"]
    assert cs.get_active_account(path=path) == "acct"
    assert cs.get_central_account("acct", path=path)["client_id"] == "cid"
    assert cs.get_classic_account("acct", path=path)["refresh_token"] == "rt"
    assert cs.get_ap_ssh_credential("acct", path=path) == {"username": "admin", "password": "pw"}
    assert cs.get_uxi_application("acct", path=path) == {"application_id": "uxi-1", "region": "us-west"}
    assert legacy.exists()  # left in place, untouched


def test_migrate_legacy_json_noop_when_token_yaml_exists(tmp_path: Path):
    legacy = tmp_path / "credentials.json"
    path = tmp_path / "token.yaml"
    _write_legacy(legacy)
    cs.add_account("other", path=path)
    assert cs.migrate_legacy_json(legacy, path) == []
    assert cs.list_accounts(path=path) == ["other"]


def test_migrate_legacy_json_noop_without_legacy_file(tmp_path: Path):
    path = tmp_path / "token.yaml"
    assert cs.migrate_legacy_json(tmp_path / "credentials.json", path) == []
    assert not path.exists()


def test_no_ssh_category_exists():
    """This tool has no controller/conductor SSH concept - unlike the
    sibling AOS8-to-AOS10 Conversion Tool project, there's deliberately
    no set_ssh_account/get_ssh_account here."""
    assert not hasattr(cs, "set_ssh_account")
    assert not hasattr(cs, "get_ssh_account")
