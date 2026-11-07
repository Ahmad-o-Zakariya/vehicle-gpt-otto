import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_capabilities import _median


class CapabilityTests(unittest.TestCase):
    def test_histogram_median_handles_even_and_odd_counts(self):
        self.assertEqual(0.1, _median(Counter({0.1: 3})))
        self.assertAlmostEqual(0.15, _median(Counter({0.1: 2, 0.2: 2})))
        self.assertIsNone(_median(Counter()))


if __name__ == "__main__":
    unittest.main()
