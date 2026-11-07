import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_dataset import _dataset_name


class ManifestClassificationTests(unittest.TestCase):
    def test_source_paths_are_classified_by_dataset(self):
        cases = {
            "DATASET/VED-master/Data/dynamic.7z": "ved",
            "DATASET/Measurement Data/TripA01.csv": "tum_bmw_i3",
            "DATASET/Simulation Data/Scenario.csv": "tum_simulation",
            "DATASET/comma2k19-master/Example_1/log.npy": "comma2k19",
            "DATASET/OpenLKA-main/OpenLKA-Failure-Sample/a.csv": "openlka",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(expected, _dataset_name(path))


if __name__ == "__main__":
    unittest.main()
