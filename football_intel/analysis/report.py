from __future__ import annotations

from football_intel.data.models import FixtureContext

from .model import Prediction


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

    lines.append("⚠️ Model estimate, not a certainty. No guarantee of profit — gamble responsibly, 18+.")
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
