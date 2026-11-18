from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time as time_module
import urllib.request
from datetime import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..analysis.report import (
    render_all_leagues,
    render_analysis,
    render_hot_picks,
    render_league_predictions,
    render_quick,
)
from ..config import get_settings
from ..service import AnalysisService, match_key

log = logging.getLogger(__name__)
settings = get_settings()
service = AnalysisService()
fixtures: dict[str, object] = {}  # callback id -> Match, per-process

LEAGUE_NAMES = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "Champions League",
}
BTN_TODAY = "⚽ Today"
BTN_LEAGUES = "🏆 Leagues"
BTN_HOT = "🔥 Hot Picks"
BTN_MATCH = "🔍 Match"
BTN_PROVIDER = "📡 Provider"
BTN_REFRESH = "♻️ Refresh"
BTN_HELP = "❓ Help"


def permitted(update: Update) -> bool:
    if not settings.allowed_users:
        return True
    return bool(update.effective_user and update.effective_user.id in settings.allowed_users)


def main_menu() -> ReplyKeyboardMarkup:
    """Persistent bottom menu — every control is a button, no slash needed."""
    keyboard = [
        [KeyboardButton(BTN_TODAY), KeyboardButton(BTN_LEAGUES), KeyboardButton(BTN_HOT)],
        [KeyboardButton(BTN_MATCH), KeyboardButton(BTN_PROVIDER), KeyboardButton(BTN_REFRESH)],
        [KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


async def send_menu(text: str, update: Update, **kwargs) -> None:
    await safe_send(text, update, reply_markup=main_menu(), **kwargs)


async def safe_send(text: str, update: Update, **kwargs) -> None:
    # Telegram hard limit is 4096 characters per message.
    for i in range(0, len(text), 3900):
        chunk = text[i : i + 3900]
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, **kwargs
                )
            elif update.message:
                await update.message.reply_text(
                    chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, **kwargs
                )
        except TelegramError as exc:
            if "can't parse entities" in str(exc).lower():
                plain = re.sub(r"[*_`]", "", chunk)
                await update.effective_chat.send_message(plain, **kwargs)
            else:
                raise


def league_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(LEAGUE_NAMES.get(lid, f"League {lid}"), callback_data=f"lg:{lid}")
        for lid in settings.leagues
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🌍 All leagues — full report", callback_data="lgall:2")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    await safe_send(
        "⚽ *Football Intel Bot*\n\n"
        "Use the buttons below — no commands needed.\n\n"
        "• *Today* — full analysis across all covered leagues\n"
        "• *Leagues* — choose one league for its own 10+ predictions\n"
        "• *Hot Picks* — strongest model signals in each league\n"
        "• *Match* — deep-dive any matchup (type \"Team A vs Team B\")\n"
        "• *Provider* — active data source\n"
        "• *Refresh* — clear cached data\n\n"
        "Estimates are model outputs, not certainties. Gamble responsibly, 18+.",
        update,
        reply_markup=main_menu(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


def split_teams(raw: str) -> list[str]:
    """Split 'A vs B', 'A v B', 'A - B' and comma-separated forms."""
    parts = re.split(r"\s+(?:vs\.?|v|-)\s+|\s*,\s*", raw.strip(), flags=re.IGNORECASE)
    return [p.strip(" \t\n-–—") for p in parts if p.strip()]


def looks_like_match(text: str) -> bool:
    return bool(
        re.search(r"\bvs\.?\b", text, re.IGNORECASE)
        or re.search(r"\s+v\s+", text, re.IGNORECASE)
        or re.search(r"\s+-\s+", text)
        or "," in text
    )


async def run_match(raw: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parts = split_teams(raw)
    context.user_data.pop("awaiting_match", None)
    if len(parts) != 2:
        await send_menu("Usage: type two teams, e.g. *Arsenal vs Chelsea*", update)
        return
    await update.effective_chat.send_action("typing")
    match = await asyncio.to_thread(service.find_fixture, parts[0], parts[1])
    if not match:
        await send_menu(
            "Couldn't find one of those teams. Try full names, e.g. *Arsenal vs Chelsea*.", update
        )
        return
    fixtures[match_key(match)] = match
    pred = await asyncio.to_thread(service.analyze, match)
    await send_menu(render_analysis(pred), update)
    log.info("Match report: %s vs %s", parts[0], parts[1])


async def cmd_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        context.user_data["awaiting_match"] = True
        await send_menu("Send the two teams, e.g. *Arsenal vs Chelsea*", update)
        return
    await run_match(raw, update, context)


async def cmd_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    text = (update.message.text or "").strip()
    log.info("Menu input: %r", text)

    if context.user_data.get("awaiting_match"):
        await run_match(text, update, context)
        return

    label = text
    if label.lower() in ("start", "help"):
        await cmd_start(update, context)
    elif label == BTN_TODAY:
        await cmd_today(update, context)
    elif label == BTN_LEAGUES:
        await safe_send(
            "🏆 Choose a league for its own report (10+ predictions each):",
            update,
            reply_markup=league_keyboard(),
        )
    elif label == BTN_HOT:
        await cmd_hot(update, context)
    elif label == BTN_MATCH:
        context.user_data["awaiting_match"] = True
        await send_menu("Send the two teams, e.g. *Arsenal vs Chelsea*", update)
    elif label == BTN_PROVIDER:
        await cmd_provider(update, context)
    elif label == BTN_REFRESH:
        await cmd_refresh(update, context)
    elif label == BTN_HELP:
        await cmd_start(update, context)
    elif looks_like_match(text):
        await run_match(text, update, context)
    else:
        await cmd_start(update, context)


async def cmd_leagues(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    await cmd_message_menu(update)


async def cmd_message_menu(update: Update) -> None:
    await safe_send(
        "🏆 Choose a league for its own report (10+ predictions each):",
        update,
        reply_markup=league_keyboard(),
    )


async def cmd_provider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    mode = settings.provider
    label = {
        "api-football": "API-Football (full: H2H, referees, injuries, tactics, xG)",
        "football-data": "football-data.org (reduced: no injuries/referees/tactics)",
        "demo": "DEMO — synthetic data (add an API key for live data)",
    }[mode]
    await send_menu(f"📡 Data source: *{label}*\nHistory window: {settings.history_seasons} seasons", update)


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    service.clear_caches()
    await send_menu("🗑 Cache cleared. Next query will re-fetch data.", update)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    args = context.args or []
    try:
        days = min(max(int(args[0]), 1), 7) if args else 2
    except ValueError:
        days = 2
    await safe_send(f"⏳ Analysing matches across all covered leagues (next {days} days)…", update)
    matches = await asyncio.to_thread(service.upcoming, days)
    if not matches:
        await send_menu("No fixtures found in that window.", update)
        return

    truncated = len(matches) > 20
    matches = matches[:20]
    preds = await asyncio.to_thread(service.digest_fast, days, 20)
    await send_menu(render_all_leagues(preds, days, truncated), update)


async def cmd_hot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    await safe_send("⏳ Building Hot Picks across all leagues — this can take a few minutes on the first run…", update)
    picks = await asyncio.to_thread(service.hot_picks, 7, 2)
    for pick in picks:
        match = service.match_for_key(pick.match_key)
        if match is not None:
            fixtures[pick.match_key] = match
    buttons = [
        InlineKeyboardButton(
            f"{LEAGUE_NAMES.get(p.league_id, p.league_name)}: {p.home_name}-{p.away_name}",
            callback_data=f"fx:{p.match_key}",
        )
        for p in picks[:8]
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    reply = InlineKeyboardMarkup(rows) if rows else None
    if reply:
        await safe_send(render_hot_picks(picks, 7), update, reply_markup=reply)
    else:
        await send_menu(render_hot_picks(picks, 7), update)


async def cb_league(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("lgall:"):
        try:
            days = min(max(int(data.split(":", 1)[1]), 1), 7)
        except ValueError:
            days = 2
        context.args = [str(days)]
        await cmd_today(update, context)
        return
    try:
        league_id = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        await safe_send("Unknown league.", update)
        return
    await safe_send("⏳ Building the league report…", update)
    name, preds, sample_filled = await asyncio.to_thread(
        service.league_predictions, league_id, 7, 10
    )
    buttons = [
        InlineKeyboardButton(
            f"{p.context.home_team.name} vs {p.context.away_team.name}",
            callback_data=f"fx:{match_key(p.context.match)}",
        )
        for p in preds[:8]
    ]
    for pred in preds:
        fixtures[match_key(pred.context.match)] = pred.context.match
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    await safe_send(
        render_league_predictions(name, preds, 7, sample_filled),
        update,
        reply_markup=InlineKeyboardMarkup(rows) if rows else None,
    )
    log.info("League report: %s (%d predictions)", name, len(preds))


async def cb_fixture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    query = update.callback_query
    await query.answer()
    key = (query.data or "").split(":", 1)[-1]
    match = fixtures.get(key) or service.match_for_key(key)
    if not match:
        await safe_send("That fixture expired. Tap *Leagues* or *Today* again.", update)
        return
    await query.message.reply_text("⏳ Analysing…")
    pred = await asyncio.to_thread(service.analyze, match)
    await safe_send(render_analysis(pred), update)


async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    preds = await asyncio.to_thread(service.digest, 2, 8)
    if not preds:
        return
    targets = list(settings.allowed_users) if settings.allowed_users else []
    text = "☀️ *Daily briefing*\n\n" + "\n".join(render_quick(p) for p in preds)
    for chat_id in targets:
        try:
            await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except TelegramError as exc:
            log.warning("Digest failed for %s: %s", chat_id, exc)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log failures instead of silently leaving the menu looking dead."""
    log.exception("Update failed: %s", context.error, exc_info=context.error)


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Open the button menu"),
        BotCommand("today", "Full analysis: all leagues"),
        BotCommand("match", "Deep-dive a matchup"),
        BotCommand("leagues", "Choose a league"),
        BotCommand("help", "Help"),
    ])
    if settings.allowed_users and app.job_queue:
        from zoneinfo import ZoneInfo

        hour, minute = (int(x) for x in settings.digest_time.split(":"))
        app.job_queue.run_daily(
            daily_digest,
            time=time(hour=hour, minute=minute, tzinfo=ZoneInfo(settings.timezone)),
            name="daily-digest",
        )


def start_health_server() -> None:
    """Tiny HTTP endpoint kept for compatibility with the legacy free web service."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, fmt, *args):
            pass

    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="health-server").start()


def start_self_ping(url: str) -> None:
    """Legacy free-service keep-alive; ignored by the paid worker."""
    log.info("Self-ping keep-alive enabled: %s", url)

    def loop() -> None:
        while True:
            time_module.sleep(300)
            try:
                urllib.request.urlopen(url, timeout=15).read()
                log.info("self-ping ok")
            except Exception as exc:
                log.warning("self-ping failed: %s", exc)

    threading.Thread(target=loop, daemon=True, name="self-ping").start()


def prewarm_cache() -> None:
    """Fetch league data in the background so the first report is fast."""
    try:
        picks = service.hot_picks(7, 2)
        log.info("Cache prewarmed: %d hot picks across all leagues", len(picks))
    except Exception as exc:
        log.warning("Cache prewarm failed: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing. Add it to .env (see .env.example).")

    start_health_server()
    if os.environ.get("SELF_PING_URL"):
        start_self_ping(os.environ["SELF_PING_URL"])
    threading.Thread(target=prewarm_cache, daemon=True, name="prewarm").start()

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .connect_timeout(25)
        .read_timeout(25)
        .write_timeout(25)
        .pool_timeout(25)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("leagues", cmd_leagues))
    app.add_handler(CommandHandler("provider", cmd_provider))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("match", cmd_match))
    app.add_handler(CallbackQueryHandler(cb_fixture, pattern=r"^fx:"))
    app.add_handler(CallbackQueryHandler(cb_league, pattern=r"^(lg:|lgall:)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_message))
    log.info("Starting bot with provider=%s", settings.provider)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
