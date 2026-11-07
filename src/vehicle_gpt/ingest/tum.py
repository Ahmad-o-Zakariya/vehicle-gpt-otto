"""TUM BMW i3 measurement loader; simulation files are intentionally excluded."""

from __future__ import annotations

import csv
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

from vehicle_gpt.storage.database import (
    convert_source_value,
    datetime_iso,
    insert_measurements,
    naive_datetime_ns,
    register_trip,
    register_vehicle,
    update_trip_bounds,
)


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference).group(0)
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def read_overview(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append(
                    "".join(
                        text.text or ""
                        for text in item.iter(f"{{{NS_MAIN}}}t")
                    )
                )
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheet = workbook.find(f"{{{NS_MAIN}}}sheets")[0]
        rel_id = sheet.attrib[f"{{{NS_REL}}}id"]
        target = rel_map[rel_id]
        target = target.lstrip("/") if target.startswith("/") else target
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheet_root = ElementTree.fromstring(book.read(target))

        rows = sheet_root.findall(f".//{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row")
        if not rows:
            raise ValueError(f"empty trip overview: {path}")
        header_row = rows[0]
        headers = {}
        for cell in header_row.findall(f"{{{NS_MAIN}}}c"):
            value = cell.find(f"{{{NS_MAIN}}}v")
            text = value.text if value is not None else ""
            if cell.attrib.get("t") == "s" and text:
                text = shared[int(text)]
            headers[_column_index(cell.attrib["r"])] = text
        trip_column = next(i for i, name in headers.items() if name == "Trip")
        date_column = next(i for i, name in headers.items() if name == "Date")

        starts = {}
        for row in rows[1:]:
            values = {}
            for cell in row.findall(f"{{{NS_MAIN}}}c"):
                index = _column_index(cell.attrib["r"])
                value = cell.find(f"{{{NS_MAIN}}}v")
                text = value.text if value is not None else ""
                if cell.attrib.get("t") == "s" and text:
                    text = shared[int(text)]
                values[index] = text
            trip = values.get(trip_column, "")
            start = values.get(date_column, "")
            if trip and start:
                starts[trip] = start
        return starts


def _mapping_by_field(catalogue: dict[str, object]) -> dict[str, tuple[str, dict, dict]]:
    result = {}
    for signal, spec in catalogue["signals"].items():
        for mapping in spec["source_mappings"]:
            if mapping["dataset"] == "tum_bmw_i3":
                result[mapping["field"]] = (signal, spec, mapping)
    return result


def _parse_overview_date(token: str) -> datetime:
    for pattern in ("%Y-%m-%d_%H-%M-%S", "%Y_%m_%d_%H-%M-%S"):
        try:
            return datetime.strptime(token, pattern)
        except ValueError:
            continue
    raise ValueError(f"unsupported TUM overview date format: {token!r}")


def load_tum(connection, catalogue: dict[str, object], root: Path) -> dict[str, object]:
    measurement_root = root / "DATASET/Measurement Data"
    overview = read_overview(measurement_root / "Overview.xlsx")
    fields = _mapping_by_field(catalogue)
    vehicle_id = "tum_bmw_i3:bmw_i3"
    register_vehicle(
        connection,
        vehicle_id,
        "single-BMW-i3-source-dataset",
        "tum_bmw_i3",
        "BMW",
        "i3",
        None,
        "EV",
        "TUM BMW i3 measurement set; model year not asserted from trip CSVs",
    )
    connection.commit()
    report = {
        "dataset": "tum_bmw_i3",
        "trips": 0,
        "source_rows": 0,
        "canonical_rows": 0,
        "rejected_rows": 0,
        "missing_values": 0,
        "files": 0,
        "sampling_intervals": {},
    }
    trip_bounds = {}
    observed_deltas = {}

    for path in sorted(measurement_root.glob("Trip*.csv")):
        trip_id = path.stem
        start_token = overview.get(trip_id)
        if not start_token:
            raise ValueError(f"trip start missing from Overview.xlsx: {trip_id}")
        start = _parse_overview_date(start_token)
        register_trip(
            connection,
            vehicle_id,
            trip_id,
            trip_id,
            "tum_bmw_i3",
            "trip_relative_seconds_plus_overview_local_wall_clock",
        )
        report["trips"] += 1
        report["files"] += 1
        rows_to_insert = []
        previous_time = None
        with path.open(encoding="cp1252", newline="") as source:
            reader = csv.DictReader(source, delimiter=";")
            if not reader.fieldnames or "Time [s]" not in reader.fieldnames:
                raise ValueError(f"unexpected TUM measurement header: {path}")
            for source_row, row in enumerate(reader, 2):
                if None in row:
                    report["rejected_rows"] += 1
                    continue
                try:
                    time_token = row["Time [s]"].strip()
                    elapsed = float(time_token)
                except (TypeError, ValueError):
                    report["rejected_rows"] += 1
                    continue
                report["source_rows"] += 1
                replay = start + timedelta(seconds=elapsed)
                source_file = path.relative_to(root).as_posix()
                if previous_time is not None:
                    delta = round(elapsed - previous_time, 4)
                    observed_deltas[delta] = observed_deltas.get(delta, 0) + 1
                previous_time = elapsed

                source_time_start = time_token
                replay_token = datetime_iso(replay)
                bounds = trip_bounds.get(trip_id)
                if bounds is None:
                    trip_bounds[trip_id] = [time_token, time_token, replay, replay]
                else:
                    if elapsed < float(bounds[0]):
                        bounds[0], bounds[2] = time_token, replay
                    if elapsed > float(bounds[1]):
                        bounds[1], bounds[3] = time_token, replay

                for field, (signal, spec, mapping) in fields.items():
                    if field not in row:
                        continue
                    value, quality = convert_source_value(row[field], mapping, spec)
                    if value is None:
                        report["missing_values"] += 1
                    rows_to_insert.append(
                        {
                            "vehicle_id": vehicle_id,
                            "trip_id": trip_id,
                            "signal": signal,
                            "unit": spec["unit"],
                            "ts_source": time_token,
                            "ts_source_seconds": elapsed,
                            "ts_replay": replay_token,
                            "ts_replay_ns": naive_datetime_ns(replay),
                            "timestamp_basis": "wall_clock_naive_local_from_overview_plus_trip_relative_seconds",
                            "value": value,
                            "quality_flag": quality,
                            "source_dataset": "tum_bmw_i3",
                            "source_file": source_file,
                            "source_row": source_row,
                            "source_field": field,
                            "source_unit": mapping["source_unit"],
                            "source_value": row[field],
                        }
                    )
                    if len(rows_to_insert) >= 20_000:
                        report["canonical_rows"] += insert_measurements(connection, rows_to_insert)
                        rows_to_insert.clear()
        if rows_to_insert:
            report["canonical_rows"] += insert_measurements(connection, rows_to_insert)
        connection.commit()
    for trip_id, bounds in trip_bounds.items():
        update_trip_bounds(
            connection,
            vehicle_id,
            trip_id,
            bounds[0],
            bounds[1],
            datetime_iso(bounds[2]),
            datetime_iso(bounds[3]),
        )
    connection.commit()
    report["sampling_intervals"] = {
        str(interval): count for interval, count in sorted(observed_deltas.items())
    }
    return report
