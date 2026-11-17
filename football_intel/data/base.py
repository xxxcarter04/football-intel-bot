from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .models import (
    FixtureContext,
    Injury,
    Match,
    RefereeStats,
    StandingRow,
    TeamRef,
    TeamStats,
)


def current_season() -> int:
    """European leagues are labelled by their starting year."""
    now = datetime.now()
    return now.year if now.month >= 7 else now.year - 1


def season_window(season: int) -> tuple[str, str]:
    return f"{season}-07-01", f"{season + 1}-06-30"


class DataProvider(Protocol):
    name: str

    def search_team(self, query: str, league_ids: list[int] | None = None) -> TeamRef | None: ...
    def team_ref(self, team_id: int, league_id: int, season: int, name: str = "") -> TeamRef: ...
    def upcoming(self, league_ids: list[int], days: int = 3) -> list[Match]: ...
    def league_matches(self, league_id: int, season: int) -> list[Match]: ...
    def team_stats(self, team: TeamRef, league_id: int, season: int) -> TeamStats: ...
    def h2h(self, team_a: int, team_b: int, limit: int = 12) -> list[Match]: ...
    def standings(self, league_id: int, season: int) -> dict[int, StandingRow]: ...
    def injuries(self, team_id: int) -> list[Injury]: ...
    def referee_stats(self, referee_id: int | None, season: int) -> RefereeStats: ...
    def league_name(self, league_id: int, season: int) -> str: ...


def build_context(
    provider: DataProvider,
    match: Match,
    history_seasons: int = 5,
) -> FixtureContext:
    """Pull every signal we need for one fixture, using the provider abstraction."""
    season = match.season
    home_ref = provider.team_ref(match.home_id, match.league_id, season, match.home_name)
    away_ref = provider.team_ref(match.away_id, match.league_id, season, match.away_name)

    stats_home = provider.team_stats(home_ref, match.league_id, season)
    stats_away = provider.team_stats(away_ref, match.league_id, season)
    h2h = provider.h2h(match.home_id, match.away_id, limit=14)
    table = provider.standings(match.league_id, season)
    injuries = {match.home_id: provider.injuries(match.home_id), match.away_id: provider.injuries(match.away_id)}
    referee = provider.referee_stats(match.referee_id, season)

    # Historical matches across the requested window, used for strength fitting.
    history: list[Match] = []
    for s in range(season - history_seasons + 1, season + 1):
        history.extend(provider.league_matches(match.league_id, s))

    flags: list[str] = []
    home_row, away_row = table.get(match.home_id), table.get(match.away_id)
    if home_row and away_row:
        if abs(home_row.position - away_row.position) <= 4:
            flags.append("table_neighbours")
        if home_row.position >= len(table) - 2:
            flags.append("home_relegation_pressure")
        if away_row.position >= len(table) - 2:
            flags.append("away_relegation_pressure")
        if home_row.position <= 4 and away_row.position <= 4:
            flags.append("top_four_clash")
        if "Champions League" in home_row.description or "Champions League" in away_row.description:
            flags.append("european_qualification")
    if match.round.lower().startswith(("semi", "final", "quarter")):
        flags.append("knockout_stage")
    if len(h2h) >= 6:
        flags.append("rivalry")

    quality = 0.55
    quality += 0.12 if stats_home.played >= 5 else 0
    quality += 0.12 if stats_away.played >= 5 else 0
    quality += 0.08 if h2h else 0
    quality += 0.08 if table else 0
    quality += 0.05 if referee.matches else 0
    if any(injuries.values()):
        quality += 0.05

    return FixtureContext(
        match=match,
        home=stats_home,
        away=stats_away,
        h2h=h2h,
        standings=table,
        injuries=injuries,
        referee=referee,
        home_team=home_ref,
        away_team=away_ref,
        league_name=provider.league_name(match.league_id, season),
        importance_flags=flags,
        data_quality=min(1.0, quality),
        history=history,
    )
