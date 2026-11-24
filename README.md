<div align="center">

# 💹 goldfx-vn — Giá vàng & Tỷ giá Việt Nam

**Crawler + kiểm định + lưu trữ giá vàng và tỷ giá ngân hàng Việt Nam từ 7 nguồn chính thức,**
**kèm REST API chỉ đọc và cảnh báo Telegram khi nguồn hỏng.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-storage-003B57?logo=sqlite&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-REST-009688?logo=fastapi&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-alert-26A5E4?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

> **Lõi crawler / pipeline là Python stdlib thuần** — không cần `pip install` gì để crawl, kiểm định và lưu.
> Chỉ phần REST API mới cần `fastapi` + `uvicorn`.

---

## 🏦 Nguồn dữ liệu

| Nguồn | Loại | Định dạng | Ghi chú khi crawl |
|---|---|---|---|
| **Vietcombank** | Tỷ giá | JSON | Có tham số `date` → backfill được lịch sử |
| **BIDV** | Tỷ giá | JSON | Chỉ tin field `currency`, `nameEN` sai lẫn lộn |
| **Techcombank** | Tỷ giá | JSON | 2/3 dòng USD thiếu `askRate` → fallback `askRateTM` |
| **SJC** | Vàng | JSON | Endpoint cũ (`textContent.php`) đóng băng từ 2022 — tránh |
| **PNJ** | Vàng | JSON | Đơn vị nghìn đồng/chỉ → ×10.000 ra VND/lượng |
| **DOJI** | Vàng | **XML** | `<DateTime>` luôn là 1970 → dùng `ts_crawled`; ⚠️ HN tính nghìn/lượng, HCM tính nghìn/chỉ **trong cùng một feed** |
| **Bảo Tín Minh Châu** | Vàng | JSON | Giá bọc trong thẻ `<b>`, chỉ chính xác theo ngày |

Thêm nguồn mới = viết thêm **1 hàm adapter** theo Data Contract, không đụng phần còn lại.

---

## 🏗️ Kiến trúc

```
                ┌──────────── cron (10 phút/lần) ────────────┐
                ▼                                            ▼
          pipeline.py                                 telegram_alert.py
  fetch → lưu RAW → parse (adapters)                  đọc health → gửi Telegram
        → validate (3 tầng) → SQLite                  khi có nguồn RED (có chống spam)
                │
                ▼
           goldfx.db  ◄──────── api.py (FastAPI, chỉ đọc, chạy liên tục)
```

| File | Vai trò |
|---|---|
| `contract.py` | **Data Contract v1** — schema chuẩn mọi adapter phải theo |
| `adapters.py` | 7 adapter cho 7 nguồn ở trên |
| `validators.py` | Kiểm định **3 tầng**: schema → luật nghiệp vụ → đối chiếu chéo giữa các nguồn |
| `pipeline.py` | Điều phối + lưu payload thô + ghi SQLite |
| `health.py` | Trạng thái từng nguồn (`GRN` / `YEL` / `RED`) cho CLI và Telegram |
| `queries.py` | Truy vấn mẫu: "bán USD ở đâu cao nhất", "SJC vs PNJ"… |
| `api.py` | REST API chỉ đọc |
| `telegram_alert.py` | Cảnh báo khi nguồn hỏng, có chống gửi lặp |
| `fixtures/` | Payload **thật** chụp từ 7 nguồn — test chạy offline |
| `tests/` | pytest cho adapters / health / api / telegram_alert |

---

## 🚀 Chạy thử

```bash
git clone https://github.com/Meow1088/goldfx-vn && cd goldfx-vn

python3 pipeline.py --fixtures fixtures/   # chạy offline bằng dữ liệu mẫu
python3 health.py                          # xem sức khỏe từng nguồn
python3 queries.py                         # vài truy vấn mẫu
```

Crawl thật và mở API:

```bash
pip install -r requirements.txt            # chỉ cần cho api.py
python3 pipeline.py --live
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
```

### 🌐 REST API

| Endpoint | Trả về |
|---|---|
| `GET /fx/{code}/latest` | Tỷ giá mới nhất của một ngoại tệ ở mọi ngân hàng |
| `GET /fx/{code}/best` | Ngân hàng mua / bán tốt nhất cho ngoại tệ đó |
| `GET /gold/sjc/compare` | So sánh giá vàng SJC giữa các nguồn |
| `GET /health/status` | Trạng thái từng nguồn |

### 🔔 Cảnh báo Telegram

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
# (tùy chọn) DOJI_API_KEY — mặc định dùng key công khai trên web DOJI
python3 telegram_alert.py      # im lặng + exit 0 khi không có nguồn RED
```

Cron gợi ý:

```cron
*/10 * * * * cd /path/goldfx-vn && python3 pipeline.py --live && python3 telegram_alert.py
```

Chống spam: `alert_state.json` lưu tập nguồn RED đã báo — chỉ gửi lại khi tập nguồn đổi, hoặc sau **6 giờ** nếu vẫn RED liên tục.

---

## 🧠 Thiết kế đáng chú ý

- **Tách `ts_source` và `ts_crawled`** → bắt được nguồn "chết lặng" (vẫn trả 200 nhưng số không đổi). Bản demo đã bắt đúng SJC đứng giá 26 giờ.
- **Chống trùng bằng `UNIQUE(source, asset, code, branch, ts_source)`** → tự đếm được tần suất cập nhật thật của từng nguồn.
- **Bản ghi lỗi không bị xóa** mà lưu kèm ghi chú để kiểm tra lại; API chỉ trả bản ghi `ok` / `warn`.
- **SQLite là đủ** cho dưới 10 nguồn × vài năm dữ liệu. Đổi sang Postgres chỉ cần thay 1 file lưu trữ, contract và adapter giữ nguyên.

---

## 🧪 Kiểm thử

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -v
```

Test chạy trên payload thật trong `fixtures/`, không cần mạng.

## 🗺️ Lộ trình

- [x] 7 adapter: VCB, BIDV, TCB, SJC, PNJ, DOJI, BTMC
- [x] REST API (FastAPI) đọc từ SQLite
- [x] Cảnh báo Telegram + chống gửi lặp
- [ ] Backfill lịch sử tỷ giá VCB từ 2023
- [ ] ACB, VietinBank — hai nguồn này render phía client, cần bắt XHR qua DevTools
- [ ] Cảnh báo khi nguồn đổi schema

---

## 📝 Giấy phép

MIT — xem [LICENSE](LICENSE).

> Dữ liệu thuộc về các ngân hàng / doanh nghiệp vàng tương ứng. Repo chỉ đọc các endpoint công khai mà chính website của họ dùng; hãy crawl với tần suất vừa phải.
