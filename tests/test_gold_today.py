"""Tests cho gold_today.py — dung boi Hermes skill 'giá vàng hôm nay'."""
import sqlite3
from datetime import datetime, timezone

from gold_today import format_report, latest_gold_rows
from pipeline import SCHEMA


def make_db(tmp_path, quotes):
    db_path = tmp_path / "test.db"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    row = {
        "source": "sjc", "asset": "gold", "code": "SJC_BAR",
        "branch": "Hồ Chí Minh", "buy_cash": 145500000.0, "buy_transfer": None,
        "sell": 148500000.0, "unit": "VND_PER_LUONG",
        "ts_source": datetime.now(timezone.utc).isoformat(),
        "ts_crawled": datetime.now(timezone.utc).isoformat(),
        "raw_hash": "abc123", "parser_version": "1.0.0",
        "validation": "ok", "notes": "",
    }
    for overrides in quotes:
        r = dict(row, **overrides)
        con.execute(
            "INSERT INTO quotes(source,asset,code,branch,buy_cash,buy_transfer,"
            "sell,unit,ts_source,ts_crawled,raw_hash,parser_version,validation,notes) "
            "VALUES(:source,:asset,:code,:branch,:buy_cash,:buy_transfer,:sell,"
            ":unit,:ts_source,:ts_crawled,:raw_hash,:parser_version,:validation,:notes)",
            r)
    con.commit()
    con.close()
    return db_path


def test_picks_only_headline_entries_in_fixed_order(tmp_path):
    """Nguon co hang chuc chi nhanh/karat (vd 12 chi nhanh SJC gia giong
    het nhau) -- chi nhung (source,code,branch) trong whitelist _HEADLINE
    moi duoc in ra, theo dung thu tu whitelist."""
    db = make_db(tmp_path, [
        {"code": "SJC_BAR", "branch": "Hồ Chí Minh"},
        {"code": "SJC_BAR", "branch": "Hải Phòng"},        # khong trong whitelist
        {"code": "SJC_RING_9999", "branch": "Hồ Chí Minh"},
        {"code": "JEWELRY_417", "branch": "Hồ Chí Minh"},  # khong trong whitelist
    ])
    rows = latest_gold_rows(db)
    keys = [(r[0], r[1], r[2]) for r in rows]
    assert keys == [("sjc", "SJC_BAR", "Hồ Chí Minh"),
                     ("sjc", "SJC_RING_9999", "Hồ Chí Minh")]


def test_format_report_uses_vietnamese_labels(tmp_path):
    db = make_db(tmp_path, [{"code": "SJC_BAR", "branch": "Hồ Chí Minh"}])
    text = format_report(latest_gold_rows(db))
    assert "SJC miếng (1L/10L/1KG)" in text
    assert "145,500,000" in text
    assert "148,500,000" in text


def test_format_report_handles_empty_db():
    text = format_report([])
    assert "Chưa có dữ liệu" in text


def test_reject_quotes_excluded(tmp_path):
    db = make_db(tmp_path, [
        {"code": "SJC_BAR", "branch": "Hồ Chí Minh", "validation": "reject"},
    ])
    assert latest_gold_rows(db) == []


def test_format_report_adds_world_comparison_and_usd_rates(tmp_path):
    db = make_db(tmp_path, [{"code": "SJC_BAR", "branch": "Hồ Chí Minh"}])
    usd_rows = [("vcb", 26070.0, 26450.0, "2026-07-15T08:10:45+07:00")]
    world = {"price_usd_oz": 4030.80, "updated_at": "2026-07-15T09:17:06Z"}
    text = format_report(latest_gold_rows(db), usd_rows, world)
    assert "Giá vàng thế giới" in text
    assert "VCB: mua 26,070 / bán 26,450" in text
    assert "cao hơn thế giới" in text


def test_format_report_degrades_gracefully_without_world_price(tmp_path):
    """Neu API gia vang the gioi loi network, report van phai in duoc
    phan vang trong nuoc + ty gia USD binh thuong, khong crash."""
    db = make_db(tmp_path, [{"code": "SJC_BAR", "branch": "Hồ Chí Minh"}])
    usd_rows = [("vcb", 26070.0, 26450.0, "2026-07-15T08:10:45+07:00")]
    text = format_report(latest_gold_rows(db), usd_rows, world=None)
    assert "SJC miếng" in text
    assert "VCB: mua 26,070" in text
    assert "Không lấy được giá vàng thế giới" in text
