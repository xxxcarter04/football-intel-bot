from __future__ import annotations

from football_intel.data.models import FixtureContext

from .model import Prediction
from .picks import HotPick


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _form_line(ctx: FixtureContext) -> str:
    def render(team_id: int, name: str) -> str:
        stats = ctx.home if team_id == ctx.match.home_id else ctx.away
        form = " ".join(f"{letter}{score}" for letter, score in stats.form[:5]) or "n/a"
        row = ctx.standings.get(team_id)
        pos = f"#{row.position} ({row.points} pts)" if row else "n/a"
        return f"{name}: {pos} | last5: {form}"

    return (
        render(ctx.match.home_id, ctx.home_team.name)
        + "\n"
        + render(ctx.match.away_id, ctx.away_team.name)
    )


def _h2h_line(ctx: FixtureContext) -> str:
    recent = [m for m in ctx.h2h if m.played][:5]
    if not recent:
        return "H2H: no recent meetings in data window."
    parts = []
    for m in recent:
        parts.append(f"{m.date.strftime('%Y')}: {m.home_name} {m.home_goals}-{m.away_goals} {m.away_name}")
    return "H2H:\n  " + "\n  ".join(parts)


def render_analysis(pred: Prediction) -> str:
    ctx = pred.context
    m = pred.markets
    h, a = pred.lam_home, pred.lam_away
    top = pred.top_scores[0]
    likely = "Home" if m["1X2"]["H"] > max(m["1X2"]["D"], m["1X2"]["A"]) else (
        "Away" if m["1X2"]["A"] > m["1X2"]["D"] else "Draw"
    )

    lines: list[str] = []
    lines.append("⚽ *MATCH INTELLIGENCE*")
    lines.append(f"{ctx.home_team.name} vs {ctx.away_team.name}")
    lines.append(
        f"{ctx.league_name} • {ctx.match.date.strftime('%d %b %Y, %H:%M')} UTC"
        + (f" • {ctx.match.round}" if ctx.match.round else "")
    )
    lines.append(f"Data confidence: {_pct(pred.confidence)} ({pred.context.data_quality:.0%} coverage)")
    if ctx.provider_error:
        lines.append("🚨 *LIVE DATA UNAVAILABLE — DEMO FALLBACK USED*")
        lines.append(f"_{ctx.provider_error}_")
    lines.append("")

    lines.append("🎯 *MODEL VERDICT*")
    lines.append(
        f"Most likely score *{top[0]}-{top[1]}* ({_pct(top[2])}) | "
        f"xG {h:.2f} – {a:.2f} | lean: *{likely}*"
    )
    lines.append("")

    lines.append("📊 *MARKETS*")
    x = m["1X2"]
    lines.append(f"1X2: 1 {_pct(x['H'])} • X {_pct(x['D'])} • 2 {_pct(x['A'])}")
    dnb = m["DNB"]
    lines.append(f"Draw no bet: 1 {_pct(dnb['H'])} • 2 {_pct(dnb['A'])}")
    for line in (1.5, 2.5):
        ou = m["OU"][line]
        lines.append(f"Over/Under {line}: over {_pct(ou['over'])} • under {_pct(ou['under'])}")
    ah_lines = (-1.5, -1.0, -0.5, 0.5, 1.0, 1.5)
    ah_bits = []
    for line in ah_lines:
        val = m["AH"][line]
        ah_bits.append(f"{line:+.1f}: {_pct(val['home'])}/{_pct(val['away'])}")
    lines.append("Handicap (home line): " + " • ".join(ah_bits))
    btts = m["BTTS"]
    lines.append(f"Both to score: yes {_pct(btts['yes'])} • no {_pct(btts['no'])}")
    alt = " | ".join(f"{sx}-{sy} {_pct(pr)}" for sx, sy, pr in pred.top_scores[:4])
    lines.append(f"Correct score: {alt}")
    lines.append("")

    lines.append("📈 *FORM & TABLE*")
    lines.append(_form_line(ctx))
    lines.append("")

    lines.append("🔁 *H2H*")
    lines.append(_h2h_line(ctx))
    lines.append("")

    if pred.features.notes:
        lines.append("🔍 *KEY FACTORS*")
        for note in pred.features.notes[:9]:
            lines.append(f"• {note}")
        if ctx.injuries.get(ctx.match.home_id) or ctx.injuries.get(ctx.match.away_id):
            for tid, label in ((ctx.match.home_id, ctx.home_team.name), (ctx.match.away_id, ctx.away_team.name)):
                inj = ctx.injuries.get(tid, [])
                if inj:
                    lines.append(f"• {label} missing: " + ", ".join(i.player for i in inj[:4]))
        lines.append("")

    lines.extend(render_pattern_section(pred))
    lines.append("")

    lines.append("⚠️ Model estimate, not a certainty. No guarantee of profit — gamble responsibly, 18+.")
    return "\n".join(lines)


def render_pattern_section(pred: Prediction) -> list[str]:
    """Full pattern-recognition block from the 3-year history window."""
    p = pred.patterns or {}
    ctx = pred.context
    lines = ["🔎 *3-YEAR PATTERN RECOGNITION*"]

    lg = p.get("league", {})
    if lg.get("matches"):
        seasons = lg.get("goal_by_season", {})
        trend_text = ", ".join(f"{s}: {v:.2f}" for s, v in sorted(seasons.items()))
        lines.append(
            f"• League: {lg['matches']} matches over {lg.get('seasons', 0)} seasons | "
            f"{lg.get('goals_per_game', 0):.2f} goals/game | "
            f"O2.5 {_pct(lg.get('over25', 0))} | home wins {_pct(lg.get('home_win', 0))} | "
            f"trend {lg.get('goal_trend', 'flat')} ({trend_text})"
        )

    for key, label in (("home", ctx.home_team.name), ("away", ctx.away_team.name)):
        t = p.get(key, {})
        if not t.get("matches"):
            continue
        lines.append(
            f"• {label}: W/D/L {_pct(t.get('win', 0))}/{_pct(t.get('draw', 0))}/{_pct(t.get('loss', 0))} | "
            f"GF {t.get('gf_per_game', 0):.2f}, GA {t.get('ga_per_game', 0):.2f} per game | "
            f"O2.5 {_pct(t.get('over25', 0))}, BTTS {_pct(t.get('btts', 0))}, clean sheets {_pct(t.get('clean_sheet', 0))}"
        )
        lines.append(
            f"   Home {t.get('home_gf', 0):.2f}-{t.get('home_ga', 0):.2f} vs "
            f"away {t.get('away_gf', 0):.2f}-{t.get('away_ga', 0):.2f} | "
            f"goals trend {t.get('goal_trend', 'flat')} | "
            f"form streak {p.get('streak_' + key, 'n/a')}"
        )

    h = p.get("h2h", {})
    if h.get("matches"):
        lines.append(
            f"• H2H ({h['matches']} meetings): {h.get('avg_goals', 0):.2f} goals/game | "
            f"O2.5 {_pct(h.get('over25', 0))} | BTTS {_pct(h.get('btts', 0))} | "
            f"home/away/draw {h.get('home_wins', 0)}/{h.get('away_wins', 0)}/{h.get('draws', 0)} | "
            f"sequence {h.get('sequence', 'n/a')}"
        )
    return lines


def pattern_line(pred: Prediction) -> str:
    """Compact one-line pattern summary for the all-match overview."""
    p = pred.patterns or {}
    h, a, lg = p.get("home", {}), p.get("away", {}), p.get("league", {})
    if not h and not a and not lg:
        return "PATTERN n/a"
    return (
        f"PATTERN {pred.context.home_team.name}: O2.5 {_pct(h.get('over25', 0))} "
        f"BTTS {_pct(h.get('btts', 0))} CS {_pct(h.get('clean_sheet', 0))} | "
        f"{pred.context.away_team.name}: O2.5 {_pct(a.get('over25', 0))} "
        f"BTTS {_pct(a.get('btts', 0))} CS {_pct(a.get('clean_sheet', 0))} | "
        f"league {lg.get('goal_trend', 'flat')} {lg.get('goals_per_game', 0):.2f} gpg"
    )


def render_leagues_overview(preds: list[Prediction], days: int, truncated: bool = False) -> str:
    """All upcoming matches by league, with | separating each market."""
    groups: dict[str, list[Prediction]] = {}
    for pred in preds:
        groups.setdefault(pred.context.league_name, []).append(pred)

    lines = [f"📊 *All leagues — predictions (next {days} days)* • {len(preds)} matches"]
    if truncated:
        lines.append("_Showing the first 20 fixtures only._")
    for league, items in groups.items():
        lines.append("")
        lines.append(f"🏆 *{league}*")
        for pred in items:
            m = pred.markets
            lines.append(
                f"{pred.context.home_team.name} vs {pred.context.away_team.name} — "
                f"1X2 {_pct(m['1X2']['H'])}/{_pct(m['1X2']['D'])}/{_pct(m['1X2']['A'])} | "
                f"OU2.5 {_pct(m['OU'][2.5]['over'])}/{_pct(m['OU'][2.5]['under'])} | "
                f"BTTS {_pct(m['BTTS']['yes'])}/{_pct(m['BTTS']['no'])} | "
                f"DNB {_pct(m['DNB']['H'])}/{_pct(m['DNB']['A'])} | "
                f"score {pred.top_scores[0][0]}-{pred.top_scores[0][1]} ({_pct(pred.top_scores[0][2])})"
            )
            lines.append(f"   {pattern_line(pred)}")
    return "\n".join(lines)


def render_quick(pred: Prediction) -> str:
    ctx = pred.context
    m = pred.markets
    return (
        f"*{ctx.home_team.name} vs {ctx.away_team.name}* • {ctx.league_name}\n"
        f"1X2 {_pct(m['1X2']['H'])}/{_pct(m['1X2']['D'])}/{_pct(m['1X2']['A'])} • "
        f"OU2.5 {_pct(m['OU'][2.5]['over'])}/{_pct(m['OU'][2.5]['under'])} • "
        f"DNB {_pct(m['DNB']['H'])}/{_pct(m['DNB']['A'])}"
    )


def render_all_leagues(preds: list[Prediction], days: int, truncated: bool = False) -> str:
    """Full analysis for every upcoming match, grouped by competition."""
    groups: dict[str, list[Prediction]] = {}
    for pred in preds:
        groups.setdefault(pred.context.league_name, []).append(pred)

    lines = [
        f"📅 *Upcoming — all covered leagues (next {days} days)* • {len(preds)} matches"
    ]
    if truncated:
        lines.append("_Showing the first 20 fixtures only._")
    for league, items in groups.items():
        lines.append("")
        lines.append(f"🏆 *{league}*")
        for pred in items:
            lines.append("")
            lines.append(render_analysis(pred))
    return "\n".join(lines)


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
    for pred in preds:
        m = pred.markets
        top = pred.top_scores[0]
        lines.append(
            f"{pred.context.home_team.name} vs {pred.context.away_team.name} — "
            f"1X2 {_pct(m['1X2']['H'])}/{_pct(m['1X2']['D'])}/{_pct(m['1X2']['A'])} | "
            f"OU2.5 {_pct(m['OU'][2.5]['over'])}/{_pct(m['OU'][2.5]['under'])} | "
            f"BTTS {_pct(m['BTTS']['yes'])}/{_pct(m['BTTS']['no'])} | "
            f"DNB {_pct(m['DNB']['H'])}/{_pct(m['DNB']['A'])} | "
            f"score {top[0]}-{top[1]} ({_pct(top[2])})"
        )
    lines.append("")
    lines.append("⚠️ Model estimate, not a certainty. Gamble responsibly, 18+.")
    return "\n".join(lines)


def render_hot_picks(picks: list[HotPick], days: int) -> str:
    """Highest-confidence model signals, grouped by league."""
    lines = [
        f"🔥 *HOT PICKS* — strongest model signals (next {days} days)",
        "These are the model's highest-probability selections in each league — NOT guaranteed outcomes.",
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
                f"• {pick.home_name} vs {pick.away_name} — {pick.market}: "
                f"*{pick.selection}* {_pct(pick.probability)} · "
                f"strength {pick.strength}/100 · edge {edge}"
            )
        lines.append("")
    lines.append("⚠️ Model estimate, not a certainty. No guarantee of profit — gamble responsibly, 18+.")
    return "\n".join(lines)
