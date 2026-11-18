# Football Intel Bot

Telegram bot that produces deep pre-match analysis and probability estimates for football matches.
Covers the top European leagues + Champions League by default: Premier League, La Liga, Serie A,
Bundesliga, Ligue 1, UCL.

## What it analyses

- **H2H** — last meetings with recency weighting
- **Referee history** — games officiated, over-2.5 rate, home-win rate (API-Football)
- **Goal profile** — scoring/conceding splits, xG regression, penalty dependence, late goals
- **Table position & importance** — points gap, relegation/top-four pressure, knockout rounds, rivalries
- **Injuries** — missing players weighted by position/estimated importance (API-Football)
- **Home/away** — separate splits plus a fitted home advantage
- **Tactics & form** — formation/style, recent points per game vs season baseline
- **Markets** — 1X2, Draw No Bet, Asian/European handicap, Over/Under 1.5/2.5/3.5/4.5, BTTS, correct score

The model is a Dixon–Coles-style Poisson score model with recency-weighted attack/defence ratings,
a low-score correction, and bounded multiplicative adjustments for the signals above.

## Quick start (demo mode, no keys needed)

```bash
pip install -r requirements.txt
python -m football_intel.cli demo
python -m football_intel.cli match "Arsenal" "Chelsea"
python -m football_intel.cli today 2
```

Demo mode uses deterministic synthetic data so the whole pipeline is testable offline. It is **not**
real football data — add a provider key for live analysis.

## Live data setup

1. Copy `.env.example` → `.env`.
2. Get a Telegram token: open Telegram → message **@BotFather** → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
3. Get football data (recommended): [API-Football on RapidAPI](https://rapidapi.com/api-sports/api/api-football).
   Free trial available; a paid plan is needed for sustained use. Put the key in `API_FOOTBALL_KEY`.
   Alternative: [football-data.org](https://www.football-data.org/client/register) free tier in `FOOTBALL_DATA_TOKEN`
   (no injuries, referees, tactics or xG).
4. Optionally set `ALLOWED_USER_IDS` to your Telegram numeric ID to restrict access and enable the daily 09:00 digest.
5. Start:

```bash
python -m football_intel.bot.main
```

## Telegram controls (buttons)

The bot is button-driven — press **Start** and use the persistent menu at the bottom of the chat:

| Button | Purpose |
|---|---|
| ⚽ Today | Full analysis for every upcoming match across all covered leagues, grouped by competition |
| 🏆 Leagues | Choose one league (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League) for its own report with at least 10 predictions |
| 🔥 Hot Picks | The model's strongest signals in each league, with confidence/strength scores — NOT guaranteed outcomes |
| 🔍 Match | Deep-dive any matchup; type e.g. `Arsenal vs Chelsea` when asked |
| 📡 Provider | Active data source |
| ♻️ Refresh | Clear the response cache |
| ❓ Help | Re-open the menu |

You can also just type `Arsenal vs Chelsea` in the chat, and the old slash commands (`/start`, `/today`, `/match`, `/leagues`, `/provider`, `/refresh`, `/help`) still work.

## Running in the background / 24-7

```bash
nohup python -m football_intel.bot.main > bot.log 2>&1 &
```

Or with Docker:

```bash
docker build -t football-intel-bot .
docker run --env-file .env -v "$PWD/.data:/app/.data" football-intel-bot
```

### Paid Render background worker (recommended / in use)

The bot runs as a **paid Render background worker** (`0.5c-512mb`, about $7/month). Workers are
always on, never spin down, and do not receive inbound HTTP traffic — Telegram updates arrive via
long polling, so no health endpoint or `SELF_PING_URL` keep-alive is needed. Compute is billed per
second, prorated, so deleting the worker stops the charge.

`render.yaml` describes the worker. To deploy it:

```bash
export GITHUB_TOKEN=...            # GitHub PAT with repo/Contents:write scope
export RENDER_API_KEY=...          # Render API key with service-create permission
export TELEGRAM_BOT_TOKEN=...
export FOOTBALL_DATA_TOKEN=...     # or API_FOOTBALL_KEY for full data
export API_FOOTBALL_KEY=...        # optional but recommended
PYTHONPATH=.deps:. python3 deploy/deploy_render.py
```

Billing must be enabled on the Render account before the API can create a paid service. The script
pushes the code to GitHub and creates the always-on worker; it takes a few minutes to build.

## Adding more leagues

Set `LEAGUE_IDS` in `.env` to any comma-separated API-Football league IDs. Lower tiers ( Championship,
Segunda, Serie B, etc.) work but data quality and API cost both change. "Every league since 2010" is not
practical: coverage is uneven and the request volume is large — start with the included set and expand.

## Notes and limits

- Probabilities are model estimates, not guarantees. No betting system is reliably profitable.
  **Gamble responsibly, 18+ only.**
- Odds/line shopping is not included; the bot outputs model probabilities, not bookmaker prices.
- Referee card/penalty averages are only populated when the provider exposes them; with football-data.org
  they fall back to defaults.
- The free football-data.org token only permits seasons 2023–2025; older seasons (e.g. 2010) return HTTP 403.
  `HISTORY_SEASONS=3` is therefore the maximum useful value on the free tier.
- This sandbox has no `python3-venv`, so dependencies were installed into `.deps`. Run with
  `PYTHONPATH=.deps:. python3 -m ...` or use Docker locally.
