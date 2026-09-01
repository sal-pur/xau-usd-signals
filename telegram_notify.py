"""Tiny Telegram Bot API helper: send text messages and read chat IDs.

Configuration is read from telegram_config.json (in this folder) or from
the TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID environment variables.
"""

import json
import os
from pathlib import Path

import requests

CONFIG_FILE = Path(__file__).with_name("telegram_config.json")
API_BASE = "https://api.telegram.org"


def load_config():
    """Return (bot_token, chat_id) from config file or environment."""
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("bot_token"), cfg.get("chat_id")
        except (OSError, ValueError) as err:
            print(f"[telegram] could not read {CONFIG_FILE.name}: {err}")
    return (os.environ.get("TELEGRAM_BOT_TOKEN"),
            os.environ.get("TELEGRAM_CHAT_ID"))


def send_message(text: str) -> bool:
    """Send a text message to the configured chat. Returns True on success."""
    token, chat_id = load_config()
    if not token or not chat_id:
        print("[telegram] not configured (no bot token / chat_id) - "
              "message not sent")
        return False
    try:
        resp = requests.post(
            f"{API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if resp.ok:
            return True
        print(f"[telegram] send failed: HTTP {resp.status_code} "
              f"{resp.text[:200]}")
        return False
    except requests.RequestException as err:
        print(f"[telegram] send failed: {err}")
        return False


def get_chat_id() -> None:
    """Print the chat IDs of recent messages sent to the bot."""
    token, _ = load_config()
    if not token:
        print("No bot token found. Put it in telegram_config.json "
              '({"bot_token": "...", "chat_id": ""}) or set the '
              "TELEGRAM_BOT_TOKEN environment variable.")
        return
    try:
        resp = requests.get(f"{API_BASE}/bot{token}/getUpdates", timeout=15)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except requests.RequestException as err:
        print(f"Could not reach Telegram: {err}")
        return
    if not updates:
        print("No messages found yet. Open your bot in Telegram, press "
              "START (or send any message), then run this again.")
        return
    seen = set()
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id and chat_id not in seen:
            seen.add(chat_id)
            name = chat.get("first_name") or chat.get("title") or "?"
            print(f"chat_id: {chat_id}   (chat: {name})")
