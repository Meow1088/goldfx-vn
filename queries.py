"""Vai query mau — chinh la logic man hinh app sau nay.
python3 queries.py
"""
import sqlite3
from pathlib import Path

con = sqlite3.connect(Path(__file__).parent / "goldfx.db")

print("== Ban USD o dau duoc gia cao nhat (buy_transfer) ==")
for r in con.execute("""
    SELECT source, buy_transfer, ts_source FROM quotes
    WHERE asset='fx' AND code='USD' AND validation IN ('ok','warn')
      AND buy_transfer IS NOT NULL
      AND ts_source=(SELECT MAX(ts_source) FROM quotes q2
                     WHERE q2.source=quotes.source AND q2.code='USD'
                       AND q2.validation IN ('ok','warn'))
    ORDER BY buy_transfer DESC"""):
    print(f"  {r[0]:5s} mua vao {r[1]:,.0f}  ({r[2]})")

print("\n== Mua USD o dau re nhat (sell) ==")
for r in con.execute("""
    SELECT source, sell, ts_source FROM quotes
    WHERE asset='fx' AND code='USD' AND validation IN ('ok','warn')
      AND sell IS NOT NULL
      AND ts_source=(SELECT MAX(ts_source) FROM quotes q2
                     WHERE q2.source=quotes.source AND q2.code='USD'
                       AND q2.validation IN ('ok','warn'))
    ORDER BY sell ASC"""):
    print(f"  {r[0]:5s} ban ra  {r[1]:,.0f}  ({r[2]})")

print("\n== Vang mieng SJC: SJC niem yet vs PNJ niem yet ==")
for r in con.execute("""
    SELECT source, code, branch, buy_cash, sell, validation, notes FROM quotes
    WHERE asset='gold' AND code IN ('SJC_BAR','SJC')
      AND branch IN ('Hồ Chí Minh','hochiminh')
      AND validation IN ('ok','warn')"""):
    print(f"  {r[0]:4s} {r[1]:8s} mua {r[3]:,.0f} / ban {r[4]:,.0f}"
          f"  [{r[5]}] {r[6]}")
con.close()
