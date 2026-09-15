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

_CSV_HEADER_ALIASES = {
    "serial": "serial", "serial number": "serial", "serial_no": "serial", "serial_number": "serial",
    "mac": "mac", "mac address": "mac", "mac_address": "mac",
    "device type": "device_type", "device_type": "device_type", "type": "device_type",
    "target group": "target_group", "target_group": "target_group", "group": "target_group",
    "target site": "target_site", "target_site": "target_site", "site": "target_site",
    "subscription key": "subscription_key", "subscription_key": "subscription_key",
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

    # --- credentials -------------------------------------------------------

    def get_credentials(self) -> dict:
        return credential_store.load()

    def get_hints(self) -> dict:
        return creds_check.HINTS

    def wipe_credentials(self, category: str) -> dict:
        credential_store.clear_category(category)
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

    def test_central(self, account: str) -> dict:
        entry = credential_store.get_central_account(account) if account else None
        if entry is None:
            return {"ok": False, "detail": f"No stored account named '{account}' - Save it first."}
        ok, detail = creds_check.test_central_account(entry)
        return {"ok": ok, "detail": detail}

    def test_classic(self, account: str) -> dict:
        entry = credential_store.get_classic_account(account) if account else None
        if entry is None:
            return {"ok": False, "detail": f"No stored account named '{account}' - Save it first."}
        ok, detail = creds_check.test_classic_account(account, entry)
        return {"ok": ok, "detail": detail}

    def test_all(self) -> list[dict]:
        data = credential_store.load()
        results = creds_check.test_all(data)
        return [{"category": r.category, "key": r.key, "ok": r.ok, "detail": r.detail} for r in results]

    # --- credential resolution helpers -----------------------------------

    def _first_account(self, category: str) -> tuple[str, dict] | None:
        data = credential_store.load().get(category, {})
        if not data:
            return None
        name = next(iter(data))
        return name, data[name]

    def _central_creds(self) -> tuple[str, str, str] | None:
        found = self._first_account("central")
        if found is None:
            return None
        _, account = found
        return account["base_url"], account["client_id"], account["client_secret"]

    def _glp_creds(self) -> tuple[str, str] | None:
        """GLP reuses New Central's client_id/secret - always against
        central.GLP_BASE_URL, never the account's own regional base_url."""
        found = self._first_account("central")
        if found is None:
            return None
        _, account = found
        return account["client_id"], account["client_secret"]

    def _classic_creds(self) -> tuple[str, str, str, str, str] | None:
        found = self._first_account("classic")
        if found is None:
            return None
        account_name, account = found
        return (
            account["base_url"], account["client_id"], account["client_secret"],
            account["refresh_token"], account_name,
        )

    def _classic_client(self, transcript: Transcript | None = None) -> tuple[object, str] | None:
        creds = self._classic_creds()
        if creds is None:
            return None, "No Classic Central credentials stored - add one in Credentials first."
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
                    "subscription_key": r.subscription_key, "added_to_glcp": r.added_to_glcp,
                    "subscription_assigned": r.subscription_assigned, "service_assigned": r.service_assigned,
                    "preprovisioned": r.preprovisioned, "site_assigned": r.site_assigned, "notes": r.notes,
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
                writer.writerow(("Serial", "MAC", "Device Type", "Target Group", "Target Site", "Subscription Key"))
                writer.writerow(["CN12345678", "11:22:33:44:AA:BB", "AP", "Building-1-APs", "Building 1", "PAYHAH3YJE6THY"])
                writer.writerow(["CN87654321", "44:33:22:11:BB:AA", "Switch", "", "", ""])
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
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

    def run_onboard_batch(self) -> dict:
        """Runs Add to GLCP -> Assign Subscription -> Assign Service for
        every working-sheet row not yet marked Added to GLCP, using each
        row's own MAC/Subscription Key. Each step runs independently for
        a device, not gated on a previous step's success - a device
        already present in GLCP should still get its subscription/
        service steps attempted."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
        rows = sheet_module.read_devices(sheet_path)
        pending = [r for r in rows if not r.added_to_glcp]
        if not pending:
            return {"ok": True, "processed": 0, "add_device": None, "subscription": None, "service": None}

        creds = self._glp_creds()
        if creds is None:
            return {"ok": False, "error": "No New Central credentials stored - add one in Credentials first."}
        client_id, client_secret = creds
        transcript = Transcript(prefix="gui-run-onboard-batch")
        client = central.CentralClient(central.GLP_BASE_URL, client_id, client_secret, transcript=transcript)

        missing_mac = [r.serial for r in pending if not r.mac]
        with_mac = [r for r in pending if r.mac]

        try:
            add_results = central.add_devices_to_glcp(client, [(r.serial, r.mac) for r in with_mac])
            identifiers = [r.serial for r in with_mac]
            assignment_results = central.restore_central_assignment(client, identifiers, None, None)
            by_key: dict[str, list] = {}
            for r in with_mac:
                by_key.setdefault(r.subscription_key or "", []).append(r.serial)
            subscription_results = []
            for key, serials in by_key.items():
                if not key:
                    continue
                subscription_results.extend(central.assign_subscription(client, serials, key))
        except central.CentralAuthError as exc:
            return {"ok": False, "error": str(exc)}

        for label, results, marker in (
            ("add_device", add_results, sheet_module.mark_added_to_glcp),
            ("assignment", assignment_results, sheet_module.mark_service_assigned),
            ("subscription", subscription_results, sheet_module.mark_subscription_assigned),
        ):
            ok_serials = [r.serial for r in results if r.ok]
            if ok_serials:
                marker(sheet_path, ok_serials)

        return {
            "ok": True,
            "processed": len(with_mac),
            "missing_mac": missing_mac,
            "add_device": self._results_dict(add_results),
            "service": self._results_dict(assignment_results),
            "subscription": self._results_dict(subscription_results) if subscription_results else None,
        }

    # --- Pre-provision (Classic Central group) -----------------------------

    def preprovision(self) -> dict:
        """Assigns every working-sheet row with a Target Group set and
        not yet marked Preprovisioned to that group in Classic Central,
        via central_classic.preprovision_device_to_group (batches of up
        to 50 serials per group)."""
        sheet_path = workspace.get_sheet()
        if sheet_path is None:
            return {"ok": False, "error": "No working device list set."}
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

    def check_device_group(self, serial: str) -> dict:
        transcript = Transcript(prefix="gui-check-device-group")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}
        try:
            group = central_classic.get_device_group(classic_client, serial)
        except (central_classic.ClassicAuthError, central_classic.ClassicAPIError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "group": group}

    def check_ap_status(self, serial: str) -> dict:
        """Despite the name (Classic Central's own endpoint name - see
        core/central_classic.py), this works for any onboarded device
        type, not just APs."""
        transcript = Transcript(prefix="gui-check-status")
        classic_client, error = self._classic_client(transcript=transcript)
        if error:
            return {"ok": False, "error": error}
        try:
            status = central_classic.get_ap_status(classic_client, serial)
        except central_classic.ClassicAuthError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True, "seen": status.seen, "status": status.status, "group_name": status.group_name,
            "site_name": status.site_name, "firmware_version": status.firmware_version,
        }

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
