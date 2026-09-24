"""Local, git-ignored, multi-account credential storage - a token.yaml
in the same shape the user's sibling aruba_central project uses, so an
account block can be copied between the two files as-is:

    accounts:
      customer_A:
        base_url: https://us4.api.central.arubanetworks.com   # New Central
        client_id: ...                                         # (also GLCP)
        client_secret: ...
        apigw_base_url: https://apigw-uswest4.central.arubanetworks.com  # Classic
        apigw_client_id: ...
        apigw_client_secret: ...
        apigw_refresh_token: ...
        uxi_application_id: ...        # optional, this tool only
        uxi_region: ...                # optional, this tool only
      home:
        ...
    default: customer_A

`default` is the ACTIVE account - every API call this tool makes uses
it, and the GUI's account dropdown changes it. Every key within an
account is optional; a New-Central-only account simply has no apigw_*
keys.

One account = one customer/tenant, holding all three credential kinds
this tool needs: New Central/GLCP (client_credentials grant, no
rotating token), Classic Central (refresh_token grant - the refresh
token rotates on every use, so update_classic_refresh_token writes the
new one straight back, or the *next* run breaks), and the UXI
application_id (not a credential - GLCP needs to know which application
to attach a UXI sensor to; per-account because it's per-workspace).
ap_ssh_* keys are stored for possible future use, nothing reads them.

Lives at token.yaml right next to the app (project root in a dev
checkout, next to the .exe in a frozen build - see default_path).
/token.yaml is .gitignore'd; OneDrive sync of this directory is an
accepted tradeoff. Rewrites go through yaml.safe_dump, so comments in a
hand-edited file are NOT preserved (same as aruba_central's own
refresh-token write-back). Plaintext, not keyring-backed - personal,
single-operator tool.

Replaces the old credentials.json store (one account per category,
"first one wins") - migrate_legacy_json carries an existing file over
once, on first run."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

FILENAME = "token.yaml"
LEGACY_FILENAME = "credentials.json"

# Per-category key names within one account block. "central" and
# "classic" names match aruba_central's token.yaml exactly.
_CENTRAL_KEYS = {"base_url": "base_url", "client_id": "client_id", "client_secret": "client_secret"}
_CLASSIC_KEYS = {
    "base_url": "apigw_base_url",
    "client_id": "apigw_client_id",
    "client_secret": "apigw_client_secret",
    "refresh_token": "apigw_refresh_token",
}
_UXI_KEYS = {"application_id": "uxi_application_id", "region": "uxi_region"}
_AP_SSH_KEYS = {"username": "ap_ssh_username", "password": "ap_ssh_password", "ap_ip": "ap_ip"}

CATEGORY_KEYS = {
    "central": _CENTRAL_KEYS,
    "classic": _CLASSIC_KEYS,
    "uxi": _UXI_KEYS,
    "ap_ssh": _AP_SSH_KEYS,
}


def _app_dir() -> Path:
    """In a dev checkout that's the project root. In a frozen PyInstaller
    onedir build, __file__ resolves inside the bundle's _internal folder,
    which an app update can replace wholesale - sys.executable's own
    directory (the dist folder holding the .exe) is the stable
    equivalent."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def default_path() -> Path:
    return _app_dir() / FILENAME


def legacy_path() -> Path:
    return _app_dir() / LEGACY_FILENAME


# --- raw file I/O -----------------------------------------------------------

def load(path: Path | None = None) -> dict:
    """The whole file, normalized to always have an `accounts` dict.
    {"accounts": {}} for a missing or empty file."""
    path = path or default_path()
    if not path.exists():
        return {"accounts": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping.")
    accounts = data.get("accounts") or {}
    data["accounts"] = {str(name): (entry or {}) for name, entry in accounts.items()}
    return data


def save(data: dict, path: Path | None = None) -> None:
    """Write-to-temp-then-replace, so a crash mid-write can't leave a
    half-written file behind - matters more than usual here, since a
    lost Classic refresh token can't be recovered without regenerating
    it in the Central UI."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding="utf-8")
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # best-effort - Windows ACLs don't honor this anyway


# --- accounts ---------------------------------------------------------------

def list_accounts(path: Path | None = None) -> list[str]:
    return list(load(path)["accounts"])


def get_active_account(path: Path | None = None) -> str | None:
    """`default` if it names a real account, else the first account in
    the file, else None."""
    data = load(path)
    accounts = data["accounts"]
    default = data.get("default")
    if default in accounts:
        return default
    return next(iter(accounts), None)


def set_active_account(account: str, path: Path | None = None) -> None:
    data = load(path)
    if account not in data["accounts"]:
        raise KeyError(account)
    data["default"] = account
    save(data, path)


def get_account(account: str, path: Path | None = None) -> dict | None:
    return load(path)["accounts"].get(account)


def add_account(account: str, path: Path | None = None) -> None:
    """Creates an empty account block (a no-op if it already exists) and
    makes it the active one."""
    data = load(path)
    data["accounts"].setdefault(account, {})
    data["default"] = account
    save(data, path)


def delete_account(account: str, path: Path | None = None) -> None:
    """Removes one whole account. If it was the active one, `default`
    moves to the first remaining account (or is dropped if none)."""
    data = load(path)
    if account not in data["accounts"]:
        return
    del data["accounts"][account]
    if data.get("default") == account:
        remaining = next(iter(data["accounts"]), None)
        if remaining is None:
            data.pop("default", None)
        else:
            data["default"] = remaining
    save(data, path)


def _update_account(account: str, values: dict, path: Path | None) -> None:
    """Merges values into one account (creating it if needed); a None
    value removes that key. Makes the account active if no account was
    active yet, so a first save on a fresh install just works."""
    data = load(path)
    entry = data["accounts"].setdefault(account, {})
    for key, value in values.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    if data.get("default") not in data["accounts"]:
        data["default"] = account
    save(data, path)


def _get_category(account: str, category: str, path: Path | None) -> dict | None:
    """One category's values out of an account, under this tool's own
    field names (base_url, refresh_token, ...). None unless every
    required key is present."""
    entry = get_account(account, path)
    if entry is None:
        return None
    mapping = CATEGORY_KEYS[category]
    values = {field: entry.get(key) for field, key in mapping.items()}
    required = {
        "central": ("base_url", "client_id", "client_secret"),
        "classic": ("base_url", "client_id", "client_secret", "refresh_token"),
        "uxi": ("application_id",),
        "ap_ssh": (),
    }[category]
    if not all(values[f] for f in required):
        return None
    if category == "ap_ssh":
        values = {k: v for k, v in values.items() if v is not None}
        return values or None
    return values


def clear_category(account: str, category: str, path: Path | None = None) -> None:
    """Removes one category's keys from one account - the account itself
    (and its other categories) stays. A no-op if not present."""
    data = load(path)
    entry = data["accounts"].get(account)
    if entry is None:
        return
    for key in CATEGORY_KEYS[category].values():
        entry.pop(key, None)
    save(data, path)


def clear_all(path: Path | None = None) -> None:
    """Removes every account. A no-op if the file doesn't exist yet."""
    path = path or default_path()
    if path.exists():
        save({"accounts": {}}, path)


# --- per-category get/set ----------------------------------------------------

def get_central_account(account: str, path: Path | None = None) -> dict | None:
    return _get_category(account, "central", path)


def set_central_account(
    account: str, base_url: str, client_id: str, client_secret: str, path: Path | None = None
) -> None:
    """New Central's client_credentials grant re-authenticates from
    client_id/client_secret whenever the cached token expires - no
    rotating token to persist."""
    _update_account(account, {"base_url": base_url, "client_id": client_id, "client_secret": client_secret}, path)


def get_classic_account(account: str, path: Path | None = None) -> dict | None:
    return _get_category(account, "classic", path)


def set_classic_account(
    account: str,
    base_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    path: Path | None = None,
) -> None:
    _update_account(account, {
        "apigw_base_url": base_url,
        "apigw_client_id": client_id,
        "apigw_client_secret": client_secret,
        "apigw_refresh_token": refresh_token,
    }, path)


def update_classic_refresh_token(
    account: str, new_refresh_token: str, path: Path | None = None
) -> None:
    """Called by ClassicTokenManager's on_refresh_token_rotated callback.
    A no-op if the account has no Classic credentials - nothing to
    update."""
    data = load(path)
    entry = data["accounts"].get(account)
    if entry is None or "apigw_refresh_token" not in entry:
        return
    entry["apigw_refresh_token"] = new_refresh_token
    save(data, path)


def get_ap_ssh_credential(account: str, path: Path | None = None) -> dict | None:
    """None (never stored), a dict with only "ap_ip" (credentials
    excluded from the file), or a dict with username/password (and
    optionally ap_ip)."""
    return _get_category(account, "ap_ssh", path)


def set_ap_ssh_credential(
    account: str, username: str | None = None, password: str | None = None,
    ap_ip: str | None = None, path: Path | None = None,
) -> None:
    """Credential for SSHing directly into a device - no feature in this
    tool calls this yet. A call fully overwrites the account's ap_ssh
    values - omitted ones are removed, not kept."""
    _update_account(account, {"ap_ssh_username": username, "ap_ssh_password": password, "ap_ip": ap_ip}, path)


def get_uxi_application(account: str, path: Path | None = None) -> dict | None:
    """{"application_id", "region"} for the account's GreenLake
    workspace, or None if not set."""
    return _get_category(account, "uxi", path)


def set_uxi_application(
    account: str, application_id: str, region: str | None = None, path: Path | None = None
) -> None:
    _update_account(account, {"uxi_application_id": application_id, "uxi_region": region}, path)


# --- one-time migration from credentials.json ---------------------------------

def migrate_legacy_json(json_path: Path | None = None, path: Path | None = None) -> list[str]:
    """If token.yaml doesn't exist yet but the old credentials.json does,
    carries every stored account over (matched by account name across
    the old central/classic/ap_ssh categories). The old workspace-wide
    UXI application_id goes onto every migrated account that has
    New Central credentials. Returns the migrated account names ([] if
    nothing to do). credentials.json itself is left in place, untouched
    - the caller tells the user it can be deleted."""
    json_path = json_path or legacy_path()
    path = path or default_path()
    if path.exists() or not json_path.exists():
        return []
    old = json.loads(json_path.read_text(encoding="utf-8"))

    accounts: dict[str, dict] = {}
    for name, e in (old.get("central") or {}).items():
        accounts.setdefault(name, {}).update(
            base_url=e.get("base_url"), client_id=e.get("client_id"), client_secret=e.get("client_secret")
        )
    for name, e in (old.get("classic") or {}).items():
        accounts.setdefault(name, {}).update(
            apigw_base_url=e.get("base_url"), apigw_client_id=e.get("client_id"),
            apigw_client_secret=e.get("client_secret"), apigw_refresh_token=e.get("refresh_token"),
        )
    for name, e in (old.get("ap_ssh") or {}).items():
        accounts.setdefault(name, {}).update(
            {_AP_SSH_KEYS[k]: v for k, v in e.items() if k in _AP_SSH_KEYS}
        )
    uxi = old.get("uxi")
    if uxi and uxi.get("application_id"):
        for entry in accounts.values():
            if entry.get("client_id"):
                entry["uxi_application_id"] = uxi["application_id"]
                if uxi.get("region"):
                    entry["uxi_region"] = uxi["region"]
    if not accounts:
        return []

    data: dict = {"accounts": {n: {k: v for k, v in e.items() if v is not None} for n, e in accounts.items()}}
    data["default"] = next(iter(data["accounts"]))
    save(data, path)
    return list(data["accounts"])
