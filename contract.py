"""Data Contract v1 — moi adapter PHAI tra ve list[Quote] theo schema nay.

Don vi:
  - fx  : VND cho 1 don vi ngoai te   (unit = "VND")
  - gold: VND cho 1 luong (10 chi)    (unit = "VND_PER_LUONG")

Thoi gian: ISO 8601. ts_source la gio VN (+07:00) do NGUON cong bo,
ts_crawled la thoi diem crawler chay. Tach rieng 2 truong nay de phat hien
"silent staleness" (nguon tra HTTP 200 nhung du lieu dong bang).
"""
from dataclasses import dataclass, asdict

PARSER_VERSION = "1.0.0"


@dataclass
class Quote:
    source: str            # 'vcb' | 'bidv' | 'sjc' | 'pnj'
    asset: str             # 'fx' | 'gold'
    code: str              # fx: 'USD', 'EUR'... | gold: 'SJC_BAR', 'RING_9999'...
    branch: str            # gold theo chi nhanh; fx de ""
    buy_cash: float
    buy_transfer: float
    sell: float
    unit: str
    ts_source: str         # thoi diem NGUON cong bo gia
    ts_crawled: str        # thoi diem crawler lay ve
    raw_hash: str          # sha256 payload goc -> truy nguoc file raw
    parser_version: str = PARSER_VERSION
    validation: str = "pending"   # pending | ok | warn | reject
    notes: str = ""

    def to_row(self):
        return asdict(self)


def parse_num(v):
    """'26,105' -> 26105.0 ; '-' / '' / None / '0.00' -> None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None
