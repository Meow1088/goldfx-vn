"""Tests cho api.py — dac biet la regression cho 2 bug queries.py da fix:
dong reject moi hon khong duoc che dong ok/warn gan nhat."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
from pipeline import SCHEMA


def insert_quote(con, **kw):
    row = {
        "source": "vcb", "asset": "fx", "code": "USD", "branch": "",
        "buy_cash": 26000.0, "buy_transfer": 26100.0, "sell": 26400.0,
        "unit": "VND", "ts_source": None, "ts_crawled": None,
        "raw_hash": "abc123", "parser_version": "1.0.0",
        "validation": "ok", "notes": "",
    }
    row.update(kw)
    con.execute(
        "INSERT INTO quotes(source,asset,code,branch,buy_cash,buy_transfer,"
        "sell,unit,ts_source,ts_crawled,raw_hash,parser_version,validation,notes) "
        "VALUES(:source,:asset,:code,:branch,:buy_cash,:buy_transfer,:sell,"
        ":unit,:ts_source,:ts_crawled,:raw_hash,:parser_version,:validation,:notes)",
        row)


def iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setattr(api, "DB", db_path)
    return TestClient(api.app), db_path


def test_missing_db_path_fails_instead_of_creating_one(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "does_not_exist.db")
    with pytest.raises(sqlite3.OperationalError):
        api.connect_readonly()
    assert not (tmp_path / "does_not_exist.db").exists()


def test_fx_latest_excludes_rejects(client):
    c, db_path = client
    con = sqlite3.connect(db_path)
    insert_quote(con, buy_transfer=26100.0, ts_source=iso(30), validation="ok")
    con.commit()
    con.close()

    resp = c.get("/fx/USD/latest")
    assert resp.status_code == 200
    rates = resp.json()["rates"]
    assert len(rates) == 1
    assert rates[0]["source"] == "vcb"


def test_fx_latest_newer_reject_does_not_hide_valid_row(client):
    """Regression: MAX(ts_source) khong duoc chon dong reject moi hon,
    che mat dong ok/warn cu hon nhung van hop le."""
    c, db_path = client
    con = sqlite3.connect(db_path)
    insert_quote(con, buy_transfer=26100.0, sell=26400.0,
                 ts_source=iso(30), validation="ok")
    insert_quote(con, buy_transfer=99999.0, sell=1.0,
                 ts_source=iso(5), validation="reject", notes="L2: gia vo ly")
    con.commit()
    con.close()

    resp = c.get("/fx/USD/latest")
    rates = resp.json()["rates"]
    assert len(rates) == 1
    assert rates[0]["buy_transfer"] == 26100.0


def test_fx_best_picks_highest_buy_transfer_and_lowest_sell(client):
    c, db_path = client
    con = sqlite3.connect(db_path)
    insert_quote(con, source="vcb", buy_transfer=26100.0, sell=26480.0,
                 ts_source=iso(10))
    insert_quote(con, source="bidv", buy_transfer=26200.0, sell=26350.0,
                 ts_source=iso(10))
    con.commit()
    con.close()

    resp = c.get("/fx/USD/best")
    body = resp.json()
    assert body["best_customer_sell"]["source"] == "bidv"
    assert body["best_customer_buy"]["source"] == "bidv"


def test_gold_sjc_compare_excludes_rejects(client):
    c, db_path = client
    con = sqlite3.connect(db_path)
    insert_quote(con, source="sjc", asset="gold", code="SJC_BAR",
                 branch="Hồ Chí Minh", buy_cash=120_000_000.0,
                 sell=122_000_000.0, unit="VND_PER_LUONG",
                 ts_source=iso(10), validation="ok")
    insert_quote(con, source="pnj", asset="gold", code="SJC",
                 branch="Hồ Chí Minh", buy_cash=119_000_000.0,
                 sell=121_500_000.0, unit="VND_PER_LUONG",
                 ts_source=iso(10), validation="reject", notes="L2: lech gia")
    con.commit()
    con.close()

    resp = c.get("/gold/sjc/compare")
    quotes = resp.json()["quotes"]
    assert [q["source"] for q in quotes] == ["sjc"]


def test_health_status_reflects_red_source(client):
    c, db_path = client
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO crawl_log(source,ts_crawled,status,n_records,n_ok,"
        "n_warn,n_reject,raw_path,message) VALUES(?,?,?,?,?,?,?,?,?)",
        ("pnj", iso(0), "error", 0, 0, 0, 0, "", "TimeoutError"))
    con.commit()
    con.close()

    resp = c.get("/health/status")
    body = resp.json()
    assert body["status"] == "RED"
    assert any(s["source"] == "pnj" and s["state"] == "RED"
               for s in body["sources"])
