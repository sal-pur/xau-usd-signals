"""
XAU/USD (Gold) 15-minute price checker with technical-analysis suggestions.

Fetches 15-minute candles from Yahoo Finance (free, no API key), computes
a small set of classic indicators (EMA crossover, SMA trend filter, RSI,
MACD) and prints a BUY / SELL / HOLD suggestion.

Usage:
    python main.py            # check now, then re-check every 15 minutes
    python main.py --once     # single check and exit
    python main.py --once --notify-on-change
                              # single check; Telegram message only when
                              # the BUY/SELL/HOLD signal changes, and
                              # silence while the market is closed
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

import telegram_notify

# Yahoo data: XAUUSD=X (spot pair) is often delisted/unavailable on Yahoo,
# so COMEX gold futures (GC=F) is the primary source and tracks XAU/USD
# almost 1:1.
TICKERS = ["GC=F", "XAUUSD=X"]
INTERVAL = "15m"        # candle interval
PERIOD = "5d"           # how much history to pull (max for 15m is ~60d)
CHECK_EVERY_MIN = 15

RSI_PERIOD = 14
EMA_FAST, EMA_SLOW = 9, 21
SMA_TREND = 50
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

# --notify-on-change state: remembers the last signal sent to Telegram.
# On GitHub Actions this small file is committed back to the repo so the
# next scheduled run knows what was already sent.
STATE_FILE = Path(__file__).with_name("last_signal.json")
MAX_CANDLE_AGE_MIN = 60   # newest candle older than this = market closed


def fetch_candles() -> pd.DataFrame:
    """Download 15-minute OHLCV data for gold, trying each ticker in turn."""
    last_err = None
    for ticker in TICKERS:
        try:
            df = yf.download(
                ticker,
                period=PERIOD,
                interval=INTERVAL,
                progress=False,
                auto_adjust=False,
            )
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    # yfinance >= 0.2.x returns MultiIndex columns per ticker
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                if len(df) >= SMA_TREND + 5:
                    print(f"Data source: Yahoo Finance ticker '{ticker}' "
                          f"({len(df)} x {INTERVAL} candles)")
                    return df
        except Exception as err:  # noqa: BLE001 - keep trying next ticker
            last_err = err
    raise RuntimeError(
        "Could not download XAU/USD data from Yahoo Finance. "
        f"Last error: {last_err}"
    )


def rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period,
                        adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period,
                        adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return 100 - 100 / (1 + rs)


def analyze(df: pd.DataFrame) -> dict:
    """Compute indicators and build a suggestion from the latest candle."""
    close = df["Close"].squeeze().astype(float)

    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    sma_trend = close.rolling(SMA_TREND).mean()

    macd_line = (close.ewm(span=MACD_FAST, adjust=False).mean()
                 - close.ewm(span=MACD_SLOW, adjust=False).mean())
    macd_signal = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()

    rsi_series = rsi(close)

    price = float(close.iloc[-1])
    ef, es = float(ema_fast.iloc[-1]), float(ema_slow.iloc[-1])
    ef_prev, es_prev = (float(ema_fast.iloc[-2]), float(ema_slow.iloc[-2]))
    st = float(sma_trend.iloc[-1])
    macd, sig = float(macd_line.iloc[-1]), float(macd_signal.iloc[-1])
    macd_prev = float(macd_line.iloc[-2]) - float(macd_signal.iloc[-2])
    rsi_now = float(rsi_series.iloc[-1])

    # --- signals -----------------------------------------------------------
    reasons, score = [], 0

    if ef > es and ef_prev <= es_prev:
        score += 2
        reasons.append(f"Bullish EMA crossover: EMA{EMA_FAST} crossed above "
                       f"EMA{EMA_SLOW} ({ef:.2f} > {es:.2f})")
    elif ef < es and ef_prev >= es_prev:
        score -= 2
        reasons.append(f"Bearish EMA crossover: EMA{EMA_FAST} crossed below "
                       f"EMA{EMA_SLOW} ({ef:.2f} < {es:.2f})")
    elif ef > es:
        score += 1
        reasons.append(f"Uptrend: EMA{EMA_FAST} ({ef:.2f}) above "
                       f"EMA{EMA_SLOW} ({es:.2f})")
    else:
        score -= 1
        reasons.append(f"Downtrend: EMA{EMA_FAST} ({ef:.2f}) below "
                       f"EMA{EMA_SLOW} ({es:.2f})")

    if price > st:
        score += 1
        reasons.append(f"Price above SMA{SMA_TREND} ({st:.2f}) - bullish bias")
    else:
        score -= 1
        reasons.append(f"Price below SMA{SMA_TREND} ({st:.2f}) - bearish bias")

    if rsi_now < 30:
        score += 2
        reasons.append(f"RSI {rsi_now:.1f} is oversold (<30) - bounce likely")
    elif rsi_now > 70:
        score -= 2
        reasons.append(f"RSI {rsi_now:.1f} is overbought (>70) - pullback risk")
    else:
        reasons.append(f"RSI {rsi_now:.1f} is neutral (30-70)")

    if macd > sig and macd_prev <= 0:
        score += 2
        reasons.append("MACD bullish: line crossed above signal line")
    elif macd < sig and macd_prev >= 0:
        score -= 2
        reasons.append("MACD bearish: line crossed below signal line")
    elif macd > sig:
        score += 1
        reasons.append(f"MACD ({macd:.2f}) above signal ({sig:.2f})")
    else:
        score -= 1
        reasons.append(f"MACD ({macd:.2f}) below signal ({sig:.2f})")

    # --- verdict -----------------------------------------------------------
    if score >= 3:
        action = "BUY"
    elif score <= -3:
        action = "SELL"
    else:
        action = "HOLD"

    candle_time = df.index[-1]
    try:
        # convert to the machine's local time zone, drop tz info for display
        candle_time = candle_time.to_pydatetime().astimezone().replace(
            tzinfo=None)
    except (TypeError, ValueError, AttributeError):
        pass

    return {
        "action": action,
        "score": score,
        "price": price,
        "reasons": reasons,
        "time": candle_time,
        "ema_fast": ef, "ema_slow": es,
        "sma_trend": st,
        "rsi": rsi_now,
        "macd": macd, "macd_signal": sig,
    }


def print_report(a: dict) -> None:
    line = "=" * 62
    print(line)
    print(f"  XAU/USD ANALYSIS  -  {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(line)
    print(f"  Latest 15m candle : {a['time']:%Y-%m-%d %H:%M}")
    print(f"  Current price     : ${a['price']:,.2f}")
    print(f"  EMA{EMA_FAST} / EMA{EMA_SLOW}       : {a['ema_fast']:,.2f} / {a['ema_slow']:,.2f}")
    print(f"  SMA{SMA_TREND}            : {a['sma_trend']:,.2f}")
    print(f"  RSI{RSI_PERIOD}           : {a['rsi']:.1f}")
    print(f"  MACD / signal     : {a['macd']:.2f} / {a['macd_signal']:.2f}")
    print(f"  Signal score      : {a['score']:+d}")
    print("-" * 62)
    print(f"  SUGGESTION        : {a['action']}")
    print("-" * 62)
    print("  Reasons:")
    for reason in a["reasons"]:
        print(f"   - {reason}")
    print(line)


def format_message(a: dict) -> str:
    """Build the Telegram message text from an analysis result."""
    icon = {"BUY": "\U0001F7E2", "SELL": "\U0001F534", "HOLD": "\u26AA"}[
        a["action"]]
    lines = [
        f"{icon} XAU/USD: {a['action']} {icon}",
        "",
        f"Price: ${a['price']:,.2f}",
        f"15m candle: {a['time']:%Y-%m-%d %H:%M}",
        "",
        f"EMA{EMA_FAST}/EMA{EMA_SLOW}: {a['ema_fast']:,.2f} / "
        f"{a['ema_slow']:,.2f}",
        f"SMA{SMA_TREND}: {a['sma_trend']:,.2f}",
        f"RSI{RSI_PERIOD}: {a['rsi']:.1f}",
        f"MACD/signal: {a['macd']:.2f} / {a['macd_signal']:.2f}",
        f"Score: {a['score']:+d}",
        "",
        "Reasons:",
    ]
    lines += [f"- {r}" for r in a["reasons"]]
    return "\n".join(lines)


def market_is_open(df: pd.DataFrame) -> bool:
    """True if the newest candle is fresh enough (i.e. market is open).

    Gold futures trade nearly 24h with a ~1h daily maintenance break and
    a weekend closure, so a candle older than MAX_CANDLE_AGE_MIN means
    the market is closed (or data is stale).
    """
    try:
        candle = df.index[-1].to_pydatetime()
        if candle.tzinfo is None:
            return True  # no timezone info - assume data is current
        age = (dt.datetime.now(dt.timezone.utc) - candle).total_seconds() / 60
        print(f"[info] latest candle is {age:.0f} minutes old")
        return age <= MAX_CANDLE_AGE_MIN
    except (TypeError, ValueError, AttributeError, IndexError):
        return True


def load_last_action():
    """Read the last notified action from the state file, if any."""
    try:
        # utf-8-sig tolerates a BOM added by editors like Notepad
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))["action"]
    except (OSError, ValueError, KeyError):
        return None


def save_state(analysis: dict) -> None:
    """Remember the last notified action (small file, committed by CI)."""
    state = {"action": analysis["action"],
             "since": f"{dt.datetime.now():%Y-%m-%d %H:%M}"}
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def run_once(notify_on_change: bool = False) -> None:
    df = fetch_candles()
    analysis = analyze(df)
    print_report(analysis)

    if notify_on_change and not market_is_open(df):
        print("[info] market appears closed (stale candle) - nothing sent")
        return

    if not notify_on_change:
        # every-check mode: always send
        telegram_notify.send_message(format_message(analysis))
        return

    last = load_last_action()
    if last is None:
        # first run with state tracking: confirm the bot is alive
        ok = telegram_notify.send_message(
            "\U0001F916 XAU/USD bot started. Current signal:\n\n"
            + format_message(analysis))
        print("[telegram] sent start-up message" if ok
              else "[telegram] start-up message not sent")
    elif last != analysis["action"]:
        ok = telegram_notify.send_message(
            f"\U0001F504 SIGNAL CHANGED: {last} -> {analysis['action']}\n\n"
            + format_message(analysis))
        print(f"[telegram] sent change notification ({last} -> "
              f"{analysis['action']})" if ok
              else "[telegram] change message not sent")
    else:
        print(f"[telegram] no change (still {last}) - nothing sent")
        return

    if ok:
        save_state(analysis)
    else:
        # message failed (e.g. network) - retry on the next run
        print("[telegram] state not saved; will retry next check")


def seconds_until_next_quarter() -> float:
    """Seconds to sleep so the next check lands on a 15-minute boundary."""
    now = dt.datetime.now()
    nxt = (now + dt.timedelta(minutes=CHECK_EVERY_MIN)).replace(
        second=0, microsecond=0)
    nxt = nxt.replace(minute=(nxt.minute // CHECK_EVERY_MIN)
                      * CHECK_EVERY_MIN)
    return max((nxt - now).total_seconds(), 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check XAU/USD every 15 minutes and suggest BUY/SELL/HOLD")
    parser.add_argument("--once", action="store_true",
                        help="run a single check and exit")
    parser.add_argument("--notify-on-change", action="store_true",
                        help="only send Telegram messages when the "
                             "BUY/SELL/HOLD signal changes; stays silent "
                             "while the market is closed")
    parser.add_argument("--get-chat-id", action="store_true",
                        help="print your Telegram chat_id(s) and exit")
    args = parser.parse_args()

    if args.get_chat_id:
        telegram_notify.get_chat_id()
        return

    if args.once:
        try:
            run_once(notify_on_change=args.notify_on_change)
        except Exception as err:  # noqa: BLE001
            # e.g. no data because the market is closed - exit cleanly so
            # scheduled cloud runs don't show as failed
            print(f"[info] nothing sent: {err}")
        return

    print(f"Watching XAU/USD on {INTERVAL} candles, "
          f"checking every {CHECK_EVERY_MIN} minutes. Ctrl+C to stop.\n")
    while True:
        try:
            run_once(notify_on_change=args.notify_on_change)
        except Exception as err:  # noqa: BLE001 - keep the loop alive
            print(f"[warn] check failed: {err}", file=sys.stderr)
        wait = seconds_until_next_quarter()
        next_time = dt.datetime.now() + dt.timedelta(seconds=wait)
        print(f"\nNext check at {next_time:%H:%M:%S} "
              f"(sleeping {wait / 60:.1f} min)... Ctrl+C to stop.")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")