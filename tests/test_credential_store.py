from pathlib import Path

from central_onboarder.core import credential_store as cs


def test_load_missing_file_returns_empty_dict(tmp_path: Path):
    assert cs.load(tmp_path / "does-not-exist.json") == {}


def test_set_and_get_central_account(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_central_account("acct", "https://us1.api.central.arubanetworks.com", "cid", "csecret", path=path)
    entry = cs.get_central_account("acct", path=path)
    assert entry == {
        "base_url": "https://us1.api.central.arubanetworks.com",
        "client_id": "cid",
        "client_secret": "csecret",
    }


def test_get_central_account_missing_returns_none(tmp_path: Path):
    assert cs.get_central_account("nope", path=tmp_path / "credentials.json") is None


def test_central_and_classic_accounts_are_independent(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_central_account("acct", "url-new", "cid-new", "secret-new", path=path)
    cs.set_classic_account("acct", "url-classic", "cid-classic", "secret-classic", "rt", path=path)
    assert cs.get_central_account("acct", path=path)["base_url"] == "url-new"
    assert cs.get_classic_account("acct", path=path)["base_url"] == "url-classic"


def test_update_classic_refresh_token_rotates_existing_entry(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_classic_account("acct", "url", "id", "secret", "rt-old", path=path)
    cs.update_classic_refresh_token("acct", "rt-new", path=path)
    entry = cs.get_classic_account("acct", path=path)
    assert entry["refresh_token"] == "rt-new"
    assert entry["client_id"] == "id"


def test_update_classic_refresh_token_noop_when_account_not_stored(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.update_classic_refresh_token("never-stored", "rt-new", path=path)
    assert not path.exists()


def test_set_and_get_ap_ssh_credential(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_ap_ssh_credential("acct", "admin", "hunter2", ap_ip="192.0.2.1", path=path)
    entry = cs.get_ap_ssh_credential("acct", path=path)
    assert entry == {"username": "admin", "password": "hunter2", "ap_ip": "192.0.2.1"}


def test_set_ap_ssh_credential_excludes_creds_when_omitted(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_ap_ssh_credential("acct", ap_ip="192.0.2.1", path=path)
    entry = cs.get_ap_ssh_credential("acct", path=path)
    assert entry == {"ap_ip": "192.0.2.1"}


def test_clear_category_removes_only_that_category(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_central_account("acct", "url", "id", "secret", path=path)
    cs.set_classic_account("acct", "url", "id", "secret", "rt", path=path)
    cs.clear_category("central", path=path)
    assert cs.get_central_account("acct", path=path) is None
    assert cs.get_classic_account("acct", path=path) is not None


def test_clear_category_noop_when_never_set(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.clear_category("central", path=path)
    assert not path.exists()


def test_clear_all(tmp_path: Path):
    path = tmp_path / "credentials.json"
    cs.set_central_account("acct", "url", "id", "secret", path=path)
    cs.set_ap_ssh_credential("acct", "u", "p", path=path)
    cs.clear_all(path=path)
    assert cs.load(path) == {}


def test_no_ssh_category_exists():
    """This tool has no controller/conductor SSH concept - unlike the
    sibling AOS8-to-AOS10 Conversion Tool project, there's deliberately
    no set_ssh_account/get_ssh_account here."""
    assert not hasattr(cs, "set_ssh_account")
    assert not hasattr(cs, "get_ssh_account")
