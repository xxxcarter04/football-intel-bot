from __future__ import annotations

import math
from dataclasses import dataclass, field

from football_intel.data.models import FixtureContext

from .features import FeatureSet, TeamStrength, _clamp, build_features
from .patterns import analyze_statistics

MAX_GOALS = 12
RHO = -0.08  # Dixon-Coles low-score correction


@dataclass
class Prediction:
    context: FixtureContext
    features: FeatureSet
    lam_home: float
    lam_away: float
    matrix: list[list[float]]
    probs: dict[str, float] = field(default_factory=dict)
    top_scores: list[tuple[int, int, float]] = field(default_factory=list)
    markets: dict = field(default_factory=dict)
    patterns: dict = field(default_factory=dict)  # historical statistics summary
    confidence: float = 0.0


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam + k * math.log(max(lam, 1e-9)) - math.lgamma(k + 1))


def _tau(x: int, y: int, lh: float, la: float) -> float:
    if x == 0 and y == 0:
        return 1 - lh * la * RHO
    if x == 0 and y == 1:
        return 1 + lh * RHO
    if x == 1 and y == 0:
        return 1 + la * RHO
    if x == 1 and y == 1:
        return 1 - RHO
    return 1.0


def _form_factor(s: TeamStrength) -> float:
    baseline = max(s.season_ppg, 0.5)
    return _clamp(1 + 0.11 * (s.form_ppg - baseline) / baseline, 0.82, 1.2)


def _attack_adjust(s: TeamStrength, fs: FeatureSet) -> float:
    # Regression to mean when scoring far above expected goals; penalties regress harder.
    xg_regression = 1 - 0.045 * _clamp(s.xg_delta, -1.5, 1.5)
    penalty_regression = 1 - 0.05 * _clamp(s.penalty_share, 0, 0.4)
    late_goals = 1 + 0.03 * (s.late_goal_share - 0.5)
    return _clamp(xg_regression * penalty_regression * late_goals * (1 - s.injury_attack_hit), 0.7, 1.15)


def predict(ctx: FixtureContext) -> Prediction:
    fs = build_features(ctx)
    h, a = fs.home, fs.away

    h2h_h = 1 + (fs.h2h_home_bias - 1) * fs.h2h_weight
    h2h_a = 1 + (1 / fs.h2h_home_bias - 1) * fs.h2h_weight
    h2h_goals = 1 + (fs.h2h_goals - 1) * fs.h2h_weight

    lam_h = (
        fs.league_avg_home * h.attack * a.defense * h.home_boost
        * _form_factor(h) * _attack_adjust(h, fs)
        * (1 + a.injury_defense_hit)
        * h2h_h * h2h_goals
        * fs.referee_goal_factor * fs.referee_home_factor
        * fs.importance_goal_factor * fs.tactical_goal_factor
    )
    lam_a = (
        fs.league_avg_away * a.attack * h.defense * a.away_drag
        * _form_factor(a) * _attack_adjust(a, fs)
        * (1 + h.injury_defense_hit)
        * h2h_a * h2h_goals
        * fs.referee_goal_factor / fs.referee_home_factor
        * fs.importance_goal_factor * fs.tactical_goal_factor
    )
    lam_h = _clamp(lam_h, 0.18, 4.2)
    lam_a = _clamp(lam_a, 0.15, 4.0)

    matrix = [
        [poisson(x, lam_h) * poisson(y, lam_a) * _tau(x, y, lam_h, lam_a)
         for y in range(MAX_GOALS + 1)]
        for x in range(MAX_GOALS + 1)
    ]
    total = sum(sum(row) for row in matrix)
    matrix = [[v / total for v in row] for row in matrix]

    ph = sum(matrix[x][y] for x in range(MAX_GOALS + 1) for y in range(x))
    pd = sum(matrix[x][x] for x in range(MAX_GOALS + 1))
    pa = sum(matrix[x][y] for x in range(MAX_GOALS + 1) for y in range(x + 1, MAX_GOALS + 1))

    scores = sorted(
        ((x, y, matrix[x][y]) for x in range(6) for y in range(6)),
        key=lambda t: -t[2],
    )[:6]

    conf = _clamp(
        ctx.data_quality * (0.75 + 0.25 * min(1.0, (h.matches + a.matches) / 80)),
        0.25, 0.96,
    )

    pred = Prediction(
        context=ctx, features=fs, lam_home=lam_h, lam_away=lam_a,
        matrix=matrix,
        probs={"H": ph, "D": pd, "A": pa},
        top_scores=scores,
        confidence=conf,
    )
    pred.markets = build_markets(pred)
    pred.patterns = analyze_statistics(ctx)
    return pred


def build_markets(p: Prediction) -> dict:
    m = p.matrix
    ph, pd, pa = p.probs["H"], p.probs["D"], p.probs["A"]

    dnb_total = ph + pa
    over_under = {}
    for line in (1.5, 2.5, 3.5, 4.5):
        over = sum(
            m[x][y] for x in range(MAX_GOALS + 1) for y in range(MAX_GOALS + 1)
            if x + y > line
        )
        over_under[line] = {"over": over, "under": 1 - over}

    handicaps = {}
    for line in [x / 2 for x in range(-6, 7)]:
        win = push = lose = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                adj = x + line - y
                if adj > 0:
                    win += m[x][y]
                elif adj == 0:
                    push += m[x][y]
                else:
                    lose += m[x][y]
        active = 1 - push
        handicaps[line] = {
            "home": win / active if active > 0 else 0,
            "away": lose / active if active > 0 else 0,
            "push": push,
        }

    btts = sum(m[x][y] for x in range(1, MAX_GOALS + 1) for y in range(1, MAX_GOALS + 1))
    return {
        "1X2": {"H": ph, "D": pd, "A": pa},
        "DNB": {"H": ph / dnb_total, "A": pa / dnb_total},
        "OU": over_under,
        "AH": handicaps,
        "BTTS": {"yes": btts, "no": 1 - btts},
    }
