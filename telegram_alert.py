"""Gui canh bao Telegram khi co nguon RED. Chay sau moi lan crawl:

    python3 pipeline.py --live && python3 telegram_alert.py

Chay nhu process rieng (khong nhung trong api.py) de tranh gui trung
canh bao khi scale nhieu Uvicorn worker sau nay.

Env can co: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from health import health_rows, status

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
STATE_PATH = Path(__file__).parent / "alert_state.json"
RESEND_AFTER_HOURS = 6  # nhac lai neu RED chua khoi phuc sau tung nay gio


def send_message(token: str, chat_id: str, text: str) -> None:
    url = TELEGRAM_API.format(token=token)
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram request failed: {e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Telegram response was not valid JSON: {e}") from e
    if not isinstance(body, dict) or not body.get("ok"):
        raise RuntimeError(f"Telegram API returned error: {body}")


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"red_sources": [], "last_sent": None}


def _save_state(red_sources, sent_at: datetime) -> None:
    STATE_PATH.write_text(json.dumps({
        "red_sources": sorted(red_sources),
        "last_sent": sent_at.isoformat(),
    }))


def _should_alert(red_sources, state: dict, now: datetime) -> bool:
    """Gui lai neu tap nguon RED thay doi (nguon moi RED, hoac nguon da
    RED nay khoi phuc), hoac da qua RESEND_AFTER_HOURS ke tu lan gui gan
    nhat (nhac lai neu van con RED keo dai, tranh im lang vinh vien)."""
    if sorted(red_sources) != state["red_sources"]:
        return True
    if state["last_sent"] is None:
        return True
    last_sent = datetime.fromisoformat(state["last_sent"])
    return (now - last_sent).total_seconds() >= RESEND_AFTER_HOURS * 3600


def main() -> int:
    rows = health_rows()
    red_sources = [r["source"] for r in rows if r["state"] == "RED"]
    if not red_sources:
        if STATE_PATH.exists():
            STATE_PATH.unlink()  # reset - lan RED tiep theo se alert ngay
        return 0

    now = datetime.now(timezone.utc)
    if not _should_alert(red_sources, _load_state(), now):
        return 0  # da alert dung tap nguon nay gan day, tranh spam moi 10p

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("telegram_alert: RED source(s) found but "
              "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 1

    try:
        send_message(token, chat_id, status())
    except RuntimeError as e:
        print(f"telegram_alert: {e}", file=sys.stderr)
        return 1

    _save_state(red_sources, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
