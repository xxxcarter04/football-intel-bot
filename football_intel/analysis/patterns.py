from __future__ import annotations

from collections import defaultdict

from football_intel.data.models import FixtureContext, Match


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _played(matches: list[Match]) -> list[Match]:
    return [m for m in matches if m.played]


def _team_matches(matches: list[Match], team_id: int) -> list[Match]:
    return [m for m in matches if team_id in (m.home_id, m.away_id)]


def _goals_for_against(m: Match, team_id: int) -> tuple[int, int]:
    if team_id == m.home_id:
        return m.home_goals or 0, m.away_goals or 0
    return m.away_goals or 0, m.home_goals or 0


def _team_profile(matches: list[Match], team_id: int) -> dict:
    played = _played(_team_matches(matches, team_id))
    if not played:
        return {"matches": 0}

    gf = ga = over25 = btts = clean = wins = draws = losses = 0
    home_gf = home_ga = away_gf = away_ga = home_n = away_n = 0
    by_season: dict[int, list[int]] = defaultdict(list)

    for m in played:
        f, a = _goals_for_against(m, team_id)
        gf += f
        ga += a
        over25 += int(f + a > 2.5)
        btts += int(f > 0 and a > 0)
        clean += int(a == 0)
        if f > a:
            wins += 1
        elif f == a:
            draws += 1
        else:
            losses += 1
        if m.home_id == team_id:
            home_gf += f
            home_ga += a
            home_n += 1
        else:
            away_gf += f
            away_ga += a
            away_n += 1
        by_season[m.season].append(f + a)

    n = len(played)
    seasons = sorted(by_season)
    trend = "flat"
    if len(seasons) >= 2:
        first = sum(by_season[seasons[0]]) / len(by_season[seasons[0]])
        last = sum(by_season[seasons[-1]]) / len(by_season[seasons[-1]])
        if last > first + 0.25:
            trend = "rising"
        elif last < first - 0.25:
            trend = "falling"

    return {
        "matches": n,
        "gf_per_game": gf / n,
        "ga_per_game": ga / n,
        "over25": _rate(over25, n),
        "btts": _rate(btts, n),
        "clean_sheet": _rate(clean, n),
        "win": _rate(wins, n),
        "draw": _rate(draws, n),
        "loss": _rate(losses, n),
        "home_gf": home_gf / home_n if home_n else 0.0,
        "home_ga": home_ga / home_n if home_n else 0.0,
        "away_gf": away_gf / away_n if away_n else 0.0,
        "away_ga": away_ga / away_n if away_n else 0.0,
        "goal_trend": trend,
    }


def _streak(form: list[tuple[str, str]]) -> str:
    if not form:
        return "n/a"
    last = form[-1][0]
    count = 0
    for letter, _ in reversed(form):
        if letter != last:
            break
        count += 1
    return f"{last}{count}" if count >= 2 else last


def _h2h_profile(h2h: list[Match], home_id: int) -> dict:
    played = _played(h2h)
    if not played:
        return {"matches": 0}
    recent = played[:6]
    goals = [(m.home_goals or 0) + (m.away_goals or 0) for m in recent]
    home_wins = sum(
        1 for m in recent if (m.home_goals or 0) > (m.away_goals or 0) and m.home_id == home_id
    )
    away_wins = sum(
        1 for m in recent if (m.away_goals or 0) > (m.home_goals or 0) and m.away_id == home_id
    )
    draws = sum(1 for m in recent if m.home_goals == m.away_goals)
    btts = sum(1 for m in recent if m.home_goals and m.away_goals)
    return {
        "matches": len(recent),
        "avg_goals": sum(goals) / len(goals),
        "over25": _rate(sum(1 for g in goals if g > 2.5), len(goals)),
        "btts": _rate(btts, len(goals)),
        "home_wins": home_wins,
        "away_wins": away_wins,
        "draws": draws,
        "sequence": " ".join(m.result for m in recent),
    }


def _league_profile(history: list[Match]) -> dict:
    played = _played(history)
    if not played:
        return {"matches": 0}
    by_season: dict[int, list[Match]] = defaultdict(list)
    for m in played:
        by_season[m.season].append(m)
    seasons = sorted(by_season)
    goal_by_season = {
        s: sum((m.home_goals or 0) + (m.away_goals or 0) for m in ms) / len(ms)
        for s, ms in by_season.items()
    }
    trend = "flat"
    if len(seasons) >= 2:
        first, last = goal_by_season[seasons[0]], goal_by_season[seasons[-1]]
        if last > first + 0.25:
            trend = "rising"
        elif last < first - 0.25:
            trend = "falling"
    over25 = sum(1 for m in played if (m.home_goals or 0) + (m.away_goals or 0) > 2.5)
    home_wins = sum(1 for m in played if (m.home_goals or 0) > (m.away_goals or 0))
    return {
        "matches": len(played),
        "seasons": len(seasons),
        "goals_per_game": sum((m.home_goals or 0) + (m.away_goals or 0) for m in played) / len(played),
        "over25": _rate(over25, len(played)),
        "home_win": _rate(home_wins, len(played)),
        "goal_trend": trend,
        "goal_by_season": goal_by_season,
    }


def analyze_patterns(ctx: FixtureContext) -> dict:
    """Recognise repeatable trends across the 3-year history window."""
    history = ctx.history
    return {
        "league": _league_profile(history),
        "home": _team_profile(history, ctx.home_team.id),
        "away": _team_profile(history, ctx.away_team.id),
        "h2h": _h2h_profile(ctx.h2h, ctx.home_team.id),
        "streak_home": _streak(ctx.home.form),
        "streak_away": _streak(ctx.away.form),
    }
