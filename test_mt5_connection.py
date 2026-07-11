# -*- coding: utf-8 -*-
"""تست اتصال به متاتریدر ۵ و ارسال اوردر آزمایشی — قدم ۱ ساخت ربات.

چه کار می‌کند؟ شش قدم را یکی‌یکی تست می‌کند و برای هرکدام ✅ یا ❌ چاپ می‌کند:
  1) نصب بودن پکیج MetaTrader5
  2) اتصال به ترمینال متاتریدر (باید باز و لاگین باشد)
  3) دمو بودن حساب (روی حساب واقعی هیچ اوردری نمی‌فرستد!)
  4) پیدا کردن نمادهای سبد (حتی اگر بروکر پسوند داشته باشد مثل AUDJPY.r)
  5) گرفتن کندل‌های H4 و M15 از یک نماد
  6) ارسال یک «پندینگ اوردر» با حداقل حجم، خیلی دور از قیمت (هرگز اجرا نمی‌شود) و حذف فوری آن

اجرا:  python test_mt5_connection.py
پیش‌نیاز:  pip install MetaTrader5
           متاتریدر ۵ باز و روی حساب دمو لاگین باشد.
           دکمه‌ی «Algo Trading» در بالای متاتریدر روشن (سبز) باشد.
نکته: بهتر است وقتی بازار باز است تست کنی (وسط هفته)؛ آخر هفته ممکن است قدم ۶ خطای «بازار بسته» بدهد که عیب برنامه نیست.
"""

import sys

MAGIC = 777001  # شناسه‌ی اوردرهای این ربات
BASKET = ["AUDJPY", "AUDUSD", "CHFJPY", "EURCAD", "EURNZD", "GBPJPY",
          "GBPNZD", "NZDCAD", "NZDUSD", "USDCAD", "USDCHF", "XAUUSD"]

def ok(msg):   print(f"  ✅ {msg}")
def bad(msg):  print(f"  ❌ {msg}")
def step(n, title): print(f"\n—— قدم {n}: {title}")

def die(hint):
    print(f"\n🛑 تست متوقف شد. راهنمایی: {hint}")
    try:
        mt5.shutdown()
    except Exception:
        pass
    sys.exit(1)

# ---------- قدم 1: پکیج ----------
step(1, "پکیج MetaTrader5")
try:
    import MetaTrader5 as mt5
    ok(f"پکیج نصب است (نسخه {mt5.__version__})")
except ImportError:
    bad("پکیج MetaTrader5 نصب نیست.")
    print("   نصب:  pip install MetaTrader5")
    sys.exit(1)

# ---------- قدم 2: اتصال ----------
step(2, "اتصال به ترمینال متاتریدر")
if not mt5.initialize():
    bad(f"اتصال برقرار نشد: {mt5.last_error()}")
    die("متاتریدر ۵ را باز کن، روی حساب دمو لاگین کن و دوباره اجرا بگیر. اگر باز بود، یک بار ببند و باز کن.")
ti = mt5.terminal_info()
ok(f"وصل شدیم به: {ti.name} | بیلد {ti.build}")
if not ti.trade_allowed:
    bad("دکمه‌ی «Algo Trading» در متاتریدر خاموش است!")
    die("در نوار بالای متاتریدر دکمه‌ی Algo Trading را بزن تا سبز شود، بعد دوباره تست بگیر. (علت اصلی «سکوت» ربات قبلی احتمالاً همین بود)")
ok("اجازه‌ی معامله‌ی خودکار (Algo Trading) روشن است")

# ---------- قدم 3: حساب ----------
step(3, "بررسی حساب")
acc = mt5.account_info()
if acc is None:
    bad("اطلاعات حساب نیامد — لاگین نیستی؟")
    die("در متاتریدر روی حساب دمو لاگین کن.")
kinds = {0: "واقعی", 1: "دمو", 2: "مسابقه"}
kind = kinds.get(acc.trade_mode, "نامشخص")
print(f"  حساب: {acc.login} | {acc.server} | {acc.currency} | نوع: {kind} | بالانس: {acc.balance:,.2f}")
if acc.trade_mode != 1:
    bad("این حساب دمو نیست!")
    die("برای تست فقط حساب دمو. در متاتریدر: File → Open an Account → حساب دمو بساز و لاگین کن.")
ok("حساب دمو است — ادامه می‌دهیم")

# ---------- قدم 4: نمادها ----------
step(4, "پیدا کردن نمادهای سبد")
def resolve_symbol(base):
    """نماد را پیدا می‌کند حتی اگر بروکر پسوند/پیشوند داشته باشد (مثل AUDJPY.r یا AUDJPYm)."""
    info = mt5.symbol_info(base)
    if info is not None:
        return base
    cands = mt5.symbols_get(f"*{base}*")
    if cands:
        # کوتاه‌ترین اسم که شامل نماد است را انتخاب کن
        return sorted((c.name for c in cands), key=len)[0]
    return None

resolved = {}
for b in BASKET:
    name = resolve_symbol(b)
    if name is None:
        bad(f"{b}: در لیست نمادهای بروکر پیدا نشد")
        continue
    if not mt5.symbol_select(name, True):
        bad(f"{b}: پیدا شد ({name}) ولی فعال‌سازی در Market Watch نشد")
        continue
    resolved[b] = name
    tail = "" if name == b else f"  ← اسم نزد بروکر: {name}"
    ok(f"{b}{tail}")
if not resolved:
    die("هیچ نمادی پیدا نشد — سرور/بروکر را چک کن.")
print(f"  جمع: {len(resolved)} از {len(BASKET)} نماد آماده")

# ---------- قدم 5: دیتا ----------
step(5, "گرفتن کندل از بروکر")
test_sym = resolved.get("AUDJPY") or list(resolved.values())[0]
for tf_name, tf in [("H4", mt5.TIMEFRAME_H4), ("M15", mt5.TIMEFRAME_M15), ("D1", mt5.TIMEFRAME_D1), ("W1", mt5.TIMEFRAME_W1)]:
    rates = mt5.copy_rates_from_pos(test_sym, tf, 0, 10)
    if rates is None or len(rates) == 0:
        bad(f"{test_sym} {tf_name}: کندل نیامد ({mt5.last_error()})")
    else:
        import datetime as _dt
        last_t = _dt.datetime.utcfromtimestamp(int(rates[-1]['time']))
        ok(f"{test_sym} {tf_name}: {len(rates)} کندل | آخرین: {last_t} | close={rates[-1]['close']}")

# ---------- قدم 6: اوردر آزمایشی ----------
step(6, "ارسال و حذف پندینگ‌اوردر آزمایشی (بی‌خطر: ۱۰٪ دورتر از قیمت، حداقل حجم)")
si = mt5.symbol_info(test_sym)
tick = mt5.symbol_info_tick(test_sym)
if si is None or tick is None or tick.bid <= 0:
    bad(f"قیمت لحظه‌ای {test_sym} نیامد — بازار بسته است؟")
    die("وسط هفته که بازار باز است دوباره تست بگیر.")

price = round(tick.bid * 0.90, si.digits)  # بای‌لیمیت ۱۰٪ زیر قیمت — هیچ‌وقت پر نمی‌شود
req = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": test_sym,
    "volume": si.volume_min,
    "type": mt5.ORDER_TYPE_BUY_LIMIT,
    "price": price,
    "magic": MAGIC,
    "comment": "ZTEST-connection",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_RETURN,
}
res = mt5.order_send(req)
if res is None:
    bad(f"order_send جواب نداد: {mt5.last_error()}")
    die("متاتریدر را ری‌استارت کن و دوباره تست بگیر.")
if res.retcode != mt5.TRADE_RETCODE_DONE:
    bad(f"اوردر رد شد | کد: {res.retcode} | پیام: {res.comment}")
    hints = {
        10027: "Algo Trading خاموش است — دکمه‌اش را در متاتریدر بزن.",
        10018: "بازار بسته است — وسط هفته تست بگیر.",
        10015: "قیمت نامعتبر — دوباره اجرا کن.",
        10014: "حجم نامعتبر — این نماد حجم حداقلی متفاوتی دارد.",
    }
    die(hints.get(res.retcode, "کد خطا را برای من بفرست تا بگویم مشکل چیست."))
ok(f"اوردر ثبت شد! تیکت: {res.order} | {test_sym} BUY LIMIT {si.volume_min} lot @ {price}")

# حذف همان اوردر
res2 = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": res.order})
if res2 is not None and res2.retcode == mt5.TRADE_RETCODE_DONE:
    ok("و با موفقیت حذف شد — مسیر ارسال/حذف اوردر کاملاً سالم است")
else:
    bad(f"اوردر ثبت شد ولی حذف نشد (تیکت {res.order}) — دستی از متاتریدر حذفش کن.")

mt5.shutdown()
print("\n🎉 همه‌ی قدم‌ها انجام شد. اگر همه ✅ بود، زیرساخت آماده است و می‌رویم سراغ ساخت خود ربات (live_trader.py).")
