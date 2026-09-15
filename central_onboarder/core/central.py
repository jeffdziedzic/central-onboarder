"""HPE Aruba New Central + GreenLake (GLCP) API client.

Standalone OAuth2 client_credentials client - no PyCentral dependency.
Ported from the sibling AOS8-to-AOS10 Conversion Tool project's own
core/central.py (built there against a real Central tenant, endpoints
and body shapes confirmed live - not guessed; see that project's own
docstrings for the original confirmation dates/tenants), trimmed down
to the functions this onboarding tool actually needs: device-group/
site listing, site creation, adding devices to GLCP, subscription
assign/remove, and Central-application (service) assign/unassign.
Conversion-specific functions (client/troubleshooting-command listing,
config-health, firmware-compliance) were left behind - see that
project's own module for those.

One credential set covers both New Central and GLCP - both go through
the same OAuth2 client_credentials grant against HPE's SSO (TOKEN_URL
below); a CentralClient pointed at GLP_BASE_URL instead of a regional
Central base_url is how gui/api.py's _glp_creds reuses the exact same
stored `central` account for GLCP calls, no separate credential
category needed."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

TOKEN_URL = "https://sso.common.cloud.hpe.com/as/token.oauth2"
GLP_BASE_URL = "https://global.api.greenlake.hpe.com"
_EXPIRY_BUFFER = 60  # refresh this many seconds before actual expiry
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF = 2.0  # seconds, doubled each attempt


class CentralAuthError(Exception):
    """Authentication/authorization failure. Never retried; the caller
    should stop and prompt for re-entry."""


class CentralAPIError(Exception):
    """An API call failed after retries, or returned something the client
    can't make sense of. Carries the raw response for troubleshooting."""

    def __init__(self, message: str, status: int | None = None, body: object = None):
        super().__init__(message)
        self.status = status
        self.body = body


class TokenManager:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._expires_at = 0.0
        self._session = requests.Session()

    def get_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        resp = self._session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise CentralAuthError(
                f"HPE GreenLake authentication failed (HTTP {resp.status_code})"
            )
        data = resp.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        self._expires_at = time.monotonic() + expires_in - _EXPIRY_BUFFER
        return self._token

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0


class CentralClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, transcript=None):
        """transcript is an optional core/transcript.py Transcript
        (default None - no change to existing behavior) - every call/
        response this client makes gets recorded via transcript.record(
        base_url, "<METHOD> <path>", <status+body or error detail>) when
        one is given."""
        self.base_url = base_url.rstrip("/")
        self._tm = TokenManager(client_id, client_secret)
        self._session = requests.Session()
        self._transcript = transcript

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._call("GET", path, params=params)

    def patch(self, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        """Never retried on a 5xx/transient network error - a PATCH here
        is a write, and a 5xx or connection error doesn't tell you
        whether the server actually processed the request before
        failing, so retrying could double-submit it."""
        return self._call("PATCH", path, params=params, body=body, retry_on_5xx=False)

    def post(self, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        """Same no-blind-retry-on-a-write rule as patch() above."""
        return self._call("POST", path, params=params, body=body, retry_on_5xx=False)

    def _call(self, method: str, path: str, params=None, body=None, retry_on_5xx: bool = True) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        command = f"{method} {path}"

        def record(outcome: object) -> None:
            if self._transcript is not None:
                self._transcript.record(self.base_url, command, outcome)

        last_exc: Exception | None = None
        attempts = _TRANSIENT_RETRY_ATTEMPTS if retry_on_5xx else 1
        for attempt in range(attempts):
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
                raise CentralAuthError(
                    f"{method} {path} refused (HTTP {resp.status_code}) - "
                    "check credentials/scope for this account"
                )
            if resp.status_code >= 500:
                record({"status": resp.status_code, "error": resp.text})
                last_exc = CentralAPIError(
                    f"{method} {path} failed (HTTP {resp.status_code})", resp.status_code, resp.text
                )
                continue

            try:
                data = resp.json() if resp.content else {}
            except ValueError as exc:
                record({"status": resp.status_code, "error": resp.text})
                raise CentralAPIError(
                    f"{method} {path} returned unparseable JSON (HTTP {resp.status_code})",
                    resp.status_code, resp.text,
                ) from exc
            if resp.status_code >= 400:
                record({"status": resp.status_code, "error": data})
                raise CentralAPIError(
                    f"{method} {path} failed (HTTP {resp.status_code}): {data}",
                    resp.status_code, data,
                )
            record({"status": resp.status_code, "body": data})
            return {"status": resp.status_code, "body": data, "headers": resp.headers}

        record({"error": f"failed after {attempts} attempt(s): {last_exc}"})
        raise CentralAPIError(f"{method} {path} failed after {attempts} attempt(s)") from last_exc


def _paginate(client: CentralClient, path: str, params: dict, limit: int = 100, cursor_param: str = "offset"):
    """Handles the pagination shapes seen across Central/GLP endpoints,
    ported from the sibling conversion project's own central.py (see
    that module's docstring for the live-confirmed detail this was
    built against): New Central's "next" cursor as a real numeric
    offset, GLP's items/count/offset/total with no "next" at all
    (falls back to offset-by-items-fetched-so-far), and a page-number
    "next" some endpoints use instead (pass cursor_param="next" for
    those - default stays "offset" for everything else)."""
    cursor = None
    fetched = 0
    while True:
        page_params = {**params, "limit": limit}
        if cursor is not None:
            page_params[cursor_param] = cursor
        result = client.get(path, params=page_params)
        body = result["body"]
        items = body.get("items", body.get("devices", []))
        yield from items
        fetched += len(items)
        total = body.get("total")
        if not items:
            return
        if total is not None and fetched >= total:
            return
        nxt = body.get("next")
        if nxt is not None:
            cursor = int(nxt) if cursor_param == "offset" else nxt
        elif total is not None:
            cursor = fetched
        else:
            return


def list_device_groups(client: CentralClient) -> dict[str, str]:
    """Group name -> scope ID, independent of whether any device is
    assigned yet - covers the common case where the target group exists
    and is configured but has zero members so far."""
    groups: dict[str, str] = {}
    for item in _paginate(client, "network-config/v1alpha1/device-groups", {}):
        name = item.get("scopeName")
        scope_id = item.get("scopeId") or item.get("id")
        if name and scope_id:
            groups[name] = scope_id
    return groups


def list_sites(client: CentralClient) -> dict[str, str]:
    """Site name -> ID, from New Central."""
    sites: dict[str, str] = {}
    for item in _paginate(client, "network-monitoring/v1/sites-health", {}):
        name = item.get("siteName")
        site_id = item.get("id")
        if name and site_id:
            sites[name] = site_id
    return sites


def create_site(
    client: CentralClient,
    name: str,
    address: str,
    city: str,
    state: str,
    zipcode: str,
    country: str = "United States",
    timezone_id: str = "America/Chicago",
) -> dict:
    """POST network-config/v1/sites - NOT v1alpha1 (that version is
    deprecated/sunset and its POST rejects real requests - see the
    sibling conversion project's own create_site docstring for the
    2026-09-03 live confirmation this was ported from). `state` must be
    the FULL state name ("Texas"), not the postal abbreviation - also
    confirmed live there. Every field sent here is required."""
    tz = ZoneInfo(timezone_id)
    now = datetime.now(tz)
    body = {
        "name": name,
        "address": address,
        "city": city,
        "state": state,
        "country": country,
        "zipcode": zipcode,
        "timezone": {
            "rawOffset": int(now.utcoffset().total_seconds() * 1000),
            "timezoneId": timezone_id,
            "timezoneName": now.tzname(),
        },
    }
    result = client.post("network-config/v1/sites", body=body)
    return result["body"]


@dataclass
class GLPDeviceRecord:
    serial: str
    assigned_state: str | None
    subscription_tier: str | None
    subscription_end: str | None
    application_id: str | None = None
    region: str | None = None
    mac_address: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def normalize_mac(mac: str) -> str | None:
    """Canonicalizes a MAC address typed in any common separator style
    to upper-case colon-separated form, matching the format GLP's own
    API returns. Returns None if the cleaned string isn't exactly 12 hex
    digits (not a real MAC) - a caller-visible "not a MAC", not an
    exception."""
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(hex_only) != 12:
        return None
    hex_only = hex_only.upper()
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


def list_glp_devices(client: CentralClient) -> list[GLPDeviceRecord]:
    """GreenLake-level device presence + Central app assignment
    (assignedState) + subscription (subscription[].tier/endTime), all in
    one call. client must be constructed with base_url=GLP_BASE_URL, not
    a regional Central host - same OAuth token/grant as New Central.

    No server-side serial filter - fetch-all-then-index client-side.

    application_id/region are read from the same item under
    "application"."id" / "region" - inferred from the PATCH body shape
    unassign_from_greenlake/restore_central_assignment write, on the
    assumption a symmetric GET returns the same field names it accepts
    on write (ported from the sibling conversion project's own
    unconfirmed-against-a-real-GET caveat - verify on first live use; a
    wrong guess here just means restore_central_assignment's auto-
    discovery comes back empty, not a wrong write)."""
    records = []
    for item in _paginate(client, "devices/v1/devices", {}):
        subs = item.get("subscription") or []
        sub = subs[0] if subs else {}
        application = item.get("application") or {}
        records.append(
            GLPDeviceRecord(
                serial=item.get("serialNumber", ""),
                assigned_state=item.get("assignedState"),
                subscription_tier=sub.get("tier"),
                subscription_end=sub.get("endTime"),
                application_id=application.get("id") if isinstance(application, dict) else None,
                region=item.get("region"),
                mac_address=normalize_mac(item["macAddress"]) if item.get("macAddress") else None,
                raw=item,
            )
        )
    return records


def list_service_managers(client: CentralClient) -> list[dict]:
    """Every service instance (application) provisioned in this GLCP
    workspace - GET service-catalog/v1/service-managers, client must be
    constructed with base_url=GLP_BASE_URL. Returns each item's raw
    dict (id, name, ... per HPE's Service Catalog API); id is assumed
    to be the same application_id restore_central_assignment/
    list_glp_devices read/write on a device record (a provisioned
    service instance IS what a device gets attached to) - NOT yet
    confirmed against a real tenant, verify on first live use. Lets an
    operator look up e.g. the UXI application's id directly instead of
    having to already have one UXI device assigned somewhere to read it
    off of (see restore_central_assignment's auto-discovery caveat)."""
    return list(_paginate(client, "service-catalog/v1/service-managers", {}))


_UNASSIGN_BATCH_SIZE = 5  # GLP's own per-request limit on this endpoint
_UNASSIGN_POLL_INTERVAL = 3.0  # seconds between async-operation status polls
_UNASSIGN_POLL_TIMEOUT = 120.0  # give up waiting on one transaction after this long


@dataclass
class UnassignResult:
    serial: str
    ok: bool
    detail: str | None = None  # None on success, an error/status string otherwise


def unassign_from_greenlake(client: CentralClient, identifiers: list[str]) -> list[UnassignResult]:
    """Detaches device(s) from the Central application instance in
    GreenLake (PATCH devices/v1/devices?id=<id> with body {"application":
    {"id": None}, "region": None}) - the device's subscription itself
    stays at the GreenLake workspace level. Reversible - see
    restore_central_assignment below.

    identifiers: each may be a serial OR a MAC address - see
    _patch_device. client must be constructed with base_url=GLP_BASE_URL."""
    return _patch_device(
        client, identifiers, body={"application": {"id": None}, "region": None}, action="unassign"
    )


def restore_central_assignment(
    client: CentralClient, identifiers: list[str], application_id: str | None = None, region: str | None = None
) -> list[UnassignResult]:
    """Assigns device(s) to a GreenLake application instance (PATCH
    devices/v1/devices?id=<id> with body {"application": {"id": <id>},
    "region": <region>}) - this is the "assign a service/application"
    primitive (GLCP terms: assigning a device to an application, e.g.
    Central or UXI, IS assigning it a service). For APs/switches/
    gateways this is the Central application; for UXI sensors (not yet
    built, v2) it would be the UXI application instead - a different
    application_id, same call shape.

    application_id/region: if either is omitted, both are auto-
    discovered from any OTHER currently-assigned device in
    list_glp_devices (excluding the identifiers being (re)assigned) - in
    practice a GreenLake workspace has exactly one Central application
    instance, so every already-assigned device shares the same
    application.id/region, which is how this can re-attach a device to
    Central without the operator having to know/record the application
    ID themselves. This auto-discovery only works for an application a
    device is ALREADY assigned to elsewhere in the workspace (Central,
    today) - a workspace with no UXI application ever assigned yet has
    nothing to discover from, so assigning UXI to a brand-new sensor
    will need an explicit application_id passed in until that's been
    confirmed against a real tenant.

    identifiers: each may be a serial OR a MAC address, see
    _patch_device."""
    if application_id is None or region is None:
        devices = list_glp_devices(client)
        excluded = {i.upper() for i in identifiers}
        discovered = next(
            (d for d in devices if d.application_id and d.serial not in excluded
             and (d.mac_address or "") not in excluded),
            None,
        )
        if discovered is not None:
            application_id = application_id or discovered.application_id
            region = region or discovered.region

    if not application_id:
        return [
            UnassignResult(
                i, False,
                "no application_id given, and none could be auto-discovered from another "
                "assigned device - pass application_id/region directly",
            )
            for i in identifiers
        ]

    return _patch_device(
        client, identifiers, body={"application": {"id": application_id}, "region": region}, action="assign"
    )


def get_subscription_id_by_key(client: CentralClient, key: str) -> str | None:
    """Resolves a GreenLake subscription KEY (the human-readable string
    printed on a license) to its internal subscription id. GET
    subscriptions/v1/subscriptions?filter=key eq '<key>'. client must be
    constructed with base_url=GLP_BASE_URL. Returns None if no
    subscription with that key exists in this workspace."""
    resp = client.get("subscriptions/v1/subscriptions", params={"filter": f"key eq '{key}'"})
    items = resp["body"].get("items") or []
    return items[0]["id"] if items else None


def assign_subscription(client: CentralClient, identifiers: list[str], subscription_key: str) -> list[UnassignResult]:
    """Assigns a SPECIFIC GreenLake subscription (by its human-readable
    key) to device(s) - PATCH devices/v1/devices?id=<id> with body
    {"subscription": [{"id": <sub_id>}]}. Deliberately distinct from
    unassign_from_greenlake/restore_central_assignment, which only touch
    the Central APPLICATION assignment - a real, separate GLP concept
    from the subscription (the license/tier that actually covers the
    device).

    identifiers: each may be a serial OR a MAC address. client must be
    constructed with base_url=GLP_BASE_URL."""
    sub_id = get_subscription_id_by_key(client, subscription_key)
    if sub_id is None:
        return [
            UnassignResult(i, False, f"subscription key '{subscription_key}' not found in this workspace")
            for i in identifiers
        ]
    return _patch_device(
        client, identifiers, body={"subscription": [{"id": sub_id}]}, action="assign subscription"
    )


def remove_subscription_key(client: CentralClient, identifiers: list[str]) -> list[UnassignResult]:
    """Removes whatever subscription is currently assigned to device(s)
    - PATCH devices/v1/devices?id=<id> with body {"subscription": []}.
    Distinct from unassign_from_greenlake, which detaches the Central
    APPLICATION, not the subscription.

    identifiers: each may be a serial OR a MAC address. client must be
    constructed with base_url=GLP_BASE_URL."""
    return _patch_device(client, identifiers, body={"subscription": []}, action="remove subscription")


def _patch_device(
    client: CentralClient, identifiers: list[str], body: dict, action: str
) -> list[UnassignResult]:
    """Shared batch-of-5/202+poll implementation behind every devices/
    v1/devices PATCH in this module.

    identifiers: each may be EITHER a serial OR a MAC address - looked
    up against list_glp_devices by serial first, then by normalized MAC.
    Resolved identifiers are DEDUPED by the underlying GLP device's own
    id, so a device typed into both a serial field and a MAC field isn't
    double-processed in the same PATCH. Every result is reported under
    the device's own canonical `.serial` from list_glp_devices, not
    whatever identifier the caller happened to type. An identifier that
    resolves to nothing is still reported back exactly as typed."""
    devices = list_glp_devices(client)
    by_serial = {d.serial: d for d in devices}
    by_mac = {d.mac_address: d for d in devices if d.mac_address}

    results: list[UnassignResult] = []
    known: dict[str, GLPDeviceRecord] = {}  # keyed by the device's own GLP id, for dedup
    for identifier in identifiers:
        dev = by_serial.get(identifier)
        if dev is None:
            normalized = normalize_mac(identifier)
            if normalized is not None:
                dev = by_mac.get(normalized)
        dev_id = dev.raw.get("id") if dev is not None else None
        if dev is None or not dev_id:
            results.append(UnassignResult(identifier, False, "not found in GLP device inventory"))
        else:
            known.setdefault(dev_id, dev)

    known_devices = list(known.values())
    for i in range(0, len(known_devices), _UNASSIGN_BATCH_SIZE):
        batch = known_devices[i:i + _UNASSIGN_BATCH_SIZE]
        ids = [dev.raw["id"] for dev in batch]
        try:
            resp = client.patch("devices/v1/devices", params={"id": ids}, body=body)
        except (CentralAuthError, CentralAPIError) as exc:
            for dev in batch:
                results.append(UnassignResult(dev.serial, False, f"{action} request failed: {exc}"))
            continue

        transaction_id = resp["body"].get("transactionId") if resp["status"] == 202 else None
        if not transaction_id:
            for dev in batch:
                results.append(
                    UnassignResult(dev.serial, False, f"unexpected response (HTTP {resp['status']}, no transactionId)")
                )
            continue

        status = _poll_unassign_transaction(client, transaction_id)
        for dev in batch:
            results.append(
                UnassignResult(dev.serial, True, None) if status == "SUCCEEDED"
                else UnassignResult(dev.serial, False, f"async operation ended '{status}'")
            )

    return results


def _poll_unassign_transaction(client: CentralClient, transaction_id: str) -> str:
    """Polls devices/v1/async-operations/{id} until its status leaves
    the pending state or _UNASSIGN_POLL_TIMEOUT elapses ('CLIENT_TIMEOUT',
    distinct from GLP's own terminal 'TIMEOUT' status).

    Tolerates an immediate 404 on the FIRST poll(s) - the async-
    operations resource for a transactionId returned by the 202 isn't
    always queryable a moment later, even though the underlying write
    goes on to succeed (see the sibling conversion project's own
    _poll_unassign_transaction docstring for the 2026-09-10 live
    confirmation this was ported from). Treated as still-pending and
    retried within the same timeout budget rather than as a hard
    failure."""
    deadline = time.monotonic() + _UNASSIGN_POLL_TIMEOUT
    while True:
        try:
            result = client.get(f"devices/v1/async-operations/{transaction_id}")
            status = result["body"].get("status")
        except CentralAPIError as exc:
            if exc.status != 404:
                raise
            status = None
        if status in ("SUCCEEDED", "FAILED", "TIMEOUT"):
            return status
        if time.monotonic() >= deadline:
            return "CLIENT_TIMEOUT"
        time.sleep(_UNASSIGN_POLL_INTERVAL)


_TRANSACTION_ID_RE = re.compile(r"async-operations/([^/?#]+)")


def add_devices_to_glcp(
    client: CentralClient, devices: list[tuple[str, str]], tags: list[dict[str, str] | None] | None = None
) -> list[UnassignResult]:
    """Adds network device(s) - BOTH a serial AND a MAC required per
    device - to the GreenLake workspace's device inventory. POST
    devices/v1/devices, body {"network": [{"serialNumber": <serial>,
    "macAddress": <mac>}, ...], "compute": [], "storage": []} -
    compute/storage MUST be present even when empty (confirmed live
    against a real tenant by the sibling conversion project this was
    ported from - a network-only body 400'd with "compute: must not be
    null; storage: must not be null").

    Async 202, same poll-devices/v1/async-operations/{id} pattern as
    _patch_device above - the transaction id may arrive either in the
    response body's transactionId field or the response's Location
    header; this checks the body first and falls back to parsing the
    Location header.

    devices: list of (serial, mac) tuples. Each mac is normalized (see
    normalize_mac) before being sent - a mac that doesn't normalize to
    12 hex digits is reported as a per-device failure without ever
    reaching the API.

    tags: optional, one dict per device (same length/order as devices,
    or None to skip tags entirely).

    client must be constructed with base_url=GLP_BASE_URL."""
    if tags is not None and len(tags) != len(devices):
        raise ValueError(f"tags has {len(tags)} entries but devices has {len(devices)} - must match 1:1 or be omitted.")
    results: list[UnassignResult] = []
    valid: list[tuple[str, str, dict[str, str] | None]] = []
    for i, (serial, mac) in enumerate(devices):
        normalized = normalize_mac(mac)
        device_tags = tags[i] if tags is not None else None
        if normalized is None:
            results.append(UnassignResult(serial, False, f"'{mac}' is not a valid MAC address"))
        else:
            valid.append((serial, normalized, device_tags))

    for i in range(0, len(valid), _UNASSIGN_BATCH_SIZE):
        batch = valid[i:i + _UNASSIGN_BATCH_SIZE]
        network = []
        for s, m, t in batch:
            entry: dict[str, object] = {"serialNumber": s, "macAddress": m}
            if t:
                entry["tags"] = t
            network.append(entry)
        body = {"network": network, "compute": [], "storage": []}
        try:
            resp = client.post("devices/v1/devices", body=body)
        except (CentralAuthError, CentralAPIError) as exc:
            for serial, _, _ in batch:
                results.append(UnassignResult(serial, False, f"add request failed: {exc}"))
            continue

        transaction_id = resp["body"].get("transactionId") if resp["status"] == 202 else None
        if not transaction_id:
            location = resp.get("headers", {}).get("Location") or resp.get("headers", {}).get("location")
            match = _TRANSACTION_ID_RE.search(location) if location else None
            transaction_id = match.group(1) if match else None
        if not transaction_id:
            for serial, _, _ in batch:
                results.append(
                    UnassignResult(serial, False, f"unexpected response (HTTP {resp['status']}, no transactionId)")
                )
            continue

        status = _poll_unassign_transaction(client, transaction_id)
        for serial, _, _ in batch:
            results.append(
                UnassignResult(serial, True, None) if status == "SUCCEEDED"
                else UnassignResult(serial, False, f"async operation ended '{status}'")
            )

    return results
