# GoldFX Data Pipeline

Crawler + validation + storage cho ty gia ngan hang & gia vang VN, cong them
REST API doc va Telegram alert. Loi crawler/pipeline van la Python stdlib
thuan; API la phan duy nhat can pip (`fastapi`, `uvicorn`).

## Kien truc

```
Scheduler (cron)
  -> pipeline.py       : fetch -> luu RAW json -> parse (adapters) -> validate -> SQLite
  -> telegram_alert.py : doc health, gui Telegram neu co nguon RED
api.py (Uvicorn, chay song song, doc-only)
  -> doc SQLite, serve JSON qua HTTP
```

| File | Vai tro |
|---|---|
| `contract.py`   | Data Contract v1 — schema chuan moi adapter phai theo |
| `adapters.py`   | 7 adapter: VCB, BIDV, SJC, PNJ, TCB, DOJI, BTMC (them nguon = them 1 ham) |
| `validators.py` | 3 tang: schema -> business rule -> cross-source |
| `pipeline.py`   | Orchestrator + raw storage + SQLite |
| `health.py`     | `health_rows()` structured + `status()` text cho CLI/Telegram |
| `queries.py`    | "Ban USD dau cao nhat", "SJC vs PNJ"... (vi du, khong phai API) |
| `api.py`        | FastAPI doc-only: `/fx/{code}/latest`, `/fx/{code}/best`, `/gold/sjc/compare`, `/health/status` |
| `telegram_alert.py` | Gui Telegram khi `health_rows()` co nguon RED |
| `fixtures/`     | Payload THAT capture 02/07/2026 — dung lam test co dinh |
| `tests/`        | pytest cho health/api/telegram_alert |

## Cai dat

```bash
pip install -r requirements.txt   # chi can cho api.py; pipeline/health/queries van stdlib
```

## Chay

```bash
python3 pipeline.py --fixtures fixtures/   # test offline
python3 pipeline.py --live                 # crawl that (chay tren may ban/VPS)
python3 health.py
python3 queries.py
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000   # REST API

# Telegram alert — can 2 bien moi truong:
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export DOJI_API_KEY=...        # key cua feed giavang.doji.vn; thieu thi nguon DOJI bao loi, nguon khac van chay
python3 telegram_alert.py    # im lang + exit 0 neu khong co nguon RED
```

Test: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -v`

Cron 10 phut/lan (crawl + alert):
`*/10 * * * * cd /path/goldfx-pipeline && python3 pipeline.py --live && python3 telegram_alert.py`

API chay lien tuc rieng (vi du qua systemd/pm2), khong nam trong cron.

## Nguon da verify

**02/07/2026:**
- VCB  `vietcombank.com.vn/api/exchangerates?date=YYYY-MM-DD` — JSON, CO THAM SO DATE -> viet script backfill lich su ngay
- BIDV `bidv.com.vn/ServicesBIDV/ExchangeDetailServlet` — JSON; CHI tin field `currency`, nameEN sai loan
- SJC  `sjc.com.vn/GoldPrice/Services/PriceService.ashx` — JSON; endpoint cu (textContent.php) dong bang 2022, TRANH
- PNJ  `edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00` — JSON, nghin dong/chi -> x10.000 ra VND/luong

**15/07/2026:**
- TCB  `techcombank.com/content/techcombank/web/vn/en/cong-cu-tien-ich/ty-gia/_jcr_content.exchange-rates.integration.json` — JSON, inputDate ISO8601 san; 2/3 dong USD thieu askRate -> fallback askRateTM
- DOJI `giavang.doji.vn/api/giavang/?api_key=...` — XML (khong phai JSON); `<DateTime>` gia vang trong nuoc la gia tri CHET (1970) -> dung ts_crawled; **CANH BAO don vi lech giua HN (nghin/luong) va HCM (nghin/chi) trong CUNG mot feed**
- BTMC `btmc.vn/ProductHome/getGoldDate?date=DD/MM/YYYY` — JSON, gia boc trong the `<b>`, nghin dong/chi, chi chinh xac theo NGAY (khong co gio)
- ACB, Vietinbank: **CHUA lam duoc** — ca 2 deu fetch rate client-side (Next.js), khong lo endpoint qua static analysis (chi curl/grep bundle JS). Can mo DevTools > Network that de bat XHR.

## Ghi chu thiet ke

- `ts_source` vs `ts_crawled` tach rieng -> phat hien silent staleness
  (health check demo da bat dung SJC dong bang 26h).
- Dedupe bang UNIQUE(source,asset,code,branch,ts_source) -> tu do dem duoc
  tan suat cap nhat cua tung nguon (update frequency fingerprint).
- Reject KHONG drop — van luu kem notes de audit; API chi serve ok/warn.
- SQLite du cho <10 nguon x vai nam du lieu. Doi Postgres = doi 1 file storage,
  contract & adapter giu nguyen.
- ACB/Vietinbank (client-rendered): bat XHR qua DevTools roi viet adapter
  tuong tu; vAPI vnappmob co ho tro Vietinbank (`ctg`) nhung can API key
  (chua co) — khong dung duoc nhu nguon tam.

## TODO Phase 2

- [ ] Backfill lich su VCB (loop date= tu 2023)
- [x] Adapter TCB, DOJI, BTMC (15/07/2026)
- [ ] Adapter ACB, Vietinbank — can bat XHR qua DevTools thu cong (xem "Nguon da verify")
- [x] Telegram alert khi health RED (`telegram_alert.py`) — schema change van con TODO
- [x] REST API (FastAPI) doc tu SQLite (`api.py`)
- [x] Alert dedup (15/07/2026) — `alert_state.json` luu tap nguon RED da
      gui + lan gui gan nhat; chi gui lai khi tap nguon thay doi hoac sau
      6h neu van RED lien tuc
