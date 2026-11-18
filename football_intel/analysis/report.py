from __future__ import annotations

from football_intel.data.models import FixtureContext

from .model import Prediction
from .picks import HotPick


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _likely_outcome(pred: Prediction) -> str:
    x = pred.markets["1X2"]
    if x["H"] > max(x["D"], x["A"]):
        return "Home win"
    if x["A"] > max(x["D"], x["H"]):
        return "Away win"
    return "Draw"


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "High"
    if confidence >= 0.55:
        return "Medium"
    return "Low"


def _form_line(ctx: FixtureContext) -> str:
    def render(team_id: int, name: str) -> str:
        stats = ctx.home if team_id == ctx.match.home_id else ctx.away
        form = " ".join(f"{letter}{score}" for letter, score in stats.form[:5]) or "n/a"
        row = ctx.standings.get(team_id)
        pos = f"#{row.position} ({row.points} pts)" if row else "table n/a"
        return f"• {name}: {pos} | Last 5: {form}"

    return "\n".join(
        [
            render(ctx.match.home_id, ctx.home_team.name),
            render(ctx.match.away_id, ctx.away_team.name),
        ]
    )


def _h2h_line(ctx: FixtureContext) -> str:
    recent = [m for m in ctx.h2h if m.played][:5]
    if not recent:
        return "• No recent head-to-head meetings in the data window."
    lines = [f"• Last {len(recent)} meetings:"]
    for m in recent:
        lines.append(f"  - {m.date.strftime('%Y-%m-%d')}: {m.home_name} {m.home_goals}-{m.away_goals} {m.away_name}")
    return "\n".join(lines)


def _outlook_lines(pred: Prediction) -> list[str]:
    m = pred.markets
    x = m["1X2"]
    ou25 = m["OU"][2.5]
    btts = m["BTTS"]
    total_goals = pred.lam_home + pred.lam_away

    if ou25["over"] >= 0.6:
        goals = f"Goals: higher chance of over 2.5 ({_pct(ou25['over'])}, expected ~{total_goals:.2f} goals)."
    elif ou25["under"] >= 0.6:
        goals = f"Goals: lower-scoring game more likely (under 2.5 {_pct(ou25['under'])}, expected ~{total_goals:.2f} goals)."
    else:
        goals = f"Goals: balanced totals (over 2.5 {_pct(ou25['over'])}, expected ~{total_goals:.2f} goals)."

    if btts["yes"] >= 0.58:
        btts_line = f"Both teams to score: more likely yes ({_pct(btts['yes'])})."
    elif btts["no"] >= 0.58:
        btts_line = f"Both teams to score: more likely no ({_pct(btts['no'])})."
    else:
        btts_line = f"Both teams to score: close call (yes {_pct(btts['yes'])}, no {_pct(btts['no'])})."

    winner = _likely_outcome(pred)
    winner_prob = max(x["H"], x["D"], x["A"])
    if winner_prob >= 0.5:
        result = f"Result prediction: {winner} is the strongest outcome ({_pct(winner_prob)})."
    else:
        result = (
            f"Result prediction: slight lean to {winner.lower()} "
            f"(H {_pct(x['H'])}, D {_pct(x['D'])}, A {_pct(x['A'])})."
        )

    return [f"• {goals}", f"• {btts_line}", f"• {result}"]


def render_analysis(pred: Prediction) -> str:
    ctx = pred.context
    m = pred.markets
    h, a = pred.lam_home, pred.lam_away
    top = pred.top_scores[0]
    likely = _likely_outcome(pred)

    lines: list[str] = []
    lines.append("⚽ *MATCH REPORT*")
    lines.append(f"*{ctx.home_team.name} vs {ctx.away_team.name}*")
    lines.append(
        f"{ctx.league_name} • {ctx.match.date.strftime('%d %b %Y, %H:%M')} UTC"
        + (f" • {ctx.match.round}" if ctx.match.round else "")
    )
    lines.append(
        f"Data confidence: {_confidence_label(pred.confidence)} ({_pct(pred.confidence)}, coverage {pred.context.data_quality:.0%})"
    )
    if ctx.provider_error:
        lines.append("")
        lines.append("🚨 *LIVE DATA UNAVAILABLE — DEMO FALLBACK USED*")
        lines.append(f"_{ctx.provider_error}_")

    lines.append("")
    lines.append("🎯 *PREDICTION*")
    lines.append(f"• Most likely result: *{likely}*")
    lines.append(f"• Most likely score: *{top[0]}-{top[1]}* ({_pct(top[2])})")
    lines.append(f"• Expected goals (xG): *{h:.2f} – {a:.2f}* (total {h + a:.2f})")
    lines.append(
        "• Win probabilities (1X2): "
        f"Home {_pct(m['1X2']['H'])} | Draw {_pct(m['1X2']['D'])} | Away {_pct(m['1X2']['A'])}"
    )

    lines.append("")
    lines.append("📊 *MARKET PROBABILITIES*")
    lines.append(
        "• 1X2: "
        f"Home {_pct(m['1X2']['H'])} | Draw {_pct(m['1X2']['D'])} | Away {_pct(m['1X2']['A'])}"
    )
    lines.append(f"• Draw No Bet: Home {_pct(m['DNB']['H'])} | Away {_pct(m['DNB']['A'])}")
    for line in (1.5, 2.5, 3.5):
        ou = m["OU"][line]
        lines.append(f"• Over/Under {line}: Over {_pct(ou['over'])} | Under {_pct(ou['under'])}")
    btts = m["BTTS"]
    lines.append(f"• Both Teams To Score: Yes {_pct(btts['yes'])} | No {_pct(btts['no'])}")
    ah_bits = []
    for line in (-1.0, -0.5, 0.0, 0.5, 1.0):
        val = m["AH"][line]
        ah_bits.append(f"{line:+.1f} H {_pct(val['home'])}/A {_pct(val['away'])}")
    lines.append("• Asian Handicap (home line): " + " • ".join(ah_bits))
    alt = " | ".join(f"{sx}-{sy} {_pct(pr)}" for sx, sy, pr in pred.top_scores[:4])
    lines.append(f"• Top scorelines: {alt}")

    lines.append("")
    lines.append("📈 *FORM & TABLE*")
    lines.append(_form_line(ctx))

    lines.append("")
    lines.append("🔁 *HEAD-TO-HEAD*")
    lines.append(_h2h_line(ctx))

    if pred.features.notes or ctx.injuries.get(ctx.match.home_id) or ctx.injuries.get(ctx.match.away_id):
        lines.append("")
        lines.append("🔍 *KEY FACTORS*")
        for note in pred.features.notes[:9]:
            lines.append(f"• {note}")
        for tid, label in ((ctx.match.home_id, ctx.home_team.name), (ctx.match.away_id, ctx.away_team.name)):
            inj = ctx.injuries.get(tid, [])
            if inj:
                lines.append(f"• {label} missing: " + ", ".join(i.player for i in inj[:4]))

    lines.append("")
    lines.extend(render_pattern_section(pred))

    lines.append("")
    lines.append("⚠️ Model estimate based on available data — not a certainty. Gamble responsibly, 18+.")
    return "\n".join(lines)


def render_pattern_section(pred: Prediction) -> list[str]:
    """Readable statistics and prediction-outlook section from recent history."""
    p = pred.patterns or {}
    ctx = pred.context
    lines = ["📊 *KEY STATISTICS & PREDICTION OUTLOOK*"]

    lg = p.get("league", {})
    if lg.get("matches"):
        seasons = lg.get("goal_by_season", {})
        season_text = ", ".join(f"{s}: {v:.2f} gpg" for s, v in sorted(seasons.items()))
        lines.append("*League statistics*")
        lines.append(
            f"• Sample: {lg['matches']} matches across {lg.get('seasons', 0)} seasons"
            + (f" ({season_text})" if season_text else "")
        )
        lines.append(
            f"• Averages: {lg.get('goals_per_game', 0):.2f} goals/game | Over 2.5 {_pct(lg.get('over25', 0))} | "
            f"Home wins {_pct(lg.get('home_win', 0))} | Goal trend: {lg.get('goal_trend', 'flat')}"
        )
    else:
        lines.append("*League statistics*")
        lines.append("• Not enough league data available.")

    for key, label in (("home", ctx.home_team.name), ("away", ctx.away_team.name)):
        t = p.get(key, {})
        lines.append("")
        lines.append(f"*{label} — recent statistics*")
        if not t.get("matches"):
            lines.append("• Not enough team data available.")
            continue
        lines.append(
            f"• Record: W {_pct(t.get('win', 0))} | D {_pct(t.get('draw', 0))} | L {_pct(t.get('loss', 0))} "
            f"({t.get('matches', 0)} matches)"
        )
        lines.append(
            f"• Goals: {t.get('gf_per_game', 0):.2f} scored, {t.get('ga_per_game', 0):.2f} conceded per game"
        )
        lines.append(
            f"• Trends: Over 2.5 {_pct(t.get('over25', 0))} | BTTS {_pct(t.get('btts', 0))} | "
            f"Clean sheets {_pct(t.get('clean_sheet', 0))} | Form streak: {p.get('streak_' + key, 'n/a')}"
        )
        lines.append(
            f"• Splits: Home {t.get('home_gf', 0):.2f}–{t.get('home_ga', 0):.2f} | "
            f"Away {t.get('away_gf', 0):.2f}–{t.get('away_ga', 0):.2f} | "
            f"Goal trend: {t.get('goal_trend', 'flat')}"
        )

    h = p.get("h2h", {})
    lines.append("")
    lines.append("*Head-to-head statistics*")
    if h.get("matches"):
        lines.append(
            f"• Recent meetings: {h['matches']} | Avg goals {h.get('avg_goals', 0):.2f} | "
            f"Over 2.5 {_pct(h.get('over25', 0))} | BTTS {_pct(h.get('btts', 0))}"
        )
        lines.append(
            f"• Results (from home-team perspective): {h.get('home_wins', 0)} wins, "
            f"{h.get('draws', 0)} draws, {h.get('away_wins', 0)} losses"
            + (f" | Sequence: {h.get('sequence')}" if h.get("sequence") else "")
        )
    else:
        lines.append("• No recent head-to-head statistics available.")

    lines.append("")
    lines.append("*Prediction outlook (from statistics + model)*")
    lines.extend(_outlook_lines(pred))
    return lines


def pattern_line(pred: Prediction) -> str:
    """Compact one-line statistics summary for the all-match overview."""
    p = pred.patterns or {}
    h, a, lg = p.get("home", {}), p.get("away", {}), p.get("league", {})
    if not h and not a and not lg:
        return "   Stats: n/a"
    home = (
        f"{pred.context.home_team.name} "
        f"(GF {h.get('gf_per_game', 0):.2f}/GA {h.get('ga_per_game', 0):.2f}, "
        f"O2.5 {_pct(h.get('over25', 0))}, BTTS {_pct(h.get('btts', 0))})"
    )
    away = (
        f"{pred.context.away_team.name} "
        f"(GF {a.get('gf_per_game', 0):.2f}/GA {a.get('ga_per_game', 0):.2f}, "
        f"O2.5 {_pct(a.get('over25', 0))}, BTTS {_pct(a.get('btts', 0))})"
    )
    league = f"League avg {lg.get('goals_per_game', 0):.2f} gpg ({lg.get('goal_trend', 'flat')})"
    return f"   Stats: {home} · {away} · {league}"


def render_leagues_overview(preds: list[Prediction], days: int, truncated: bool = False) -> str:
    """All upcoming matches by league, with easy-to-read prediction summaries."""
    groups: dict[str, list[Prediction]] = {}
    for pred in preds:
        groups.setdefault(pred.context.league_name, []).append(pred)

    lines = [f"📊 *All leagues — predictions (next {days} days)*", f"{len(preds)} matches"]
    if truncated:
        lines.append("_Showing the first 20 fixtures only._")
    for league, items in groups.items():
        lines.append("")
        lines.append(f"🏆 *{league}*")
        for pred in items:
            m = pred.markets
            top = pred.top_scores[0]
            likely = _likely_outcome(pred)
            x = m["1X2"]
            ou = m["OU"][2.5]
            btts = m["BTTS"]
            lines.append(f"*{pred.context.home_team.name} vs {pred.context.away_team.name}*")
            lines.append(
                f"   Prediction: {likely} | Score {top[0]}-{top[1]} ({_pct(top[2])}) | "
                f"xG {pred.lam_home:.2f}-{pred.lam_away:.2f}"
            )
            lines.append(
                f"   1X2: H {_pct(x['H'])} D {_pct(x['D'])} A {_pct(x['A'])} | "
                f"O/U 2.5: {_pct(ou['over'])}/{_pct(ou['under'])} | "
                f"BTTS: {_pct(btts['yes'])}/{_pct(btts['no'])} | "
                f"DNB: {_pct(m['DNB']['H'])}/{_pct(m['DNB']['A'])}"
            )
            lines.append(pattern_line(pred))
    return "\n".join(lines)


def render_quick(pred: Prediction) -> str:
    ctx = pred.context
    m = pred.markets
    top = pred.top_scores[0]
    likely = _likely_outcome(pred)
    return (
        f"*{ctx.home_team.name} vs {ctx.away_team.name}* • {ctx.league_name}\n"
        f"Prediction: {likely} | Score {top[0]}-{top[1]} ({_pct(top[2])}) | xG {pred.lam_home:.2f}-{pred.lam_away:.2f}\n"
        f"1X2 H {_pct(m['1X2']['H'])} D {_pct(m['1X2']['D'])} A {_pct(m['1X2']['A'])} • "
        f"O/U 2.5 {_pct(m['OU'][2.5]['over'])}/{_pct(m['OU'][2.5]['under'])} • "
        f"BTTS {_pct(m['BTTS']['yes'])}/{_pct(m['BTTS']['no'])}"
    )


def render_all_leagues(preds: list[Prediction], days: int, truncated: bool = False) -> str:
    """Full analysis for every upcoming match, grouped by competition."""
    groups: dict[str, list[Prediction]] = {}
    for pred in preds:
        groups.setdefault(pred.context.league_name, []).append(pred)

    lines = [
        f"📅 *Upcoming matches — all covered leagues (next {days} days)*",
        f"{len(preds)} matches",
    ]
    if truncated:
        lines.append("_Showing the first 20 fixtures only._")
    for league, items in groups.items():
        lines.append("")
        lines.append(f"🏆 *{league}*")
        for pred in items:
            lines.append("")
            lines.append(render_analysis(pred))
            lines.append("")
            lines.append("—" * 24)
    return "\n".join(lines).rstrip("— \n")


def render_league_menu(leagues: list[tuple[int, str]], days: int) -> str:
    """Short overview of the per-league buttons available in Telegram."""
    lines = [f"🏆 *Leagues* — pick one from the buttons below (next {days} days)", ""]
    for league_id, name in leagues:
        lines.append(f"• {name} (ID {league_id})")
    lines.append("")
    lines.append("Each league opens its own report with at least 10 predictions.")
    return "\n".join(lines)


def render_league_predictions(
    league_name: str,
    preds: list[Prediction],
    days: int,
    sample_filled: bool = False,
) -> str:
    """Dedicated report for a single competition."""
    lines = [
        f"🏆 *{league_name}*",
        f"{len(preds)} predictions • next {days} days",
    ]
    if sample_filled:
        lines.append("ℹ️ Sample pairings added to reach 10 predictions; real fixtures shown first.")
    lines.append("")
    for i, pred in enumerate(preds, 1):
        m = pred.markets
        top = pred.top_scores[0]
        x = m["1X2"]
        ou = m["OU"][2.5]
        btts = m["BTTS"]
        likely = _likely_outcome(pred)
        lines.append(f"*{i}. {pred.context.home_team.name} vs {pred.context.away_team.name}*")
        lines.append(
            f"   Prediction: {likely} | Score {top[0]}-{top[1]} ({_pct(top[2])}) | xG {pred.lam_home:.2f}-{pred.lam_away:.2f}"
        )
        lines.append(
            f"   1X2: H {_pct(x['H'])} D {_pct(x['D'])} A {_pct(x['A'])} | "
            f"O/U 2.5: {_pct(ou['over'])}/{_pct(ou['under'])} | "
            f"BTTS: {_pct(btts['yes'])}/{_pct(btts['no'])} | "
            f"DNB: {_pct(m['DNB']['H'])}/{_pct(m['DNB']['A'])}"
        )
    lines.append("")
    lines.append("⚠️ Model estimate based on available data — not a certainty. Gamble responsibly, 18+.")
    return "\n".join(lines)


def render_hot_picks(picks: list[HotPick], days: int) -> str:
    """Highest-confidence model signals, grouped by league."""
    lines = [
        f"🔥 *HOT PICKS* — strongest model signals (next {days} days)",
        "Highest-probability selections based on model statistics and predictions. Not guaranteed outcomes.",
        "",
    ]
    if not picks:
        lines.append("No strong signals found in this window. Try another league or a wider window.")
        lines.append("")
        lines.append("⚠️ Model estimate, not a certainty. Gamble responsibly, 18+.")
        return "\n".join(lines)

    groups: dict[str, list[HotPick]] = {}
    for pick in picks:
        groups.setdefault(pick.league_name, []).append(pick)
    for league_name, items in groups.items():
        lines.append(f"🏆 *{league_name}*")
        for pick in items[:4]:
            edge = f"+{_pct(pick.edge)}" if pick.edge >= 0 else _pct(pick.edge)
            lines.append(
                f"• {pick.home_name} vs {pick.away_name}\n"
                f"  Pick: *{pick.selection}* ({pick.market}) | Probability {_pct(pick.probability)} | "
                f"Strength {pick.strength}/100 | Edge {edge}"
            )
        lines.append("")
    lines.append("⚠️ Model estimate, not a certainty. No guarantee of profit — gamble responsibly, 18+.")
    return "\n".join(lines)
