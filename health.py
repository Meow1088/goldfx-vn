"""Health check cho admin: python3 health.py
Doc goldfx.db, in trang thai tung nguon. Ket noi Telegram bot sau nay chi
viec goi ham status() va gui text di.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).parent / "goldfx.db"
STALE_WARN_MIN, STALE_RED_MIN = 120, 24 * 60


def health_rows(db_path: Path = DB) -> list[dict]:
    """Trang thai tung nguon, ke ca nguon chi co error trong crawl_log
    (chua tung insert duoc quote nao) — UNION voi quotes de khong bo sot.
    """
    # mode=ro: chi doc, that bai thay vi vo tinh tao/sua db hoac rollback
    # mot stale journal neu co (rollback co the xoa sach du lieu chua commit).
    con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                          timeout=10)
    try:
        rows = con.execute("""
            SELECT s.source,
                   (SELECT MAX(ts_source) FROM quotes q WHERE q.source = s.source),
                   (SELECT ts_crawled FROM crawl_log c WHERE c.source = s.source
                    ORDER BY c.id DESC LIMIT 1),
                   (SELECT status  FROM crawl_log c WHERE c.source = s.source
                    ORDER BY c.id DESC LIMIT 1),
                   (SELECT message FROM crawl_log c WHERE c.source = s.source
                    ORDER BY c.id DESC LIMIT 1),
                   (SELECT SUM(CASE WHEN validation='reject' THEN 1 ELSE 0 END)
                    FROM quotes q WHERE q.source = s.source)
            FROM (SELECT source FROM quotes UNION SELECT source FROM crawl_log) s
            ORDER BY s.source""").fetchall()
    finally:
        con.close()

    now = datetime.now(timezone.utc)
    result = []
    for src, last_src, last_crawl, st, msg, n_rej in rows:
        try:
            age = (now - datetime.fromisoformat(last_src)).total_seconds() / 60
        except (ValueError, TypeError):
            age = None
        if st == "error":
            state, extra = "RED", msg
        elif age is None or age > STALE_RED_MIN:
            state, extra = "RED", f"nguon dong bang {age/60:.0f}h" if age else "?"
        elif age > STALE_WARN_MIN:
            state, extra = "YEL", f"nguon chua cap nhat {age:.0f} phut"
        else:
            state, extra = "GRN", ""
        result.append({
            "source": src,
            "state": state,
            "last_source": last_src,
            "last_crawl": last_crawl,
            "crawl_status": st,
            "rejects": n_rej or 0,
            "age_minutes": age,
            "message": extra,
        })
    return result


def status(db_path: Path = DB) -> str:
    lines = []
    for r in health_rows(db_path):
        lines.append(f"[{r['state']}] {r['source']:5s} "
                     f"last_source={r['last_source'] or '?':25s} "
                     f"rejects={r['rejects']}  {r['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(status())
