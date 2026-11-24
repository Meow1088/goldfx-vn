"""In gia vang hom nay (SJC, PNJ, DOJI, BTMC) + ty gia USD ngan hang +
so sanh gia vang the gioi, tat ca trong 1 lan chay. Dung cho Hermes skill
"giá vàng hôm nay": chay pipeline.py --live truoc de lay du lieu moi, roi
chay script nay de format ket qua.

python3 gold_today.py
"""
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = Path(__file__).parent / "goldfx.db"
_TROY_OZ_TO_LUONG = 37.5 / 31.1034768
_WORLD_GOLD_URL = "https://api.gold-api.com/price/XAU"

# Danh sach "headline" thu gon - moi nguon co hang chuc bien the
# branch/karat (vd SJC co 12 chi nhanh gia giong het nhau, PNJ co ~20 ma
# vang trang suc theo tuoi) khong dang in het trong 1 tin nhan Telegram.
# (source, code, branch, label)
_HEADLINE = [
    ("sjc", "SJC_BAR", "Hồ Chí Minh", "SJC miếng (1L/10L/1KG)"),
    ("sjc", "SJC_RING_9999", "Hồ Chí Minh", "SJC nhẫn trơn 9999"),
    ("pnj", "SJC", "hochiminh", "PNJ niêm yết vàng miếng SJC"),
    ("doji", "DOJI_BAR", "Hà Nội", "DOJI miếng (Hà Nội)"),
    ("doji", "DOJI_BAR", "Hồ Chí Minh", "DOJI miếng (Hồ Chí Minh)"),
    ("btmc", "BTMC_BAR", "", "Bảo Tín Minh Châu miếng"),
    ("btmc", "BTMC_RING", "", "Bảo Tín Minh Châu nhẫn"),
]


def latest_gold_rows(db_path: Path = DB):
    con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                          timeout=10)
    try:
        rows = con.execute("""
            SELECT source, code, branch, buy_cash, sell, unit, ts_source, validation
            FROM quotes
            WHERE asset='gold' AND validation IN ('ok','warn')
              AND ts_source = (
                  SELECT MAX(q2.ts_source) FROM quotes q2
                  WHERE q2.source = quotes.source AND q2.code = quotes.code
                    AND q2.branch = quotes.branch AND q2.asset='gold'
                    AND q2.validation IN ('ok','warn'))
        """).fetchall()
    finally:
        con.close()
    by_key = {(r[0], r[1], r[2]): r for r in rows}
    return [by_key[(src, code, branch)] for src, code, branch, _ in _HEADLINE
            if (src, code, branch) in by_key]


def latest_usd_summary(db_path: Path = DB):
    """Ty gia USD tung ngan hang, ban ghi moi nhat. Mot so ngan hang (TCB)
    khong co dong code='USD' thuan ma chi niem yet theo menh gia ("USD
    (50,100)"...) -- lay tat ca bien the roi chon 1 dong dai dien moi
    nguon: uu tien code='USD' thuan (VCB/BIDV), neu khong co thi lay dong
    buy_transfer cao nhat (thuong ung voi menh gia lon = ty gia chuan)."""
    con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                          timeout=10)
    try:
        rows = con.execute("""
            SELECT source, code, buy_transfer, sell, ts_source FROM quotes
            WHERE asset='fx' AND code LIKE 'USD%' AND validation IN ('ok','warn')
              AND ts_source=(SELECT MAX(ts_source) FROM quotes q2
                             WHERE q2.source=quotes.source AND q2.code=quotes.code
                               AND q2.validation IN ('ok','warn'))
        """).fetchall()
    finally:
        con.close()

    best = {}
    for source, code, buy_transfer, sell, ts_source in rows:
        rank = (code == "USD", buy_transfer or 0)
        if source not in best or rank > best[source][0]:
            best[source] = (rank, (source, buy_transfer, sell, ts_source))
    return sorted((v[1] for v in best.values()), key=lambda r: r[0])


def fetch_world_gold_usd(timeout=8):
    """Gia vang the gioi XAU/USD tu API cong khai, khong can key. Loi
    network o day KHONG duoc lam sap ca report - goi cho nay luon boc
    trong try/except o call site."""
    req = urllib.request.Request(_WORLD_GOLD_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return {"price_usd_oz": data["price"], "updated_at": data.get("updatedAt")}


def format_report(gold_rows, usd_rows=(), world=None) -> str:
    if not gold_rows:
        return "Chưa có dữ liệu giá vàng (goldfx.db rỗng — cần chạy pipeline.py --live trước)."

    labels = {(src, code, branch): label for src, code, branch, label in _HEADLINE}
    now_str = datetime.now(timezone.utc).astimezone().strftime("%H:%M %d/%m/%Y")
    lines = [f"Giá vàng cập nhật lúc {now_str}:"]
    for source, code, branch, buy, sell, unit, ts_source, validation in gold_rows:
        label = labels.get((source, code, branch), f"{source.upper()} {code}")
        flag = " [cảnh báo dữ liệu]" if validation == "warn" else ""
        buy_s = f"{buy:,.0f}" if buy is not None else "?"
        sell_s = f"{sell:,.0f}" if sell is not None else "?"
        lines.append(f"- {label}: mua {buy_s} / bán {sell_s} {unit}{flag}")

    # sell (gia ngan hang ban USD cho khach) dung de quy doi gia vang the
    # gioi ra VND - gan voi chi phi thuc te de mua USD roi quy doi vang.
    usd_sell_rate = usd_rows[0][2] if usd_rows else None
    if world and usd_sell_rate:
        vnd_per_luong = world["price_usd_oz"] * usd_sell_rate * _TROY_OZ_TO_LUONG
        lines.append("")
        lines.append(f"Giá vàng thế giới: {world['price_usd_oz']:,.2f} USD/oz "
                     f"(quy đổi ~{vnd_per_luong:,.0f} VND/lượng theo tỷ giá {usd_sell_rate:,.0f})")
        sjc_sell = next((r[4] for r in gold_rows
                         if r[0] == "sjc" and r[1] == "SJC_BAR" and r[4]), None)
        if sjc_sell:
            diff = sjc_sell - vnd_per_luong
            pct = diff / vnd_per_luong * 100
            lines.append(f"→ SJC trong nước đang cao hơn thế giới ~{diff:,.0f} VND/lượng (+{pct:.1f}%)")
    elif not world:
        lines.append("")
        lines.append("(Không lấy được giá vàng thế giới lúc này — bỏ qua phần so sánh.)")

    if usd_rows:
        lines.append("")
        lines.append("Tỷ giá USD ngân hàng:")
        for source, buy_transfer, sell, ts_source in usd_rows:
            lines.append(f"- {source.upper()}: mua {buy_transfer:,.0f} / bán {sell:,.0f}")

    return "\n".join(lines)


if __name__ == "__main__":
    gold_rows = latest_gold_rows()
    usd_rows = latest_usd_summary()
    try:
        world = fetch_world_gold_usd()
    except Exception:
        world = None
    print(format_report(gold_rows, usd_rows, world))
