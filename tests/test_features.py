"""Offline tests for per-league reports, hot picks and match lookup."""
import os
import unittest

# Force deterministic demo mode BEFORE importing config/service.
os.environ["API_FOOTBALL_KEY"] = ""
os.environ["FOOTBALL_DATA_TOKEN"] = ""

from football_intel.analysis.picks import HotPick, pick_strength  # noqa: E402
from football_intel.analysis.report import (  # noqa: E402
    render_hot_picks,
    render_league_predictions,
)
from football_intel.config import get_settings  # noqa: E402

get_settings.cache_clear()

from football_intel.service import AnalysisService  # noqa: E402


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = AnalysisService()

    def test_each_league_has_at_least_ten_predictions(self):
        expected = {39: "Premier League", 140: "La Liga", 135: "Serie A",
                    78: "Bundesliga", 61: "Ligue 1", 2: "Champions League"}
        for league_id, name in expected.items():
            with self.subTest(league=name):
                got_name, preds, _ = self.svc.league_predictions(league_id, days=7, min_predictions=10)
                self.assertEqual(got_name, name)
                self.assertGreaterEqual(len(preds), 10)
                self.assertTrue(all(p.context.match.league_id == league_id for p in preds))

    def test_hot_picks_cover_every_league_and_are_well_formed(self):
        picks = self.svc.hot_picks(days=7, per_league=2)
        self.assertGreaterEqual(len(picks), 10)
        self.assertGreaterEqual(len({p.league_id for p in picks}), 5)
        seen = set()
        for pick in picks:
            self.assertIsInstance(pick, HotPick)
            self.assertTrue(0 <= pick.strength <= 99)
            self.assertGreater(pick.probability, pick.baseline)
            self.assertTrue(pick.home_name and pick.away_name)
            identity = (pick.match_key, pick.market, pick.selection)
            self.assertNotIn(identity, seen)
            seen.add(identity)

    def test_renderers(self):
        _, preds, filled = self.svc.league_predictions(39, days=7, min_predictions=10)
        report = render_league_predictions("Premier League", preds, 7, filled)
        self.assertIn("Premier League", report)
        self.assertIn("10 predictions", report)
        self.assertIn("Gamble responsibly", report)

        picks = self.svc.hot_picks(7, 2)
        hot = render_hot_picks(picks, 7)
        for name in {p.league_name for p in picks}:
            self.assertIn(name, hot)
        self.assertIn("not a certainty", hot)

    def test_match_aliases(self):
        cases = [
            ("Man Utd", "Spurs"),
            ("Manchester United", "Tottenham Hotspur"),
            ("Juventus", "Inter"),
            ("barca", "real"),
        ]
        for a, b in cases:
            with self.subTest(match=f"{a} vs {b}"):
                match = self.svc.find_fixture(a, b)
                self.assertIsNotNone(match)
                self.assertTrue(match.home_name and match.away_name)

    def test_strength_is_bounded_and_monotonic(self):
        low = pick_strength(0.55, 0.5, 0.8)
        high = pick_strength(0.85, 0.5, 0.8)
        self.assertLess(low, high)
        self.assertTrue(all(0 <= pick_strength(p, 0.5, c) <= 99
                            for p in (0.0, 0.5, 1.0) for c in (0.0, 1.0)))


if __name__ == "__main__":
    unittest.main()
