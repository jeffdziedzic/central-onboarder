"""Local, git-ignored credential storage for values that need to survive
across GUI sessions - specifically Classic Central's refresh_token,
which rotates on every use (core/central_classic.py) - a stale one left
unpersisted breaks the *next* run, not just this one.

Lives at credentials.json right next to this project (resolved relative
to this module's own location, not a hardcoded path, so it stays correct
regardless of where a given user's checkout lives) - same convention the
sibling AOS8-to-AOS10 Conversion Tool project uses for its own
credentials.json. Each user who runs this tool gets their own checkout
with their own credentials.json resident right there - not tucked away
under a home-directory dotfile. /credentials.json is .gitignore'd;
OneDrive sync of this directory is an accepted tradeoff, not something
this module tries to route around.

Three categories: `central` (New Central + GLCP OAuth, client_credentials
grant - no rotating token to persist, and reused for GLCP calls too, see
core/central.py's module docstring), `classic` (Classic Central OAuth,
refresh_token grant - needed for group pre-provisioning and site
association), `ap_ssh` (fleet-wide admin credential for SSHing directly
into a device - not wired to any feature yet in this tool, kept for
possible future use). Deliberately does NOT carry the sibling project's
`ssh` category (host-keyed controller/Mobility-Conductor credential) -
this tool has no controller/conductor concept.

Plaintext JSON, not OS-keyring-backed - matches the sibling project's
precedent, and this is a personal/unofficial single-operator tool, not
something with a security review budget for keyring integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_path() -> Path:
    """credentials.json sits right next to the app. In a dev checkout
    that's the project root. In a frozen PyInstaller onedir build,
    __file__ instead resolves inside the bundle's _internal folder,
    which an app update can legitimately replace/regenerate wholesale -
    sys.executable's own directory (the real dist folder holding the
    .exe, sitting next to _internal, not inside it) is the stable
    equivalent - same pattern proven live by the sibling conversion
    project's own credential_store.py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "credentials.json"
    return _PROJECT_ROOT / "credentials.json"


def load(path: Path | None = None) -> dict:
    path = path or default_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(data: dict, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # best-effort - Windows ACLs don't honor this anyway


def clear_category(category: str, path: Path | None = None) -> None:
    """Removes one whole credential category (every stored account under
    it). A no-op, not an error, if that category was already empty or
    never set."""
    data = load(path)
    if category in data:
        del data[category]
        save(data, path)


def clear_all(path: Path | None = None) -> None:
    """Removes every stored credential across every category. A no-op if
    credentials.json doesn't exist yet."""
    save({}, path)


def get_central_account(account: str, path: Path | None = None) -> dict | None:
    return load(path).get("central", {}).get(account)


def set_central_account(
    account: str, base_url: str, client_id: str, client_secret: str, path: Path | None = None
) -> None:
    """New Central's client_credentials grant re-authenticates from
    client_id/client_secret whenever the cached token expires - unlike
    Classic Central, there's no rotating refresh_token to persist."""
    data = load(path)
    data.setdefault("central", {})[account] = {
        "base_url": base_url,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    save(data, path)


def get_classic_account(account: str, path: Path | None = None) -> dict | None:
    return load(path).get("classic", {}).get(account)


def set_classic_account(
    account: str,
    base_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    path: Path | None = None,
) -> None:
    data = load(path)
    data.setdefault("classic", {})[account] = {
        "base_url": base_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    save(data, path)


def update_classic_refresh_token(
    account: str, new_refresh_token: str, path: Path | None = None
) -> None:
    """Called by ClassicTokenManager's on_refresh_token_rotated callback.
    A no-op if the account was never persisted - nothing to update."""
    data = load(path)
    entry = data.get("classic", {}).get(account)
    if entry is None:
        return
    entry["refresh_token"] = new_refresh_token
    save(data, path)


def get_ap_ssh_credential(account: str, path: Path | None = None) -> dict | None:
    """Three possible returns: None (never stored), a dict with only
    "ap_ip" (credentials excluded from the file), or a dict with
    username/password (and optionally ap_ip) for the normal case."""
    return load(path).get("ap_ssh", {}).get(account)


def set_ap_ssh_credential(
    account: str, username: str | None = None, password: str | None = None,
    ap_ip: str | None = None, path: Path | None = None,
) -> None:
    """Credential for SSHing directly into an individual device -
    fleet-wide (or at least per-account), not one entry per device. No
    feature in this tool calls this yet; kept in the store on the
    chance a future SSH-based action needs it, same as the sibling
    conversion project's own ap_ssh category.

    username/password default to None ("exclude credentials from the
    file" checkbox, if this is ever wired into the GUI) - when omitted,
    only ap_ip is persisted. A call always fully overwrites the
    account's entry - pass the values you want to keep, not just the
    ones changing."""
    data = load(path)
    entry: dict[str, str] = {}
    if username is not None:
        entry["username"] = username
    if password is not None:
        entry["password"] = password
    if ap_ip is not None:
        entry["ap_ip"] = ap_ip
    data.setdefault("ap_ssh", {})[account] = entry
    save(data, path)
