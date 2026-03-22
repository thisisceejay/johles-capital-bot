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
    """Visual impact indicator — compact premium style."""
    bars = {"High": "▰▰▰ HIGH", "Medium": "▰▰░ MED", "Low": "▰░░ LOW"}
    return bars.get(impact, "░░░")


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_session_briefing(session_name: str, events: list) -> str:
    """Format a session opening briefing — compact premium style."""
    now_utc = datetime.utcnow()
    session = SESSIONS[session_name]
    pairs_str = "  ".join(session["pairs"])
    session_icons = {"ASIAN": "🌏", "LONDON": "🏛", "NEW YORK": "🗽"}
    icon = session_icons.get(session_name, "📡")

    if not events:
        return (
            f"{icon} <b>{session_name}</b>  <code>{now_utc.strftime('%H:%M')} UTC</code>\n"
            f"<code>{pairs_str}</code>\n"
            f"✅  Clear — no high-impact events"
        )
    else:
        lines = f"{icon} <b>{session_name}</b>  <code>{now_utc.strftime('%H:%M')} UTC</code>\n"
        lines += f"<code>{pairs_str}</code>\n"
        lines += f"🔴  <b>{len(events)} high-impact event{'s' if len(events)>1 else ''} ahead</b>\n\n"
        for e in events:
            event_time = parse_event_time(e)
            time_str = event_time.strftime("%H:%M") if event_time else "TBC"
            forecast = e.get("forecast", "—") or "—"
            prev = e.get("previous", "—") or "—"
            lines += (
                f"<b>▌{e.get('country','').upper()}  {time_str}</b>  {e.get('title','')}\n"
                f"  F <code>{forecast}</code>  P <code>{prev}</code>\n"
            )
        return lines.rstrip()


def fmt_warning(event: dict, minutes: int) -> str:
    """Format a pre-event warning — compact premium style."""
    event_time = parse_event_time(event)
    time_str = event_time.strftime("%H:%M") if event_time else "TBC"
    pairs = "  ".join(get_pairs_for_event(event))
    prev = event.get("previous", "—") or "—"
    forecast = event.get("forecast", "—") or "—"
    currency = event.get("country", "").upper()
    title = event.get("title", "")

    if minutes == 30:
        icon = "⚠️"
        note = "Review positions."
    else:
        icon = "🚨"
        note = "Final warning."

    return (
        f"{icon} <b>{minutes}MIN  ▌{currency}  {time_str} UTC</b>\n"
        f"<b>{title}</b>\n"
        f"<code>{pairs}</code>\n"
        f"F <code>{forecast}</code>  P <code>{prev}</code>\n"
        f"<i>{note}</i>"
    )


def fmt_result(event: dict) -> str:
    """Format a post-event result — compact premium style."""
    event_time = parse_event_time(event)
    time_str = event_time.strftime("%H:%M") if event_time else "TBC"
    pairs = "  ".join(get_pairs_for_event(event))
    prev     = event.get("previous", "—") or "—"
    forecast = event.get("forecast", "—") or "—"
    actual   = event.get("actual", "—") or "—"
    currency = event.get("country", "").upper()
    title    = event.get("title", "")

    verdict = "📊"
    tag = "—"
    try:
        a = float(actual.replace("%","").replace("K","000").replace("M","000000").strip())
        f_val = float(forecast.replace("%","").replace("K","000").replace("M","000000").strip())
        if a > f_val:
            verdict = "✅"
            tag = "BEAT"
        elif a < f_val:
            verdict = "❌"
            tag = "MISS"
        else:
            verdict = "➡️"
            tag = "IN LINE"
    except:
        pass

    return (
        f"{verdict} <b>▌{currency}  {time_str}  {tag}</b>\n"
        f"{title}\n"
        f"<code>{pairs}</code>\n"
        f"A <code>{actual}</code>  F <code>{forecast}</code>  P <code>{prev}</code>"
    )




# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLER — responds to /week, /today, /next, /help
# ══════════════════════════════════════════════════════════════════════════════

def get_updates(offset: int = 0) -> list:
    """Poll Telegram for new messages/commands."""
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 5},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("result", [])
    except:
        pass
    return []


def fmt_week_view(events: list) -> str:
    """Format full week high-impact calendar — like ForexFactory red folder view."""
    filtered = filter_events(events)
    if not filtered:
        return (
            "📅 <b>JOHLES CAPITAL · WEEKLY CALENDAR</b>
"
            "─────────────────────────────────
"
            "✅ No high-impact events this week.
"
            "<i>JOHLES Capital Intelligence</i>"
        )

    # Group by day
    days = {}
    for e in filtered:
        t = parse_event_time(e)
        if t:
            day = t.strftime("%A %d %B")
        else:
            day = e.get("date", "Unknown")
        if day not in days:
            days[day] = []
        days[day].append(e)

    msg = (
        "📅 <b>JOHLES CAPITAL · WEEKLY HIGH-IMPACT CALENDAR</b>
"
        "─────────────────────────────────

"
    )

    for day, day_events in days.items():
        msg += f"<b>🗓 {day}</b>
"
        for e in day_events:
            t = parse_event_time(e)
            time_str = t.strftime("%H:%M UTC") if t else "TBC"
            currency = e.get("country", "").upper()
            title = e.get("title", "")
            forecast = e.get("forecast", "—") or "—"
            prev = e.get("previous", "—") or "—"
            pairs = " · ".join(get_pairs_for_event(e))
            msg += (
                f"  🔴 <b>{time_str}</b> {currency} — <b>{title}</b>
"
                f"       <code>{pairs}</code>
"
                f"       Forecast: <b>{forecast}</b>  |  Prev: {prev}
"
            )
        msg += "
"

    msg += "─────────────────────────────────
"
    msg += f"<b>{len(filtered)} high-impact events this week</b>
"
    msg += "<i>JOHLES Capital Intelligence</i>"
    return msg


def fmt_today_view(events: list) -> str:
    """Format today's high-impact events."""
    today = datetime.utcnow().date()
    filtered = [e for e in filter_events(events) if parse_event_time(e) and parse_event_time(e).date() == today]

    if not filtered:
        return (
            f"📅 <b>TODAY — {today.strftime('%A %d %B %Y')}</b>
"
            "─────────────────────────────────
"
            "✅ No high-impact events today.
"
            "Clear to trade your setups.
"
            "<i>JOHLES Capital Intelligence</i>"
        )

    msg = (
        f"📅 <b>TODAY — {today.strftime('%A %d %B %Y').upper()}</b>
"
        "─────────────────────────────────

"
    )

    for e in filtered:
        t = parse_event_time(e)
        time_str = t.strftime("%H:%M UTC") if t else "TBC"
        currency = e.get("country", "").upper()
        title = e.get("title", "")
        forecast = e.get("forecast", "—") or "—"
        prev = e.get("previous", "—") or "—"
        pairs = " · ".join(get_pairs_for_event(e))
        now = datetime.utcnow()
        if t:
            diff = (t - now).total_seconds() / 60
            if diff > 0:
                status = f"in {int(diff)}min"
            else:
                status = "passed"
        else:
            status = ""

        msg += (
            f"🔴 <b>{time_str}</b> {f'({status})' if status else ''}
"
            f"<b>{currency} — {title}</b>
"
            f"Pairs: <code>{pairs}</code>
"
            f"Forecast: <b>{forecast}</b>  |  Previous: {prev}
"
            f"Impact: {impact_bar(e.get('impact',''))}

"
        )

    msg += "─────────────────────────────────
"
    msg += "<i>JOHLES Capital Intelligence</i>"
    return msg


def fmt_next_event(events: list) -> str:
    """Show the very next upcoming high-impact event."""
    now = datetime.utcnow()
    upcoming = []
    for e in filter_events(events):
        t = parse_event_time(e)
        if t and t > now:
            upcoming.append((t, e))
    upcoming.sort(key=lambda x: x[0])

    if not upcoming:
        return (
            "⏭ <b>NEXT HIGH-IMPACT EVENT</b>
"
            "─────────────────────────────────
"
            "No upcoming events found this week.
"
            "<i>JOHLES Capital Intelligence</i>"
        )

    t, e = upcoming[0]
    diff = (t - now).total_seconds() / 60
    hours = int(diff // 60)
    mins = int(diff % 60)
    time_left = f"{hours}h {mins}min" if hours > 0 else f"{mins} minutes"
    currency = e.get("country", "").upper()
    title = e.get("title", "")
    forecast = e.get("forecast", "—") or "—"
    prev = e.get("previous", "—") or "—"
    pairs = " · ".join(get_pairs_for_event(e))

    return (
        f"⏭ <b>NEXT HIGH-IMPACT EVENT</b>
"
        f"─────────────────────────────────
"
        f"🔴 <b>{currency} — {title}</b>
"
        f"🕐 <b>{t.strftime('%H:%M UTC')} · {t.strftime('%A %d %B')}</b>
"
        f"⏱ <b>{time_left} away</b>

"
        f"Pairs: <code>{pairs}</code>
"
        f"Forecast: <b>{forecast}</b>  |  Previous: {prev}
"
        f"Impact: {impact_bar(e.get('impact',''))}
"
        f"─────────────────────────────────
"
        f"<i>JOHLES Capital Intelligence</i>"
    )


def fmt_help() -> str:
    return (
        "🤖 <b>JOHLES CAPITAL INTELLIGENCE</b>
"
        "─────────────────────────────────
"
        "<b>Available commands:</b>

"
        "/week — Full week high-impact calendar
"
        "/today — Today's events only
"
        "/next — Next upcoming event
"
        "/help — Show this menu

"
        "─────────────────────────────────
"
        "<b>Automatic alerts:</b>
"
        "• Session briefing at market open
"
        "• 30-min warning before events
"
        "• 10-min warning before events
"
        "• Result summary after events
"
        "─────────────────────────────────
"
        "<i>Monitoring: EURUSD · GBPUSD · USDJPY
"
        "AUDUSD · USDCAD · NZDUSD · USDCHF · XAUUSD</i>"
    )


def handle_commands(calendar_cache: list, last_update_id: list):
    """Check for and handle incoming commands."""
    updates = get_updates(last_update_id[0] + 1)
    for update in updates:
        last_update_id[0] = update.get("update_id", last_update_id[0])
        msg = update.get("message", {})
        text = msg.get("text", "").strip().lower()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Only respond to our chat
        if chat_id != CHAT_ID:
            continue

        if text in ["/week", "/week@johlescapitalbot"]:
            send_message(fmt_week_view(calendar_cache))
            log.info("Sent /week response")
        elif text in ["/today", "/today@johlescapitalbot"]:
            send_message(fmt_today_view(calendar_cache))
            log.info("Sent /today response")
        elif text in ["/next", "/next@johlescapitalbot"]:
            send_message(fmt_next_event(calendar_cache))
            log.info("Sent /next response")
        elif text in ["/help", "/start", "/help@johlescapitalbot"]:
            send_message(fmt_help())
            log.info("Sent /help response")


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

    last_update_id = [0]  # track last processed update

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

            # Handle incoming commands (/week, /today, /next, /help)
            handle_commands(calendar_cache, last_update_id)

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
