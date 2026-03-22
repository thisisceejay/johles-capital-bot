"""
JOHLES Capital Intelligence Bot
Forex economic news alerts via Telegram
"""

import requests
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

BOT_TOKEN    = "8605698200:AAFPDaGc96pLb6sh8m1-zsabLThUqk0UxW4"
CHAT_ID      = "950479698"
CALENDAR_API = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

SESSIONS = {
    "ASIAN":    {"hour": 23, "minute": 0, "pairs": ["USDJPY", "AUDUSD", "NZDUSD"]},
    "LONDON":   {"hour": 7,  "minute": 0, "pairs": ["EURUSD", "GBPUSD", "USDCHF", "XAUUSD"]},
    "NEW YORK": {"hour": 12, "minute": 0, "pairs": ["EURUSD", "GBPUSD", "USDCAD", "XAUUSD"]},
}

TARGET_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "NZD", "CHF"}
TARGET_IMPACT     = {"High"}

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("johles_bot.log")]
)
log = logging.getLogger("JOHLES")

sent_alerts            = set()
session_briefings_sent = set()


def send_message(text):
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("Message sent OK")
            return True
        log.error(f"Telegram error: {r.status_code} {r.text}")
        return False
    except Exception as e:
        log.error(f"Send failed: {e}")
        return False


def get_updates(offset=0):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 2}, timeout=8
        )
        if r.status_code == 200:
            return r.json().get("result", [])
    except:
        pass
    return []


def fetch_calendar():
    try:
        r = requests.get(CALENDAR_API, timeout=15)
        if r.status_code == 200:
            events = r.json()
            log.info(f"Calendar fetched: {len(events)} events")
            return events
        log.error(f"Calendar API error: {r.status_code}")
        return []
    except Exception as e:
        log.error(f"Calendar fetch failed: {e}")
        return []


def parse_event_time(event):
    try:
        date_str = event.get("date", "")
        time_str = event.get("time", "")
        if not date_str or not time_str or time_str.lower() in ["all day", "tentative", ""]:
            return None
        dt  = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
        utc = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
        return utc.astimezone(timezone.utc).replace(tzinfo=None)
    except:
        return None


def parse_event_date(event):
    """Parse just the date from the event for display."""
    try:
        date_str = event.get("date", "")
        if not date_str:
            return None
        return datetime.strptime(date_str, "%m-%d-%Y")
    except:
        return None


def filter_events(events):
    return [e for e in events if e.get("country","").upper() in TARGET_CURRENCIES and e.get("impact","") in TARGET_IMPACT]


def get_pairs_for_event(event):
    return CURRENCY_PAIRS.get(event.get("country","").upper(), [])


def get_session_for_now(now):
    for name, s in SESSIONS.items():
        if now.hour == s["hour"] and now.minute == s["minute"]:
            return name
    return None


def get_session_events(session_name, events):
    sh    = SESSIONS[session_name]["hour"]
    end_h = (sh + 6) % 24
    result = []
    for e in filter_events(events):
        t = parse_event_time(e)
        if t:
            if sh < end_h:
                if sh <= t.hour < end_h:
                    result.append(e)
            else:
                if t.hour >= sh or t.hour < end_h:
                    result.append(e)
    return result


def make_event_key(event):
    return f"{event.get('title','').replace(' ','_')}_{event.get('date','')}"


# ── MESSAGE FORMATTERS ────────────────────────────────────────────────────────

def fmt_session_briefing(session_name, events):
    now  = datetime.utcnow()
    sess = SESSIONS[session_name]
    pairs_str = "  ".join(sess["pairs"])
    icons = {"ASIAN": "\U0001f30f", "LONDON": "\U0001f3db", "NEW YORK": "\U0001f5fd"}
    icon  = icons.get(session_name, "\U0001f4e1")

    if not events:
        return (
            f"{icon} <b>{session_name}</b>  <code>{now.strftime('%H:%M')} UTC</code>\n"
            f"<code>{pairs_str}</code>\n"
            f"\u2705  Clear \u2014 no high-impact events"
        )

    lines  = f"{icon} <b>{session_name}</b>  <code>{now.strftime('%H:%M')} UTC</code>\n"
    lines += f"<code>{pairs_str}</code>\n"
    lines += f"\U0001f534  <b>{len(events)} high-impact event{'s' if len(events)>1 else ''} ahead</b>\n\n"
    for e in events:
        t        = parse_event_time(e)
        ts       = t.strftime("%H:%M") if t else "TBC"
        forecast = e.get("forecast", "\u2014") or "\u2014"
        prev     = e.get("previous", "\u2014") or "\u2014"
        lines += f"<b>\u258c{e.get('country','').upper()}  {ts}</b>  {e.get('title','')}\n"
        lines += f"  F <code>{forecast}</code>  P <code>{prev}</code>\n"
    return lines.rstrip()


def fmt_warning(event, minutes):
    t        = parse_event_time(event)
    ts       = t.strftime("%H:%M") if t else "TBC"
    pairs    = "  ".join(get_pairs_for_event(event))
    forecast = event.get("forecast", "\u2014") or "\u2014"
    prev     = event.get("previous", "\u2014") or "\u2014"
    currency = event.get("country", "").upper()
    title    = event.get("title", "")
    icon     = "\u26a0\ufe0f" if minutes == 30 else "\U0001f6a8"
    note     = "Review positions." if minutes == 30 else "Final warning."
    return (
        f"{icon} <b>{minutes}MIN  \u258c{currency}  {ts} UTC</b>\n"
        f"<b>{title}</b>\n"
        f"<code>{pairs}</code>\n"
        f"F <code>{forecast}</code>  P <code>{prev}</code>\n"
        f"<i>{note}</i>"
    )


def fmt_result(event):
    t        = parse_event_time(event)
    ts       = t.strftime("%H:%M") if t else "TBC"
    pairs    = "  ".join(get_pairs_for_event(event))
    prev     = event.get("previous", "\u2014") or "\u2014"
    forecast = event.get("forecast", "\u2014") or "\u2014"
    actual   = event.get("actual", "\u2014") or "\u2014"
    currency = event.get("country", "").upper()
    title    = event.get("title", "")
    verdict  = "\U0001f4ca"
    tag      = "\u2014"
    try:
        a = float(actual.replace("%","").replace("K","000").replace("M","000000").strip())
        f = float(forecast.replace("%","").replace("K","000").replace("M","000000").strip())
        if a > f:
            verdict, tag = "\u2705", "BEAT"
        elif a < f:
            verdict, tag = "\u274c", "MISS"
        else:
            verdict, tag = "\u27a1\ufe0f", "IN LINE"
    except:
        pass
    return (
        f"{verdict} <b>\u258c{currency}  {ts}  {tag}</b>\n"
        f"{title}\n"
        f"<code>{pairs}</code>\n"
        f"A <code>{actual}</code>  F <code>{forecast}</code>  P <code>{prev}</code>"
    )


def fmt_week_view(events):
    filtered = filter_events(events)
    if not filtered:
        return "\U0001f4c5 <b>WEEK</b>  \u2705 No high-impact events this week."

    # Group by date
    days = {}
    for e in filtered:
        t   = parse_event_time(e)
        d   = parse_event_date(e)
        if d:
            day_key = d.strftime("%a %d %b").upper()
        else:
            day_key = "DATE TBC"
        days.setdefault(day_key, []).append((t, e))

    msg = f"\U0001f4c5 <b>THIS WEEK \u2014 {len(filtered)} HIGH-IMPACT EVENTS</b>\n"
    msg += "\u2500" * 28 + "\n\n"

    for day, items in days.items():
        msg += f"\U0001f4cc <b>{day}</b>\n"
        for t, e in items:
            ts       = t.strftime("%H:%M UTC") if t else "time TBC"
            currency = e.get("country", "").upper()
            title    = e.get("title", "")
            forecast = e.get("forecast", "\u2014") or "\u2014"
            prev     = e.get("previous", "\u2014") or "\u2014"
            msg += f"  \U0001f534 {ts}  <b>{currency}</b> \u2014 {title}\n"
            msg += f"       Forecast <code>{forecast}</code>   Prev <code>{prev}</code>\n"
        msg += "\n"

    msg += "<i>Source: ForexFactory \u00b7 High-impact only</i>"
    return msg.rstrip()


def fmt_today_view(events):
    today    = datetime.utcnow().date()
    now      = datetime.utcnow()
    filtered = [e for e in filter_events(events) if parse_event_time(e) and parse_event_time(e).date() == today]

    date_label = today.strftime("%A %d %B").upper()

    if not filtered:
        return (
            f"\U0001f4c5 <b>{date_label}</b>\n"
            f"\u2705 No high-impact events today.\n"
            f"<i>Clear to trade your setups.</i>"
        )

    msg  = f"\U0001f4c5 <b>{date_label}</b>\n"
    msg += f"\U0001f534 <b>{len(filtered)} high-impact event{'s' if len(filtered)>1 else ''}</b>\n"
    msg += "\u2500" * 28 + "\n\n"

    for e in filtered:
        t        = parse_event_time(e)
        ts       = t.strftime("%H:%M UTC") if t else "TBC"
        currency = e.get("country", "").upper()
        title    = e.get("title", "")
        forecast = e.get("forecast", "\u2014") or "\u2014"
        prev     = e.get("previous", "\u2014") or "\u2014"
        if t:
            diff = int((t - now).total_seconds() / 60)
            if diff > 0:
                eta = f"in {diff}min"
            elif diff > -60:
                eta = f"{abs(diff)}min ago"
            else:
                eta = "passed"
        else:
            eta = ""
        msg += f"\U0001f534 <b>{ts}</b>  <i>{eta}</i>\n"
        msg += f"<b>{currency}</b> \u2014 {title}\n"
        msg += f"Forecast <code>{forecast}</code>   Prev <code>{prev}</code>\n\n"

    msg += "<i>Source: ForexFactory \u00b7 High-impact only</i>"
    return msg.rstrip()


def fmt_next_event(events):
    now      = datetime.utcnow()
    upcoming = sorted(
        [(parse_event_time(e), e) for e in filter_events(events) if parse_event_time(e) and parse_event_time(e) > now],
        key=lambda x: x[0]
    )
    if not upcoming:
        return "\u23ed <b>NEXT EVENT</b>\nNo upcoming high-impact events found this week."

    t, e     = upcoming[0]
    diff     = (t - now).total_seconds() / 60
    h, m     = int(diff // 60), int(diff % 60)
    eta      = f"{h}h {m}m away" if h > 0 else f"{m} minutes away"
    forecast = e.get("forecast", "\u2014") or "\u2014"
    prev     = e.get("previous", "\u2014") or "\u2014"
    pairs    = "  ".join(get_pairs_for_event(e))
    currency = e.get("country", "").upper()
    title    = e.get("title", "")
    date_str = t.strftime("%A %d %B").upper()

    return (
        f"\u23ed <b>NEXT HIGH-IMPACT EVENT</b>\n"
        f"\u2500" * 28 + f"\n\n"
        f"\U0001f534 <b>{currency} \u2014 {title}</b>\n"
        f"\U0001f4c5 {date_str}\n"
        f"\U0001f552 {t.strftime('%H:%M UTC')}\n"
        f"\u23f1 <b>{eta}</b>\n\n"
        f"Pairs: <code>{pairs}</code>\n"
        f"Forecast <code>{forecast}</code>   Prev <code>{prev}</code>\n\n"
        f"<i>Source: ForexFactory \u00b7 High-impact only</i>"
    )


def fmt_help():
    return (
        "\U0001f916 <b>JOHLES CAPITAL INTELLIGENCE</b>\n\n"
        "/week  \u2014 Full week calendar\n"
        "/today \u2014 Today's events\n"
        "/next  \u2014 Next event countdown\n"
        "/help  \u2014 This menu\n\n"
        "<i>Auto alerts: session open \u00b7 30min \u00b7 10min \u00b7 result</i>\n"
        "<i>EURUSD \u00b7 GBPUSD \u00b7 USDJPY \u00b7 AUDUSD\n"
        "USDCAD \u00b7 NZDUSD \u00b7 USDCHF \u00b7 XAUUSD</i>"
    )


# ── COMMAND HANDLER ───────────────────────────────────────────────────────────

def handle_commands(calendar_cache, last_update_id):
    updates = get_updates(last_update_id[0] + 1)
    for update in updates:
        last_update_id[0] = update.get("update_id", last_update_id[0])
        msg     = update.get("message", {})
        text    = msg.get("text", "").strip().lower()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != CHAT_ID:
            continue
        log.info(f"Command received: {text}")
        if text in ["/week", "/week@johlescapitalbot"]:
            send_message(fmt_week_view(calendar_cache))
        elif text in ["/today", "/today@johlescapitalbot"]:
            send_message(fmt_today_view(calendar_cache))
        elif text in ["/next", "/next@johlescapitalbot"]:
            send_message(fmt_next_event(calendar_cache))
        elif text in ["/help", "/start", "/help@johlescapitalbot"]:
            send_message(fmt_help())


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def main():
    log.info("=== JOHLES Capital Intelligence Bot starting ===")
    last_update_id = [0]

    send_message(
        "\U0001f7e2 <b>JOHLES CAPITAL INTELLIGENCE</b>\n"
        "Online. Monitoring high-impact events.\n\n"
        "<code>EURUSD  GBPUSD  USDJPY  AUDUSD\n"
        "USDCAD  NZDUSD  USDCHF  XAUUSD</code>\n\n"
        "<i>Type /help for commands</i>"
    )

    calendar_cache = []
    last_fetch     = 0
    loop_count     = 0

    while True:
        try:
            now    = datetime.utcnow()
            now_ts = time.time()

            # Refresh calendar every 4 hours
            if now_ts - last_fetch > 14400:
                calendar_cache = fetch_calendar()
                last_fetch     = now_ts

            high_impact = filter_events(calendar_cache)

            # Check commands every loop (every 5 seconds — fast response)
            handle_commands(calendar_cache, last_update_id)

            # Only run alerts and session briefings every 60 seconds
            if loop_count % 12 == 0:

                # Session briefing
                session = get_session_for_now(now)
                if session:
                    key = f"{session}_{now.strftime('%Y-%m-%d')}"
                    if key not in session_briefings_sent:
                        events_this_session = get_session_events(session, calendar_cache)
                        if send_message(fmt_session_briefing(session, events_this_session)):
                            session_briefings_sent.add(key)
                            log.info(f"Session briefing sent: {session}")

                # Event alerts
                for event in high_impact:
                    event_time = parse_event_time(event)
                    if not event_time:
                        continue
                    key  = make_event_key(event)
                    diff = (event_time - now).total_seconds() / 60

                    if 29 <= diff <= 31:
                        alert_key = f"{key}_30min"
                        if alert_key not in sent_alerts:
                            if send_message(fmt_warning(event, 30)):
                                sent_alerts.add(alert_key)

                    elif 9 <= diff <= 11:
                        alert_key = f"{key}_10min"
                        if alert_key not in sent_alerts:
                            if send_message(fmt_warning(event, 10)):
                                sent_alerts.add(alert_key)

                    elif -10 <= diff <= -5:
                        alert_key = f"{key}_result"
                        if alert_key not in sent_alerts:
                            if send_message(fmt_result(event)):
                                sent_alerts.add(alert_key)

            loop_count += 1
            time.sleep(5)

        except KeyboardInterrupt:
            log.info("Bot stopped.")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
