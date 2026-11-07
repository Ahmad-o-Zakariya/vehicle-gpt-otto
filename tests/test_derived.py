import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_derived import build, hash_outputs
from generate_overlays import _freeze_frame_metadata, _thermal_ramp_value


class DerivedTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            (ROOT / "src/vehicle_gpt/storage/schema.sql").read_text()
        )
        self.connection.execute(
            "INSERT INTO signal_catalog VALUES (?,?,?,?,?)",
            ("vehicle.speed", "m/s", "float", None, "speed"),
        )
        self.connection.execute(
            "INSERT INTO vehicle_registry VALUES (?,?,?,?,?,?,?,?)",
            ("v1", "1", "test", "T", "M", None, "EV", "fixture"),
        )
        self.connection.execute(
            "INSERT INTO trip_registry VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("v1", "t1", "t1", "test", "0", "12", "source_seconds", None, None, "real"),
        )
        base = 1_700_000_000_000_000_000
        for second in range(13):
            self.connection.execute(
                """INSERT INTO canonical_measurement(vehicle_id,trip_id,signal,unit,ts_source,
                   ts_source_seconds,ts_replay,ts_replay_ns,timestamp_basis,value,quality_flag,
                   provenance,source_dataset,source_file,source_row,source_field,source_unit,source_value)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "v1",
                    "t1",
                    "vehicle.speed",
                    "m/s",
                    str(second),
                    float(second),
                    None,
                    base + second * 1_000_000_000,
                    "source_seconds",
                    float(second),
                    "ok",
                    "real",
                    "test",
                    "fixture",
                    second + 1,
                    "speed",
                    "m/s",
                    str(second),
                ),
            )
        self.connection.execute(
            """INSERT INTO overlay_event VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "e1",
                "v1",
                "t1",
                "test.event",
                "12",
                None,
                base + 12_000_000_000,
                "synthetic",
                "inj1",
                "{}",
            ),
        )
        self.connection.execute(
            "INSERT INTO overlay_sample(event_id,signal,unit,ts_replay_ns,value,quality_flag,injection_id) VALUES (?,?,?,?,?,?,?)",
            (
                "e1",
                "vehicle.speed",
                "m/s",
                base + 12_000_000_000,
                50.0,
                "synthetic_injected",
                "inj1",
            ),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def _snapshot(self):
        return {
            table: self.connection.execute(
                f"SELECT * FROM {table} ORDER BY 1,2,3,4"
            ).fetchall()
            for table in (
                "derived_1hz",
                "trip_rollup",
                "event_window",
                "deviation_flag",
            )
        }

    def test_rebuild_is_deterministic_and_overlay_is_applied(self):
        build(self.connection)
        first = self._snapshot()
        first_hashes = hash_outputs(self.connection)
        value = self.connection.execute(
            "SELECT value,provenance FROM derived_1hz WHERE bucket_start_ns=?",
            (1_700_000_012_000_000_000,),
        ).fetchone()
        self.assertEqual((50.0, "synthetic"), value)
        self.assertTrue(first["event_window"])
        build(self.connection)
        self.assertEqual(first, self._snapshot())
        self.assertEqual(first_hashes, hash_outputs(self.connection))

    def _insert_speed_at(self, base, tick, value):
        ts_ns = base + tick
        seconds = 12 + tick / 1_000_000_000
        self.connection.execute(
            """INSERT INTO canonical_measurement(vehicle_id,trip_id,signal,unit,ts_source,
               ts_source_seconds,ts_replay,ts_replay_ns,timestamp_basis,value,quality_flag,
               provenance,source_dataset,source_file,source_row,source_field,source_unit,source_value)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "v1",
                "t1",
                "vehicle.speed",
                "m/s",
                str(seconds),
                seconds,
                None,
                ts_ns,
                "source_seconds",
                value,
                "ok",
                "real",
                "test",
                "fixture",
                tick,
                "speed",
                "m/s",
                str(value),
            ),
        )

    def _add_ten_hz_bucket_source(self, base):
        for index in range(1, 10):
            self._insert_speed_at(
                base, 12_000_000_000 + index * 100_000_000, float(index)
            )

    def test_overlay_replaces_entire_bucket_not_only_exact_timestamp(self):
        base = 1_700_000_000_000_000_000
        self._add_ten_hz_bucket_source(base)
        build(self.connection)
        row = self.connection.execute(
            "SELECT value,sample_count,provenance FROM derived_1hz WHERE vehicle_id='v1' AND trip_id='t1' AND signal='vehicle.speed' AND bucket_start_ns=?",
            (base + 12_000_000_000,),
        ).fetchone()
        self.assertEqual(row, (50.0, 1, "synthetic"))
        real_only = self.connection.execute(
            "SELECT value,provenance FROM derived_1hz WHERE vehicle_id='v1' AND trip_id='t1' AND signal='vehicle.speed' AND bucket_start_ns=?",
            (base + 11_000_000_000,),
        ).fetchone()
        self.assertEqual(real_only, (11.0, "real"))

    def test_multiple_overlays_aggregate_without_real_dilution(self):
        base = 1_700_000_000_000_000_000
        self._add_ten_hz_bucket_source(base)
        self.connection.execute(
            "INSERT INTO overlay_sample(event_id,signal,unit,ts_replay_ns,value,quality_flag,injection_id,provenance) VALUES (?,?,?,?,?,?,?,?)",
            (
                "e1",
                "vehicle.speed",
                "m/s",
                base + 12_100_000_000,
                60.0,
                "synthetic_injected",
                "inj1",
                "synthetic",
            ),
        )
        build(self.connection)
        row = self.connection.execute(
            "SELECT value,sample_count,provenance FROM derived_1hz WHERE vehicle_id='v1' AND trip_id='t1' AND signal='vehicle.speed' AND bucket_start_ns=?",
            (base + 12_000_000_000,),
        ).fetchone()
        self.assertEqual(row, (55.0, 2, "synthetic"))

    def test_synthetic_missingness_is_not_filled_from_source(self):
        base = 1_700_000_000_000_000_000
        self.connection.execute(
            "INSERT INTO signal_catalog VALUES (?,?,?,?,?)",
            ("thermal.coolant_temperature_inlet", "degC", "float", None, "coolant"),
        )
        self.connection.execute(
            """INSERT INTO canonical_measurement(vehicle_id,trip_id,signal,unit,ts_source,
               ts_source_seconds,ts_replay,ts_replay_ns,timestamp_basis,value,quality_flag,
               provenance,source_dataset,source_file,source_row,source_field,source_unit,source_value)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "v1",
                "t1",
                "thermal.coolant_temperature_inlet",
                "degC",
                "3",
                3.0,
                None,
                base + 3_000_000_000,
                "source_seconds",
                46.0,
                "ok",
                "real",
                "test",
                "fixture",
                30,
                "coolant",
                "degC",
                "46",
            ),
        )
        self.connection.execute(
            "INSERT INTO overlay_event VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "e2",
                "v1",
                "t1",
                "dropout",
                "3",
                None,
                base + 3_000_000_000,
                "synthetic",
                "inj2",
                "{}",
            ),
        )
        self.connection.execute(
            "INSERT INTO overlay_sample(event_id,signal,unit,ts_replay_ns,value,quality_flag,injection_id,provenance) VALUES (?,?,?,?,?,?,?,?)",
            (
                "e2",
                "thermal.coolant_temperature_inlet",
                "degC",
                base + 3_000_000_000,
                None,
                "synthetic_sensor_dropout",
                "inj2",
                "synthetic",
            ),
        )
        build(self.connection)
        row = self.connection.execute(
            "SELECT value,sample_count,quality_flag,provenance FROM derived_1hz WHERE signal='thermal.coolant_temperature_inlet' AND bucket_start_ns=?",
            (base + 3_000_000_000,),
        ).fetchone()
        self.assertEqual(row, (None, 1, "all_missing", "synthetic"))

    def test_thermal_ramp_uses_explicit_pointwise_source_baseline(self):
        self.assertEqual(_thermal_ramp_value(20.0, 21.0, -300, 300, 20), 20.0)
        self.assertEqual(_thermal_ramp_value(22.0, 21.0, -150, 300, 20), 32.0)
        self.assertEqual(_thermal_ramp_value(21.0, 21.0, 0, 300, 20), 41.0)
        self.assertEqual(_thermal_ramp_value(None, 21.0, -150, 300, 20), 31.0)

    def test_freeze_frame_keeps_source_snapshot_separate_from_injected_state(self):
        metadata = _freeze_frame_metadata(
            {"battery.temperature": 8.0, "coolant": 46.0},
            {"battery.temperature": 28.0, "coolant": None},
        )
        self.assertEqual(metadata["captured_source_values"]["battery.temperature"], 8.0)
        self.assertEqual(
            metadata["synthetic_injected_values_at_T0"]["battery.temperature"], 28.0
        )
        self.assertIsNone(metadata["synthetic_injected_values_at_T0"]["coolant"])
        self.assertEqual(
            metadata["captured_source_values_provenance"], "real_source_snapshot_at_T0"
        )


if __name__ == "__main__":
    unittest.main()
