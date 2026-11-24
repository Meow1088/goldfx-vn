"""Validation 3 tang. Tang nao fail thi ghi vao quote.validation + notes,
KHONG drop du lieu — van luu de audit, nhung API chi serve validation='ok'/'warn'.
"""
from datetime import datetime, timezone
from statistics import median

# ---- Tang 1: schema -------------------------------------------------------

def layer1_schema(q) -> bool:
    if not q.source or not q.code or not q.ts_source:
        q.validation, q.notes = "reject", "L1: thieu field bat buoc"
        return False
    if q.buy_cash is None and q.buy_transfer is None and q.sell is None:
        q.validation, q.notes = "reject", "L1: khong co gia nao"
        return False
    return True

# ---- Tang 2: business rule ------------------------------------------------

RANGES = {  # (min, max) hop ly — chan gia tri vo ly do parser/nguon loi
    ("fx", "USD"): (20_000, 40_000),
    ("fx", "EUR"): (20_000, 45_000),
    ("fx", "JPY"): (100, 300),
    ("fx", "*"):   (0.5, 200_000),
    ("gold", "*"): (3_000_000, 1_000_000_000),   # VND/luong
}
MAX_STALE_HOURS = {"fx": 24, "gold": 24}   # qua nguong -> warn
JUMP_WARN, JUMP_REJECT = 0.03, 0.15        # bien dong so voi lan truoc

def layer2_business(q, prev_price=None) -> bool:
    lo, hi = RANGES.get((q.asset, q.code)) or RANGES[(q.asset, "*")]
    for label, v in (("buy_cash", q.buy_cash), ("buy_transfer", q.buy_transfer),
                     ("sell", q.sell)):
        if v is not None and not (lo <= v <= hi):
            q.validation, q.notes = "reject", f"L2: {label}={v} ngoai [{lo},{hi}]"
            return False
    buy = q.buy_transfer or q.buy_cash
    if buy and q.sell and buy >= q.sell:
        q.validation, q.notes = "warn", f"L2: buy>=sell ({buy}>={q.sell})"
    # silent staleness: nguon cong bo qua lau so voi luc crawl
    try:
        ts_s = datetime.fromisoformat(q.ts_source)
        ts_c = datetime.fromisoformat(q.ts_crawled)
        if ts_c.tzinfo is None:
            ts_c = ts_c.replace(tzinfo=timezone.utc)
        age_h = (ts_c - ts_s).total_seconds() / 3600
        if age_h > MAX_STALE_HOURS[q.asset]:
            q.validation = "warn" if q.validation == "pending" else q.validation
            q.notes += f" L2: du lieu nguon cu {age_h:.0f}h"
    except ValueError:
        q.validation, q.notes = "reject", "L2: ts_source khong parse duoc"
        return False
    # bien dong bat thuong so voi gia gan nhat trong DB
    ref = q.sell or buy
    if prev_price and ref:
        chg = abs(ref - prev_price) / prev_price
        if chg > JUMP_REJECT:
            q.validation, q.notes = "reject", f"L2: nhay {chg:.1%} so lan truoc"
            return False
        if chg > JUMP_WARN:
            q.validation = "warn"
            q.notes += f" L2: bien dong {chg:.1%}"
    return True

# ---- Tang 3: cross-source -------------------------------------------------
# So gia cung mot tai san giua nhieu nguon; lech qua nguong -> nghi ngo.

COMPARABLE = {  # nhom (asset, key so sanh) : {source: code}
    ("fx", "USD"):     {"vcb": "USD", "bidv": "USD"},
    ("gold", "SJC_BAR"): {"sjc": "SJC_BAR", "pnj": "SJC"},
}
CROSS_DEV_WARN, CROSS_DEV_REJECT = 0.02, 0.05

def layer3_cross(quotes) -> None:
    for (asset, _key), src_codes in COMPARABLE.items():
        group = [q for q in quotes
                 if q.asset == asset and q.validation != "reject"
                 and q.code == src_codes.get(q.source)
                 and q.sell and (asset == "fx" or q.branch in ("Hồ Chí Minh", "hochiminh", ""))]
        if len(group) < 2:
            continue
        med = median(q.sell for q in group)
        for q in group:
            dev = abs(q.sell - med) / med
            if dev > CROSS_DEV_REJECT:
                q.validation, q.notes = "reject", f"L3: lech {dev:.1%} vs median {med:,.0f}"
            elif dev > CROSS_DEV_WARN:
                q.validation = "warn"
                q.notes += f" L3: lech {dev:.1%} vs median"


def run_all(quotes, prev_lookup=None) -> None:
    """prev_lookup: callable(q) -> gia gan nhat trong DB hoac None."""
    for q in quotes:
        if not layer1_schema(q):
            continue
        prev = prev_lookup(q) if prev_lookup else None
        layer2_business(q, prev)
    layer3_cross(quotes)
    for q in quotes:
        if q.validation == "pending":
            q.validation = "ok"
