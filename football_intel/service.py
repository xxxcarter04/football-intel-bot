from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .analysis.model import Prediction, predict
from .config import get_settings
from .data.base import build_context, current_season
from .data.demo import DemoProvider, get_provider
from .data.models import Match

log = logging.getLogger(__name__)


class AnalysisService:
    """Orchestrates data collection and modelling with a safe demo fallback."""

    def __init__(self):
        self.provider = get_provider()
        self.fallback = DemoProvider()
        self.settings = get_settings()

    def analyze(self, match: Match, history_seasons: int | None = None) -> Prediction:
        try:
            ctx = build_context(
                self.provider, match, history_seasons or self.settings.history_seasons
            )
        except Exception as exc:
            log.warning("Live provider failed (%s); using demo fallback", exc)
            ctx = build_context(self.fallback, match, history_seasons or self.settings.history_seasons)
            ctx.provider_error = str(exc)[:160]
        return predict(ctx)

    def upcoming(self, days: int = 2) -> list[Match]:
        try:
            return self.provider.upcoming(self.settings.leagues, days)
        except Exception as exc:
            log.warning("Upcoming fixtures failed (%s); using demo fallback", exc)
            return self.fallback.upcoming(self.settings.leagues, days)

    def digest(self, days: int = 2, limit: int = 12) -> list[Prediction]:
        return [self.analyze(m) for m in self.upcoming(days)[:limit]]

    def find_fixture(self, query_a: str, query_b: str) -> Match | None:
        try:
            parsed = self._find_fixture_with(self.provider, query_a, query_b)
            if parsed:
                return parsed
        except Exception as exc:
            log.warning("Fixture lookup failed (%s); using demo fallback", exc)
        return self._find_fixture_with(self.fallback, query_a, query_b)

    def _find_fixture_with(self, provider, query_a: str, query_b: str) -> Match | None:
        a = provider.search_team(query_a, self.settings.leagues)
        b = provider.search_team(query_b, self.settings.leagues)
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
