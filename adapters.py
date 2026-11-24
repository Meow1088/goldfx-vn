"""Adapter cho tung nguon: payload goc -> list[Quote] theo Data Contract.

Them nguon moi = them 1 ham parse_<source>() o day. Khong dong cham gi
den validation / storage / API.
"""
import json
import os
from datetime import datetime, timezone, timedelta

from contract import Quote, parse_num

TZ_VN = timezone(timedelta(hours=7))

# ------------------------------------------------------------------ VCB ----
# https://www.vietcombank.com.vn/api/exchangerates?date=YYYY-MM-DD
# Co tham so date -> backfill duoc lich su.

def parse_vcb(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    ts_source = payload["UpdatedDate"]  # ISO san: "2026-07-02T08:09:09+07:00"
    out = []
    for r in payload.get("Data", []):
        out.append(Quote(
            source="vcb", asset="fx", code=r["currencyCode"].strip(), branch="",
            buy_cash=parse_num(r.get("cash")),
            buy_transfer=parse_num(r.get("transfer")),
            sell=parse_num(r.get("sell")),
            unit="VND", ts_source=ts_source,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out

# ----------------------------------------------------------------- BIDV ----
# https://bidv.com.vn/ServicesBIDV/ExchangeDetailServlet
# CANH BAO: nameEN sai loan (THB ghi "JPY", GBP ghi "Euro") -> CHI tin
# truong `currency`. So co dau phay dang string.

def parse_bidv(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    day = payload.get("day_vi", "")            # "02/07/2026"
    hour = payload.get("hour", "00:00")        # "08:11"
    ts_source = datetime.strptime(f"{day} {hour}", "%d/%m/%Y %H:%M") \
                        .replace(tzinfo=TZ_VN).isoformat()
    out = []
    for r in payload.get("data", []):
        code = r["currency"].strip()           # giu nguyen "USD(1-2-5)"...
        out.append(Quote(
            source="bidv", asset="fx", code=code, branch="",
            buy_cash=parse_num(r.get("muaTm")),
            buy_transfer=parse_num(r.get("muaCk")),
            sell=parse_num(r.get("ban")),
            unit="VND", ts_source=ts_source,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out

# ------------------------------------------------------------------ SJC ----
# https://sjc.com.vn/GoldPrice/Services/PriceService.ashx
# BuyValue/SellValue da la VND day du. latestDate: "13:41 01/07/2026".
# CANH BAO: cac endpoint cu (textContent.php...) van tra 200 nhung dong
# bang tu 2022 — day chinh la ly do phai check ts_source o validation.

_SJC_CODE = {
    "Vàng SJC 1L, 10L, 1KG": "SJC_BAR",
    "Vàng SJC 5 chỉ": "SJC_BAR_5C",
    "Vàng SJC 0.5 chỉ, 1 chỉ, 2 chỉ": "SJC_BAR_SMALL",
    "Vàng nhẫn SJC 99,99% 1 chỉ, 2 chỉ, 5 chỉ": "SJC_RING_9999",
    "Vàng nhẫn SJC 99,99% 0.5 chỉ, 0.3 chỉ": "SJC_RING_9999_SMALL",
}

def parse_sjc(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    ts_source = datetime.strptime(payload["latestDate"], "%H:%M %d/%m/%Y") \
                        .replace(tzinfo=TZ_VN).isoformat()
    out = []
    for r in payload.get("data", []):
        code = _SJC_CODE.get(r["TypeName"])
        if code is None:                       # nu trang: slug tu ten
            code = "JEWELRY_" + "".join(c for c in r["TypeName"] if c.isdigit())
        out.append(Quote(
            source="sjc", asset="gold", code=code,
            branch=r.get("BranchName", ""),
            buy_cash=r.get("BuyValue") or None, buy_transfer=None,
            sell=r.get("SellValue") or None,
            unit="VND_PER_LUONG", ts_source=ts_source,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out

# ------------------------------------------------------------------ PNJ ----
# https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00
# Gia tinh bang NGHIN DONG / CHI -> nhan 10_000 de ra VND / LUONG.
# masp="SJC" = gia vang mieng SJC do PNJ niem yet -> doi chieu cheo voi SJC.

_PNJ_FACTOR = 10_000

def parse_pnj(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    ts_source = datetime.strptime(payload["updateDate"], "%d/%m/%Y %H:%M:%S") \
                        .replace(tzinfo=TZ_VN).isoformat()
    branch = payload.get("chinhanh", "")
    out = []
    for r in payload.get("data", []):
        buy, sell = parse_num(r.get("giamua")), parse_num(r.get("giaban"))
        out.append(Quote(
            source="pnj", asset="gold", code=r["masp"].strip(), branch=branch,
            buy_cash=buy * _PNJ_FACTOR if buy else None, buy_transfer=None,
            sell=sell * _PNJ_FACTOR if sell else None,
            unit="VND_PER_LUONG", ts_source=ts_source,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out


# ------------------------------------------------------------------ TCB ----
# https://techcombank.com/content/techcombank/web/vn/en/cong-cu-tien-ich/
#   ty-gia/_jcr_content.exchange-rates.integration.json
# JSON, inputDate da la ISO8601 (+Z). askRate = ban chuyen khoan, thieu o
# 2/3 dong USD -> fallback ve askRateTM (ban tien mat).

def parse_tcb(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    out = []
    for r in payload.get("exchangeRate", {}).get("data", []):
        sell = parse_num(r.get("askRate")) or parse_num(r.get("askRateTM"))
        out.append(Quote(
            source="tcb", asset="fx", code=r["label"].strip(), branch="",
            buy_cash=parse_num(r.get("bidRateTM")),
            buy_transfer=parse_num(r.get("bidRateCK")),
            sell=sell,
            unit="VND", ts_source=r["inputDate"],
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out

# ----------------------------------------------------------------- DOJI ----
# http://giavang.doji.vn/api/giavang/?api_key=...  (XML, khong phai JSON!)
# CANH BAO 1: <DateTime> cua DGPlist/JewelryList la gia tri CHET
#   "07:00 01/01/1970" — khong dung duoc lam ts_source, phai dung ts_crawled.
# CANH BAO 2: DON VI LECH GIUA CHI NHANH trong CUNG mot feed —
#   dong "DOJI HN *" la nghin dong/LUONG (x1_000), dong "DOJI HCM *" la
#   nghin dong/CHI (x10_000, giong PNJ). Nham 2 factor nay se ra gia sai
#   lech 10 lan va bi validator L3 cross-source reject.

_DOJI_ROWS = {
    "DOJI HN lẻ":   ("DOJI_BAR", "Hà Nội", 1_000),
    "DOJI HN buôn": ("DOJI_BAR_WHOLESALE", "Hà Nội", 1_000),
    "DOJI HCM lẻ":  ("DOJI_BAR", "Hồ Chí Minh", 10_000),
    "DOJI HCM buôn": ("DOJI_BAR_WHOLESALE", "Hồ Chí Minh", 10_000),
}

def parse_doji(payload: str, ts_crawled: str, raw_hash: str) -> list:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(payload)
    out = []
    for row in root.findall("./DGPlist/Row"):
        info = _DOJI_ROWS.get(row.get("Name", "").strip())
        if info is None:
            continue
        code, branch, factor = info
        buy, sell = parse_num(row.get("Buy")), parse_num(row.get("Sell"))
        out.append(Quote(
            source="doji", asset="gold", code=code, branch=branch,
            buy_cash=buy * factor if buy else None, buy_transfer=None,
            sell=sell * factor if sell else None,
            unit="VND_PER_LUONG", ts_source=ts_crawled,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out

# ----------------------------------------------------------------- BTMC ----
# https://btmc.vn/ProductHome/getGoldDate?date=DD/MM/YYYY
# JSON nhung gia tri boc trong "<b>...</b>". Nghin dong/CHI -> x10_000 ra
# VND/LUONG (giong PNJ). CANH BAO: response khong echo lai ngay/gio that
# su cap nhat -> dung ts_crawled lam ts_source (chi chinh xac theo ngay).

_BTMC_FACTOR = 10_000

def _btmc_num(v):
    if v is None:
        return None
    return parse_num(v.replace("<b>", "").replace("</b>", ""))

def parse_btmc(payload: dict, ts_crawled: str, raw_hash: str) -> list:
    d = payload.get("Data", {})
    items = [
        ("BTMC_BAR", "btmcvangmiengmua", "btmcvangmiengban"),
        ("BTMC_RING", "btmcvangnhanmua", "btmcvangnhanban"),
        ("SJC", "sjcmua", "sjcban"),  # BTMC niem yet gia SJC -> doi chieu cheo
    ]
    out = []
    for code, buy_key, sell_key in items:
        buy, sell = _btmc_num(d.get(buy_key)), _btmc_num(d.get(sell_key))
        if buy is None and sell is None:
            continue
        out.append(Quote(
            source="btmc", asset="gold", code=code, branch="",
            buy_cash=buy * _BTMC_FACTOR if buy else None, buy_transfer=None,
            sell=sell * _BTMC_FACTOR if sell else None,
            unit="VND_PER_LUONG", ts_source=ts_crawled,
            ts_crawled=ts_crawled, raw_hash=raw_hash,
        ))
    return out


ADAPTERS = {
    "vcb": parse_vcb, "bidv": parse_bidv, "sjc": parse_sjc, "pnj": parse_pnj,
    "tcb": parse_tcb, "doji": parse_doji, "btmc": parse_btmc,
}

SOURCE_URLS = {
    "vcb":  "https://www.vietcombank.com.vn/api/exchangerates?date={today}",
    "bidv": "https://bidv.com.vn/ServicesBIDV/ExchangeDetailServlet",
    "sjc":  "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx",
    "pnj":  "https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00",
    "tcb":  "https://techcombank.com/content/techcombank/web/vn/en/cong-cu-tien-ich/ty-gia/_jcr_content.exchange-rates.integration.json",
    "doji": "http://giavang.doji.vn/api/giavang/?api_key=" + os.environ.get("DOJI_API_KEY", "258fbd2a72ce8481089d88c678e9fe4f"),  # key cong khai tren web DOJI
    "btmc": "https://btmc.vn/ProductHome/getGoldDate?date={today_dmy}",
}
