"""Read-only FastAPI service over goldfx.db.
Chay:  python3 -m uvicorn api:app --reload
Khong co write path nao — moi ket noi mo bang SQLite URI mode=ro, that bai
thay vi vo tinh tao/sua db neu duong dan sai hoac con stale journal.
"""
import sqlite3
from pathlib import Path

from fastapi import FastAPI

from health import health_rows, status

DB = Path(__file__).parent / "goldfx.db"

app = FastAPI(title="GoldFX API", version="1.0")


def connect_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    # Looked up at call time (not bound as a default) so tests can swap
    # `api.DB` via monkeypatch and have every endpoint pick it up.
    db_path = db_path or DB
    con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                          timeout=10)
    con.row_factory = sqlite3.Row
    return con


@app.get("/fx/{code}/latest")
def fx_latest(code: str):
    code = code.upper()
    con = connect_readonly()
    try:
        rows = con.execute("""
            SELECT source, code, buy_cash, buy_transfer, sell, unit,
                   ts_source, ts_crawled, validation, notes
            FROM quotes
            WHERE asset='fx' AND code=? AND validation IN ('ok','warn')
              AND ts_source = (
                  SELECT MAX(q2.ts_source) FROM quotes q2
                  WHERE q2.source = quotes.source AND q2.asset='fx'
                    AND q2.code=? AND q2.validation IN ('ok','warn'))
            ORDER BY source
        """, (code, code)).fetchall()
    finally:
        con.close()
    return {"code": code, "rates": [dict(r) for r in rows]}


@app.get("/fx/{code}/best")
def fx_best(code: str):
    rates = fx_latest(code)["rates"]
    best_sell = None  # nguon tra buy_transfer cao nhat — khach ban ngoai te loi nhat
    best_buy = None   # nguon tinh sell thap nhat — khach mua ngoai te re nhat
    for r in rates:
        if r["buy_transfer"] is not None and (
                best_sell is None or r["buy_transfer"] > best_sell["rate"]):
            best_sell = {"source": r["source"], "rate": r["buy_transfer"],
                         "field": "buy_transfer", "ts_source": r["ts_source"]}
        if r["sell"] is not None and (
                best_buy is None or r["sell"] < best_buy["rate"]):
            best_buy = {"source": r["source"], "rate": r["sell"],
                       "field": "sell", "ts_source": r["ts_source"]}
    return {"code": code.upper(), "best_customer_sell": best_sell,
            "best_customer_buy": best_buy}


@app.get("/gold/sjc/compare")
def gold_sjc_compare():
    con = connect_readonly()
    try:
        rows = con.execute("""
            SELECT source, code, branch, buy_cash, buy_transfer, sell, unit,
                   ts_source, ts_crawled, validation, notes
            FROM quotes
            WHERE asset='gold' AND code IN ('SJC_BAR','SJC')
              AND branch IN ('Hồ Chí Minh','hochiminh')
              AND validation IN ('ok','warn')
              AND ts_source = (
                  SELECT MAX(q2.ts_source) FROM quotes q2
                  WHERE q2.source = quotes.source AND q2.code = quotes.code
                    AND q2.branch = quotes.branch AND q2.asset='gold'
                    AND q2.validation IN ('ok','warn'))
            ORDER BY source
        """).fetchall()
    finally:
        con.close()
    return {"quotes": [dict(r) for r in rows]}


@app.get("/health/status")
def health_status():
    # Pass api.py's own DB (looked up fresh, not health.py's default) so
    # tests can monkeypatch api.DB and have this endpoint follow along.
    rows = health_rows(DB)
    order = {"RED": 0, "YEL": 1, "GRN": 2}
    worst = min((r["state"] for r in rows), key=lambda s: order[s], default="GRN")
    return {"status": worst, "text": status(DB), "sources": rows}
