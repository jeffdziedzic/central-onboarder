"""Build/read/update the device onboarding list.

One tab does the work ('Devices') - unlike the sibling AOS8-to-AOS10
Conversion Tool's multi-tab batch-tracking workbook (that tool merges a
live SSH/API capture into an 'All APs' tab and stages a subset into
'Batch List'), this tool's device list has no live source to merge
from - every row is either typed into the GUI or imported from a CSV
the operator supplies. So there's just one editable list, plus a
hidden 'Reference' tab backing the Target Group/Target Site dropdowns,
same pattern as that sibling project's own load_destinations.

The workbook is the artifact of record - this module never keeps a
second copy of device data. It reads a sheet just long enough to merge
in new/changed rows and writes it straight back out.

'Devices' columns (1-indexed):
  1  Serial               operator-entered (key)
  2  MAC                  operator-entered
  3  Device Type          operator-entered - AP / Switch / Gateway (UXI
                           reserved for a future release, not offered
                           yet - see project README)
  4  Target Group         operator-entered - Classic Central group to
                           pre-provision into
  5  Target Site          operator-entered - New Central site to
                           assign once the device has checked in
  6  Subscription Key     operator-entered - GreenLake subscription key
                           to assign, may be blank (skip that step)
  7  Added to GLCP        tool-owned tracking, never operator-entered
  8  Subscription Assigned  tool-owned tracking
  9  Service Assigned     tool-owned tracking (Central application
                           assignment - see core/central.py's
                           restore_central_assignment)
  10 Preprovisioned       tool-owned tracking (Classic Central group)
  11 Site Assigned        tool-owned tracking (manual, run once the
                           device has checked into Central - see the
                           GUI's Assign Site screen)
  12 Notes                operator-entered, never touched by this module
"""

from __future__ import annotations

import hashlib
import re
from copy import copy
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation


class SheetLockedError(Exception):
    """Raised when saving the workbook fails because something else has
    it open (e.g. Excel). The underlying PermissionError is raised
    immediately, before any bytes are written - the original file is
    left completely untouched."""


def _save(wb: openpyxl.Workbook, path: Path) -> None:
    try:
        wb.save(path)
    except PermissionError as exc:
        raise SheetLockedError(
            f"could not save '{path}' - it looks like it's open in another program "
            f"(e.g. Excel). Close it there and try again. The file itself is untouched."
        ) from exc


DEVICES_SHEET = "Devices"
HEADER_ROW = 1
DATA_START_ROW = 2

COL_SERIAL = 1
COL_MAC = 2
COL_DEVICE_TYPE = 3
COL_TARGET_GROUP = 4
COL_TARGET_SITE = 5
COL_SUBSCRIPTION_KEY = 6
COL_ADDED_TO_GLCP = 7
COL_SUBSCRIPTION_ASSIGNED = 8
COL_SERVICE_ASSIGNED = 9
COL_PREPROVISIONED = 10
COL_SITE_ASSIGNED = 11
COL_NOTES = 12
NUM_COLUMNS = 12

# Operator-entered columns - a CSV import or manual-add merge writes
# these; nothing else in this module ever touches them.
EDITABLE_COLUMNS = (
    COL_SERIAL, COL_MAC, COL_DEVICE_TYPE, COL_TARGET_GROUP, COL_TARGET_SITE, COL_SUBSCRIPTION_KEY,
)
# Tool-owned tracking columns - written only by this module's mark_*
# functions, in response to a real GUI action's result.
TRACKING_COLUMNS = (
    COL_ADDED_TO_GLCP, COL_SUBSCRIPTION_ASSIGNED, COL_SERVICE_ASSIGNED,
    COL_PREPROVISIONED, COL_SITE_ASSIGNED,
)

DEVICE_TYPES = ("AP", "Switch", "Gateway")  # UXI deferred - see module docstring

EXPECTED_DEVICES_HEADERS = (
    "Serial", "MAC", "Device Type", "Target Group", "Target Site", "Subscription Key",
    "Added to GLCP", "Subscription Assigned", "Service Assigned", "Preprovisioned",
    "Site Assigned", "Notes",
)


@dataclass
class SchemaMismatch:
    column: int
    expected: str
    actual: object


@dataclass
class SchemaValidationResult:
    ok: bool
    mismatches: list[SchemaMismatch] = field(default_factory=list)


def validate_sheet_schema(sheet_path: Path) -> SchemaValidationResult:
    """Compares the Devices tab's actual header row against the current
    expected column layout, position for position - not just a count,
    since a reordered column would misread data just as badly as a
    missing one. Catches a sheet built under an older schema being
    silently misread under today's column offsets."""
    result = SchemaValidationResult(ok=True)
    wb = openpyxl.load_workbook(sheet_path, read_only=True)
    try:
        if DEVICES_SHEET not in wb.sheetnames:
            return result
        ws = wb[DEVICES_SHEET]
        for column, expected in enumerate(EXPECTED_DEVICES_HEADERS, start=1):
            actual = ws.cell(row=HEADER_ROW, column=column).value
            if actual != expected:
                result.ok = False
                result.mismatches.append(SchemaMismatch(column, expected, actual))
    finally:
        wb.close()
    return result


# The bundled template pre-formats and pre-validates rows 2-101 (borders,
# tracking-column fill, Device Type dropdown). A large device list runs
# past that easily - rows beyond it need formatting/validation extended
# by hand, or they render unstyled with no dropdown.
TEMPLATE_STYLED_LAST_ROW = 101
_DEVICE_TYPE_VALIDATION_SQREF = f"C2:C{TEMPLATE_STYLED_LAST_ROW}"

# Hidden reference sheet backing the Target Group / Target Site dropdowns
# - created on first use by load_destinations, not baked into the
# template, since not every device list needs live group/site data
# pulled in.
REFERENCE_SHEET = "Reference"
REF_COL_GROUP = 1
REF_COL_SITE = 2
REF_HEADER_ROW = 1
REF_DATA_START_ROW = 2
REF_MAX_ROWS = 500
_GROUP_REFERENCE_RANGE = (
    f"'{REFERENCE_SHEET}'!$A${REF_DATA_START_ROW}:$A${REF_DATA_START_ROW + REF_MAX_ROWS - 1}"
)
_SITE_REFERENCE_RANGE = (
    f"'{REFERENCE_SHEET}'!$B${REF_DATA_START_ROW}:$B${REF_DATA_START_ROW + REF_MAX_ROWS - 1}"
)
_TARGET_GROUP_COLUMN_LETTER = "D"
_TARGET_SITE_COLUMN_LETTER = "E"


@dataclass
class DeviceRow:
    serial: str
    mac: str | None
    device_type: str | None
    target_group: str | None
    target_site: str | None
    subscription_key: str | None
    added_to_glcp: str | None
    subscription_assigned: str | None
    service_assigned: str | None
    preprovisioned: str | None
    site_assigned: str | None
    notes: str | None


def read_devices(sheet_path: Path) -> list[DeviceRow]:
    wb = openpyxl.load_workbook(sheet_path)
    ws = wb[DEVICES_SHEET]
    rows = []
    for row_number in range(DATA_START_ROW, ws.max_row + 1):
        serial = ws.cell(row=row_number, column=COL_SERIAL).value
        if not serial:
            continue
        rows.append(
            DeviceRow(
                serial=serial,
                mac=ws.cell(row=row_number, column=COL_MAC).value,
                device_type=ws.cell(row=row_number, column=COL_DEVICE_TYPE).value,
                target_group=ws.cell(row=row_number, column=COL_TARGET_GROUP).value,
                target_site=ws.cell(row=row_number, column=COL_TARGET_SITE).value,
                subscription_key=ws.cell(row=row_number, column=COL_SUBSCRIPTION_KEY).value,
                added_to_glcp=ws.cell(row=row_number, column=COL_ADDED_TO_GLCP).value,
                subscription_assigned=ws.cell(row=row_number, column=COL_SUBSCRIPTION_ASSIGNED).value,
                service_assigned=ws.cell(row=row_number, column=COL_SERVICE_ASSIGNED).value,
                preprovisioned=ws.cell(row=row_number, column=COL_PREPROVISIONED).value,
                site_assigned=ws.cell(row=row_number, column=COL_SITE_ASSIGNED).value,
                notes=ws.cell(row=row_number, column=COL_NOTES).value,
            )
        )
    return rows


def _template_path() -> Path:
    return resources.files("central_onboarder.assets") / "device_list_template.xlsx"


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Called by the caller before starting a possibly-slow operation, so a
# later write can detect a concurrent edit at write time.
hash_existing = sha256_of_file


def _is_marked(value: object) -> bool:
    return isinstance(value, str) and value.strip().upper() == "Y"


@dataclass
class ExistingRow:
    row_number: int
    key: str | None
    values: dict[int, object]


@dataclass
class SourceRow:
    key: str
    sort_value: str
    values: dict[int, object]


def _load_existing_rows(ws) -> list[ExistingRow]:
    rows: list[ExistingRow] = []
    for row_number in range(DATA_START_ROW, ws.max_row + 1):
        key = ws.cell(row=row_number, column=COL_SERIAL).value
        any_value = any(
            ws.cell(row=row_number, column=c).value is not None for c in range(1, NUM_COLUMNS + 1)
        )
        if not any_value:
            continue
        values = {c: ws.cell(row=row_number, column=c).value for c in range(1, NUM_COLUMNS + 1)}
        rows.append(ExistingRow(row_number=row_number, key=key, values=values))
    return rows


def _copy_row_style(ws, src_row: int, dst_row: int) -> None:
    for col in range(1, NUM_COLUMNS + 1):
        src = ws.cell(row=src_row, column=col)
        dst = ws.cell(row=dst_row, column=col)
        dst.font = copy(src.font)
        dst.border = copy(src.border)
        dst.fill = copy(src.fill)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)
        dst.alignment = copy(src.alignment)


def _extend_row_formatting(ws, last_row: int) -> None:
    if last_row <= TEMPLATE_STYLED_LAST_ROW:
        return
    for row_number in range(TEMPLATE_STYLED_LAST_ROW + 1, last_row + 1):
        _copy_row_style(ws, TEMPLATE_STYLED_LAST_ROW, row_number)


def _extend_data_validation(ws, old_sqref: str, last_row: int, col_letters: str) -> None:
    if last_row <= TEMPLATE_STYLED_LAST_ROW:
        return
    first, last = col_letters
    new_sqref = f"{first}{DATA_START_ROW}:{last}{last_row}"
    for dv in ws.data_validations.dataValidation:
        if str(dv.sqref) == old_sqref:
            dv.sqref = new_sqref


def _find_column_validation(ws, column_letter: str) -> DataValidation | None:
    pattern = re.compile(rf"^{column_letter}{DATA_START_ROW}:{column_letter}\d+$")
    for dv in ws.data_validations.dataValidation:
        if pattern.match(str(dv.sqref)):
            return dv
    return None


def _set_column_list_validation(ws, column_letter: str, last_row: int, range_ref: str) -> None:
    """Create or update (never duplicate) a list validation on a column's
    data rows, sourced from a range reference elsewhere in the workbook."""
    dv = _find_column_validation(ws, column_letter)
    if dv is not None:
        dv.formula1 = range_ref
        dv.sqref = f"{column_letter}{DATA_START_ROW}:{column_letter}{last_row}"
        return
    dv = DataValidation(type="list", formula1=range_ref, allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{column_letter}{DATA_START_ROW}:{column_letter}{last_row}")


def _extend_column_list_validation_if_present(ws, column_letter: str, last_row: int) -> None:
    dv = _find_column_validation(ws, column_letter)
    if dv is not None:
        dv.sqref = f"{column_letter}{DATA_START_ROW}:{column_letter}{last_row}"


def _extend_auto_filter(ws, last_row: int) -> None:
    if last_row <= TEMPLATE_STYLED_LAST_ROW or not ws.auto_filter.ref:
        return
    from openpyxl.utils.cell import range_boundaries

    min_col, min_row, max_col, _max_row = range_boundaries(ws.auto_filter.ref)
    ws.auto_filter.ref = f"{ws.cell(row=min_row, column=min_col).coordinate}:" \
        f"{ws.cell(row=last_row, column=max_col).coordinate}"


def _merge_rows(ws, existing_rows: list[ExistingRow], source_rows: list[SourceRow]) -> tuple[set[str], int, int, int]:
    """Update matched rows in place (editable columns only - tracking
    columns and Notes are never touched by a merge), append unmatched
    source rows after the last existing row. Returns (matched_keys,
    rows_updated, rows_added, last_row)."""
    by_key = {r.key: r for r in source_rows}
    matched: set[str] = set()
    next_row = DATA_START_ROW
    rows_updated = 0

    for existing in existing_rows:
        next_row = max(next_row, existing.row_number + 1)
        src = by_key.get(existing.key) if existing.key else None
        if src is None:
            continue
        matched.add(existing.key)
        for col in EDITABLE_COLUMNS:
            ws.cell(row=existing.row_number, column=col).value = src.values.get(col)
        rows_updated += 1

    new_rows = sorted((r for r in source_rows if r.key not in matched), key=lambda r: r.sort_value)
    rows_added = 0
    for r in new_rows:
        row_number = next_row
        next_row += 1
        for col in EDITABLE_COLUMNS:
            ws.cell(row=row_number, column=col).value = r.values.get(col)
        rows_added += 1

    return matched, rows_updated, rows_added, next_row - 1


@dataclass
class MergeDevicesReport:
    rows_added: int = 0
    rows_updated: int = 0
    skipped_blank_serial_rows: int = 0
    aborted_reason: str | None = None


def _merge_devices(
    sheet_path: Path,
    devices: list[dict],
    out_path: Path | None,
    expected_hash: str | None,
) -> MergeDevicesReport:
    """Shared by add_devices_from_csv/add_devices_manual - devices is a
    list of dicts with keys serial/mac/device_type/target_group/
    target_site/subscription_key (any missing key treated as blank).
    Merges by serial: a matched row's editable columns are overwritten
    with the new values (last-imported wins), an unmatched one is
    appended. Tracking columns/Notes are never touched.

    If sheet_path doesn't exist yet, starts from the bundled template."""
    report = MergeDevicesReport()
    out_path = out_path or sheet_path

    if expected_hash is not None and Path(sheet_path).exists():
        current_hash = sha256_of_file(sheet_path)
        if current_hash != expected_hash:
            report.aborted_reason = (
                f"{sheet_path} changed on disk since it was read - aborting without writing"
            )
            return report

    if Path(sheet_path).exists():
        wb = openpyxl.load_workbook(sheet_path)
    else:
        wb = openpyxl.load_workbook(_template_path())
    ws = wb[DEVICES_SHEET]

    source_rows = []
    for d in devices:
        serial = (d.get("serial") or "").strip()
        if not serial:
            report.skipped_blank_serial_rows += 1
            continue
        source_rows.append(
            SourceRow(
                key=serial,
                sort_value=serial,
                values={
                    COL_SERIAL: serial,
                    COL_MAC: d.get("mac") or None,
                    COL_DEVICE_TYPE: d.get("device_type") or None,
                    COL_TARGET_GROUP: d.get("target_group") or None,
                    COL_TARGET_SITE: d.get("target_site") or None,
                    COL_SUBSCRIPTION_KEY: d.get("subscription_key") or None,
                },
            )
        )
    # last one wins on duplicate serials within the same import
    source_rows = list({r.key: r for r in source_rows}.values())

    existing_rows = _load_existing_rows(ws)
    matched, rows_updated, rows_added, last_row = _merge_rows(ws, existing_rows, source_rows)

    _extend_row_formatting(ws, last_row)
    _extend_data_validation(ws, _DEVICE_TYPE_VALIDATION_SQREF, last_row, "CC")
    _extend_auto_filter(ws, last_row)
    _extend_column_list_validation_if_present(ws, _TARGET_GROUP_COLUMN_LETTER, last_row)
    _extend_column_list_validation_if_present(ws, _TARGET_SITE_COLUMN_LETTER, last_row)

    report.rows_added = rows_added
    report.rows_updated = rows_updated
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    _save(wb, out_path)
    return report


def add_devices_manual(
    sheet_path: Path,
    devices: list[dict],
    out_path: Path | None = None,
    expected_hash: str | None = None,
) -> MergeDevicesReport:
    """Devices typed/edited directly in the GUI's Device List screen."""
    return _merge_devices(sheet_path, devices, out_path, expected_hash)


def add_devices_from_csv(
    csv_rows: list[dict],
    sheet_path: Path,
    out_path: Path | None = None,
    expected_hash: str | None = None,
) -> MergeDevicesReport:
    """csv_rows: already-parsed CSV rows (dicts) from the GUI's CSV
    import - column names expected to match EXPECTED_DEVICES_HEADERS'
    editable subset case-insensitively (Serial/MAC/Device Type/Target
    Group/Target Site/Subscription Key); the GUI layer is responsible
    for parsing the raw file and normalizing header names before
    calling this."""
    devices = [
        {
            "serial": row.get("serial", ""),
            "mac": row.get("mac", ""),
            "device_type": row.get("device_type", ""),
            "target_group": row.get("target_group", ""),
            "target_site": row.get("target_site", ""),
            "subscription_key": row.get("subscription_key", ""),
        }
        for row in csv_rows
    ]
    return _merge_devices(sheet_path, devices, out_path, expected_hash)


def _mark_column(
    sheet_path: Path, serials: list[str], column: int, out_path: Path | None, expected_hash: str | None
) -> MergeDevicesReport:
    report = MergeDevicesReport()
    out_path = out_path or sheet_path

    if expected_hash is not None:
        current_hash = sha256_of_file(sheet_path)
        if current_hash != expected_hash:
            report.aborted_reason = (
                f"{sheet_path} changed on disk since it was read - aborting without writing"
            )
            return report

    wb = openpyxl.load_workbook(sheet_path)
    ws = wb[DEVICES_SHEET]
    wanted = set(serials)
    marked = 0
    for row_number in range(DATA_START_ROW, ws.max_row + 1):
        if ws.cell(row=row_number, column=COL_SERIAL).value in wanted:
            ws.cell(row=row_number, column=column).value = "Y"
            marked += 1
    report.rows_updated = marked
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    _save(wb, out_path)
    return report


def mark_added_to_glcp(sheet_path: Path, serials: list[str], out_path: Path | None = None, expected_hash: str | None = None) -> MergeDevicesReport:
    return _mark_column(sheet_path, serials, COL_ADDED_TO_GLCP, out_path, expected_hash)


def mark_subscription_assigned(sheet_path: Path, serials: list[str], out_path: Path | None = None, expected_hash: str | None = None) -> MergeDevicesReport:
    return _mark_column(sheet_path, serials, COL_SUBSCRIPTION_ASSIGNED, out_path, expected_hash)


def mark_service_assigned(sheet_path: Path, serials: list[str], out_path: Path | None = None, expected_hash: str | None = None) -> MergeDevicesReport:
    return _mark_column(sheet_path, serials, COL_SERVICE_ASSIGNED, out_path, expected_hash)


def mark_preprovisioned(sheet_path: Path, serials: list[str], out_path: Path | None = None, expected_hash: str | None = None) -> MergeDevicesReport:
    return _mark_column(sheet_path, serials, COL_PREPROVISIONED, out_path, expected_hash)


def mark_site_assigned(sheet_path: Path, serials: list[str], out_path: Path | None = None, expected_hash: str | None = None) -> MergeDevicesReport:
    return _mark_column(sheet_path, serials, COL_SITE_ASSIGNED, out_path, expected_hash)


def _ensure_reference_sheet(wb: openpyxl.Workbook):
    if REFERENCE_SHEET in wb.sheetnames:
        ws = wb[REFERENCE_SHEET]
    else:
        ws = wb.create_sheet(REFERENCE_SHEET)
        ws.sheet_state = "hidden"
        ws.cell(row=REF_HEADER_ROW, column=REF_COL_GROUP).value = "Group"
        ws.cell(row=REF_HEADER_ROW, column=REF_COL_SITE).value = "Site"
    return ws


@dataclass
class LoadDestinationsReport:
    groups_loaded: int = 0
    sites_loaded: int = 0
    aborted_reason: str | None = None


def load_destinations(
    sheet_path: Path,
    groups: dict[str, str],
    sites: dict[str, str],
    out_path: Path | None = None,
    expected_hash: str | None = None,
) -> LoadDestinationsReport:
    """Refresh the hidden Reference tab and the Target Group / Target
    Site dropdowns on the Devices tab from live Central data. groups/
    sites are name -> ID dicts already fetched by the caller
    (core/central.py's list_device_groups / core/central_classic.py's
    list_sites) - this function never talks to Central itself.

    Never writes into Target Group/Site themselves - which destination
    a device gets is a decision a human makes; this only gives them a
    live list of valid names to pick from instead of free-typing one
    and risking a typo."""
    report = LoadDestinationsReport()
    out_path = out_path or sheet_path

    if len(groups) > REF_MAX_ROWS or len(sites) > REF_MAX_ROWS:
        report.aborted_reason = (
            f"{max(len(groups), len(sites))} entries exceeds the {REF_MAX_ROWS}-row reference "
            "list cap - contact the tool maintainer to raise it"
        )
        return report

    if expected_hash is not None:
        current_hash = sha256_of_file(sheet_path)
        if current_hash != expected_hash:
            report.aborted_reason = (
                f"{sheet_path} changed on disk since it was read - aborting without writing"
            )
            return report

    wb = openpyxl.load_workbook(sheet_path)
    ref_ws = _ensure_reference_sheet(wb)

    for r in range(REF_DATA_START_ROW, REF_DATA_START_ROW + REF_MAX_ROWS):
        ref_ws.cell(row=r, column=REF_COL_GROUP).value = None
        ref_ws.cell(row=r, column=REF_COL_SITE).value = None

    for i, name in enumerate(sorted(groups)):
        ref_ws.cell(row=REF_DATA_START_ROW + i, column=REF_COL_GROUP).value = name
    for i, name in enumerate(sorted(sites)):
        ref_ws.cell(row=REF_DATA_START_ROW + i, column=REF_COL_SITE).value = name

    devices_ws = wb[DEVICES_SHEET]
    last_row = max(devices_ws.max_row, TEMPLATE_STYLED_LAST_ROW)
    _set_column_list_validation(devices_ws, _TARGET_GROUP_COLUMN_LETTER, last_row, _GROUP_REFERENCE_RANGE)
    _set_column_list_validation(devices_ws, _TARGET_SITE_COLUMN_LETTER, last_row, _SITE_REFERENCE_RANGE)

    report.groups_loaded = len(groups)
    report.sites_loaded = len(sites)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    _save(wb, out_path)
    return report
