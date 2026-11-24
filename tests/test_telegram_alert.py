"""Tests cho telegram_alert.py. Khong bao gio goi network that — health_rows,
status, send_message deu duoc monkeypatch."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import telegram_alert as ta


def fake_rows(state):
    return [{"source": "vcb", "state": state, "last_source": None,
              "last_crawl": None, "crawl_status": "ok", "rejects": 0,
              "age_minutes": None, "message": ""}]


@pytest.fixture(autouse=True)
def isolated_state_path(tmp_path, monkeypatch):
    """Khong bao gio dung alert_state.json that cua repo trong test."""
    monkeypatch.setattr(ta, "STATE_PATH", tmp_path / "alert_state.json")


def test_no_red_source_exits_zero_without_sending(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("GRN"))
    called = []
    monkeypatch.setattr(ta, "send_message", lambda *a: called.append(a))
    assert ta.main() == 0
    assert called == []


def test_red_source_without_credentials_fails_without_sending(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    called = []
    monkeypatch.setattr(ta, "send_message", lambda *a: called.append(a))
    assert ta.main() == 1
    assert called == []


def test_red_source_with_credentials_sends_status_text(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.setattr(ta, "status", lambda: "[RED] vcb ...")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    called = []
    monkeypatch.setattr(ta, "send_message",
                         lambda token, chat_id, text: called.append(
                             (token, chat_id, text)))
    assert ta.main() == 0
    assert called == [("tok123", "chat456", "[RED] vcb ...")]


def test_send_message_failure_makes_main_return_nonzero(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")

    def boom(*a):
        raise RuntimeError("Telegram API returned error: {'ok': False}")
    monkeypatch.setattr(ta, "send_message", boom)
    assert ta.main() == 1


def test_repeat_red_same_source_is_not_resent(monkeypatch):
    """Cron chay lai moi 10 phut voi CUNG 1 nguon RED -- khong duoc gui
    lai ngay, dung day la fix cho TODO 'Alert dedup'."""
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    called = []
    monkeypatch.setattr(ta, "send_message",
                         lambda *a: called.append(a))
    assert ta.main() == 0
    assert len(called) == 1
    assert ta.main() == 0  # lan 2, cung nguon RED -> khong gui nua
    assert len(called) == 1


def test_new_red_source_is_sent_even_if_another_already_alerted(monkeypatch):
    rows_vcb = fake_rows("RED")
    rows_vcb_and_bidv = fake_rows("RED") + [
        {"source": "bidv", "state": "RED", "last_source": None,
         "last_crawl": None, "crawl_status": "ok", "rejects": 0,
         "age_minutes": None, "message": ""}]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    called = []
    monkeypatch.setattr(ta, "send_message", lambda *a: called.append(a))

    monkeypatch.setattr(ta, "health_rows", lambda: rows_vcb)
    assert ta.main() == 0
    monkeypatch.setattr(ta, "health_rows", lambda: rows_vcb_and_bidv)
    assert ta.main() == 0
    assert len(called) == 2  # tap nguon RED thay doi -> gui lai


def test_recovery_then_new_red_resends_immediately(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    called = []
    monkeypatch.setattr(ta, "send_message", lambda *a: called.append(a))
    assert ta.main() == 0
    assert len(called) == 1

    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("GRN"))
    assert ta.main() == 0  # khoi phuc -> reset state, khong gui
    assert not ta.STATE_PATH.exists()

    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    assert ta.main() == 0  # RED lai tu dau -> gui ngay, khong cho dedup chan
    assert len(called) == 2


def test_resends_after_cooldown_even_if_same_source(monkeypatch):
    monkeypatch.setattr(ta, "health_rows", lambda: fake_rows("RED"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    called = []
    monkeypatch.setattr(ta, "send_message", lambda *a: called.append(a))
    assert ta.main() == 0
    assert len(called) == 1

    old_state = json.loads(ta.STATE_PATH.read_text())
    stale_sent = (datetime.fromisoformat(old_state["last_sent"])
                 - timedelta(hours=ta.RESEND_AFTER_HOURS, minutes=1))
    old_state["last_sent"] = stale_sent.isoformat()
    ta.STATE_PATH.write_text(json.dumps(old_state))

    assert ta.main() == 0
    assert len(called) == 2


def test_send_message_raises_on_ok_false(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"ok": False, "description": "bad chat id"}).encode()

    monkeypatch.setattr(ta.urllib.request, "urlopen", lambda *a, **kw: FakeResponse())
    with pytest.raises(RuntimeError, match="ok.*False|bad chat id"):
        ta.send_message("tok", "chat", "hello")


def test_send_message_succeeds_on_ok_true(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"ok": True}).encode()

    monkeypatch.setattr(ta.urllib.request, "urlopen", lambda *a, **kw: FakeResponse())
    ta.send_message("tok", "chat", "hello")  # must not raise
