"""
JOHLES Capital Intelligence Bot
================================
Forex economic news alerts via Telegram
Covers: EURUSD · GBPUSD · USDJPY · AUDUSD · USDCAD · NZDUSD · USDCHF · XAUUSD

Alert schedule:
  - Session briefing at London, New York and Asian open
  - 30-minute warning before each high-impact event
  - 10-minute warning before each high-impact event
  - Post-event result (5 minutes after)
"""

import requests
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
BOT_TOKEN = "8605698200:AAFPDaGc96pLb6sh8m1-zsabLThUqk0UxW4"
CHAT_ID   = "950479698"

# Free economic calendar API (no key needed)
CALENDAR_API = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Session open times in UTC
SESSIONS = {
    "ASIAN":    {"hour": 23, "minute": 0,  "pairs": ["USDJPY", "AUDUSD", "NZDUSD"]},
    "LONDON":   {"hour": 7,  "minute": 0,  "pairs": ["EURUSD", "GBPUSD", "USDCHF", "XAUUSD"]},
    "NEW YORK": {"hour": 12, "minute": 0,  "pairs": ["EURUSD", "GBPUSD", "USDCAD", "XAUUSD"]},
}

# Only these currencies affect our pairs
TARGET_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "NZD", "CHF"}

# Impact levels to include (only HIGH)
TARGET_IMPACT = {"High"}

# Pairs affected by each currency
CURRENCY_PAIRS = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF", "XAUUSD"],
    "EUR": ["EURUSD"],
    "GBP": ["GBPUSD"],
    "JPY": ["USDJPY"],
    "AUD": ["AUDUSD"],
    "CAD": ["USDCAD"],
    "NZD": ["NZDUSD"],
    "CHF": ["USDCHF"],
}

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("johles_bot.log")
    ]
)
log = logging.getLogger("JOHLES")

# ── STATE TRACKING ────────────────────────────────────────────────────────────
# Tracks which alerts have already been sent to avoid duplicates
sent_alerts = set()   # keys: "EVENT_ID_TYPE" e.g. "nfp_2026-03-20_30min"
session_briefings_sent = set()  # keys: "LONDON_2026-03-20"


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info(f"Message sent OK")
            return True
        else:
            log.error(f"Telegram error: {r.status_code} {r.text}")
            return False
    except Exception as e:
        log.error(f"Send failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR
# ══════════════════════════════════════════════════════════════════════════════

def fetch_calendar() -> list:
    """Fetch this week's economic calendar from ForexFactory."""
    try:
        r = requests.get(CALENDAR_API, timeout=15)
        if r.status_code == 200:
            events = r.json()
            log.info(f"Calendar fetched: {len(events)} events")
            return events
        else:
            log.error(f"Calendar API error: {r.status_code}")
            return []
    except Exception as e:
        log.error(f"Calendar fetch failed: {e}")
        return []


def parse_event_time(event: dict) -> Optional[datetime]:
    """Parse event datetime to UTC datetime object."""
    try:
        date_str = event.get("date", "")
        time_str = event.get("time", "")
        if not date_str or not time_str or time_str.lower() in ["all day", "tentative", ""]:
            return None
        dt_str = f"{date_str} {time_str}"
        # ForexFactory uses Eastern Time (UTC-5 standard, UTC-4 DST)
        # We approximate with UTC-5 — adjust if needed
        fmt = "%m-%d-%Y %I:%M%p"
        dt = datetime.strptime(dt_str, fmt)
        # Convert from ET to UTC (add 5 hours — adjust for DST if needed)
        dt_utc = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
        return dt_utc.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception as e:
        return None


def filter_events(events: list) -> list:
    """Filter to only high-impact events affecting our pairs."""
    filtered = []
    for e in events:
        currency = e.get("country", "").upper()
        impact   = e.get("impact", "")
        if currency in TARGET_CURRENCIES and impact in TARGET_IMPACT:
            filtered.append(e)
    return filtered


def get_pairs_for_event(event: dict) -> list:
    """Get which of our pairs are affected by this event."""
    currency = event.get("country", "").upper()
    return CURRENCY_PAIRS.get(currency, [])


def impact_bar(impact: str) -> str:
    """Visual impact bar."""
    bars = {"High": "🔴🔴🔴🔴🔴", "Medium": "🟡🟡🟡░░", "Low": "🟢🟢░░░"}
    return bars.get(impact, "░░░░░")


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_session_briefing(session_name: str, events: list) -> str:
    """Format a session opening briefing."""
    now_utc = datetime.utcnow()
    session = SESSIONS[session_name]
    pairs_str = " · ".join(session["pairs"])

    header = (
        f"📊 <b>JOHLES CAPITAL · SESSION BRIEFING</b>\n"
        f"{'─' * 32}\n"
        f"<b>{session_name} SESSION OPEN</b>\n"
        f"{now_utc.strftime('%A %d %B %Y · %H:%M UTC')}\n"
        f"<i>Key pairs: {pairs_str}</i>\n"
        f"{'─' * 32}\n\n"
    )

    if not events:
        body = "✅ <b>No high-impact events this session.</b>\nClear conditions. Trade your setup.\n"
    else:
        body = f"⚡ <b>{len(events)} HIGH-IMPACT EVENT(S) THIS SESSION</b>\n\n"
        for e in events:
            event_time = parse_event_time(e)
            time_str = event_time.strftime("%H:%M UTC") if event_time else "TBC"
            pairs = " · ".join(get_pairs_for_event(e))
            prev = e.get("previous", "—") or "—"
            forecast = e.get("forecast", "—") or "—"
            body += (
                f"🕐 <b>{time_str}</b>  {e.get('country','').upper()} — <b>{e.get('title','')}</b>\n"
                f"   Pairs: <code>{pairs}</code>\n"
                f"   Forecast: <b>{forecast}</b>  |  Previous: {prev}\n"
                f"   Impact: {impact_bar(e.get('impact',''))}\n\n"
            )

    footer = (
        f"{'─' * 32}\n"
        f"<i>JOHLES Capital Intelligence · Alerts active</i>"
    )
    return header + body + footer


def fmt_warning(event: dict, minutes: int) -> str:
    """Format a pre-event warning."""
    event_time = parse_event_time(event)
    time_str = event_time.strftime("%H:%M UTC") if event_time else "TBC"
    pairs = " · ".join(get_pairs_for_event(event))
    prev = event.get("previous", "—") or "—"
    forecast = event.get("forecast", "—") or "—"
    currency = event.get("country", "").upper()
    title = event.get("title", "")

    if minutes == 30:
        urgency = "⚠️"
        action = "Review open positions. Decide if you want news exposure or not."
        color = "🟡"
    else:
        urgency = "🚨"
        action = "Final warning. Close positions now if avoiding news, or prepare your entry."
        color = "🔴"

    return (
        f"{urgency} <b>JOHLES CAPITAL · {minutes}MIN WARNING</b>\n"
        f"{'─' * 32}\n"
        f"{color} <b>{currency} — {title}</b>\n"
        f"🕐 <b>{time_str}</b>  ({minutes} minutes away)\n\n"
        f"📌 Pairs affected: <code>{pairs}</code>\n"
        f"📊 Forecast: <b>{forecast}</b>\n"
        f"📈 Previous: {prev}\n"
        f"💥 Impact: {impact_bar(event.get('impact',''))}\n\n"
        f"{'─' * 32}\n"
        f"⚡ <b>ACTION:</b> {action}\n"
        f"{'─' * 32}\n"
        f"<i>JOHLES Capital Intelligence</i>"
    )


def fmt_result(event: dict) -> str:
    """Format a post-event result."""
    event_time = parse_event_time(event)
    time_str = event_time.strftime("%H:%M UTC") if event_time else "TBC"
    pairs = " · ".join(get_pairs_for_event(event))
    prev     = event.get("previous", "—") or "—"
    forecast = event.get("forecast", "—") or "—"
    actual   = event.get("actual", "—") or "Pending..."
    currency = event.get("country", "").upper()
    title    = event.get("title", "")

    # Determine beat/miss/inline
    assessment = "📋 Result posted — check charts for reaction."
    try:
        a = float(actual.replace("%","").replace("K","000").replace("M","000000").strip())
        f = float(forecast.replace("%","").replace("K","000").replace("M","000000").strip())
        if a > f:
            assessment = "✅ BEAT FORECAST — Bullish for " + currency
        elif a < f:
            assessment = "❌ MISSED FORECAST — Bearish for " + currency
        else:
            assessment = "➡️ IN LINE WITH FORECAST — Muted reaction expected"
    except:
        pass

    return (
        f"📋 <b>JOHLES CAPITAL · EVENT RESULT</b>\n"
        f"{'─' * 32}\n"
        f"<b>{currency} — {title}</b>\n"
        f"🕐 {time_str}\n\n"
        f"📌 Pairs: <code>{pairs}</code>\n"
        f"🎯 Forecast: {forecast}\n"
        f"📊 Previous: {prev}\n"
        f"✅ <b>Actual: {actual}</b>\n\n"
        f"{'─' * 32}\n"
        f"{assessment}\n"
        f"{'─' * 32}\n"
        f"<i>JOHLES Capital Intelligence</i>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

def get_session_for_now(now: datetime) -> Optional[str]:
    """Return which session just opened (within the last minute)."""
    for name, s in SESSIONS.items():
        if now.hour == s["hour"] and now.minute == s["minute"]:
            return name
    return None


def get_session_events(session_name: str, all_events: list) -> list:
    """Get events scheduled during a session window."""
    session = SESSIONS[session_name]
    session_start = datetime.utcnow().replace(
        hour=session["hour"], minute=session["minute"], second=0, microsecond=0
    )
    # Next session is roughly 8 hours later
    session_end = session_start + timedelta(hours=8)
    result = []
    for e in filter_events(all_events):
        t = parse_event_time(e)
        if t and session_start <= t <= session_end:
            result.append(e)
    return result


def make_event_key(event: dict) -> str:
    """Unique key for an event."""
    return f"{event.get('title','').replace(' ','_')}_{event.get('date','')}"


def main():
    log.info("═══ JOHLES Capital Intelligence Bot starting ═══")

    # Send startup message
    send_message(
        "🟢 <b>JOHLES CAPITAL INTELLIGENCE</b>\n"
        "─────────────────────────────────\n"
        "System online. Monitoring high-impact\n"
        "Forex events for:\n\n"
        "<code>EURUSD · GBPUSD · USDJPY · AUDUSD\n"
        "USDCAD · NZDUSD · USDCHF · XAUUSD</code>\n\n"
        "Alert schedule:\n"
        "• Session briefing at market open\n"
        "• 30-min warning before events\n"
        "• 10-min warning before events\n"
        "• Result summary after events\n"
        "─────────────────────────────────\n"
        "<i>JOHLES Capital · Stage 1 · Cycle 1</i>"
    )

    # Cache calendar (refresh every 4 hours)
    calendar_cache = []
    last_fetch = 0

    while True:
        try:
            now = datetime.utcnow()
            now_ts = time.time()

            # Refresh calendar every 4 hours
            if now_ts - last_fetch > 14400:
                calendar_cache = fetch_calendar()
                last_fetch = now_ts
                log.info(f"Calendar refreshed: {len(calendar_cache)} total, {len(filter_events(calendar_cache))} high-impact")

            high_impact = filter_events(calendar_cache)

            # ── Session briefing ──────────────────────────────────────────────
            session = get_session_for_now(now)
            if session:
                key = f"{session}_{now.strftime('%Y-%m-%d')}"
                if key not in session_briefings_sent:
                    events_this_session = get_session_events(session, calendar_cache)
                    msg = fmt_session_briefing(session, events_this_session)
                    if send_message(msg):
                        session_briefings_sent.add(key)
                        log.info(f"Session briefing sent: {session}")

            # ── Event alerts ──────────────────────────────────────────────────
            for event in high_impact:
                event_time = parse_event_time(event)
                if not event_time:
                    continue

                key = make_event_key(event)
                diff = (event_time - now).total_seconds() / 60  # minutes until event

                # 30-minute warning
                if 29 <= diff <= 31:
                    alert_key = f"{key}_30min"
                    if alert_key not in sent_alerts:
                        if send_message(fmt_warning(event, 30)):
                            sent_alerts.add(alert_key)
                            log.info(f"30min warning sent: {event.get('title')}")

                # 10-minute warning
                elif 9 <= diff <= 11:
                    alert_key = f"{key}_10min"
                    if alert_key not in sent_alerts:
                        if send_message(fmt_warning(event, 10)):
                            sent_alerts.add(alert_key)
                            log.info(f"10min warning sent: {event.get('title')}")

                # Post-event result (5-10 min after)
                elif -10 <= diff <= -5:
                    alert_key = f"{key}_result"
                    if alert_key not in sent_alerts:
                        if send_message(fmt_result(event)):
                            sent_alerts.add(alert_key)
                            log.info(f"Result sent: {event.get('title')}")

            # Check every 60 seconds
            time.sleep(60)

        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
            send_message("🔴 <b>JOHLES Capital Intelligence</b>\nBot stopped manually.")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
