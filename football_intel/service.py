from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .analysis.model import Prediction, predict
from .analysis.picks import HotPick, candidate_signals
from .config import get_settings
from .data.base import build_context, current_season
from .data.demo import DemoProvider, TEAM_ALIASES, get_provider, normalize_name
from .data.models import Match

log = logging.getLogger(__name__)


def match_key(match: Match) -> str:
    """Stable callback key for a fixture (sign preserved, so ids never collide)."""
    return str(match.id)


class AnalysisService:
    """Orchestrates data collection and modelling with a safe demo fallback."""

    def __init__(self):
        self.provider = get_provider()
        self.fallback = DemoProvider()
        self.settings = get_settings()
        self._match_registry: dict[str, Match] = {}
        self._league_cache: dict[tuple, tuple[datetime, tuple[str, list[Prediction], bool]]] = {}

    def analyze(self, match: Match, history_seasons: int | None = None) -> Prediction:
        try:
            ctx = build_context(
                self.provider, match, history_seasons or self.settings.history_seasons
            )
        except Exception as exc:
            log.warning("Live provider failed (%s); using demo fallback", exc)
            ctx = build_context(self.fallback, match, history_seasons or self.settings.history_seasons)
            ctx.provider_error = str(exc)[:160]
        self._match_registry[match_key(match)] = match
        return predict(ctx)

    def match_for_key(self, key: str) -> Match | None:
        """Resolve a callback key produced by match_key()."""
        return self._match_registry.get(str(key))

    def clear_caches(self) -> None:
        """Used by the Refresh button."""
        self._league_cache.clear()
        cache = getattr(self.provider, "cache", None)
        if cache:
            cache.clear()

    def upcoming(self, days: int = 2) -> list[Match]:
        try:
            return self.provider.upcoming(self.settings.leagues, days)
        except Exception as exc:
            log.warning("Upcoming fixtures failed (%s); using demo fallback", exc)
            return self.fallback.upcoming(self.settings.leagues, days)

    def digest(self, days: int = 2, limit: int = 12) -> list[Prediction]:
        return [self.analyze(m) for m in self.upcoming(days)[:limit]]

    def _provider_fixtures(self, league_id: int, days: int) -> list[Match]:
        try:
            return [
                m for m in self.provider.upcoming([league_id], days)
                if m.league_id == league_id
            ]
        except Exception as exc:
            log.warning("League fixtures failed for %s (%s); using demo fallback", league_id, exc)
            return []

    def _league_teams(self, league_id: int) -> list[tuple[int, str]]:
        """Collect (id, name) pairs seen in league results, with a demo fallback."""
        for provider in (self.provider, self.fallback):
            try:
                matches = provider.league_matches(league_id, current_season())
            except Exception:
                continue
            teams: dict[int, str] = {}
            for m in matches:
                teams.setdefault(m.home_id, m.home_name)
                teams.setdefault(m.away_id, m.away_name)
            if len(teams) >= 2:
                return list(teams.items())
        return []

    def _sample_pairings(self, league_id: int, count: int, days: int) -> list[Match]:
        """Deterministic illustrative pairings when real fixtures are scarce.

        These are clearly flagged to the user by the report layer; they are not
        presented as scheduled matches.
        """
        teams = self._league_teams(league_id)
        if len(teams) < 2:
            return []
        out: list[Match] = []
        now = datetime.now(timezone.utc)
        n = len(teams)
        for i in range(max(0, count)):
            home = teams[i % n]
            away = teams[(i * 7 + 3) % n]
            if away[0] == home[0]:
                away = teams[(i * 7 + 4) % n]
            if away[0] == home[0]:
                continue
            out.append(Match(
                id=-(1_000_000 + league_id * 10_000 + i),
                date=now + timedelta(days=1 + (i % max(days, 1)), hours=(i % 8)),
                league_id=league_id, season=current_season(),
                home_id=home[0], away_id=away[0], home_name=home[1], away_name=away[1],
                status="NS", referee_name="TBC", round="Sample pairing",
            ))
        return out

    def league_predictions(
        self, league_id: int, days: int = 7, min_predictions: int = 10
    ) -> tuple[str, list[Prediction], bool]:
        """All predictions for ONE league, with at least `min_predictions` entries.

        Returns (league_name, predictions, sample_filled). Real scheduled fixtures
        always come first; sample pairings are appended only when needed.
        """
        days = max(1, days)
        cache_key = (league_id, days, min_predictions)
        cached = self._league_cache.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < 900:
            return cached[1]
        matches = self._provider_fixtures(league_id, max(days, 7))
        if not matches:
            matches = [
                m for m in self.fallback.upcoming([league_id], max(days, 7))
                if m.league_id == league_id
            ]
        matches = sorted(matches, key=lambda m: m.date)[:min_predictions]

        preds = [self.analyze(m) for m in matches]
        sample_filled = False
        if len(preds) < min_predictions:
            sample_filled = True
            for m in self._sample_pairings(league_id, min_predictions - len(preds), days):
                preds.append(self.analyze(m))

        try:
            name = self.provider.league_name(league_id, current_season())
        except Exception:
            name = ""
        if not name:
            try:
                name = self.fallback.league_name(league_id, current_season())
            except Exception:
                name = f"League {league_id}"
        result = (name, preds, sample_filled)
        self._league_cache[cache_key] = (datetime.now(timezone.utc), result)
        return result

    def hot_picks(self, days: int = 7, per_league: int = 2) -> list[HotPick]:
        """Strongest model signals across every configured league."""
        leagues = self.settings.leagues
        if not leagues:
            return []
        # Make sure the feature surfaces at least ten picks overall.
        per_league = max(per_league, (10 + len(leagues) - 1) // len(leagues))
        picks: list[HotPick] = []
        for league_id in leagues:
            name, preds, _ = self.league_predictions(league_id, days, min_predictions=10)
            chosen: list[HotPick] = []
            used_matches: set[str] = set()
            for pred in preds:
                key = match_key(pred.context.match)
                for signal in candidate_signals(pred, match_key=key):
                    if signal.match_key in used_matches:
                        continue
                    chosen.append(signal)
                    used_matches.add(signal.match_key)
                    break
            picks.extend(sorted(chosen, key=lambda p: (-p.strength, -p.probability))[:per_league])
        return sorted(picks, key=lambda p: (-p.strength, -p.probability))

    def find_fixture(self, query_a: str, query_b: str) -> Match | None:
        try:
            parsed = self._find_fixture_with(self.provider, query_a, query_b)
            if parsed:
                return parsed
        except Exception as exc:
            log.warning("Fixture lookup failed (%s); using demo fallback", exc)
        return self._find_fixture_with(self.fallback, query_a, query_b)

    @staticmethod
    def _resolve_query(provider, query: str):
        """Try raw, normalized and alias-expanded forms against a provider."""
        forms: list[str] = []
        for candidate in (query, normalize_name(query), TEAM_ALIASES.get(normalize_name(query), "")):
            candidate = candidate.strip()
            if candidate and candidate not in forms:
                forms.append(candidate)
        for form in forms:
            try:
                team = provider.search_team(form, None)
            except Exception:
                team = None
            if team:
                return team
        return None

    def _find_fixture_with(self, provider, query_a: str, query_b: str) -> Match | None:
        a = self._resolve_query(provider, query_a)
        b = self._resolve_query(provider, query_b)
        if not a or not b:
            return None

        try:
            for m in provider.upcoming(self.settings.leagues, 14):
                if {m.home_id, m.away_id} == {a.id, b.id}:
                    return m
        except Exception:
            pass

        h2h = provider.h2h(a.id, b.id, limit=1)
        league = a.league_id or self.settings.leagues[0]
        return Match(
            id=-abs(a.id * 10000 + b.id),
            date=datetime.now(timezone.utc) + timedelta(days=1),
            league_id=league,
            season=current_season(),
            home_id=a.id,
            away_id=b.id,
            home_name=a.name,
            away_name=b.name,
            status="NS",
            referee_id=h2h[0].referee_id if h2h else None,
            referee_name=h2h[0].referee_name if h2h else "TBC",
        )
