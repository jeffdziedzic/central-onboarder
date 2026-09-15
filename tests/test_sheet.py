from pathlib import Path

import openpyxl
import pytest

from central_onboarder.core import sheet as sheet_module


def _device(serial, **overrides):
    d = {
        "serial": serial, "mac": "11:22:33:44:AA:BB", "device_type": "AP",
        "target_group": "Building-1-APs", "target_site": "Building 1", "subscription_key": "KEY123",
    }
    d.update(overrides)
    return d


def test_add_devices_manual_creates_new_sheet_from_template(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    report = sheet_module.add_devices_manual(out, [_device("S1"), _device("S2")])
    assert report.rows_added == 2
    assert report.rows_updated == 0
    assert out.exists()

    rows = sheet_module.read_devices(out)
    assert {r.serial for r in rows} == {"S1", "S2"}


def test_add_devices_manual_merges_by_serial(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1", target_group="Old Group")])
    report = sheet_module.add_devices_manual(out, [_device("S1", target_group="New Group")])
    assert report.rows_added == 0
    assert report.rows_updated == 1
    rows = sheet_module.read_devices(out)
    assert len(rows) == 1
    assert rows[0].target_group == "New Group"


def test_add_devices_manual_skips_blank_serial(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    report = sheet_module.add_devices_manual(out, [_device(""), _device("S1")])
    assert report.skipped_blank_serial_rows == 1
    assert report.rows_added == 1


def test_add_devices_manual_never_touches_tracking_columns_on_merge(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1")])
    sheet_module.mark_added_to_glcp(out, ["S1"])
    sheet_module.add_devices_manual(out, [_device("S1", target_group="New Group")])
    rows = sheet_module.read_devices(out)
    assert rows[0].added_to_glcp == "Y"
    assert rows[0].target_group == "New Group"


def test_mark_functions_only_touch_matching_serials(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1"), _device("S2")])
    sheet_module.mark_preprovisioned(out, ["S1"])
    rows = {r.serial: r for r in sheet_module.read_devices(out)}
    assert rows["S1"].preprovisioned == "Y"
    assert rows["S2"].preprovisioned is None


def test_add_devices_from_csv_maps_rows(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    csv_rows = [{"serial": "S1", "mac": "AA:BB:CC:DD:EE:FF", "device_type": "Switch"}]
    report = sheet_module.add_devices_from_csv(csv_rows, out)
    assert report.rows_added == 1
    rows = sheet_module.read_devices(out)
    assert rows[0].device_type == "Switch"


def test_validate_sheet_schema_ok_for_fresh_sheet(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1")])
    result = sheet_module.validate_sheet_schema(out)
    assert result.ok is True
    assert result.mismatches == []


def test_validate_sheet_schema_detects_renamed_header(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1")])
    wb = openpyxl.load_workbook(out)
    wb[sheet_module.DEVICES_SHEET].cell(row=1, column=1).value = "Serial Number"
    wb.save(out)
    result = sheet_module.validate_sheet_schema(out)
    assert result.ok is False
    assert result.mismatches[0].column == 1


def test_expected_hash_guard_aborts_on_concurrent_edit(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1")])
    stale_hash = sheet_module.hash_existing(out)
    sheet_module.add_devices_manual(out, [_device("S2")])  # changes the file on disk

    report = sheet_module.add_devices_manual(out, [_device("S3")], expected_hash=stale_hash)
    assert report.aborted_reason is not None
    rows = sheet_module.read_devices(out)
    assert {r.serial for r in rows} == {"S1", "S2"}  # S3 never written


def test_load_destinations_populates_reference_sheet_and_dropdown(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    sheet_module.add_devices_manual(out, [_device("S1")])
    report = sheet_module.load_destinations(out, groups={"Group A": "id1"}, sites={"Site A": "id2"})
    assert report.groups_loaded == 1
    assert report.sites_loaded == 1
    wb = openpyxl.load_workbook(out)
    assert sheet_module.REFERENCE_SHEET in wb.sheetnames
    ref_ws = wb[sheet_module.REFERENCE_SHEET]
    assert ref_ws.cell(row=sheet_module.REF_DATA_START_ROW, column=sheet_module.REF_COL_GROUP).value == "Group A"


def test_grows_past_template_styled_range(tmp_path: Path):
    out = tmp_path / "device-list.xlsx"
    devices = [_device(f"S{i}") for i in range(sheet_module.TEMPLATE_STYLED_LAST_ROW + 5)]
    report = sheet_module.add_devices_manual(out, devices)
    assert report.rows_added == len(devices)
    rows = sheet_module.read_devices(out)
    assert len(rows) == len(devices)
