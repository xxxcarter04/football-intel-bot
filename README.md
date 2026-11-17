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

Telegram commands:

| Command | Purpose |
|---|---|
| `/today [days]` | Upcoming fixtures with tap-to-expand buttons |
| `/match Team A vs Team B` | Full deep-dive report |
| `/leagues` | Covered competitions |
| `/provider` | Active data source |
| `/refresh` | Clear the response cache |
| `/help` | Help |

You can also just type `Arsenal vs Chelsea` in the chat.

## Running in the background / 24-7

```bash
nohup python -m football_intel.bot.main > bot.log 2>&1 &
```

Or with Docker:

```bash
docker build -t football-intel-bot .
docker run --env-file .env -v "$PWD/.data:/app/.data" football-intel-bot
```

### Free Render deployment (currently in use)

The bot runs as a **free Render web service**. Render's free web services sleep after ~15 minutes
without inbound traffic, so the app exposes a tiny HTTP health endpoint (`PORT`, default 8080) and,
when `SELF_PING_URL` is set, pings that URL every 5 minutes from a background thread to stay awake.

`render.yaml` describes this service. The live deployment is at
`https://football-intel-bot-free.onrender.com/`.

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
- This sandbox has no `python3-venv`, so dependencies were installed into `.deps`. Run with
  `PYTHONPATH=.deps:. python3 -m ...` or use Docker locally.
