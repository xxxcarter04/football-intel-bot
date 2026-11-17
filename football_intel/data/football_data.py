from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from httpx import HTTPStatusError

from ..config import get_settings
from .base import current_season
from .cache import Cache
from .models import (
    GoalProfile,
    Injury,
    Match,
    RefereeStats,
    StandingRow,
    TeamRef,
    TeamStats,
)

# API-Football league id -> football-data.org competition code
CODES = {39: "PL", 140: "PD", 135: "SA", 78: "BL1", 61: "FL1", 2: "CL"}
CANON = {v: k for k, v in CODES.items()}
NAMES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1", 2: "Champions League"}


class FootballDataProvider:
    name = "football-data"

    def __init__(self):
        s = get_settings()
        if not s.football_data_token:
            raise ValueError("FOOTBALL_DATA_TOKEN is not set")
        self.client = httpx.Client(
            headers={"X-Auth-Token": s.football_data_token}, timeout=25
        )
        self.base = "https://api.football-data.org/v4"
        self.cache = Cache(s.cache_ttl_hours)

    @retry(
        retry=retry_if_exception_type(HTTPStatusError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=20),
    )
    def _get(self, path: str, params: dict | None = None, ttl: float | None = None):
        params = params or {}
        key = f"{self.name}:{path}:{sorted(params.items())}"
        cached = self.cache.get(key, ttl)
        if cached is not None:
            return cached
        r = self.client.get(f"{self.base}/{path}", params=params)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "6"))
            import time
            time.sleep(min(max(retry_after, 6), 30))
        r.raise_for_status()
        body = r.json()
        self.cache.set(key, body)
        return body

    @staticmethod
    def _parse(item: dict) -> Match | None:
        if not item.get("homeTeam") or not item.get("awayTeam"):
            return None
        score = item.get("score", {}).get("fullTime", {})
        comp = item.get("competition", {})
        lid = CANON.get(comp.get("code", ""), comp.get("id", 39))
        return Match(
            id=item["id"],
            date=datetime.fromisoformat(item["utcDate"].replace("Z", "+00:00")),
            league_id=lid,
            season=int(item.get("season", {}).get("startDate", "2010")[:4]),
            home_id=item["homeTeam"]["id"],
            away_id=item["awayTeam"]["id"],
            home_name=item["homeTeam"].get("shortName") or item["homeTeam"]["name"],
            away_name=item["awayTeam"].get("shortName") or item["awayTeam"]["name"],
            home_goals=score.get("home"),
            away_goals=score.get("away"),
            status=item.get("status", "SCHEDULED"),
            venue=(item.get("venue") or {}).get("name", "") or "",
            round=item.get("matchday", "") and f"Matchday {item['matchday']}",
        )

    def _season_matches(self, league_id: int, season: int) -> list[Match]:
        code = CODES.get(league_id, "PL")
        start = f"{season}-08-01"
        end = f"{season + 1}-06-30"
        data = self._get(
            f"/competitions/{code}/matches",
            {"dateFrom": start, "dateTo": end, "limit": 400},
            ttl=3600 if season >= current_season() else 7 * 86400,
        )
        return [m for item in data.get("matches", []) if (m := self._parse(item))]

    def search_team(self, query: str, league_ids: list[int] | None = None) -> TeamRef | None:
        # football-data.org ignores `search` on some plans, so filter client-side.
        q = query.lower().strip()
        wanted = {
            CODES[lid] for lid in (league_ids or list(CODES))
            if lid in CODES
        }
        teams: list[dict] = []
        for offset in range(0, 1000, 100):
            data = self._get("/teams", {"limit": 100, "offset": offset}, ttl=7 * 86400)
            page = data.get("teams", [])
            teams.extend(page)
            if len(page) < 100:
                break

        exact = [t for t in teams if q in (t.get("name") or "").lower()
                 or q in (t.get("shortName") or "").lower()
                 or q == (t.get("tla") or "").lower()]
        if not exact:
            exact = [t for t in teams if any(word in (t.get("name") or "").lower() for word in q.split())]
        if not exact:
            return None
        if wanted:
            exact.sort(key=lambda t: 0 if (t.get("competition") or {}).get("code") in wanted else 1)
        team = exact[0]
        comp = (team.get("competition") or {}).get("code", "")
        return TeamRef(
            id=team["id"], name=team.get("shortName") or team["name"],
            code=team.get("tla", ""), league_id=CANON.get(comp, 39),
            season=current_season(),
        )

    def team_ref(self, team_id: int, league_id: int, season: int, name: str = "") -> TeamRef:
        return TeamRef(id=team_id, name=name or f"Team {team_id}", league_id=league_id, season=season)

    def upcoming(self, league_ids: list[int], days: int = 3) -> list[Match]:
        now = datetime.now(timezone.utc)
        out: list[Match] = []
        for lid in league_ids:
            data = self._get(
                f"/competitions/{CODES.get(lid, 'PL')}/matches",
                {
                    "dateFrom": now.strftime("%Y-%m-%d"),
                    "dateTo": (now + timedelta(days=days)).strftime("%Y-%m-%d"),
                },
                ttl=15 * 60,
            )
            out.extend(m for item in data.get("matches", []) if (m := self._parse(item)))
        return sorted({m.id: m for m in out}.values(), key=lambda m: m.date)

    def league_matches(self, league_id: int, season: int) -> list[Match]:
        return self._season_matches(league_id, season)

    def h2h(self, team_a: int, team_b: int, limit: int = 12) -> list[Match]:
        data = self._get(f"/teams/{team_a}/matches", {"limit": 200}, ttl=6 * 3600)
        all_matches = [m for item in data.get("matches", []) if (m := self._parse(item))]
        return sorted(
            [m for m in all_matches if m.played and team_b in (m.home_id, m.away_id)],
            key=lambda m: m.date,
            reverse=True,
        )[:limit]

    def standings(self, league_id: int, season: int) -> dict[int, StandingRow]:
        data = self._get(f"/competitions/{CODES.get(league_id, 'PL')}/standings", {"season": season}, ttl=3600)
        tables = (data.get("standings") or [{}])[0].get("table", [])
        out = {}
        for row in tables:
            team = row["team"]
            out[team["id"]] = StandingRow(
                team_id=team["id"], position=row["position"], played=row["playedGames"],
                points=row["points"], goals_for=row.get("goalsFor", 0),
                goals_against=row.get("goalsAgainst", 0), form=row.get("form", "") or "",
            )
        return out

    def injuries(self, team_id: int) -> list[Injury]:
        return []  # not available on football-data.org

    def referee_stats(self, referee_id: int | None, season: int) -> RefereeStats:
        return RefereeStats(referee_id=referee_id, name="TBC")  # not available

    def league_name(self, league_id: int, season: int) -> str:
        return NAMES.get(league_id, f"League {league_id}")

    def team_stats(self, team: TeamRef, league_id: int, season: int) -> TeamStats:
        matches = [
            m for m in self._season_matches(league_id, season)
            if team.id in (m.home_id, m.away_id) and m.played
        ]
        stats = TeamStats(team_id=team.id, style="balanced")
        form = []
        for m in matches:
            home = m.home_id == team.id
            gf, ga = int((m.home_goals if home else m.away_goals) or 0), int((m.away_goals if home else m.home_goals) or 0)
            stats.played += 1
            stats.gf += gf
            stats.ga += ga
            if home:
                stats.gf_home += gf
                stats.ga_home += ga
            else:
                stats.gf_away += gf
                stats.ga_away += ga
            letter = "W" if gf > ga else "D" if gf == ga else "L"
            stats.wins += letter == "W"
            stats.draws += letter == "D"
            stats.losses += letter == "L"
            stats.clean_sheets += ga == 0
            stats.btts += gf > 0 and ga > 0
            form.append((letter, f"{gf}-{ga}"))
        stats.form = form[-8:][::-1]
        stats.goals = GoalProfile()
        return stats
