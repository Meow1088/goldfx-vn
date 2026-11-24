"""Tests cho health.health_rows() — dac biet la bug fix nguon chi co
error trong crawl_log (chua tung insert duoc quote nao) van phai hien RED,
thay vi bien mat khoi health output nhu truoc."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from health import health_rows, STALE_WARN_MIN, STALE_RED_MIN
from pipeline import SCHEMA


def make_db(tmp_path, quotes=(), crawl_logs=()):
    db_path = tmp_path / "test.db"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    for q in quotes:
        con.execute(
            "INSERT INTO quotes(source,asset,code,branch,buy_cash,buy_transfer,"
            "sell,unit,ts_source,ts_crawled,raw_hash,parser_version,validation,notes) "
            "VALUES(:source,:asset,:code,:branch,:buy_cash,:buy_transfer,:sell,"
            ":unit,:ts_source,:ts_crawled,:raw_hash,:parser_version,:validation,:notes)",
            q)
    for c in crawl_logs:
        con.execute(
            "INSERT INTO crawl_log(source,ts_crawled,status,n_records,n_ok,"
            "n_warn,n_reject,raw_path,message) VALUES(:source,:ts_crawled,"
            ":status,:n_records,:n_ok,:n_warn,:n_reject,:raw_path,:message)",
            c)
    con.commit()
    con.close()
    return db_path


def quote_row(source, ts_source, validation="ok"):
    return {
        "source": source, "asset": "fx", "code": "USD", "branch": "",
        "buy_cash": 26000.0, "buy_transfer": 26100.0, "sell": 26400.0,
        "unit": "VND", "ts_source": ts_source, "ts_crawled": ts_source,
        "raw_hash": "abc123", "parser_version": "1.0.0",
        "validation": validation, "notes": "",
    }


def crawl_log_row(source, status, message=""):
    return {
        "source": source, "ts_crawled": datetime.now(timezone.utc).isoformat(),
        "status": status, "n_records": 0, "n_ok": 0, "n_warn": 0,
        "n_reject": 0, "raw_path": "", "message": message,
    }


def iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def test_recent_source_is_green(tmp_path):
    db = make_db(tmp_path,
                 quotes=[quote_row("vcb", iso(10))],
                 crawl_logs=[crawl_log_row("vcb", "ok")])
    rows = {r["source"]: r for r in health_rows(db)}
    assert rows["vcb"]["state"] == "GRN"


def test_source_between_thresholds_is_yellow(tmp_path):
    db = make_db(tmp_path,
                 quotes=[quote_row("bidv", iso(STALE_WARN_MIN + 10))],
                 crawl_logs=[crawl_log_row("bidv", "ok")])
    rows = {r["source"]: r for r in health_rows(db)}
    assert rows["bidv"]["state"] == "YEL"


def test_stale_source_is_red(tmp_path):
    db = make_db(tmp_path,
                 quotes=[quote_row("sjc", iso(STALE_RED_MIN + 60))],
                 crawl_logs=[crawl_log_row("sjc", "ok")])
    rows = {r["source"]: r for r in health_rows(db)}
    assert rows["sjc"]["state"] == "RED"


def test_error_only_source_shows_as_red_not_missing(tmp_path):
    """Regression: truoc khi fix, nguon loi truoc khi insert duoc quote nao
    hoan toan vang mat khoi health output vi query cu GROUP BY tren
    `quotes` (khong co dong nao de group)."""
    db = make_db(tmp_path,
                 quotes=[],
                 crawl_logs=[crawl_log_row("pnj", "error",
                                            "TimeoutError: read timed out")])
    rows = {r["source"]: r for r in health_rows(db)}
    assert "pnj" in rows
    assert rows["pnj"]["state"] == "RED"
    assert rows["pnj"]["message"] == "TimeoutError: read timed out"
    assert rows["pnj"]["last_source"] is None


def test_missing_db_path_fails_instead_of_creating_one(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    with pytest.raises(sqlite3.OperationalError):
        health_rows(missing)
    assert not missing.exists()


def test_survives_stale_rollback_journal_in_wal_mode(tmp_path):
    """Regression: mot hot rollback journal (.db-journal) tung khien
    health_rows() (mode=ro) crash voi 'attempt to write a readonly
    database', vi SQLite phai rollback truoc khi doc duoc nhung mode=ro
    khong ghi duoc. WAL mode (pipeline._connect()) loai bo van de nay vi
    reader khong con phu thuoc vao trang thai journal cua writer."""
    db = make_db(tmp_path,
                 quotes=[quote_row("vcb", iso(10))],
                 crawl_logs=[crawl_log_row("vcb", "ok")])

    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.close()

    # Gia lap 1 write transaction dang do dang (journal/WAL con treo) roi
    # bi ngat giua chung, khong commit/rollback.
    con = sqlite3.connect(db, timeout=1)
    con.execute("BEGIN")
    con.execute("INSERT INTO quotes(source,asset,code,branch,ts_source,"
                "ts_crawled,validation) VALUES('x','fx','X','','t','t','ok')")

    rows = {r["source"]: r for r in health_rows(db)}
    con.rollback()
    con.close()

    assert rows["vcb"]["state"] == "GRN"
