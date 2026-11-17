from __future__ import annotations

import argparse
import re

from .analysis.report import render_analysis, render_quick
from .service import AnalysisService


def main() -> None:
    parser = argparse.ArgumentParser(description="Football match intelligence (no Telegram required)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    match = sub.add_parser("match", help="Analyse a matchup")
    match.add_argument("teams", nargs="+", help='e.g. "Arsenal" "Chelsea" or "Arsenal vs Chelsea"')

    sub.add_parser("demo", help="Analyse a sample fixture")
    today = sub.add_parser("today", help="List upcoming fixtures")
    today.add_argument("days", nargs="?", type=int, default=2)

    args = parser.parse_args()
    svc = AnalysisService()

    if args.cmd == "demo":
        fixture = svc.find_fixture("Arsenal", "Chelsea") or svc.upcoming(2)[0]
        print(render_analysis(svc.analyze(fixture)))
    elif args.cmd == "today":
        preds = svc.digest(args.days, limit=12)
        for p in preds:
            print(render_quick(p))
    else:
        raw = " ".join(args.teams)
        parts = re.split(r"\s+(?:vs|v|-)\s+", raw, flags=re.I)
        if len(parts) != 2 and len(args.teams) == 2:
            parts = args.teams
        if len(parts) != 2:
            parser.error('Provide two teams: python -m football_intel.cli match "Arsenal" "Chelsea"')
        fixture = svc.find_fixture(*parts)
        if not fixture:
            raise SystemExit("Team not found.")
        print(render_analysis(svc.analyze(fixture)))


if __name__ == "__main__":
    main()
