"""The pywebview js_api bridge - every method here is callable from the
frontend as `pywebview.api.<method>(...)`, returning a JSON-serializable
result (pywebview marshals it back as a resolved Promise). This is the
ONLY module under central_onboarder/gui/ that imports from
central_onboarder/core/ - static/ talks to Python exclusively through
Api, never directly to core/, same "logic lives in core/, front-end
stays thin" shape the sibling AOS8-to-AOS10 Conversion Tool project
follows.

get_credentials() returns full, unmasked values - deliberately, not a
gap. pywebview's js_api bridge is local IPC within one process, not a
network boundary. Masking secret fields is a presentation concern,
handled in static/js/app.js."""

from __future__ import annotations

import csv
import functools
import inspect
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import webview

from central_onboarder import assets
from central_onboarder.core import central, central_classic, credential_store, creds_check
from central_onboarder.core import action_log as action_log_module
from central_onboarder.core import sheet as sheet_module
from central_onboarder.core import workspace
from central_onboarder.core.transcript import Transcript
from central_onboarder.version import VERSION

_PREPROVISION_CHUNK_SIZE = 50  # documented cap on /configuration/v1/devices/move

_DEVICE_TYPE_TO_CLASSIC = {
    "AP": central_classic.DEVICE_TYPE_AP,
    "Switch": central_classic.DEVICE_TYPE_SWITCH,
    "Gateway": central_classic.DEVICE_TYPE_GATEWAY,
}

# GLCP device record's deviceType -> which Classic Central monitoring
# endpoint to try first in Check Status. Only an ordering hint (the
# field name/values aren't live-confirmed) - get_device_status falls
# back to trying all three regardless.
_GLCP_DEVICE_TYPE_HINT = {
    "AP": "AP", "IAP": "AP",
    "SWITCH": "Switch",
    "GATEWAY": "Gateway", "CONTROLLER": "Gateway",
}

_CSV_HEADER_ALIASES = {
    "serial": "serial", "serial number": "serial", "serial_no": "serial", "serial_number": "serial",
    "mac": "mac", "mac address": "mac", "mac_address": "mac",
    "device type": "device_type", "device_type": "device_type", "type": "device_type",
    "target group": "target_group", "target_group": "target_group", "group": "target_group",
    "target site": "target_site", "target_site": "target_site", "site": "target_site",
    "subscription key": "subscription_key", "subscription_key": "subscription_key",
    "hostname": "hostname", "host name": "hostname", "host_name": "hostname",
}


class Api:
    def __init__(self, action_log: action_log_module.ActionLog | None = None):
        """action_log is opt-in and defaults to None - every test and
        every direct `Api()` construction is completely unaffected. Only
        gui/app.py's real entry point passes a real ActionLog in - see
        core/action_log.py's own module docstring for why."""
        self._action_log = action_log
        if action_log is not None:
            self._wrap_methods_for_logging()

    def _wrap_methods_for_logging(self) -> None:
        """Replaces every public method on THIS INSTANCE with a
        logging-wrapped version that records to self._action_log -
        instance-level wrapping so there's one place to maintain and new
        methods added later are covered automatically."""
        for name in dir(type(self)):
            if name.startswith("_"):
                continue
            attr = getattr(type(self), name)
            if not callable(attr):
                continue
            setattr(self, name, self._make_logged(name, getattr(self, name)))

    def _make_logged(self, name: str, bound_method):
        sig = inspect.signature(bound_method)

        @functools.wraps(bound_method)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = bound_method(*args, **kwargs)
            except Exception as exc:
                self._action_log.log(
                    name, sig, args, kwargs, ok=False, error=str(exc),
                    duration_s=time.monotonic() - start,
                )
                raise
            self._action_log.log(
                name, sig, args, kwargs, ok=True, error=None,
                duration_s=time.monotonic() - start,
            )
            return result

        return wrapper

    # --- meta ------------------------------------------------------------

    def get_version(self) -> dict:
        return {"version": VERSION}

    def open_changelog(self) -> dict:
        return self._open_doc(assets.gui_changelog_path())

    def open_user_guide(self) -> dict:
        return self._open_doc(assets.gui_guide_path())

    def _open_doc(self, path: Path) -> dict:
        """Opens a bundled .md file in whatever app the OS has associated
        with .md files, rather than rendering markdown in-app. Only
        Windows has actually been run, matching this project's standing
        "packaging beyond Windows is unverified" caveat."""
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=True)
            else:
                subprocess.run(["xdg-open", str(path)], check=True)
            return {"ok": True}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"Couldn't open {path}: {exc}"}

    # --- credentials / accounts ------------------------------------------

    def get_credentials(self) -> dict:
        """Everything the Credentials screen and the account dropdown
        need: every account (full values - see module docstring), which
        one is active, and where the file lives.

        Also where the one-time credentials.json -> token.yaml migration
        runs (it's the first call the frontend makes that touches
        credentials) - a no-op once token.yaml exists."""
        migrated = credential_store.migrate_legacy_json()
        data = credential_store.load()
        return {
            "path": str(credential_store.default_path()),
            "accounts": data["accounts"],
            "active": credential_store.get_active_account(),
            "migrated": migrated,
            "legacy_file_present": credential_store.legacy_path().exists(),
        }

    def get_hints(self) -> dict:
        return creds_check.HINTS

    def set_active_account(self, account: str) -> dict:
        try:
            credential_store.set_active_account(account)
        except KeyError:
            return {"ok": False, "error": f"No account named '{account}'."}
        return {"ok": True}

    def add_account(self, account: str) -> dict:
        account = (account or "").strip()
        if not account:
            return {"ok": False, "error": "Account name is required."}
        if account in credential_store.list_accounts():
            return {"ok": False, "error": f"An account named '{account}' already exists."}
        credential_store.add_account(account)
        return {"ok": True}

    def delete_account(self, account: str) -> dict:
        credential_store.delete_account(account)
        return {"ok": True}

    def wipe_credentials(self, account: str, category: str) -> dict:
        credential_store.clear_category(account, category)
        return {"ok": True}

    def wipe_all_credentials(self) -> dict:
        credential_store.clear_all()
        return {"ok": True}

    def save_central(self, account: str, base_url: str, client_id: str, client_secret: str) -> dict:
        if not all((account, base_url, client_id, client_secret)):
            return {"ok": False, "error": "All fields are required."}
        credential_store.set_central_account(
            account, creds_check.normalize_base_url(base_url), client_id, client_secret
        )
        return {"ok": True}

    def save_classic(
        self, account: str, base_url: str, client_id: str, client_secret: str, refresh_token: str
    ) -> dict:
        if not all((account, base_url, client_id, client_secret, refresh_token)):
            return {"ok": False, "error": "All fields are required."}
        credential_store.set_classic_account(
            account, creds_check.normalize_base_url(base_url), client_id, client_secret, refresh_token
        )
        return {"ok": True}

    def save_ap_ssh(self, account: str, username: str, password: str, ap_ip: str | None = None) -> dict:
        """Storage only - no feature in this tool reads this credential
        yet. Kept for possible future use, same as credential_store's
        own ap_ssh category docstring."""
        if not all((account, username, password)):
            return {"ok": False, "error": "All fields are required."}
        credential_store.set_ap_ssh_credential(account, username, password, ap_ip=ap_ip)
        return {"ok": True}

    def save_uxi(self, account: str, application_id: str, region: str | None = None) -> dict:
        """Not a credential - the GreenLake application_id (and its
        region) for the UXI application in this account's workspace,
        used by run_onboard_batch/assign_service for UXI rows since
        restore_central_assignment's auto-discovery has nothing to find
        it from in a workspace where no UXI sensor has ever been
        assigned yet."""
        if not account:
            return {"ok": False, "error": "Select or add an account first."}
        if not application_id:
            return {"ok": False, "error": "Application ID is required."}
        credential_store.set_uxi_application(account, application_id, region or None)
        return {"ok": True}

    def list_glcp_services(self) -> dict:
        """Look-up-from-GLCP for the UXI Application card - lists every
        service instance provisioned in the workspace (id + name), so
        the operator can find e.g. "HPE Aruba Networking UXI"'s id
        directly rather than needing an already-assigned UXI device to
        read it off of. See core/central.list_service_managers for the
        not-yet-confirmed-against-a-real-tenant caveat on this endpoint."""
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-list-glcp-services")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            items = central.list_service_managers(client)
        except (central.CentralAuthError, central.CentralAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        services = [{"id": i.get("id"), "name": i.get("name")} for i in items if i.get("id")]
        return {"ok": True, "services": services}

    def test_central(self, account: str) -> dict:
        entry = credential_store.get_central_account(account) if account else None
        if entry is None:
            return {"ok": False, "detail": f"Account '{account}' has no New Central credentials - Save them first."}
        ok, detail = creds_check.test_central_account(entry)
        return {"ok": ok, "detail": detail}

    def test_classic(self, account: str) -> dict:
        entry = credential_store.get_classic_account(account) if account else None
        if entry is None:
            return {"ok": False, "detail": f"Account '{account}' has no Classic Central credentials - Save them first."}
        ok, detail = creds_check.test_classic_account(account, entry)
        return {"ok": ok, "detail": detail}

    def test_all(self) -> list[dict]:
        results = creds_check.test_all()
        return [{"category": r.category, "key": r.key, "ok": r.ok, "detail": r.detail} for r in results]

    # --- credential resolution helpers -----------------------------------
    # Every API call uses the ACTIVE account (token.yaml's `default`, set
    # by the account dropdown) - read fresh from disk on each call, so
    # switching accounts takes effect on the very next call.

    def _central_creds(self) -> tuple[str, str, str] | None:
        account = credential_store.get_active_account()
        entry = credential_store.get_central_account(account) if account else None
        if entry is None:
            return None
        return entry["base_url"], entry["client_id"], entry["client_secret"]

    def _glp_creds(self) -> tuple[str, str] | None:
        """GLP reuses New Central's client_id/secret - always against
        central.GLP_BASE_URL, never the account's own regional base_url."""
        creds = self._central_creds()
        if creds is None:
            return None
        _, client_id, client_secret = creds
        return client_id, client_secret

    def _classic_creds(self) -> tuple[str, str, str, str, str] | None:
        account = credential_store.get_active_account()
        entry = credential_store.get_classic_account(account) if account else None
        if entry is None:
            return None
        return (
            entry["base_url"], entry["client_id"], entry["client_secret"],
            entry["refresh_token"], account,
        )

    def _classic_client(self, transcript: Transcript | None = None) -> tuple[object, str] | None:
        creds = self._classic_creds()
        if creds is None:
            return None, "The selected account has no Classic Central credentials - add them in Credentials first."
        base_url, client_id, client_secret, refresh_token, account_name = creds
        tm = central_classic.ClassicTokenManager(
            base_url, client_id, client_secret, refresh_token,
            on_refresh_token_rotated=lambda new_rt: credential_store.update_classic_refresh_token(account_name, new_rt),
        )
        return central_classic.ClassicCentralClient(base_url, tm, transcript=transcript), None

    # --- working device list ----------------------------------------------

    def _batch_summary(self, sheet_path: Path) -> dict | None:
        try:
            rows = sheet_module.read_devices(sheet_path)
        except (KeyError, FileNotFoundError):
            return None
        if not rows:
            return None
        return {
            "total": len(rows),
            "added_to_glcp": sum(1 for r in rows if r.added_to_glcp),
            "site_assigned": sum(1 for r in rows if r.site_assigned),
        }

    def _schema_mismatch_error(self, sheet_path: Path) -> str | None:
        """Also where a pre-Hostname sheet gets upgraded in place (see
        sheet.upgrade_sheet_schema) - a no-op for a current sheet."""
        try:
            sheet_module.upgrade_sheet_schema(sheet_path)
        except sheet_module.SheetLockedError:
            return (
                f"'{sheet_path}' needs a one-time upgrade (new Hostname columns) but is open in "
                "another program - close it in Excel and try again."
            )
        result = sheet_module.validate_sheet_schema(sheet_path)
        if result.ok:
            return None
        return (
            f"'{sheet_path}' doesn't match this version's expected Devices column layout "
            f"({len(result.mismatches)} column(s) differ) - it may have been built by an older "
            "version of this tool."
        )

    def get_working_sheet(self) -> dict:
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"path": None, "summary": None, "schema_error": None}
        return {
            "path": str(sheet_path),
            "summary": self._batch_summary(sheet_path),
            "schema_error": self._schema_mismatch_error(sheet_path) if sheet_path.exists() else None,
        }

    def pick_new_sheet_path(self) -> str | None:
        window = webview.windows[0]
        result = window.create_file_dialog(
            webview.FileDialog.SAVE, file_types=("Excel files (*.xlsx)",), save_filename="device-list.xlsx"
        )
        return result if isinstance(result, str) else (result[0] if result else None)

    def pick_existing_sheet_path(self) -> str | None:
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Excel files (*.xlsx)",))
        return result[0] if result else None

    def create_new_sheet(self, out_path: str) -> dict:
        """Starts a brand-new device list at out_path from the bundled
        template, and sets it as the working sheet."""
        report = sheet_module.add_devices_manual(Path(out_path), [], out_path=Path(out_path))
        if report.aborted_reason:
            return {"ok": False, "error": report.aborted_reason}
        workspace.set_sheet(Path(out_path))
        return {"ok": True, **self.get_working_sheet()}

    def set_working_sheet(self, sheet_path: str) -> dict:
        """Sets an existing .xlsx as the working device list - refuses a
        sheet whose Devices tab doesn't match this version's expected
        column layout, same schema-guard the sibling conversion project
        applies."""
        path = Path(sheet_path)
        if not path.exists():
            return {"ok": False, "error": f"'{sheet_path}' doesn't exist."}
        error = self._schema_mismatch_error(path)
        if error:
            return {"ok": False, "error": error}
        workspace.set_sheet(path)
        return {"ok": True, **self.get_working_sheet()}

    def reset_to_default(self) -> dict:
        """Tools screen action - clears the working-sheet pointer and
        every stored credential. Never deletes any actual file."""
        workspace.clear_sheet()
        credential_store.clear_all()
        return {"ok": True}

    def get_devices(self) -> dict:
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        rows = sheet_module.read_devices(sheet_path)
        return {
            "ok": True,
            "devices": [
                {
                    "serial": r.serial, "mac": r.mac, "device_type": r.device_type,
                    "target_group": r.target_group, "target_site": r.target_site,
                    "subscription_key": r.subscription_key, "hostname": r.hostname,
                    "added_to_glcp": r.added_to_glcp,
                    "subscription_assigned": r.subscription_assigned, "service_assigned": r.service_assigned,
                    "preprovisioned": r.preprovisioned, "site_assigned": r.site_assigned,
                    "hostname_set": r.hostname_set, "notes": r.notes,
                }
                for r in rows
            ],
        }

    def add_devices_manual(self, devices: list[dict]) -> dict:
        """devices: list of {serial, mac, device_type, target_group,
        target_site, subscription_key} from the Device List screen's
        editable grid. Merges by serial into the working sheet (creating
        one at the default location next to the app if none is set
        yet)."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            sheet_path = workspace.default_path().parent / "device-list.xlsx"
        report = sheet_module.add_devices_manual(sheet_path, devices)
        if report.aborted_reason:
            return {"ok": False, "error": report.aborted_reason}
        workspace.set_sheet(sheet_path)
        return {"ok": True, "rows_added": report.rows_added, "rows_updated": report.rows_updated}

    def pick_csv_path(self) -> str | None:
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.OPEN, file_types=("CSV files (*.csv)",))
        return result[0] if result else None

    def save_csv_template(self) -> dict:
        window = webview.windows[0]
        path = window.create_file_dialog(
            webview.FileDialog.SAVE, file_types=("CSV files (*.csv)",), save_filename="device-import-template.csv"
        )
        path = path if isinstance(path, str) else (path[0] if path else None)
        if not path:
            return {"ok": False, "error": None}
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(("Serial", "MAC", "Device Type", "Target Group", "Target Site", "Subscription Key", "Hostname"))
                writer.writerow(["CN12345678", "11:22:33:44:AA:BB", "AP", "Building-1-APs", "Building 1", "PAYHAH3YJE6THY", "BLDG1-AP-01"])
                writer.writerow(["CN87654321", "44:33:22:11:BB:AA", "Switch", "", "", "", "BLDG1-SW-01"])
        except OSError as exc:
            return {"ok": False, "error": f"Could not write template: {exc}"}
        return {"ok": True, "path": path}

    def import_csv(self, csv_path: str) -> dict:
        """Parses csv_path (any header casing/spacing matching
        _CSV_HEADER_ALIASES) and merges the rows into the working device
        list, same as add_devices_manual. A column this tool doesn't
        recognize is ignored, not an error - lets an operator reuse a
        richer export from elsewhere without stripping columns first."""
        try:
            text = Path(csv_path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            return {"ok": False, "error": f"Could not read '{csv_path}': {exc}"}

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return {"ok": False, "error": "CSV has no header row."}
        column_map = {
            raw: _CSV_HEADER_ALIASES.get(raw.strip().lower())
            for raw in reader.fieldnames
        }
        if "serial" not in column_map.values():
            return {"ok": False, "error": "CSV has no recognizable Serial column."}

        devices = []
        for row in reader:
            mapped = {}
            for raw_key, value in row.items():
                key = column_map.get(raw_key)
                if key:
                    mapped[key] = (value or "").strip()
            devices.append(mapped)

        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            sheet_path = workspace.default_path().parent / "device-list.xlsx"
        report = sheet_module.add_devices_from_csv(devices, sheet_path)
        if report.aborted_reason:
            return {"ok": False, "error": report.aborted_reason}
        workspace.set_sheet(sheet_path)
        return {
            "ok": True, "rows_added": report.rows_added, "rows_updated": report.rows_updated,
            "skipped_blank_serial_rows": report.skipped_blank_serial_rows,
        }

    # --- Central/Classic destinations --------------------------------------

    def get_central_destinations(self) -> dict:
        """Live New Central group/site names, for the Device List
        screen's Target Group/Target Site pickers."""
        creds = self._central_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        base_url, client_id, client_secret = creds
        transcript = Transcript(prefix="gui-central-destinations")
        client = central.CentralClient(base_url, client_id, client_secret, transcript=transcript)
        try:
            groups = central.list_device_groups(client)
            sites = central.list_sites(client)
        except (central.CentralAuthError, central.CentralAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "groups": sorted(groups), "sites": sorted(sites)}

    def load_destinations(self) -> dict:
        """Writes live New Central group/site names into the working
        sheet's Target Group/Target Site dropdown validation, so editing
        the sheet directly in Excel also has a live pick-list."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        creds = self._central_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        base_url, client_id, client_secret = creds
        transcript = Transcript(prefix="gui-load-destinations")
        client = central.CentralClient(base_url, client_id, client_secret, transcript=transcript)
        try:
            groups = central.list_device_groups(client)
            sites = central.list_sites(client)
        except (central.CentralAuthError, central.CentralAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        report = sheet_module.load_destinations(sheet_path, groups=groups, sites=sites)
        if report.aborted_reason:
            return {"ok": False, "error": report.aborted_reason}
        return {"ok": True, "groups_loaded": report.groups_loaded, "sites_loaded": report.sites_loaded}

    def create_site(
        self,
        name: str,
        address: str,
        city: str,
        state: str,
        zipcode: str,
        country: str = "United States",
        timezone_id: str = "America/Chicago",
    ) -> dict:
        """Tools screen - creates a new New Central site."""
        creds = self._central_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        base_url, client_id, client_secret = creds
        transcript = Transcript(prefix="gui-create-site")
        client = central.CentralClient(base_url, client_id, client_secret, transcript=transcript)
        try:
            body = central.create_site(client, name, address, city, state, zipcode, country, timezone_id)
        except (central.CentralAuthError, central.CentralAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "site": body}

    # --- Onboard (GLCP: add device, subscription, service) ---------------

    @staticmethod
    def _results_dict(results) -> dict:
        return {
            "ok": all(r.ok for r in results),
            "results": [{"serial": r.serial, "ok": r.ok, "detail": r.detail} for r in results],
        }

    def add_devices_to_glcp(self, serials: list[str], macs: list[str]) -> dict:
        """Adds device(s) to the GLCP workspace inventory - needs BOTH a
        serial AND a MAC per device, paired positionally."""
        if len(serials) != len(macs):
            return {"ok": False, "error": f"{len(serials)} serial(s) but {len(macs)} MAC(s) - each device needs both, paired in order."}
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-add-devices-to-glcp")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.add_devices_to_glcp(client, list(zip(serials, macs)))
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        ok_serials = [r.serial for r in results if r.ok]
        sheet_path = workspace.get_sheet()
        if ok_serials and sheet_path is not None:
            sheet_module.mark_added_to_glcp(sheet_path, ok_serials)
        return self._results_dict(results)

    def assign_subscription(self, identifiers: list[str], subscription_key: str) -> dict:
        """identifiers: each may be a serial OR a MAC address."""
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-assign-subscription")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.assign_subscription(client, identifiers, subscription_key)
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        ok_serials = [r.serial for r in results if r.ok]
        sheet_path = workspace.get_sheet()
        if ok_serials and sheet_path is not None:
            sheet_module.mark_subscription_assigned(sheet_path, ok_serials)
        return self._results_dict(results)

    def remove_subscription_key(self, identifiers: list[str]) -> dict:
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-remove-subscription-key")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.remove_subscription_key(client, identifiers)
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        return self._results_dict(results)

    def assign_service(self, identifiers: list[str], application_id: str | None = None, region: str | None = None) -> dict:
        """"Assign service" = GLCP's "assign an application" action - for
        APs/switches/gateways today that's Central; a future UXI
        sensor's own onboarding would pass UXI's application_id instead
        (see core/central.py's restore_central_assignment docstring for
        why application_id/region are optional - auto-discovered from
        another already-Central-assigned device when omitted, which only
        works for an application already present somewhere in this
        workspace)."""
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-assign-service")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.restore_central_assignment(client, identifiers, application_id, region)
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        ok_serials = [r.serial for r in results if r.ok]
        sheet_path = workspace.get_sheet()
        if ok_serials and sheet_path is not None:
            sheet_module.mark_service_assigned(sheet_path, ok_serials)
        return self._results_dict(results)

    def remove_service(self, identifiers: list[str]) -> dict:
        """Detaches device(s) from the Central application in GreenLake
        (core.central.unassign_from_greenlake) - the reverse of
        assign_service above. Same as remove_subscription_key: doesn't
        touch the working sheet's Service Assigned tracking column, it
        only reflects what run_onboard_batch/assign_service have done."""
        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-remove-service")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.unassign_from_greenlake(client, identifiers)
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        return self._results_dict(results)

    # --- Sheet-driven ("Run X"/checked "Pull from Device List") steps -----
    #
    # Each of these has the same shape as _run_preprovision below (the
    # original of this pattern): a private _run_X(sheet_path) that reads
    # the CURRENT working sheet and acts on whatever's eligible by that
    # row's OWN values (not an explicit caller-supplied list - that's
    # what the plain add_devices_to_glcp/assign_subscription/
    # assign_service methods above are for), plus a public run_X()
    # wrapper that resolves the working sheet path. run_onboard_batch
    # composes all four; each Manual card's "Pull from Device List"
    # checkbox calls its matching run_X() directly (2026-09-15 - the
    # checkbox used to just copy serials into the manual field, which
    # silently dropped each row's own group/site/key and didn't skip
    # already-done rows the way these do).

    def _run_add_to_glcp(self, sheet_path) -> dict:
        """Adds every row not yet marked Added to GLCP (and with a MAC
        set - add_devices_to_glcp needs both) to GLCP, using each row's
        own serial/MAC."""
        rows = sheet_module.read_devices(sheet_path)
        pending = [r for r in rows if not r.added_to_glcp]
        missing_mac = [r.serial for r in pending if not r.mac]
        with_mac = [r for r in pending if r.mac]
        if not with_mac:
            return {"ok": True, "results": [], "missing_mac": missing_mac}

        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-run-add-to-glcp")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = central.add_devices_to_glcp(client, [(r.serial, r.mac) for r in with_mac])
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}
        ok_serials = [r.serial for r in results if r.ok]
        if ok_serials:
            sheet_module.mark_added_to_glcp(sheet_path, ok_serials)
        out = self._results_dict(results)
        out["missing_mac"] = missing_mac
        return out

    def run_add_to_glcp(self) -> dict:
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        return self._run_add_to_glcp(sheet_path)

    def _run_assign_service(self, sheet_path) -> dict:
        """Assigns every row not yet marked Service Assigned, split by
        each row's own Device Type - UXI rows get the stored UXI
        application (credential_store's uxi entry), everything else
        auto-discovers Central's, same split run_onboard_batch always
        used. Split out (not just one restore_central_assignment call
        for everyone) so a mixed AP+UXI batch never has UXI rows
        accidentally grab Central's auto-discovered application_id -
        restore_central_assignment's auto-discovery just grabs ANY
        already-assigned device's id, it doesn't know about "UXI vs
        Central" on its own."""
        rows = sheet_module.read_devices(sheet_path)
        pending = [r for r in rows if not r.service_assigned]
        if not pending:
            return {"ok": True, "results": []}

        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-run-assign-service")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)

        uxi_serials = [r.serial for r in pending if r.device_type == "UXI"]
        central_serials = [r.serial for r in pending if r.device_type != "UXI"]
        results: list = []
        try:
            if central_serials:
                results.extend(central.restore_central_assignment(client, central_serials, None, None))
            if uxi_serials:
                active = credential_store.get_active_account()
                uxi_app = credential_store.get_uxi_application(active) if active else None
                if uxi_app is None:
                    results.extend(
                        central.UnassignResult(
                            s, False, "No UXI application_id stored for the selected account - set it in Credentials first."
                        )
                        for s in uxi_serials
                    )
                else:
                    results.extend(
                        central.restore_central_assignment(
                            client, uxi_serials, uxi_app["application_id"], uxi_app.get("region")
                        )
                    )
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}

        ok_serials = [r.serial for r in results if r.ok]
        if ok_serials:
            sheet_module.mark_service_assigned(sheet_path, ok_serials)
        return self._results_dict(results)

    def run_assign_service(self) -> dict:
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        return self._run_assign_service(sheet_path)

    def _run_assign_subscription(self, sheet_path) -> dict:
        """Assigns every row with a Subscription Key set and not yet
        marked Subscription Assigned, grouped by each row's own key
        (one assign_subscription call per distinct key, not per row)."""
        rows = sheet_module.read_devices(sheet_path)
        by_key: dict[str, list[str]] = {}
        for r in rows:
            if r.subscription_key and not r.subscription_assigned:
                by_key.setdefault(r.subscription_key, []).append(r.serial)
        if not by_key:
            return {"ok": True, "results": []}

        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "The selected account has no New Central credentials - add them in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-run-assign-subscription")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
        try:
            results = []
            for key, serials in by_key.items():
                results.extend(central.assign_subscription(client, serials, key))
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}

        ok_serials = [r.serial for r in results if r.ok]
        if ok_serials:
            sheet_module.mark_subscription_assigned(sheet_path, ok_serials)
        return self._results_dict(results)

    def run_assign_subscription(self) -> dict:
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        return self._run_assign_subscription(sheet_path)

    def run_onboard_batch(self) -> dict:
        """Runs Add to GLCP -> Assign Service -> Assign Subscription ->
        Pre-Provision, each step against the CURRENT working sheet (see
        the _run_X methods above/_run_preprovision below) - every step
        is independent, gated only on its own tracking column, not on a
        previous step's success or on whether THIS run's Add to GLCP
        touched a given row: a row already added to GLCP in an earlier
        run still gets picked up here if it's still missing its
        service/subscription/group. Pre-provisioning is skipped (not
        failed) when no Classic Central credentials are stored, since
        GLCP-side onboarding shouldn't be blocked on a platform this
        workspace may not use yet."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}

        add_result = self._run_add_to_glcp(sheet_path)
        if not add_result.get("ok") and "error" in add_result:
            return add_result
        service_result = self._run_assign_service(sheet_path)
        if not service_result.get("ok") and "error" in service_result:
            return service_result
        subscription_result = self._run_assign_subscription(sheet_path)
        if not subscription_result.get("ok") and "error" in subscription_result:
            return subscription_result

        preprov_result = self._run_preprovision(sheet_path)
        if not preprov_result.get("ok") and "error" in preprov_result:
            # Missing Classic Central creds shouldn't fail a batch whose
            # GLCP-side steps may have already succeeded - surface it as
            # a skip, not a batch failure.
            preprov_result = {"ok": True, "provisioned": 0, "failed": 0, "skipped": preprov_result["error"]}

        return {
            "ok": True,
            "add_device": add_result,
            "service": service_result,
            "subscription": subscription_result,
            "preprovision": preprov_result,
        }

    # --- Pre-provision (Classic Central group) -----------------------------

    def _run_preprovision(self, sheet_path) -> dict:
        """Shared by preprovision() (standalone re-run) and
        run_onboard_batch() above. Assigns every working-sheet row with
        a Target Group set and not yet marked Preprovisioned to that
        group in Classic Central, via
        central_classic.preprovision_device_to_group (batches of up to
        50 serials per group). Returns {"ok": False, "error": "..."}
        when no Classic Central credentials are stored, same as every
        other creds-gated method here - run_onboard_batch (the only
        caller besides the standalone preprovision() below) downgrades
        that specific case to a non-fatal "skipped" note rather than
        failing the whole batch."""
        rows = sheet_module.read_devices(sheet_path)
        by_group: dict[str, list[str]] = {}
        for r in rows:
            if r.target_group and not r.preprovisioned:
                by_group.setdefault(r.target_group, []).append(r.serial)
        if not by_group:
            return {"ok": True, "provisioned": 0, "failed": 0}

        transcript = Transcript(prefix="gui-preprovision")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}

        provisioned: list[str] = []
        failed = 0
        for group, serials in by_group.items():
            for i in range(0, len(serials), _PREPROVISION_CHUNK_SIZE):
                chunk = serials[i:i + _PREPROVISION_CHUNK_SIZE]
                try:
                    central_classic.preprovision_device_to_group(classic_client, group, chunk)
                except central_classic.ClassicAPIError:
                    failed += len(chunk)
                    continue
                provisioned.extend(chunk)

        if provisioned:
            sheet_module.mark_preprovisioned(sheet_path, provisioned)
        return {"ok": failed == 0, "provisioned": len(provisioned), "failed": failed}

    def preprovision(self) -> dict:
        """Standalone re-run of the pre-provision step alone (e.g. to
        retry rows that failed, without re-running the GLCP steps)."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        return self._run_preprovision(sheet_path)

    def preprovision_manual(self, identifiers: list[str], group: str) -> dict:
        """Manual, single-shot counterpart to preprovision()/
        run_onboard_batch's pre-provision step - assigns an explicit
        list of identifiers to an explicit group, for devices not
        tracked in the working sheet at all. NOTE: Classic Central's
        /configuration/v1/devices/move endpoint (preprovision_device_to_
        group) is documented as taking serial numbers specifically -
        unlike the GLCP-side manual cards above, a MAC address here is
        unverified and may be rejected by the API."""
        if not identifiers or not group:
            return {"ok": False, "error": "Serial(s)/MAC(s) and Group are required."}
        transcript = Transcript(prefix="gui-preprovision-manual")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}

        provisioned: list[str] = []
        failed = 0
        for i in range(0, len(identifiers), _PREPROVISION_CHUNK_SIZE):
            chunk = identifiers[i:i + _PREPROVISION_CHUNK_SIZE]
            try:
                central_classic.preprovision_device_to_group(classic_client, group, chunk)
            except central_classic.ClassicAPIError:
                failed += len(chunk)
                continue
            provisioned.extend(chunk)

        sheet_path = workspace.get_sheet()
        if provisioned and sheet_path is not None:
            sheet_module.mark_preprovisioned(sheet_path, provisioned)
        return {"ok": failed == 0, "provisioned": len(provisioned), "failed": failed}

    def check_full_status(self, identifier: str) -> dict:
        """Check Status card's real answer - identifier may be a serial
        OR a MAC. Looks up state across both platforms this tool
        touches: GLCP/New Central (device presence, service/application
        assignment, subscription) via list_glp_devices, then Classic
        Central (pre-provisioned group, site, check-in status) via
        get_device_status (AP, switch or gateway - GLCP's deviceType,
        if present, only decides which endpoint is tried first). The
        Classic Central endpoints are serial-keyed, so
        a MAC identifier is resolved to its serial from the GLCP match
        first - if the device isn't in GLCP yet (or no New Central
        creds are stored), a MAC input can't be resolved and the
        Classic Central section is skipped rather than guessed at."""
        identifier = identifier.strip()
        if not identifier:
            return {"ok": False, "error": "Serial or MAC is required."}
        mac = central.normalize_mac(identifier)
        is_mac_input = mac is not None
        serial = None if is_mac_input else identifier

        result: dict = {"ok": True, "identifier": identifier}
        type_hint = None

        creds = self._glp_creds()
        if creds is None:
            result["glcp"] = {"skipped": "The selected account has no New Central credentials."}
        else:
            client_id, client_secret = creds
            transcript = Transcript(prefix="gui-check-status-glcp")
            client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)
            try:
                devices = central.list_glp_devices(client)
            except (central.CentralAuthError, central.CentralAPIError) as exc:
                result["glcp"] = {"error": str(exc)}
            else:
                match = next(
                    (d for d in devices if d.serial == identifier or (mac and d.mac_address == mac)), None
                )
                if match is None:
                    result["glcp"] = {"in_glcp": False}
                else:
                    serial = match.serial
                    type_hint = _GLCP_DEVICE_TYPE_HINT.get(str(match.raw.get("deviceType") or "").upper())
                    result["glcp"] = {
                        "in_glcp": True,
                        "mac": match.mac_address,
                        "service_assigned": bool(match.application_id),
                        "subscription_tier": match.subscription_tier,
                        "subscription_end": match.subscription_end,
                    }

        if serial is None:
            result["classic"] = {"skipped": "Device not found in GLCP - can't resolve a serial from this MAC."}
            return result

        transcript = Transcript(prefix="gui-check-status-classic")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            result["classic"] = {"skipped": error}
            return result
        try:
            status = central_classic.get_device_status(classic_client, serial, type_hint)
        except (central_classic.ClassicAuthError, central_classic.ClassicAPIError) as exc:
            result["classic"] = {"error": str(exc)}
            return result
        result["classic"] = {
            "checked_in": status.seen,
            "device_type": status.device_type,
            "status": status.status,
            "group": status.group_name,
            "site": status.site_name,
        }
        return result

    # --- Assign Site (manual, run once devices have checked in) -----------

    def get_classic_sites(self) -> dict:
        transcript = Transcript(prefix="gui-classic-sites")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}
        try:
            sites = central_classic.list_sites(classic_client)
        except (central_classic.ClassicAuthError, central_classic.ClassicAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "sites": sorted(sites)}

    def assign_site(self) -> dict:
        """Assigns every working-sheet row with a Target Site set and
        not yet marked Site Assigned - a deliberate, manual, operator-
        triggered step (not an automatic background poll), run once the
        operator knows those devices have actually checked into Central.
        Grouped by (Target Site, Device Type) since Classic Central's
        site-association call takes one device_type per call."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        rows = sheet_module.read_devices(sheet_path)
        by_site_and_type: dict[tuple[str, str], list[str]] = {}
        unrecognized_types: set[str] = set()
        for r in rows:
            if not (r.target_site and not r.site_assigned):
                continue
            classic_type = _DEVICE_TYPE_TO_CLASSIC.get(r.device_type or "")
            if classic_type is None:
                unrecognized_types.add(r.device_type or "(blank)")
                continue
            by_site_and_type.setdefault((r.target_site, classic_type), []).append(r.serial)

        if not by_site_and_type:
            return {"ok": True, "assigned": 0, "failed": 0, "unresolved_sites": [], "unrecognized_types": sorted(unrecognized_types)}

        transcript = Transcript(prefix="gui-assign-site")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}
        try:
            site_ids = central_classic.list_sites(classic_client)
        except (central_classic.ClassicAuthError, central_classic.ClassicAPIError) as exc:
            return {"ok": False, "error": str(exc)}

        unresolved = sorted({site for (site, _t) in by_site_and_type if site not in site_ids})
        assigned: list[str] = []
        failed = 0
        for (site, device_type), serials in by_site_and_type.items():
            site_id = site_ids.get(site)
            if site_id is None:
                continue
            for i in range(0, len(serials), _PREPROVISION_CHUNK_SIZE):
                chunk = serials[i:i + _PREPROVISION_CHUNK_SIZE]
                try:
                    central_classic.associate_devices_to_site(classic_client, site_id, device_type, chunk)
                except central_classic.ClassicAPIError:
                    failed += len(chunk)
                    continue
                assigned.extend(chunk)

        if assigned:
            sheet_module.mark_site_assigned(sheet_path, assigned)

        return {
            "ok": failed == 0 and not unresolved,
            "assigned": len(assigned), "failed": failed,
            "unresolved_sites": unresolved, "unrecognized_types": sorted(unrecognized_types),
        }

    def assign_site_manual(self, identifiers: list[str], device_type: str, site_name: str) -> dict:
        """Manual, single-shot counterpart to assign_site above - assigns
        an explicit list of serials to an explicit site, for devices not
        tracked in the working sheet at all (or to jump ahead of its
        Target Site bookkeeping). Marks matching sheet rows Site
        Assigned on success, same as assign_site, but doesn't require
        the sheet to have a row for these serials."""
        classic_type = _DEVICE_TYPE_TO_CLASSIC.get(device_type)
        if classic_type is None:
            return {"ok": False, "error": f"Unrecognized device type: {device_type!r}"}
        if not identifiers:
            return {"ok": False, "error": "Serial(s) are required."}

        transcript = Transcript(prefix="gui-assign-site-manual")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}
        try:
            site_ids = central_classic.list_sites(classic_client)
        except (central_classic.ClassicAuthError, central_classic.ClassicAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        site_id = site_ids.get(site_name)
        if site_id is None:
            return {"ok": False, "error": f"Site not found in Classic Central: {site_name!r}"}

        assigned: list[str] = []
        failed = 0
        for i in range(0, len(identifiers), _PREPROVISION_CHUNK_SIZE):
            chunk = identifiers[i:i + _PREPROVISION_CHUNK_SIZE]
            try:
                central_classic.associate_devices_to_site(classic_client, site_id, classic_type, chunk)
            except central_classic.ClassicAPIError:
                failed += len(chunk)
                continue
            assigned.extend(chunk)

        sheet_path = workspace.get_sheet()
        if assigned and sheet_path is not None:
            sheet_module.mark_site_assigned(sheet_path, assigned)

        return {"ok": failed == 0, "assigned": len(assigned), "failed": failed}

    # --- Set Hostname (Post Onboard - New Central System Information) -------

    def _new_central_client(self, prefix: str) -> tuple[object, str | None]:
        creds = self._central_creds()
        if creds is None:
            return None, "The selected account has no New Central credentials - add them in Credentials first."
        base_url, client_id, client_secret = creds
        return central.CentralClient(base_url, client_id, client_secret, transcript=Transcript(prefix=prefix)), None

    def _set_hostnames(self, pairs: list[tuple[str, str]], prefix: str) -> tuple[list, str | None]:
        client, error = self._new_central_client(prefix)
        if error:
            return [], error
        try:
            return central.set_hostnames(client, pairs), None
        except central.CentralAuthError as exc:
            return [], str(exc)

    def run_set_hostname(self) -> dict:
        """Sets the hostname of every working-sheet row with a Hostname
        set and not yet marked Hostname Set (UXI rows skipped - not a New
        Central device). Each row's own Hostname value is used. Devices
        must already be provisioned in New Central (in a device group or
        site) - see core/central.py's set_hostname."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        rows = sheet_module.read_devices(sheet_path)
        pairs = [
            (r.serial, str(r.hostname).strip())
            for r in rows
            if r.hostname and str(r.hostname).strip() and not r.hostname_set and r.device_type != "UXI"
        ]
        if not pairs:
            return {"ok": True, "results": []}
        results, error = self._set_hostnames(pairs, "gui-run-set-hostname")
        if error:
            return {"ok": False, "error": error}
        ok_serials = [r.serial for r in results if r.ok]
        if ok_serials:
            sheet_module.mark_hostname_set(sheet_path, ok_serials)
        return self._results_dict(results)

    def set_hostname_manual(self, serials: list[str], hostnames: list[str]) -> dict:
        """Explicit serial/hostname pairs (paired in order), independent
        of the sheet. A matching sheet row is marked Hostname Set only if
        its own Hostname column equals the hostname just applied - a
        manual rename to something else shouldn't claim the sheet's
        planned hostname is done."""
        serials = [s.strip() for s in serials if s and s.strip()]
        hostnames = [h.strip() for h in hostnames if h and h.strip()]
        if not serials:
            return {"ok": False, "error": "Serial(s) are required."}
        if len(serials) != len(hostnames):
            return {"ok": False, "error": f"{len(serials)} serial(s) but {len(hostnames)} hostname(s) - they're paired in order."}
        pairs = list(zip(serials, hostnames))
        results, error = self._set_hostnames(pairs, "gui-set-hostname-manual")
        if error:
            return {"ok": False, "error": error}

        sheet_path = workspace.get_sheet()
        if sheet_path is not None and sheet_path.exists():
            applied = {r.serial: h for r, (_s, h) in zip(results, pairs) if r.ok}
            to_mark = [
                row.serial for row in sheet_module.read_devices(sheet_path)
                if row.serial in applied and str(row.hostname or "").strip() == applied[row.serial]
            ]
            if to_mark:
                sheet_module.mark_hostname_set(sheet_path, to_mark)
        return self._results_dict(results)
