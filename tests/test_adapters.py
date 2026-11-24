"""Tests cho 3 adapter moi (TCB/DOJI/BTMC) — tap trung vao cac quirk da
phat hien khi research: DOJI lech don vi giua chi nhanh, BTMC gia boc
trong the <b>, TCB thieu askRate phai fallback ve askRateTM."""
import json

from adapters import parse_tcb, parse_doji, parse_btmc


def test_parse_tcb_uses_ask_rate_when_present():
    payload = {"exchangeRate": {"data": [
        {"itemId": "1", "label": "EUR", "askRate": "30705",
         "bidRateCK": "29628", "bidRateTM": "29407",
         "sourceCurrency": "EUR", "targetCurrency": "VND",
         "inputDate": "2026-07-15T13:32:00.933Z"},
    ]}}
    out = parse_tcb(payload, "2026-07-15T13:32:00+00:00", "hash1")
    assert len(out) == 1
    q = out[0]
    assert q.code == "EUR"
    assert q.buy_cash == 29407.0
    assert q.buy_transfer == 29628.0
    assert q.sell == 30705.0
    assert q.ts_source == "2026-07-15T13:32:00.933Z"


def test_parse_tcb_falls_back_to_ask_rate_tm_when_ask_rate_missing():
    """Regression: mot so dong USD chi co askRateTM, khong co askRate."""
    payload = {"exchangeRate": {"data": [
        {"itemId": "2", "label": "USD (1,2)", "bidRateTM": "25994",
         "sourceCurrency": "USD", "targetCurrency": "VND",
         "askRateTM": "26494", "inputDate": "2026-07-15T13:32:00.933Z"},
    ]}}
    out = parse_tcb(payload, "2026-07-15T13:32:00+00:00", "hash1")
    assert out[0].sell == 26494.0


def test_parse_doji_applies_different_factor_per_branch():
    """Regression: cung mot feed nhung don vi HN (nghin/luong) va HCM
    (nghin/chi) lech nhau 10 lan neu dung chung 1 factor."""
    xml = """<?xml version='1.0' encoding='utf-8'?>
<GoldList><DGPlist>
    <DateTime>07:00 01/01/1970</DateTime>
    <Row Name='DOJI HN lẻ' Key='x' Sell='148,500' Buy='145,500' />
    <Row Name='DOJI HCM lẻ' Key='x' Sell='14,850' Buy='14,550' />
</DGPlist></GoldList>"""
    out = {q.branch: q for q in parse_doji(xml, "2026-07-15T00:00:00+00:00", "h")}
    assert out["Hà Nội"].sell == 148_500_000.0
    assert out["Hồ Chí Minh"].sell == 148_500_000.0
    assert out["Hà Nội"].code == out["Hồ Chí Minh"].code == "DOJI_BAR"


def test_parse_doji_uses_ts_crawled_since_datetime_field_is_dead():
    xml = """<?xml version='1.0' encoding='utf-8'?>
<GoldList><DGPlist>
    <DateTime>07:00 01/01/1970</DateTime>
    <Row Name='DOJI HN lẻ' Key='x' Sell='148,500' Buy='145,500' />
</DGPlist></GoldList>"""
    out = parse_doji(xml, "2026-07-15T09:00:00+00:00", "h")
    assert out[0].ts_source == "2026-07-15T09:00:00+00:00"


def test_parse_btmc_strips_html_and_applies_factor():
    payload = {"Data": {
        "btmcvangmiengmua": "<b>14350</b>", "btmcvangmiengban": "<b>14750</b>",
        "btmcvangnhanmua": "<b>14350</b>", "btmcvangnhanban": "<b>14750</b>",
        "btmcvangquamungmua": "<b>14350</b>", "btmcvangquamungban": "<b>14750</b>",
        "sjcmua": "<b>14350</b>", "sjcban": "<b>14850</b>",
        "trangsucmua": "<b>14150</b>", "trangsucban": "<b>14650</b>",
        "trangsucmua1": "<b>14130</b>", "trangsucban1": "<b>14630</b>",
        "vangnguyenlieumua": "<b>13100</b>", "vangnguyenlieuban": None,
        "xemchitiet": None,
    }}
    out = {q.code: q for q in parse_btmc(payload, "2026-07-15T00:00:00+00:00", "h")}
    assert out["BTMC_BAR"].buy_cash == 143_500_000.0
    assert out["BTMC_BAR"].sell == 147_500_000.0
    assert out["SJC"].sell == 148_500_000.0


def test_parse_btmc_skips_null_only_products():
    payload = {"Data": {
        "btmcvangmiengmua": None, "btmcvangmiengban": None,
        "btmcvangnhanmua": None, "btmcvangnhanban": None,
        "sjcmua": None, "sjcban": None,
    }}
    assert parse_btmc(payload, "2026-07-15T00:00:00+00:00", "h") == []
