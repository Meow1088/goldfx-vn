"""Scheduler -> Crawler -> Raw storage -> Validation -> Normalize -> SQLite.

Chay live:      python3 pipeline.py --live
Chay fixtures:  python3 pipeline.py --fixtures fixtures/
Rebuild tu raw: python3 pipeline.py --replay raw/YYYY/MM/DD
Cron goi y:     */10 * * * * cd /path && python3 pipeline.py --live

Raw response luu o raw/YYYY/MM/DD/<source>_<HHMMSS>.json — parser/DB loi
van rebuild lai duoc toan bo tu day qua --replay.
"""
import argparse, hashlib, json, re, sqlite3, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from adapters import ADAPTERS, SOURCE_URLS
from validators import run_all

BASE = Path(__file__).parent
DB = BASE / "goldfx.db"
RAW = BASE / "raw"
UA = {"User-Agent": "Mozilla/5.0 (GoldFX crawler; contact: you@example.com)"}
_XML_SOURCES = {"doji"}  # nguon tra XML thay vi JSON

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY,
  source TEXT, asset TEXT, code TEXT, branch TEXT,
  buy_cash REAL, buy_transfer REAL, sell REAL, unit TEXT,
  ts_source TEXT, ts_crawled TEXT,
  raw_hash TEXT, parser_version TEXT, validation TEXT, notes TEXT,
  UNIQUE(source, asset, code, branch, ts_source)
);
CREATE INDEX IF NOT EXISTS idx_quotes_lookup ON quotes(source, code, ts_source);
CREATE TABLE IF NOT EXISTS crawl_log(
  id INTEGER PRIMARY KEY,
  source TEXT, ts_crawled TEXT, status TEXT,
  n_records INTEGER, n_ok INTEGER, n_warn INTEGER, n_reject INTEGER,
  raw_path TEXT, message TEXT
);
"""


def fetch_live(source: str) -> bytes:
    now = datetime.now()
    url = SOURCE_URLS[source].format(
        today=now.strftime("%Y-%m-%d"), today_dmy=now.strftime("%d/%m/%Y"))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def save_raw(source: str, blob: bytes, now: datetime) -> Path:
    d = RAW / now.strftime("%Y/%m/%d")
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{source}_{now.strftime('%H%M%S')}.json"
    p.write_bytes(blob)
    return p


def prev_price_lookup(con):
    def lookup(q):
        row = con.execute(
            "SELECT COALESCE(sell, buy_transfer, buy_cash) FROM quotes "
            "WHERE source=? AND code=? AND branch=? AND validation IN ('ok','warn') "
            "ORDER BY ts_source DESC LIMIT 1",
            (q.source, q.code, q.branch)).fetchone()
        return row[0] if row else None
    return lookup


def _connect():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    # WAL: readers (health.py, mode=ro) khong bi chan boi journal cua writer
    # nay nua -> mode=ro se khong con nhan "attempt to write a readonly
    # database" khi co hot rollback journal dang cho xu ly.
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _process_round(con, sources, ts_crawled, blob_fn, raw_path_fn):
    """1 round crawl: fetch (qua blob_fn) -> parse -> validate ca round
    cung nhau (L3 can du lieu moi nguon) -> insert. Dung chung cho --live,
    --fixtures va --replay."""
    all_quotes = []
    per_source = {}

    for src in sources:
        try:
            blob = blob_fn(src)
            raw_path = raw_path_fn(src, blob)
            raw_hash = hashlib.sha256(blob).hexdigest()[:16]
            parsed = blob.decode("utf-8") if src in _XML_SOURCES else json.loads(blob)
            quotes = ADAPTERS[src](parsed, ts_crawled, raw_hash)
            per_source[src] = (quotes, str(raw_path), None)
            all_quotes.extend(quotes)
        except Exception as e:  # crawl/parse loi -> log, khong sap ca batch
            per_source[src] = ([], "", f"{type(e).__name__}: {e}")

    run_all(all_quotes, prev_price_lookup(con))   # L3 can du lieu MOI nguon

    for src, (quotes, raw_path, err) in per_source.items():
        n = {"ok": 0, "warn": 0, "reject": 0}
        for q in quotes:
            n[q.validation] += 1
            r = q.to_row()
            con.execute(
                "INSERT OR IGNORE INTO quotes(source,asset,code,branch,buy_cash,"
                "buy_transfer,sell,unit,ts_source,ts_crawled,raw_hash,"
                "parser_version,validation,notes) "
                "VALUES(:source,:asset,:code,:branch,:buy_cash,:buy_transfer,"
                ":sell,:unit,:ts_source,:ts_crawled,:raw_hash,:parser_version,"
                ":validation,:notes)", r)
        status = "error" if err else ("ok" if n["reject"] == 0 else "partial")
        con.execute(
            "INSERT INTO crawl_log(source,ts_crawled,status,n_records,n_ok,"
            "n_warn,n_reject,raw_path,message) VALUES(?,?,?,?,?,?,?,?,?)",
            (src, ts_crawled, status, len(quotes), n["ok"], n["warn"],
             n["reject"], raw_path, err or ""))
        flag = "OK " if status == "ok" else ("ERR" if err else "WRN")
        print(f"[{flag}] {src:5s} {len(quotes):3d} records "
              f"(ok={n['ok']} warn={n['warn']} reject={n['reject']})"
              + (f"  <- {err}" if err else ""))


def run(sources, fixtures_dir=None):
    con = _connect()
    now = datetime.now(timezone.utc)
    ts_crawled = now.isoformat(timespec="seconds")

    def blob_fn(src):
        if fixtures_dir:
            ext = "xml" if src in _XML_SOURCES else "json"
            return (Path(fixtures_dir) / f"{src}.{ext}").read_bytes()
        return fetch_live(src)

    def raw_path_fn(src, blob):
        return save_raw(src, blob, datetime.now())

    _process_round(con, sources, ts_crawled, blob_fn, raw_path_fn)
    con.commit()
    con.close()


_RAW_NAME_RE = re.compile(r"^([a-z]+)_(\d{6})\.(json|xml)$")


def replay(raw_dir):
    """Dung raw JSON/XML da luu (raw/YYYY/MM/DD/<source>_<HHMMSS>.<ext>) de
    rebuild lai quotes/crawl_log tu dau -- ung voi loi hua trong docstring
    module nay. Gom cac file theo (ngay, HHMM) lam 1 "round" de L3 cross-
    source validation co du lieu nhieu nguon cung luc, giong 1 lan --live
    that; giay le (giay thu 2 trong HHMMSS) bi bo qua khi gom nhom."""
    con = _connect()

    rounds = {}  # (date_str, hhmm) -> {source: Path}
    for p in sorted(Path(raw_dir).rglob("*")):
        if not p.is_file():
            continue
        m = _RAW_NAME_RE.match(p.name)
        if not m:
            continue
        src, hhmmss, ext = m.groups()
        if src not in ADAPTERS:
            continue
        try:
            dd, mm, yyyy = p.parent.name, p.parent.parent.name, p.parent.parent.parent.name
            date_str = f"{yyyy}-{mm}-{dd}"
        except AttributeError:
            continue
        rounds.setdefault((date_str, hhmmss[:4]), {})[src] = p

    for (date_str, hhmm), files in sorted(rounds.items()):
        ts_crawled = f"{date_str}T{hhmm[:2]}:{hhmm[2:]}:00+00:00"
        sources = sorted(files)

        def blob_fn(src, files=files):
            return files[src].read_bytes()

        def raw_path_fn(src, blob, files=files):
            return files[src]

        _process_round(con, sources, ts_crawled, blob_fn, raw_path_fn)

    con.commit()
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--fixtures")
    ap.add_argument("--replay", help="Rebuild DB tu raw/ da luu (vd: raw/2026/07/15)")
    ap.add_argument("--sources", default="vcb,bidv,sjc,pnj,tcb,doji,btmc")
    a = ap.parse_args()
    if not a.live and not a.fixtures and not a.replay:
        sys.exit("Chon --live, --fixtures <dir>, hoac --replay <raw_dir>")
    if a.replay:
        replay(a.replay)
    else:
        run(a.sources.split(","), fixtures_dir=a.fixtures)
