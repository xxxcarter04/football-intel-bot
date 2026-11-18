from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time as time_module
import urllib.request
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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

from ..analysis.report import render_all_leagues, render_analysis, render_quick
from ..config import get_settings
from ..service import AnalysisService

log = logging.getLogger(__name__)
settings = get_settings()
service = AnalysisService()
fixtures: dict[str, object] = {}  # callback id -> Match, per-process


def permitted(update: Update) -> bool:
    if not settings.allowed_users:
        return True
    return bool(update.effective_user and update.effective_user.id in settings.allowed_users)


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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    await safe_send(
        "⚽ *Football Intel Bot*\n\n"
        "Commands:\n"
        "/today [days] — full analysis for every match, all leagues\n"
        "/match Team A vs Team B — one-match deep dive\n"
        "/leagues — covered competitions\n"
        "/provider — active data source\n"
        "/refresh — clear cached data\n"
        "/help — this message\n\n"
        "Tip: /today gives the full report for every upcoming match across all leagues. Estimates are model outputs, not certainties.",
        update,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_leagues(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    text = "🏆 *Covered competitions*\n" + "\n".join(
        f"• {service.provider.league_name(lid, 0)} (id {lid})" for lid in settings.leagues
    )
    await safe_send(text, update)


async def cmd_provider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    mode = settings.provider
    label = {
        "api-football": "API-Football (full: H2H, referees, injuries, tactics, xG)",
        "football-data": "football-data.org (reduced: no injuries/referees/tactics)",
        "demo": "DEMO — synthetic data (add an API key for live data)",
    }[mode]
    await safe_send(f"📡 Data source: *{label}*\nHistory window: {settings.history_seasons} seasons", update)


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    cache = getattr(service.provider, "cache", None)
    if cache:
        cache.clear()
    await safe_send("🗑 Cache cleared. Next query will re-fetch data.", update)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    args = context.args or []
    try:
        days = min(max(int(args[0]), 1), 7) if args else 2
    except ValueError:
        days = 2
    await update.effective_chat.send_action("typing")
    matches = await asyncio.to_thread(service.upcoming, days)
    if not matches:
        await safe_send("No fixtures found in that window.", update)
        return

    truncated = len(matches) > 20
    matches = matches[:20]
    preds = await asyncio.to_thread(lambda: [service.analyze(m) for m in matches])
    await safe_send(render_all_leagues(preds, days, truncated), update)


async def cb_fixture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    query = update.callback_query
    await query.answer()
    key = (query.data or "").split(":", 1)[-1]
    match = fixtures.get(key)
    if not match:
        await safe_send("That fixture expired. Run /today again.", update)
        return
    await query.message.reply_text("⏳ Analysing…")
    pred = await asyncio.to_thread(service.analyze, match)
    await safe_send(render_analysis(pred), update)


async def cmd_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await safe_send("Usage: /match Arsenal vs Chelsea", update)
        return
    parts = re.split(r"\s+(?:vs|v|-)\s+", raw, flags=re.IGNORECASE)
    if len(parts) != 2:
        await safe_send("Usage: /match Arsenal vs Chelsea", update)
        return
    await update.effective_chat.send_action("typing")
    match = await asyncio.to_thread(service.find_fixture, parts[0], parts[1])
    if not match:
        await safe_send("Couldn't find one of those teams. Try full names, e.g. /match Arsenal vs Chelsea.", update)
        return
    pred = await asyncio.to_thread(service.analyze, match)
    await safe_send(render_analysis(pred), update)


async def cmd_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not permitted(update):
        return
    text = (update.message.text or "").strip()
    if " vs " in text.lower() or re.search(r"\s+v\s+", text, re.I):
        context.args = [text]
        await cmd_match(update, context)
    else:
        await cmd_start(update, context)


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


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("today", "Full analysis: all leagues"),
        BotCommand("match", "Deep-dive a matchup"),
        BotCommand("leagues", "Covered leagues"),
        BotCommand("provider", "Data source status"),
        BotCommand("refresh", "Clear cache"),
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
    """Tiny HTTP endpoint so Render's free web service stays reachable."""

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
    """Keep Render's free web service awake from inside the process."""
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing. Add it to .env (see .env.example).")

    start_health_server()
    if os.environ.get("SELF_PING_URL"):
        start_self_ping(os.environ["SELF_PING_URL"])

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .connect_timeout(25)
        .read_timeout(25)
        .write_timeout(25)
        .pool_timeout(25)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("leagues", cmd_leagues))
    app.add_handler(CommandHandler("provider", cmd_provider))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("match", cmd_match))
    app.add_handler(CallbackQueryHandler(cb_fixture, pattern=r"^fx:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_message))
    log.info("Starting bot with provider=%s", settings.provider)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
