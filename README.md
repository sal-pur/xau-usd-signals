# XAU/USD 15-Minute Suggestion Bot

A Python program that checks the Gold / USD (XAU/USD) price on **15-minute
candles** and prints a **BUY / SELL / HOLD** suggestion based on classic
technical analysis.

## How it works

- Data: free 15-minute candles from Yahoo Finance — COMEX gold futures
  (`GC=F`, tracks XAU/USD almost 1:1); the spot pair `XAUUSD=X` is tried
  as a fallback. No API key needed.
- Indicators used:
  - EMA 9 / EMA 21 crossover (momentum + crossovers)
  - SMA 50 trend filter (price above/below)
  - RSI(14) (overbought > 70 / oversold < 30)
  - MACD (12, 26, 9) line vs signal line
- Each signal adds or subtracts from a score; the final suggestion is:
  - score >= +3 → **BUY**
  - score <= -3 → **SELL**
  - otherwise → **HOLD**

## Setup

```bash
cd C:\Users\Admin\Documents\xauusd_signals
pip install -r requirements.txt
```

## Run

```bash
python main.py          # check now, then every 15 minutes (aligned to :00/:15/:30/:45)
python main.py --once   # single check and exit
```

Press `Ctrl+C` to stop the loop.

## Telegram integration (push signals to your phone)

The bot can send every signal to your Telegram every 15 minutes. One-time
setup:

**Step 1 — create a bot and get the token**

1. Open Telegram, search for **@BotFather** and start a chat.
2. Send `/newbot`, follow the prompts (pick a name and username).
3. BotFather replies with an **API token** like
   `123456789:AAH4x...your-token-here`. Copy it.

**Step 2 — get your chat ID**

1. Create the config file `telegram_config.json` next to `main.py`:

   ```json
   {
     "bot_token": "123456789:AAH4x...your-token-here",
     "chat_id": ""
   }
   ```

2. Open your new bot in Telegram and press **START** (send any message).
3. Run:

   ```bash
   python main.py --get-chat-id
   ```

   It prints your `chat_id`. Put it into `telegram_config.json`.

**Step 3 — run**

```bash
python main.py                      # a message every 15 minutes
python main.py --notify-on-change   # message only when the signal changes (recommended)
```

In `--notify-on-change` mode you get a message only when the suggestion
flips (e.g. HOLD -> BUY), prefixed with "🔄 SIGNAL CHANGED", plus one
start-up message so you know the bot is alive. While the market is
closed (weekends, the daily ~1h maintenance break) the bot sends
nothing at all.

Every 15 minutes the bot analyses XAU/USD; a message looks like:

> 🟢 XAU/USD: BUY 🟢
> Price: $4,418.20
> RSI14: 48.3
> ... reasons ...

Alternatively, you can skip the config file and set the environment
variables `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` instead.

**Keeping it running 24/7**

- Leave the terminal window open (simplest), or
- Run it hidden on Windows: `pythonw main.py` (no console window), or
- Better: run it in the cloud so it works even when your PC is off — see below.

## Run in the cloud for free (GitHub Actions) — no PC needed

GitHub can run this script on **their servers** every 15 minutes, 24/7, for
free. Your PC can be off; you just watch Telegram.

**Step 1 — put the project on GitHub**

1. Create a free account at [github.com](https://github.com) if you don't
   have one.
2. Click **+** (top right) → **New repository** → name it e.g.
   `xauusd-signals` → keep it **Public** (free unlimited Actions) → Create.
3. Upload the project files (`main.py`, `telegram_notify.py`,
   `requirements.txt`, and the whole `.github` folder — easiest with
   GitHub Desktop or `git`). **Do not upload `telegram_config.json`.**

**Step 2 — add your Telegram secrets**

1. In your repo: **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** twice:
   - Name: `TELEGRAM_BOT_TOKEN`, Value: your bot token from @BotFather
   - Name: `TELEGRAM_CHAT_ID`, Value: your chat ID
3. (If you don't have a chat ID yet: run `python main.py --get-chat-id`
   on your PC once.)

**Step 3 — enable it**

1. Open the **Actions** tab in your repo → click
   *"I understand my workflows, go ahead and enable them"* (if shown).
2. Select the **xauusd-signal** workflow → **Run workflow** to test it
   once. You should receive a Telegram message within a minute.
3. Done! GitHub now runs it automatically every 15 minutes. Each run
   appears in the Actions tab with logs; failures are also visible there.

**Good to know**

- GitHub's scheduler runs in UTC and can occasionally be a few minutes
  late — that's normal.
- The cloud workflow uses `--notify-on-change`, so you only get a
  message when the signal actually flips. To remember the last signal
  between runs (each run is a fresh machine), the workflow commits a
  tiny `last_signal.json` back to the repo — it only changes when the
  signal changes. The `permissions: contents: write` block in the
  workflow file enables this automatically.
- Market closed = silence: on weekends and during the daily maintenance
  break the bot detects stale candles, sends nothing, and exits cleanly
  (runs still show green in the Actions tab).
- Public repos get unlimited free Actions minutes; private repos get a
  free monthly quota (this job uses < 1 minute per run, ~96 runs/day).

## Other hosting options (comparison)

| Option | Cost | Effort | Notes |
|---|---|---|---|
| **GitHub Actions** (above) | Free | Easy | Recommended; scheduled, no server |
| Oracle Cloud "Always Free" VPS | Free | Medium | A real tiny Linux server; full control, more setup |
| Cheap VPS (Hetzner, DigitalOcean, ...) | ~$4-5/month | Medium | Runs 24/7 via `python main.py` under `tmux`/systemd |
| Raspberry Pi at home | One-off cost | Medium | Not cloud, but doesn't occupy your PC |
| PythonAnywhere | Free tier limited | Easy | Always-on tasks need a paid plan |

## Sample output

```
==============================================================
  XAU/USD ANALYSIS  -  2026-09-01 14:30:02
==============================================================
  Latest 15m candle : 2026-09-01 14:30
  Current price     : $3,412.85
  EMA9 / EMA21      : 3,411.20 / 3,408.75
  SMA50             : 3,405.10
  RSI14             : 58.3
  MACD / signal     : 1.42 / 0.98
  Signal score      : +3
--------------------------------------------------------------
  SUGGESTION        : BUY
--------------------------------------------------------------
  Reasons:
   - Uptrend: EMA9 (3411.20) above EMA21 (3408.75)
   - Price above SMA50 (3405.10) - bullish bias
   - RSI 58.3 is neutral (30-70)
   - MACD (1.42) above signal (0.98)
==============================================================
```

## Disclaimer

This tool is for **informational/educational purposes only** and is **not
financial advice**. Technical indicators on short timeframes produce many
false signals. Always do your own research and manage risk.
