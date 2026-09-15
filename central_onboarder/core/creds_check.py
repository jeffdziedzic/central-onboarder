"""Cheapest real check per stored credential category, plus the "where
do you get this" guidance text shown before/while entering each
category. Ported from the sibling AOS8-to-AOS10 Conversion Tool
project's own creds_check.py, trimmed to the `central`/`classic`
categories this tool actively tests (ap_ssh isn't wired to any feature
here - see credential_store.py - so no connection-test exists for it
yet)."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from . import central, central_classic


def normalize_base_url(base_url: str) -> str:
    """The Central UI's REST API tab shows just the host (e.g.
    apigw-uswest4.central.arubanetworks.com) - a missing scheme fails
    with an opaque requests.exceptions.MissingSchema later. Catch it
    here instead, at the one place a human is typing/pasting this in."""
    if not base_url.startswith(("http://", "https://")):
        return f"https://{base_url}"
    return base_url


HINTS = {
    "central": (
        "Create your API Client in GreenLake Portal (not New Central UI)\n"
        "Manage Workspace -> Personal API Gateway -> Create personal API client\n"
        "Provide a name and select your Central instance\n"
        "Copy your Client ID and Secret. Note that your secret won't be visible again\n"
        "\n"
        "Find your Base URL in New Central\n"
        "Hamburger Menu in top left -> API Gateway -> Manage\n"
        "Base URL will be at the top of the screen in the middle\n"
        "\n"
        "This same account is also used for GLCP device/subscription calls -\n"
        "no separate GLCP credential is needed."
    ),
    "classic": (
        "In the Classic Central UI create the REST API Client\n"
        "Global -> Organization -> Platform Integration tab -> My Apps & Tokens\n"
        "Click Add Apps & Tokens and click Generate. Client ID and Client Secret can be copied\n"
        "To get the refresh token Click Download Token. It can be found in the pop-up\n"
        "\n"
        "Find your Base URL in Classic Central\n"
        "Global -> Organization -> Platform Integration tab -> APIs\n"
        "The Base URL is the documentation link without /swagger/nms.\n"
        "Example: https://app1-apigw.central.arubanetworks.com"
    ),
    "ap_ssh": (
        "This is the admin password configured in New Central for the User Administration "
        "Profile\n"
        "Library -> System -> User Administration\n"
        "\n"
        "Not used by any action in this tool yet - stored for possible future use."
    ),
}


@dataclass
class CredentialTestResult:
    category: str  # "central" | "classic"
    key: str  # account name
    ok: bool
    detail: str


def test_central_account(entry: dict) -> tuple[bool, str]:
    """Cheapest real check: fetch an OAuth token (client_credentials). A
    successful token fetch also validates GreenLake/GLP auth - both go
    through the same TOKEN_URL/grant."""
    tm = central.TokenManager(entry["client_id"], entry["client_secret"])
    try:
        tm.get_token()
    except (central.CentralAuthError, requests.exceptions.RequestException) as exc:
        return False, str(exc)
    return True, "authenticated (also covers GreenLake/GLP - same OAuth grant)"


def test_classic_account(account: str, entry: dict, path=None) -> tuple[bool, str]:
    """Classic Central's refresh_token rotates on every use - wires
    on_refresh_token_rotated so testing doesn't silently strand the
    stored token."""
    from . import credential_store

    tm = central_classic.ClassicTokenManager(
        entry["base_url"], entry["client_id"], entry["client_secret"], entry["refresh_token"],
        on_refresh_token_rotated=lambda new_rt: credential_store.update_classic_refresh_token(
            account, new_rt, path
        ),
    )
    try:
        tm.get_token()
    except (central_classic.ClassicAuthError, requests.exceptions.RequestException) as exc:
        return False, str(exc)
    return True, "authenticated"


def test_all(data: dict, path=None) -> list[CredentialTestResult]:
    """data is credential_store.load()'s own shape - caller loads it
    (and passes the same `path` it loaded from, for update_classic_
    refresh_token's benefit)."""
    results: list[CredentialTestResult] = []

    for account in sorted(data.get("central", {})):
        ok, detail = test_central_account(data["central"][account])
        results.append(CredentialTestResult("central", account, ok, detail))

    for account in sorted(data.get("classic", {})):
        ok, detail = test_classic_account(account, data["classic"][account], path)
        results.append(CredentialTestResult("classic", account, ok, detail))

    return results
