from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import get_settings
from .base import current_season, season_window
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


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class APIFootballProvider:
    name = "api-football"

    def __init__(self):
        s = get_settings()
        if not s.api_football_key:
            raise ValueError("API_FOOTBALL_KEY is not set")
        self.key = s.api_football_key
        self.host = s.api_football_host
        self.base = f"https://{self.host}/v3"
        self.cache = Cache(s.cache_ttl_hours)
        self.client = httpx.Client(
            headers={
                "x-rapidapi-key": self.key,
                "x-rapidapi-host": self.host,
            },
            timeout=25,
        )
        self._league_cache: dict[int, str] = {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get(self, path: str, params: dict | None = None, ttl: float | None = None) -> list | dict:
        params = params or {}
        cache_key = f"{self.name}:{path}:{sorted(params.items())}"
        cached = self.cache.get(cache_key, ttl)
        if cached is not None:
            return cached
        r = self.client.get(f"{self.base}/{path}", params=params)
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"API-Football error: {body['errors']}")
        result = body.get("response", [])
        self.cache.set(cache_key, result)
        return result

    # ---------- parsing ----------
    @staticmethod
    def _parse_match(item: dict) -> Match:
        fx = item["fixture"]
        league = item["league"]
        teams = item["teams"]
        goals = item.get("goals") or {}
        referee = fx.get("referee") or ""
        return Match(
            id=fx["id"],
            date=_dt(fx["date"]),
            league_id=league["id"],
            season=league["season"],
            home_id=teams["home"]["id"],
            away_id=teams["away"]["id"],
            home_name=teams["home"]["name"],
            away_name=teams["away"]["name"],
            home_goals=goals.get("home"),
            away_goals=goals.get("away"),
            status=fx["status"]["short"],
            referee_id=int(referee.split()[0]) if referee and referee.split()[0].isdigit() else None,
            referee_name=" ".join(referee.split()[1:]) or referee,
            venue=(fx.get("venue") or {}).get("name", "") or "",
            round=league.get("round", "") or "",
        )

    # ---------- provider interface ----------
    def search_team(self, query: str, league_ids: list[int] | None = None) -> TeamRef | None:
        data = self._get("teams", {"search": query})
        if not data:
            return None
        items = data if isinstance(data, list) else [data]
        if league_ids:
            items = [i for i in items if i.get("league", {}).get("id") in league_ids] or items
        team = items[0]["team"]
        return TeamRef(
            id=team["id"],
            name=team["name"],
            code=team.get("code", "") or "",
            league_id=items[0].get("league", {}).get("id", 0),
            season=current_season(),
        )

    def team_ref(self, team_id: int, league_id: int, season: int, name: str = "") -> TeamRef:
        key = f"team:{team_id}"
        cached = self.cache.get(key, 7 * 86400)
        if cached:
            return TeamRef(**cached)
        data = self._get("teams", {"id": team_id, "league": league_id, "season": season})
        item = data[0] if data else {}
        team = item.get("team", {})
        ref = TeamRef(
            id=team_id,
            name=name or team.get("name", f"Team {team_id}"),
            code=team.get("code", "") or "",
            league_id=league_id,
            season=season,
        )
        self.cache.set(key, vars(ref))
        return ref

    def league_matches(self, league_id: int, season: int) -> list[Match]:
        start, end = season_window(season)
        ttl = 6 * 3600 if season >= current_season() else 7 * 86400
        data = self._get(
            "fixtures",
            {"league": league_id, "season": season, "from": start, "to": end},
            ttl=ttl,
        )
        return [self._parse_match(i) for i in data if i.get("fixture")]

    def upcoming(self, league_ids: list[int], days: int = 3) -> list[Match]:
        now = datetime.now(timezone.utc)
        start = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=days)).strftime("%Y-%m-%d")
        out: list[Match] = []
        for lid in league_ids:
            data = self._get(
                "fixtures",
                {"league": lid, "season": current_season(), "from": start, "to": end},
                ttl=15 * 60,
            )
            out.extend(self._parse_match(i) for i in data if i.get("fixture"))
        return sorted({m.id: m for m in out}.values(), key=lambda m: m.date)

    def h2h(self, team_a: int, team_b: int, limit: int = 12) -> list[Match]:
        data = self._get("fixtures", {"teamA": team_a, "teamB": team_b, "last": limit}, ttl=6 * 3600)
        return [self._parse_match(i) for i in data if i.get("fixture") and i["fixture"]["status"]["short"] == "FT"]

    def standings(self, league_id: int, season: int) -> dict[int, StandingRow]:
        data = self._get("standings", {"league": league_id, "season": season}, ttl=3600)
        if not data:
            return {}
        table = data[0]["standings"][0]
        out: dict[int, StandingRow] = {}
        for row in table:
            out[row["team"]["id"]] = StandingRow(
                team_id=row["team"]["id"],
                position=row["rank"],
                played=row["played"],
                points=row["points"],
                goals_for=row["goalsFor"],
                goals_against=row["goalsAgainst"],
                form=row.get("form", "") or "",
                description=row.get("description", "") or "",
            )
        return out

    def injuries(self, team_id: int) -> list[Injury]:
        data = self._get("injuries", {"team": team_id, "season": current_season()}, ttl=30 * 60)
        out = []
        for item in data:
            player = item.get("player", {})
            out.append(
                Injury(
                    team_id=team_id,
                    player=player.get("name", "Unknown"),
                    position=(player.get("position") or ""),
                    reason=(item.get("reason") or ""),
                    importance=0.8 if player.get("position") in ("Attacker", "Midfielder") else 0.6,
                )
            )
        return out

    def referee_stats(self, referee_id: int | None, season: int) -> RefereeStats:
        if not referee_id:
            return RefereeStats(referee_id=None, name="TBC")
        data = self._get("fixtures", {"idReferee": referee_id, "last": 40}, ttl=24 * 3600)
        matches = [self._parse_match(i) for i in data if i.get("fixture")]
        finished = [m for m in matches if m.played]
        if not finished:
            return RefereeStats(referee_id=referee_id, name="TBC")
        over = sum(1 for m in finished if (m.home_goals or 0) + (m.away_goals or 0) >= 3)
        home_wins = sum(1 for m in finished if m.result == "H")
        return RefereeStats(
            referee_id=referee_id,
            name=finished[-1].referee_name or "TBC",
            matches=len(finished),
            home_win_rate=round(100 * home_wins / len(finished), 1),
            over25_rate=round(100 * over / len(finished), 1),
            avg_penalties=0.0,  # enriched from events only when available; see README
        )

    def league_name(self, league_id: int, season: int) -> str:
        if league_id in self._league_cache:
            return self._league_cache[league_id]
        data = self._get("leagues", {"id": league_id, "season": season}, ttl=7 * 86400)
        name = data[0]["league"]["name"] if data else f"League {league_id}"
        self._league_cache[league_id] = name
        return name

    def team_stats(self, team: TeamRef, league_id: int, season: int) -> TeamStats:
        """Aggregate from match results (robust across provider data quirks)."""
        matches = [m for m in self.league_matches(league_id, season) if team.id in (m.home_id, m.away_id)]
        matches = [m for m in matches if m.played]
        stats = TeamStats(team_id=team.id, formation="", style="")
        form: list[tuple[str, str]] = []

        for m in matches:
            home = m.home_id == team.id
            gf, ga = (m.home_goals, m.away_goals) if home else (m.away_goals, m.home_goals)
            gf, ga = int(gf or 0), int(ga or 0)
            stats.played += 1
            stats.gf += gf
            stats.ga += ga
            if home:
                stats.gf_home += gf
                stats.ga_home += ga
            else:
                stats.gf_away += gf
                stats.ga_away += ga
            if gf > ga:
                stats.wins += 1
                letter = "W"
            elif gf == ga:
                stats.draws += 1
                letter = "D"
            else:
                stats.losses += 1
                letter = "L"
            stats.clean_sheets += int(ga == 0)
            stats.btts += int(gf > 0 and ga > 0)
            form.append((letter, f"{gf}-{ga}"))

        stats.form = form[-8:][::-1]

        # Optional enrichment from the statistics endpoint (xG, possession, formation).
        try:
            data = self._get(
                "teams/statistics",
                {"team": team.id, "league": league_id, "season": season},
                ttl=6 * 3600,
            )
            if isinstance(data, dict):
                stats.formation = (data.get("formation") or [{}])[0].get("formation", "") or ""
                goals_total = (data.get("goals") or {}).get("total", {})
                totals = goals_total.get("total", {})
                stats.goals.xg_for = _safe_float((data.get("xG") or {}).get("total", {}).get("total"))
                stats.goals.xg_against = _safe_float((data.get("xGA") or {}).get("total", {}).get("total"))
                stats.goals.big_chances_for = _safe_float(totals.get("big_chances"))
                stats.possession = _safe_float(
                    (data.get("ball possession") or {}).get("total")
                )
        except Exception:
            pass

        if stats.possession and stats.possession >= 55:
            stats.style = "possession"
        elif stats.possession and stats.possession < 45:
            stats.style = "counter"
        else:
            stats.style = "balanced"
        return stats


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
