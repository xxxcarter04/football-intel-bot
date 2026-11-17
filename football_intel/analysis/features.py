from __future__ import annotations

import math
from dataclasses import dataclass, field

from football_intel.data.models import FixtureContext, Match


@dataclass
class TeamStrength:
    attack: float = 1.0
    defense: float = 1.0
    home_boost: float = 1.0
    away_drag: float = 1.0
    matches: int = 0
    form_ppg: float = 1.0
    season_ppg: float = 1.0
    xg_delta: float = 0.0
    penalty_share: float = 0.0
    late_goal_share: float = 0.5
    injury_attack_hit: float = 0.0
    injury_defense_hit: float = 0.0


@dataclass
class FeatureSet:
    league_avg_home: float = 1.55
    league_avg_away: float = 1.25
    home: TeamStrength = field(default_factory=TeamStrength)
    away: TeamStrength = field(default_factory=TeamStrength)
    h2h_weight: float = 0.0
    h2h_goals: float = 1.0
    h2h_home_bias: float = 1.0
    referee_goal_factor: float = 1.0
    referee_home_factor: float = 1.0
    importance_goal_factor: float = 1.0
    tactical_goal_factor: float = 1.0
    notes: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ppg(letters: list[str]) -> float:
    if not letters:
        return 1.0
    return sum(3 if x == "W" else 1 if x == "D" else 0 for x in letters) / len(letters)


def fit_strengths(matches: list[Match], team_ids: tuple[int, int]) -> tuple[dict[int, TeamStrength], float, float]:
    """Fit simple Dixon-Coles-style attack/defence ratings with time decay."""
    finished = [m for m in matches if m.played]
    if not finished:
        return {t: TeamStrength() for t in team_ids}, 1.55, 1.25

    latest = max(m.date for m in finished)
    totals: dict[int, dict[str, float]] = {
        t: {"gf": 0.0, "ga": 0.0, "gf_h": 0.0, "ga_h": 0.0, "gf_a": 0.0, "ga_a": 0.0, "n": 0.0}
        for t in team_ids
    }
    home_goals = away_goals = count = 0.0

    for m in finished:
        age = (latest - m.date).days / 365.25
        w = math.exp(-0.28 * age)  # recency weighting
        hg, ag = int(m.home_goals or 0), int(m.away_goals or 0)
        home_goals += hg * w
        away_goals += ag * w
        count += w
        for tid, gf, ga, is_home in ((m.home_id, hg, ag, True), (m.away_id, ag, hg, False)):
            if tid not in totals:
                continue
            d = totals[tid]
            d["gf"] += gf * w
            d["ga"] += ga * w
            d["n"] += w
            if is_home:
                d["gf_h"] += gf * w
                d["ga_h"] += ga * w
            else:
                d["gf_a"] += gf * w
                d["ga_a"] += ga * w

    lh = home_goals / max(count, 1)
    la = away_goals / max(count, 1)
    league_avg = (lh + la) / 2
    out: dict[int, TeamStrength] = {}
    for tid in team_ids:
        d = totals[tid]
        n = d["n"]
        shrink = n / (n + 9) if n > 0 else 0
        gf_avg = d["gf"] / max(n, 1)
        ga_avg = d["ga"] / max(n, 1)
        attack = 1 + ((gf_avg / max(league_avg, 0.3)) - 1) * shrink
        defense = 1 + ((ga_avg / max(league_avg, 0.3)) - 1) * shrink
        home_boost = 1 + (((d["gf_h"] / max(n / 2, 1)) / max(lh, 0.3)) - 1) * shrink * 0.5
        away_drag = 1 + (((d["gf_a"] / max(n / 2, 1)) / max(la, 0.3)) - 1) * shrink * 0.5
        out[tid] = TeamStrength(
            attack=_clamp(attack, 0.55, 1.6),
            defense=_clamp(defense, 0.55, 1.6),
            home_boost=_clamp(home_boost, 0.8, 1.25),
            away_drag=_clamp(away_drag, 0.8, 1.25),
            matches=int(n),
        )
    return out, lh, la


def build_features(ctx: FixtureContext) -> FeatureSet:
    hid, aid = ctx.match.home_id, ctx.match.away_id
    strengths, lh, la = fit_strengths(ctx.history, (hid, aid))
    fs = FeatureSet(league_avg_home=lh, league_avg_away=la)
    fs.home = strengths[hid]
    fs.away = strengths[aid]
    home, away = ctx.home, ctx.away

    # Recent form vs season baseline.
    for team, stats, strength in ((home, ctx.home, fs.home), (away, ctx.away, fs.away)):
        recent = [x[0] for x in stats.form[:5]]
        strength.form_ppg = _ppg(recent)
        strength.season_ppg = (
            (stats.wins * 3 + stats.draws) / max(stats.played, 1) if stats.played else 1.0
        )

    # Goal type / xG regression (penalties and overperformance are less repeatable).
    for stats, strength in ((home, fs.home), (away, fs.away)):
        g = stats.goals
        if g.xg_for and stats.played:
            strength.xg_delta = (stats.gf / stats.played) - g.xg_for
        if stats.gf:
            strength.penalty_share = g.penalties_scored / max(stats.gf, 1)
        total_half = g.first_half_for + g.second_half_for
        if total_half:
            strength.late_goal_share = g.second_half_for / total_half

    # Injuries: attacker/keeper absences weighted by estimated importance.
    for tid, strength in ((hid, fs.home), (aid, fs.away)):
        for injury in ctx.injuries.get(tid, []):
            key = injury.position.lower()
            if "att" in key or "mid" in key:
                strength.injury_attack_hit += 0.07 * injury.importance
            else:
                strength.injury_defense_hit += 0.06 * injury.importance

    # H2H signal, decaying with age.
    h2h = [m for m in ctx.h2h if m.played]
    if h2h:
        wsum = 0.0
        gsum = 0.0
        hs = 0.0
        for i, m in enumerate(h2h):
            w = 1 / (1 + i * 0.25)
            gsum += ((m.home_goals or 0) + (m.away_goals or 0)) * w
            hs += ((m.home_goals or 0) - (m.away_goals or 0)) * w
            wsum += w
        h2h_avg = gsum / max(wsum, 1)
        fs.h2h_goals = _clamp(1 + 0.45 * (h2h_avg / max(lh + la, 1) - 1), 0.88, 1.12)
        fs.h2h_home_bias = _clamp(1 + (hs / max(wsum, 1)) * 0.06, 0.85, 1.18)
        fs.h2h_weight = _clamp(len(h2h) / 12, 0, 1)

    # Referee influence.
    ref = ctx.referee
    if ref.matches >= 10:
        fs.referee_goal_factor = _clamp(1 + 0.3 * (ref.over25_rate / 55.0 - 1), 0.95, 1.07)
        fs.referee_home_factor = _clamp(1 + 0.3 * (ref.home_win_rate / 45.0 - 1), 0.95, 1.07)
        fs.notes.append(
            f"Ref {ref.name}: {ref.matches} games, {ref.over25_rate:.0f}% over 2.5, "
            f"{ref.home_win_rate:.0f}% home wins."
        )

    # Match importance: decisive games tend to be cagey.
    if ctx.importance_flags:
        fs.importance_goal_factor = 0.94 if len(ctx.importance_flags) > 1 else 0.97
        fs.notes.append("Stakes elevated: " + ", ".join(ctx.importance_flags).replace("_", " ") + ".")

    # Tactical matchup heuristic.
    if home.style and away.style:
        high = {"pressing", "counter"}
        if home.style in high or away.style in high:
            fs.tactical_goal_factor = 1.06
        if home.style == "possession" and away.style == "counter":
            fs.tactical_goal_factor = 1.08
        fs.notes.append(f"Styles: {home.style} vs {away.style} ({home.formation or 'n/a'} / {away.formation or 'n/a'}).")

    # Table context.
    hr, ar = ctx.standings.get(hid), ctx.standings.get(aid)
    if hr and ar:
        gap = abs(hr.points - ar.points)
        fs.factors["table_gap"] = float(gap)
        if gap <= 3:
            fs.notes.append(f"Table: {ctx.home_team.name} {hr.position} vs {ctx.away_team.name} {ar.position}, {gap} pts apart.")
        else:
            fs.notes.append(f"Table: {ctx.home_team.name} {hr.position} ({hr.points} pts) vs {ctx.away_team.name} {ar.position} ({ar.points} pts).")

    return fs
