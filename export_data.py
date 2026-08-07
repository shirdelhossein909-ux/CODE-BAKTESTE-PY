# -*- coding: utf-8 -*-
"""اکسپورت خودکار دیتای متاتریدر ۵ برای بک‌تست.

برای هر نماد سبد، کندل‌های H4 و D1 و W1 را از همان بروکری که ربات رویش کار می‌کند
می‌گیرد و در پوشه‌ی «دیتا» یک فایل ZIP به اسم همان نماد می‌سازد — دقیقاً با همان
فرمتی که run_backtest.py انتظار دارد.

اجرا:  دابل‌کلیک روی export_data.bat  (یا:  python export_data.py)
پیش‌نیاز: متاتریدر ۵ باز و لاگین باشد.
"""

import os
import sys
import zipfile
import datetime as dt

import pandas as pd

# ---------------- تنظیمات ----------------
SYMBOLS = ["XAUUSD", "AUDJPY", "AUDUSD", "CHFJPY", "EURCAD", "EURNZD",
           "GBPJPY", "GBPNZD", "NZDCAD", "NZDUSD", "USDCAD", "USDCHF"]
OUT_DIR = "دیتا"          # پوشه‌ی خروجی (کنار همین فایل ساخته می‌شود)
YEARS_BACK = 6            # چند سال دیتا گرفته شود
# -----------------------------------------

try:
    import MetaTrader5 as mt5
except ImportError:
    print("پکیج MetaTrader5 نصب نیست. نصب:  pip install MetaTrader5")
    input("Enter بزن...")
    sys.exit(1)

TFS = [("240", mt5.TIMEFRAME_H4), ("1D", mt5.TIMEFRAME_D1), ("1W", mt5.TIMEFRAME_W1)]


def resolve(base):
    """اسم نماد نزد بروکر (با پسوند احتمالی) را پیدا می‌کند."""
    if mt5.symbol_info(base) is not None:
        mt5.symbol_select(base, True)
        return base
    cands = mt5.symbols_get(f"*{base}*")
    if cands:
        name = sorted((c.name for c in cands), key=len)[0]
        mt5.symbol_select(name, True)
        return name
    return None


def fetch(name, tf, start, end):
    rates = mt5.copy_rates_range(name, tf, start, end)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    out = df[["time", "open", "high", "low", "close"]].copy()
    # فرمت خروجی: date,time,open,high,low,close  (بدون سطر عنوان — مثل متاتریدر)
    out.insert(0, "date", out["time"].dt.strftime("%Y.%m.%d"))
    out["time"] = out["time"].dt.strftime("%H:%M")
    return out


def main():
    print("=" * 60)
    print(" اکسپورت دیتای متاتریدر برای بک‌تست")
    print("=" * 60)

    if not mt5.initialize():
        print(f"❌ اتصال به متاتریدر برقرار نشد: {mt5.last_error()}")
        print("   متاتریدر ۵ را باز کن و لاگین باش، بعد دوباره اجرا کن.")
        input("Enter بزن...")
        return

    acc = mt5.account_info()
    print(f"✅ وصل شد | حساب {acc.login} ({acc.server})" if acc else "✅ وصل شد")

    os.makedirs(OUT_DIR, exist_ok=True)
    end = dt.datetime.now() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=365 * YEARS_BACK)
    print(f"بازه‌ی دیتا: {start.date()} تا {end.date()}\n")

    ok = 0
    for base in SYMBOLS:
        name = resolve(base)
        if name is None:
            print(f"⚠️ {base}: نزد بروکر پیدا نشد — رد شد")
            continue

        parts = {}
        for tag, tf in TFS:
            df = fetch(name, tf, start, end)
            if df is None or df.empty:
                print(f"⚠️ {base} {tag}: دیتا نیامد")
                parts = {}
                break
            parts[tag] = df

        if not parts:
            continue

        zpath = os.path.join(OUT_DIR, f"{base}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for tag, df in parts.items():
                z.writestr(f"{base}-{tag}.csv", df.to_csv(index=False, header=False))

        n = len(parts["240"])
        first, last = parts["240"]["date"].iloc[0], parts["240"]["date"].iloc[-1]
        print(f"✅ {base}: {n:,} کندل ۴ساعته | {first} → {last} | ذخیره شد: {zpath}")
        ok += 1

    mt5.shutdown()
    print("\n" + "=" * 60)
    print(f"🎉 تمام شد — {ok} از {len(SYMBOLS)} نماد آماده شد.")
    print(f"   فایل‌ها در پوشه‌ی «{OUT_DIR}» هستند.")
    print("   حالا همین پوشه را به‌جای پوشه‌ی دیتای قبلی بگذار و بک‌تست بگیر.")
    print("=" * 60)
    input("Enter بزن...")


if __name__ == "__main__":
    main()
