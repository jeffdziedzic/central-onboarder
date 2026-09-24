"""HPE Aruba "Classic" Central API client - device pre-provisioning and
site association.

core/central.py talks to *New* Central and GLCP (OAuth2 client_credentials
against HPE SSO). This talks to *Classic* Central, a genuinely different
API surface: different base paths (configuration/v1, central/v2 - not
network-config/network-monitoring) and a different OAuth grant
(refresh_token against this tenant's own Classic Central API Gateway
app, Global > Organization > Platform Integration tab > REST API > My
Apps & Tokens - NOT New Central's client_credentials/GLP SSO).

Ported from the sibling AOS8-to-AOS10 Conversion Tool project's own
core/central_classic.py, unchanged - see that module's own docstring
for the live-confirmed detail (dates, tenants, real serials) this was
built against. Two operations:

  - device pre-provisioning/group assignment: assigning a device's
    serial to a group, whether or not it's connected yet - POST
    /configuration/v1/devices/move. If not yet connected, this is
    pre-provisioning ("fork into the right group automatically on
    check-in"); if already connected/grouped, the same call moves it to
    the target group (per Aruba's own current API reference - both
    cases are the same endpoint). Max 50 serials/call, enforced here
    client-side.
  - site association: assigning a device's serial to a Central site -
    POST /central/v2/sites/associations, resolving the site name to
    Classic Central's own numeric site_id via GET /central/v2/sites
    first (a different ID space from New Central's site IDs -
    core/central.py's list_sites).
  - post-onboarding status: GET /monitoring/v1/aps/{serial} - a
    not-yet-checked-in serial 404s; once seen, status is "Up"/"Down",
    matching Central's own UI (Online/Offline).

Auth/call pattern ported from the sibling project's own
ClassicTokenManager/ClassicCentralClient (not imported - this tool
stands alone). That pattern was exercised regularly there against a
real Classic Central tenant; a customer tenant's own API Gateway app/
refresh token would need to be issued separately to run this against a
customer tenant for real.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

_EXPIRY_BUFFER = 60  # refresh this many seconds before actual expiry
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF = 2.0  # seconds, doubled each attempt

_MAX_PREPROVISION_SERIALS_PER_CALL = 50  # documented cap, see module docstring

# Device types accepted by the pre-provisioning and site-association APIs.
DEVICE_TYPE_AP = "IAP"
DEVICE_TYPE_SWITCH = "SWITCH"
DEVICE_TYPE_CONTROLLER = "CONTROLLER"
DEVICE_TYPE_GATEWAY = "GATEWAY"  # confirmed by user 2026-09-15, not a CONTROLLER-class guess


class ClassicAuthError(Exception):
    """Authentication/authorization failure. Never retried; the caller
    should stop and prompt for re-entry."""


class ClassicAPIError(Exception):
    """An API call failed after retries, or returned something the client
    can't make sense of. Carries the raw response for troubleshooting."""

    def __init__(self, message: str, status: int | None = None, body: object = None):
        super().__init__(message)
        self.status = status
        self.body = body


class ClassicTokenManager:
    """OAuth2 refresh_token grant against a Classic Central API Gateway
    app. Unlike New Central's client_credentials grant, the refresh
    token itself can rotate on use; pass on_refresh_token_rotated to
    persist a new one somewhere durable. This class doesn't persist
    anything itself."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        on_refresh_token_rotated=None,
    ):
        self.token_url = f"{base_url.rstrip('/')}/oauth2/token"
        self.client_id = client_id
        self.client_secret = client_secret
        self._refresh_token = refresh_token
        self._on_rotated = on_refresh_token_rotated
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._session = requests.Session()

    def get_token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        resp = self._session.post(
            self.token_url,
            params={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
            },
            timeout=60,
        )
        if resp.status_code != 200:
            raise ClassicAuthError(
                f"Classic Central token refresh failed (HTTP {resp.status_code})"
            )
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        self._expires_at = time.monotonic() + expires_in - _EXPIRY_BUFFER
        new_rt = data.get("refresh_token")
        if new_rt and new_rt != self._refresh_token:
            self._refresh_token = new_rt
            if self._on_rotated:
                self._on_rotated(new_rt)
        return self._access_token

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0


class ClassicCentralClient:
    def __init__(self, base_url: str, token_manager: ClassicTokenManager, transcript=None):
        """transcript is an optional core/transcript.py Transcript
        (default None - no change to existing behavior)."""
        self.base_url = base_url.rstrip("/")
        self._tm = token_manager
        self._session = requests.Session()
        self._transcript = transcript

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._call("GET", path, params=params)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._call("POST", path, body=body)

    def delete(self, path: str, body: dict | None = None) -> dict:
        return self._call("DELETE", path, body=body)

    def _call(self, method: str, path: str, params=None, body=None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        command = f"{method} {path}"

        def record(outcome: object) -> None:
            if self._transcript is not None:
                self._transcript.record(self.base_url, command, outcome)

        last_exc: Exception | None = None
        for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
            if attempt:
                time.sleep(_TRANSIENT_RETRY_BACKOFF * (2 ** (attempt - 1)))
            headers = {
                "Authorization": f"Bearer {self._tm.get_token()}",
                "Content-Type": "application/json",
            }
            try:
                resp = self._session.request(
                    method, url, headers=headers, params=params, json=body, timeout=60
                )
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                continue

            if resp.status_code == 401:
                self._tm.invalidate()
                headers["Authorization"] = f"Bearer {self._tm.get_token()}"
                resp = self._session.request(
                    method, url, headers=headers, params=params, json=body, timeout=60
                )
            if resp.status_code in (401, 403):
                record({"status": resp.status_code, "error": resp.text})
                raise ClassicAuthError(
                    f"{method} {path} refused (HTTP {resp.status_code}) - "
                    "check credentials/scope for this account"
                )
            if resp.status_code >= 500:
                record({"status": resp.status_code, "error": resp.text})
                last_exc = ClassicAPIError(
                    f"{method} {path} failed (HTTP {resp.status_code})", resp.status_code, resp.text
                )
                continue

            try:
                data = resp.json() if resp.content else {}
            except ValueError as exc:
                record({"status": resp.status_code, "error": resp.text})
                raise ClassicAPIError(
                    f"{method} {path} returned unparseable JSON (HTTP {resp.status_code})",
                    resp.status_code, resp.text,
                ) from exc
            if resp.status_code >= 400:
                record({"status": resp.status_code, "error": data})
                raise ClassicAPIError(
                    f"{method} {path} failed (HTTP {resp.status_code}): {data}",
                    resp.status_code, data,
                )
            record({"status": resp.status_code, "body": data})
            return {"status": resp.status_code, "body": data}

        record({"error": f"failed after {_TRANSIENT_RETRY_ATTEMPTS} attempt(s): {last_exc}"})
        raise ClassicAPIError(f"{method} {path} failed after {_TRANSIENT_RETRY_ATTEMPTS} attempts") from last_exc


def preprovision_device_to_group(
    client: ClassicCentralClient, group: str, serials: list[str]
) -> dict:
    """Pre-provision devices to a group ahead of check-in - AND, per
    Aruba's own current API reference, the same call also moves an
    ALREADY-connected/already-grouped device to `group` - not
    pre-provisioning-only despite the name. Raises ValueError before
    calling out if serials exceeds the documented 50-per-call cap."""
    if len(serials) > _MAX_PREPROVISION_SERIALS_PER_CALL:
        raise ValueError(
            f"max {_MAX_PREPROVISION_SERIALS_PER_CALL} serials per call, got {len(serials)}"
        )
    result = client.post("configuration/v1/devices/move", body={"group": group, "serials": serials})
    return result["body"]


def get_device_group(client: ClassicCentralClient, serial: str) -> str | None:
    """Current group assignment for one serial. No bulk "list everything
    pre-provisioned" endpoint exists in Aruba's public API - checking a
    whole batch means one call per serial, not one call for the batch."""
    result = client.get(f"configuration/v1/devices/{serial}/group")
    return result["body"].get("group") or None


@dataclass
class APStatus:
    serial: str
    seen: bool
    status: str | None = None
    group_name: str | None = None
    site_name: str | None = None
    firmware_version: str | None = None
    down_reason: str | None = None
    ip_address: str | None = None
    raw: dict = field(default_factory=dict, repr=False)
    device_type: str | None = None  # "AP" / "Switch" / "Gateway" - which endpoint answered


# Classic Central's per-device monitoring endpoints are type-specific -
# an AP serial 404s on the switch endpoint and vice versa, so a
# switch/gateway looked up only via monitoring/v1/aps always looks
# "not seen" even when it's Up (found live 2026-09-24: a 6100 switch
# and a 70xx gateway both came back not-seen from the AP-only lookup).
_STATUS_ENDPOINTS = {
    "AP": "monitoring/v1/aps",
    "Switch": "monitoring/v1/switches",
    "Gateway": "monitoring/v1/gateways",
}


def get_device_status(
    client: ClassicCentralClient, serial: str, device_type_hint: str | None = None
) -> APStatus:
    """Status for a serial of ANY device type - tries the AP, switch
    and gateway monitoring endpoints in turn (the hinted type first,
    if given, to save calls) and returns the first that knows the
    serial. seen=False only if all three 404. Any non-404 failure
    propagates.

    AP responses carry the site as `site_name` (live-confirmed);
    switch/gateway responses are read from `site_name` or `site`,
    whichever is present - which one they use is not yet confirmed."""
    order = list(_STATUS_ENDPOINTS)
    if device_type_hint in _STATUS_ENDPOINTS:
        order.remove(device_type_hint)
        order.insert(0, device_type_hint)
    for device_type in order:
        try:
            result = client.get(f"{_STATUS_ENDPOINTS[device_type]}/{serial}")
        except ClassicAPIError as exc:
            if exc.status == 404:
                continue
            raise
        body = result["body"] or {}
        return APStatus(
            serial=serial,
            seen=True,
            status=body.get("status"),
            group_name=body.get("group_name"),
            site_name=body.get("site_name") or body.get("site"),
            firmware_version=body.get("firmware_version"),
            down_reason=body.get("down_reason"),
            ip_address=body.get("ip_address"),
            raw=body,
            device_type=device_type,
        )
    return APStatus(serial=serial, seen=False)


def get_ap_status(client: ClassicCentralClient, serial: str) -> APStatus:
    """GET monitoring/v1/aps/{serial}. A 404 means seen=False (not
    onboarded / never checked in) - not an error, that's the expected
    state for every device before it connects. Any other failure
    propagates.

    site_name is None until a site has actually been assigned for this
    device (see associate_devices_to_site below)."""
    try:
        result = client.get(f"monitoring/v1/aps/{serial}")
    except ClassicAPIError as exc:
        if exc.status == 404:
            return APStatus(serial=serial, seen=False)
        raise
    body = result["body"]
    return APStatus(
        serial=serial,
        seen=True,
        status=body.get("status"),
        group_name=body.get("group_name"),
        site_name=body.get("site_name"),
        firmware_version=body.get("firmware_version"),
        down_reason=body.get("down_reason"),
        ip_address=body.get("ip_address"),
        raw=body,
    )


def list_sites(client: ClassicCentralClient) -> dict[str, int]:
    """Site name -> Classic Central's own numeric site_id (GET
    /central/v2/sites) - a different ID space from New Central's site
    IDs (core/central.py's list_sites), needed because
    associate_devices_to_site takes this numeric ID, not New Central's.
    Offset-paginated (no "next" cursor field) - stop once a page comes
    back short of the page size."""
    sites: dict[str, int] = {}
    offset = 0
    limit = 100
    while True:
        result = client.get("central/v2/sites", params={"offset": offset, "limit": limit})
        body = result["body"]
        page = body.get("sites", [])
        for item in page:
            name = item.get("site_name")
            site_id = item.get("site_id")
            if name and site_id is not None:
                sites[name] = site_id
        offset += len(page)
        total = body.get("total")
        if not page or len(page) < limit or (total is not None and offset >= total):
            return sites


def associate_devices_to_site(
    client: ClassicCentralClient, site_id: int, device_type: str, serials: list[str]
) -> dict:
    """Assign device(s) to a Central site - device_type is one of
    DEVICE_TYPE_AP/SWITCH/CONTROLLER/GATEWAY."""
    result = client.post(
        "central/v2/sites/associations",
        body={"site_id": site_id, "device_type": device_type, "device_ids": serials},
    )
    return result["body"]
