"""Deterministic synthetic provider so the bot is fully usable with zero API keys.

Replace by setting API_FOOTBALL_KEY (or FOOTBALL_DATA_TOKEN) in .env.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from .base import current_season, season_window
from .models import (
    GoalProfile,
    Injury,
    Match,
    RefereeStats,
    StandingRow,
    TeamRef,
    TeamStats,
)

TEAMS: dict[int, list[tuple[int, str, float]]] = {
    39: [(42, "Arsenal", 1.30), (49, "Chelsea", 1.18), (50, "Man City", 1.38), (40, "Liverpool", 1.32),
         (6, "Man Utd", 1.10), (4, "Tottenham", 1.08), (5, "Newcastle", 1.02), (63, "Aston Villa", 1.00),
         (65, "Brighton", 0.98), (51, "West Ham", 0.92), (58, "Everton", 0.85), (66, "Brentford", 0.86)],
    140: [(541, "Real Madrid", 1.36), (529, "Barcelona", 1.32), (530, "Atletico", 1.18), (533, "Athletic Bilbao", 1.06),
          (536, "Villarreal", 1.04), (531, "Betis", 0.98), (548, "Valencia", 0.90), (543, "Sevilla", 0.92)],
    135: [(503, "Inter", 1.30), (505, "Juventus", 1.22), (498, "AC Milan", 1.20), (505 + 1, "Napoli", 1.18),
          (507, "Lazio", 1.02), (524, "Roma", 1.06), (502, "Fiorentina", 0.96), (517, "Atalanta", 1.08)],
    78: [(165, "Bayern", 1.40), (157, "Dortmund", 1.20), (156, "Leverkusen", 1.18), (526, "Leipzig", 1.10),
         (530 + 1, "Stuttgart", 1.00), (522, "Frankfurt", 0.98), (532, "Freiburg", 0.94), (168, "Wolfsburg", 0.92)],
    61: [(164, "PSG", 1.38), (524 + 1, "Marseille", 1.10), (521, "Lyon", 1.04), (496, "Monaco", 1.08),
         (538, "Lille", 1.02), (512, "Nice", 0.96), (484, "Lens", 0.96), (456, "Rennes", 0.92)],
    2: [(42, "Arsenal", 1.30), (50, "Man City", 1.38), (541, "Real Madrid", 1.36), (529, "Barcelona", 1.32),
        (165, "Bayern", 1.40), (503, "Inter", 1.30), (498, "AC Milan", 1.20), (505, "Juventus", 1.22)],
}
NAMES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1", 2: "Champions League"}
STRENGTH = {tid: s for teams in TEAMS.values() for tid, _, s in teams}
TEAM_NAMES = {tid: n for teams in TEAMS.values() for tid, n, _ in teams}


def _poisson(lam: float, rng: random.Random) -> int:
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


class DemoProvider:
    name = "demo"
    history_seasons = 5

    def __init__(self):
        self._cache: dict[tuple, list[Match]] = {}
        self._strength = STRENGTH

    def _season_matches(self, league_id: int, season: int) -> list[Match]:
        key = (league_id, season)
        if key in self._cache:
            return self._cache[key]
        teams = TEAMS.get(league_id, TEAMS[39])
        rng = random.Random(f"{league_id}-{season}")
        start, _ = season_window(season)
        base = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        matches: list[Match] = []
        mid = season * 100000 + league_id * 1000
        for a in range(len(teams)):
            for b in range(len(teams)):
                if a == b:
                    continue
                hid, hname, hs = teams[a]
                aid, aname, as_ = teams[b]
                lam_h = 1.55 * hs / as_ * 1.12
                lam_a = 1.35 * as_ / hs * 0.88
                hg, ag = _poisson(lam_h, rng), _poisson(lam_a, rng)
                date = base + timedelta(days=(len(matches) % 200) * 1.5)
                matches.append(Match(
                    id=mid + len(matches), date=date, league_id=league_id, season=season,
                    home_id=hid, away_id=aid, home_name=hname, away_name=aname,
                    home_goals=hg, away_goals=ag, status="FT",
                    referee_id=(mid % 7) + 1,
                    referee_name=["M. Oliver", "D. Orsato", "C. Turpin", "S. Marciniak", "J. Mohan", "A. Taylor", "F. Brych"][mid % 7],
                    venue=f"{hname} Stadium", round=f"Matchday {(len(matches) // len(teams)) + 1}",
                ))
        self._cache[key] = matches
        return matches

    def search_team(self, query: str, league_ids: list[int] | None = None) -> TeamRef | None:
        q = query.lower()
        for lid, teams in TEAMS.items():
            if league_ids and lid not in league_ids:
                continue
            for tid, name, _ in teams:
                if q in name.lower() or name.lower() in q:
                    return TeamRef(id=tid, name=name, league_id=lid, season=current_season())
        return None

    def team_ref(self, team_id: int, league_id: int, season: int, name: str = "") -> TeamRef:
        return TeamRef(
            id=team_id, name=name or TEAM_NAMES.get(team_id, f"Team {team_id}"),
            league_id=league_id, season=season,
        )

    def league_matches(self, league_id: int, season: int) -> list[Match]:
        return self._season_matches(league_id, season)

    def upcoming(self, league_ids: list[int], days: int = 3) -> list[Match]:
        season = current_season()
        out = []
        for lid in league_ids:
            teams = TEAMS.get(lid, TEAMS[39])
            rng = random.Random(f"next-{lid}-{season}")
            now = datetime.now(timezone.utc)
            for i in range(6):
                h, a = rng.sample(teams, 2)
                out.append(Match(
                    id=9_000_000 + lid * 1000 + i, date=now + timedelta(days=i % (days + 1)),
                    league_id=lid, season=season, home_id=h[0], away_id=a[0],
                    home_name=h[1], away_name=a[1], status="NS", referee_id=(i % 7) + 1,
                    referee_name=["M. Oliver", "D. Orsato", "C. Turpin", "S. Marciniak", "J. Mohan", "A. Taylor", "F. Brych"][i % 7],
                    venue=f"{h[1]} Stadium", round=f"Matchday {20 + i}",
                ))
        return sorted(out, key=lambda m: m.date)

    def h2h(self, team_a: int, team_b: int, limit: int = 12) -> list[Match]:
        all_matches = [
            m for lid in TEAMS for s in range(current_season() - self.history_seasons + 1, current_season() + 1)
            for m in self._season_matches(lid, s)
            if {team_a, team_b} == {m.home_id, m.away_id} and m.played
        ]
        return sorted(all_matches, key=lambda m: m.date, reverse=True)[:limit]

    def standings(self, league_id: int, season: int) -> dict[int, StandingRow]:
        rows = {t[0]: [t[0], 0, 0, 0, 0, 0, ""] for t in TEAMS.get(league_id, TEAMS[39])}
        for m in self._season_matches(league_id, season):
            if not m.played:
                continue
            rows[m.home_id][2] += 1
            rows[m.away_id][2] += 1
            rows[m.home_id][4] += m.home_goals or 0
            rows[m.home_id][5] += m.away_goals or 0
            rows[m.away_id][4] += m.away_goals or 0
            rows[m.away_id][5] += m.home_goals or 0
            if m.result == "H":
                rows[m.home_id][1] += 3
            elif m.result == "A":
                rows[m.away_id][1] += 3
            else:
                rows[m.home_id][1] += 1
                rows[m.away_id][1] += 1
        ordered = sorted(rows.values(), key=lambda r: (-r[1], -(r[4] - r[5])))
        out = {}
        for pos, r in enumerate(ordered, 1):
            out[r[0]] = StandingRow(r[0], pos, r[2], r[1], r[4], r[5], form="WWDLW"[: min(5, r[2])])
        return out

    def injuries(self, team_id: int) -> list[Injury]:
        rng = random.Random(f"inj-{team_id}-{current_season()}")
        names = ["Key striker", "Starting midfielder", "First-choice keeper", "Wing-back", "Centre-back"]
        if rng.random() < 0.35:
            return []
        picked = rng.sample(names, rng.randint(1, 3))
        return [Injury(team_id, n, "Attacker" if "striker" in n else "Midfielder" if "midfielder" in n else "Defender",
                       "Knock", 0.85 if "Key" in n else 0.6) for n in picked]

    def referee_stats(self, referee_id: int | None, season: int) -> RefereeStats:
        if not referee_id:
            return RefereeStats(None, "TBC")
        rng = random.Random(f"ref-{referee_id}")
        return RefereeStats(
            referee_id, f"Referee #{referee_id}", matches=28 + rng.randint(0, 12),
            avg_yellow=round(3.2 + rng.random() * 1.8, 1), avg_red=round(rng.random() * 0.3, 2),
            avg_fouls=round(20 + rng.random() * 8, 1), avg_penalties=round(rng.random() * 0.5, 2),
            home_win_rate=round(38 + rng.random() * 16, 1), over25_rate=round(48 + rng.random() * 18, 1),
        )

    def league_name(self, league_id: int, season: int) -> str:
        return NAMES.get(league_id, f"League {league_id}")

    def team_stats(self, team: TeamRef, league_id: int, season: int) -> TeamStats:
        matches = [m for m in self._season_matches(league_id, season)
                   if team.id in (m.home_id, m.away_id) and m.played]
        stats = TeamStats(team_id=team.id, style="balanced")
        stats.formation = ["4-3-3", "4-2-3-1", "3-4-3", "4-4-2"][team.id % 4]
        stats.style = ["possession", "counter", "balanced", "pressing"][team.id % 4]
        stats.possession = 54 + (team.id % 7) - 3
        form = []
        for m in matches:
            home = m.home_id == team.id
            gf, ga = int((m.home_goals if home else m.away_goals) or 0), int((m.away_goals if home else m.home_goals) or 0)
            stats.played += 1
            stats.gf += gf
            stats.ga += ga
            if home:
                stats.gf_home += gf; stats.ga_home += ga
            else:
                stats.gf_away += gf; stats.ga_away += ga
            letter = "W" if gf > ga else "D" if gf == ga else "L"
            stats.wins += letter == "W"; stats.draws += letter == "D"; stats.losses += letter == "L"
            stats.clean_sheets += ga == 0
            stats.btts += gf > 0 and ga > 0
            stats.goals.first_half_for += gf // 2
            stats.goals.second_half_for += gf - gf // 2
            stats.goals.first_half_against += ga // 2
            stats.goals.second_half_against += ga - ga // 2
            form.append((letter, f"{gf}-{ga}"))
        stats.form = form[-8:][::-1]
        stats.goals.xg_for = round(stats.gf / max(1, stats.played) * (0.9 + (team.id % 5) * 0.05), 2)
        stats.goals.xg_against = round(stats.ga / max(1, stats.played) * (0.9 + (team.id % 3) * 0.06), 2)
        stats.goals.penalties_scored = team.id % 4
        return stats


def get_provider():
    s = get_settings()
    if s.provider == "api-football":
        from .api_football import APIFootballProvider
        return APIFootballProvider()
    if s.provider == "football-data":
        from .football_data import FootballDataProvider
        return FootballDataProvider()
    return DemoProvider()
