import sqlite3
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.main = sqlite3.connect(":memory:")
        self.main.execute("PRAGMA foreign_keys = ON")
        self.main.executescript(
            (ROOT / "src/vehicle_gpt/storage/schema.sql").read_text()
        )

    def tearDown(self):
        self.main.close()

    def test_canonical_contract_and_ground_truth_isolation(self):
        columns = {
            row[1]
            for row in self.main.execute("PRAGMA table_info(canonical_measurement)")
        }
        self.assertTrue(
            {
                "vehicle_id",
                "trip_id",
                "signal",
                "unit",
                "ts_source",
                "ts_replay",
                "value",
                "quality_flag",
                "provenance",
                "source_dataset",
            }.issubset(columns)
        )
        self.assertNotIn(
            "injection",
            {
                row[0]
                for row in self.main.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            },
        )
        sidecar = sqlite3.connect(":memory:")
        sidecar.executescript(
            (ROOT / "src/vehicle_gpt/ground_truth/schema.sql").read_text()
        )
        sidecar_tables = {
            row[0]
            for row in sidecar.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue({"injection", "injection_signal", "split_manifest"} <= sidecar_tables)
        sidecar.close()

    def test_canonical_layer_rejects_synthetic_provenance(self):
        self.main.execute(
            "INSERT INTO signal_catalog VALUES (?, ?, ?, ?, ?)",
            ("vehicle.speed", "m/s", "float", None, "speed"),
        )
        self.main.execute(
            "INSERT INTO vehicle_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ved:455", "455", "ved", "Nissan", "Leaf", None, "EV", "VED static registry"),
        )
        self.main.execute(
            "INSERT INTO trip_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("ved:455", "trip:1", "1", "ved", "1", "2", "elapsed_ms", None, None, "real"),
        )
        values = (
            "ved:455", "trip:1", "vehicle.speed", "m/s", "100", 0.1,
            None, None, "elapsed_ms", 2.0, "ok", "synthetic", "ved", "a.csv", 2,
            "Vehicle Speed[km/h]", "km/h", "7.2",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.main.execute(
                """INSERT INTO canonical_measurement (
                    vehicle_id,trip_id,signal,unit,ts_source,ts_source_seconds,
                    ts_replay,ts_replay_ns,timestamp_basis,value,quality_flag,
                    provenance,source_dataset,source_file,source_row,source_field,
                    source_unit,source_value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )

    def test_catalogue_has_source_mapping_and_explicit_cadence(self):
        catalogue = yaml.safe_load((ROOT / "configs/signals.yaml").read_text())
        self.assertEqual(26, len(catalogue["signals"]))
        self.assertEqual("value / 3.6", catalogue["signals"]["vehicle.speed"]["source_mappings"][0]["conversion"])
        self.assertIsNone(catalogue["signals"]["vehicle.speed"]["expected_sampling_hz"])
        self.assertEqual(10, catalogue["signals"]["battery.temperature"]["source_mappings"][0]["expected_sampling_hz"])


if __name__ == "__main__":
    unittest.main()
