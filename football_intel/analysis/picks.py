"""Shared signal model for the "Hot Picks" feature.

A HotPick is one concrete market selection extracted from a full Prediction.
The selection logic lives here so that the service layer (which builds picks) and
the reporting layer (which renders them) agree on a single contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class HotPick:
    league_id: int
    league_name: str
    home_name: str
    away_name: str
    market: str          # e.g. "1X2", "Draw no bet", "Over/Under 2.5", "Both to score"
    selection: str       # e.g. "Home win", "Over 2.5", "BTTS: No"
    probability: float   # 0..1 model probability of this selection
    baseline: float      # reference probability (1/3 for 1X2, 1/2 for binary markets)
    edge: float          # probability - baseline
    strength: int        # 0..100, ranking score combining edge and data confidence
    confidence: float    # model data confidence for the underlying fixture
    match_key: str       # key into the bot's fixture registry; "" if unavailable
    date: datetime


def pick_strength(probability: float, baseline: float, confidence: float) -> int:
    """Turn a probability edge plus data confidence into a 0..100 ranking score."""
    span = max(1e-9, 1.0 - baseline)
    edge_ratio = max(0.0, min(1.0, (probability - baseline) / span))
    score = 52 + 46 * edge_ratio
    score *= 0.8 + 0.2 * max(0.0, min(1.0, confidence))
    return int(round(max(0.0, min(99.0, score))))


def _candidate(
    pred,
    *,
    league_id: int,
    league_name: str,
    market: str,
    selection: str,
    probability: float,
    baseline: float,
    match_key: str,
) -> HotPick:
    return HotPick(
        league_id=league_id,
        league_name=league_name,
        home_name=pred.context.home_team.name,
        away_name=pred.context.away_team.name,
        market=market,
        selection=selection,
        probability=probability,
        baseline=baseline,
        edge=probability - baseline,
        strength=pick_strength(probability, baseline, pred.confidence),
        confidence=pred.confidence,
        match_key=match_key,
        date=pred.context.match.date,
    )


def candidate_signals(pred, match_key: str = "") -> list[HotPick]:
    """All plausible strong signals from one prediction, best-first.

    Redundant markets are collapsed (only the strongest 1X2/DNB/OU/BTTS side is
    kept) so one match cannot crowd out every other match in a league.
    """
    ctx = pred.context
    league_id = ctx.match.league_id
    league_name = ctx.league_name
    markets = pred.markets
    out: list[HotPick] = []

    # 1X2 — strongest side only.
    x = markets.get("1X2", {})
    best_1x2 = max(x, key=lambda k: x.get(k, 0.0)) if x else ""
    if best_1x2:
        label = {"H": "Home win", "D": "Draw", "A": "Away win"}[best_1x2]
        out.append(_candidate(
            pred, league_id=league_id, league_name=league_name, market="1X2",
            selection=label, probability=x[best_1x2], baseline=1 / 3, match_key=match_key,
        ))

    # Draw no bet — strongest side only.
    dnb = markets.get("DNB", {})
    best_dnb = max(dnb, key=lambda k: dnb.get(k, 0.0)) if dnb else ""
    if best_dnb and dnb[best_dnb] > 0.5:
        out.append(_candidate(
            pred, league_id=league_id, league_name=league_name, market="Draw no bet",
            selection="Home" if best_dnb == "H" else "Away",
            probability=dnb[best_dnb], baseline=0.5, match_key=match_key,
        ))

    # Over/under — strongest side across the standard lines.
    ou_best: tuple[str, float, float] | None = None  # (selection, probability, baseline)
    for line, values in markets.get("OU", {}).items():
        for side in ("over", "under"):
            val = values.get(side, 0.0)
            if val > 0.5 and (ou_best is None or val > ou_best[1]):
                ou_best = (f"{side.title()} {line}", val, 0.5)
    if ou_best:
        out.append(_candidate(
            pred, league_id=league_id, league_name=league_name,
            market=f"Over/Under {ou_best[0].split()[-1]}",
            selection=ou_best[0], probability=ou_best[1], baseline=ou_best[2],
            match_key=match_key,
        ))

    # Both to score — strongest side only.
    btts = markets.get("BTTS", {})
    best_btts = max(btts, key=lambda k: btts.get(k, 0.0)) if btts else ""
    if best_btts and btts[best_btts] > 0.5:
        out.append(_candidate(
            pred, league_id=league_id, league_name=league_name, market="Both to score",
            selection="Yes" if best_btts == "yes" else "No",
            probability=btts[best_btts], baseline=0.5, match_key=match_key,
        ))

    # Keep genuinely strong candidates only, strongest first.
    out = [p for p in out if p.probability >= p.baseline + 0.04]
    return sorted(out, key=lambda p: (-p.strength, -p.probability))
