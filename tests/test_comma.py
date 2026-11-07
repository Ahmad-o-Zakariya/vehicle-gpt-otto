import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.ingest.comma2k19 import iter_decoded_samples, verify_segment


class CommaReplayTests(unittest.TestCase):
    def test_dbc_decode_matches_segment_processed_channels(self):
        segment = ROOT / "DATASET/comma2k19-master/Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40"
        result = verify_segment(segment)
        self.assertTrue(result["passed"])
        self.assertEqual(4974, result["steering_samples_compared"])
        self.assertEqual(4974, result["wheel_speed_samples_compared"])
        self.assertEqual(19896, result["wheel_speed_components_compared"])
        self.assertLessEqual(result["steering_max_abs_error_deg"], 1e-9)
        self.assertLessEqual(result["wheel_speed_max_abs_error_mps"], 1e-9)

    def test_decoded_source_rows_are_traceable(self):
        segment = ROOT / "DATASET/comma2k19-master/Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40"
        rows = list(iter_decoded_samples(segment))
        self.assertEqual(24870, len(rows))
        self.assertTrue(all(row["source_row"] > 0 and row["source_value"] for row in rows))
        self.assertEqual({"deg", "km/h"}, {row["source_unit"] for row in rows})
        self.assertEqual({"vehicle.steering_angle", "vehicle.wheel_speed_fl", "vehicle.wheel_speed_fr", "vehicle.wheel_speed_rl", "vehicle.wheel_speed_rr"}, {row["signal"] for row in rows})


if __name__ == "__main__":
    unittest.main()
