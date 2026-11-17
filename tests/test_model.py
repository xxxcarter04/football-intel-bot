import unittest

from football_intel.analysis.model import build_markets, predict
from football_intel.service import AnalysisService


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = AnalysisService()
        cls.fixture = cls.svc.find_fixture("Arsenal", "Chelsea")
        cls.pred = cls.svc.analyze(cls.fixture)

    def test_one_x_two_sums_to_one(self):
        p = self.pred.probs
        self.assertAlmostEqual(p["H"] + p["D"] + p["A"], 1.0, places=6)

    def test_dnb_has_no_draw(self):
        self.assertEqual(set(self.pred.markets["DNB"]), {"H", "A"})
        self.assertAlmostEqual(sum(self.pred.markets["DNB"].values()), 1.0, places=6)

    def test_over_under_complements(self):
        for line, v in self.pred.markets["OU"].items():
            self.assertAlmostEqual(v["over"] + v["under"], 1.0, places=6)

    def test_handicap_push_handling(self):
        for line, v in self.pred.markets["AH"].items():
            self.assertAlmostEqual(v["home"] + v["away"], 1.0, places=6)
            self.assertGreaterEqual(v["push"], 0)

    def test_lambdas_positive(self):
        self.assertGreater(self.pred.lam_home, 0)
        self.assertGreater(self.pred.lam_away, 0)


if __name__ == "__main__":
    unittest.main()
