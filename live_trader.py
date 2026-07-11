# -*- coding: utf-8 -*-
"""ربات معامله‌گر لایو (نسخه ۱) — اتصال استراتژی زون عرضه/تقاضا به متاتریدر ۵.

طرز کار:
  - مغز ربات همان `backtest_one` از run_backtest.py است (یک مغز برای بک‌تست و لایو).
  - هر بار که یک کندل ۴ ساعته بسته می‌شود، دیتای بسته‌شده از متاتریدر گرفته می‌شود،
    استراتژی روی آن بازپخش می‌شود و «سفارش‌های در انتظاری که الان باید وجود داشته باشند»
    در می‌آید؛ بعد با سفارش‌های واقعی داخل متاتریدر مقایسه و همگام‌سازی می‌شود:
    سفارشِ جاافتاده گذاشته می‌شود، سفارشِ باطل‌شده حذف می‌شود.
  - حد ضرر و حد سود روی خود سفارش ست می‌شود و اجرایش با سرور بروکر است
    (حتی اگر کامپیوتر خاموش شود، استاپ و تارگت پوزیشن‌های باز سر جایشان هستند).
  - هر تصمیم در فایل لاگ روزانه ثبت می‌شود (پوشه‌ی logs) + فایل ضربان قلب (heartbeat.txt)
    که هر نیم دقیقه به‌روز می‌شود؛ اگر قدیمی بود یعنی ربات از کار افتاده — دیگر سکوت خاموش نداریم.

اجرا:  python live_trader.py     (متاتریدر ۵ باز، لاگینِ دمو، Algo Trading روشن)
توقف:  Ctrl+C
"""

import os
import sys
import math
import time as _time
import datetime as dt

import pandas as pd

import run_backtest as rb

# ================== تنظیمات ==================
BASKET = ["AUDJPY", "AUDUSD", "CHFJPY", "EURCAD", "EURNZD", "GBPJPY",
          "GBPNZD", "NZDCAD", "NZDUSD", "USDCAD", "USDCHF", "XAUUSD"]

RISK_PER_TRADE = 0.005   # ریسک هر معامله: نیم درصد از اکویتی
RESERVE = 0.15           # سرمایه‌ی رزرو (مثل بک‌تست)
MAX_OPEN_TOTAL = 5       # سقف پوزیشن باز هم‌زمان کل حساب
ENTRY_OFF = -0.50        # ورود وسط زون (مثل بک‌تست)
RR = 3.0                 # حد سود = ۳ برابر ریسک

POLL_SECONDS = 30        # هر چند ثانیه چک کند کندل جدید آمده یا نه
H4_BARS = 2000           # عمق تاریخچه برای بازپخش استراتژی
D1_BARS = 500
W1_BARS = 300

MAGIC = 777001           # امضای سفارش‌های این ربات
ALLOW_REAL = False       # قفل ایمنی: فقط حساب دمو
LOG_DIR = "logs"
# =============================================

# بازپخش لایو باید کل پنجره‌ی دیتا را ببیند (بدون برش تاریخ بک‌تست)
rb.BACKTEST_START = pd.Timestamp("2000-01-01")
rb.BACKTEST_END = None
rb.USE_M15 = False

try:
    import MetaTrader5 as mt5
except ImportError:
    print("پکیج MetaTrader5 نصب نیست:  pip install MetaTrader5")
    sys.exit(1)


# ---------------- لاگ و ضربان قلب ----------------
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg, symbol=""):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {symbol + ' | ' if symbol else ''}{msg}"
    print(line, flush=True)
    fname = os.path.join(LOG_DIR, "journal_" + dt.datetime.now().strftime("%Y%m%d") + ".txt")
    try:
        with open(fname, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def heartbeat(status="OK"):
    try:
        with open(os.path.join(LOG_DIR, "heartbeat.txt"), "w", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat()} | {status}\n")
    except Exception:
        pass


# ---------------- اتصال و ایمنی ----------------
def connect_or_die():
    if not mt5.initialize():
        log(f"🛑 اتصال به متاتریدر برقرار نشد: {mt5.last_error()} — متاتریدر ۵ را باز کن و لاگین باش.")
        sys.exit(1)
    ti = mt5.terminal_info()
    if not ti.trade_allowed:
        log("🛑 دکمه‌ی Algo Trading خاموش است! روشنش کن و دوباره اجرا بگیر.")
        mt5.shutdown(); sys.exit(1)
    acc = mt5.account_info()
    if acc is None:
        log("🛑 اطلاعات حساب نیامد — لاگین نیستی؟")
        mt5.shutdown(); sys.exit(1)
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and not ALLOW_REAL:
        log(f"🛑 حساب {acc.login} دمو نیست! این نسخه فقط روی دمو کار می‌کند (قفل ایمنی ALLOW_REAL).")
        mt5.shutdown(); sys.exit(1)
    log(f"✅ وصل شد | حساب {acc.login} ({acc.server}) | نوع: {'دمو' if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else 'واقعی'} | بالانس {acc.balance:,.2f} {acc.currency}")
    return acc


def resolve_symbol(base):
    """پیدا کردن اسم نماد نزد بروکر (با پسوند/پیشوند احتمالی) و فعال‌سازی آن."""
    if mt5.symbol_info(base) is not None:
        mt5.symbol_select(base, True)
        return base
    cands = mt5.symbols_get(f"*{base}*")
    if cands:
        name = sorted((c.name for c in cands), key=len)[0]
        mt5.symbol_select(name, True)
        return name
    return None


# ---------------- دیتا ----------------
def fetch_df(broker_name, timeframe, count):
    """کندل‌های «بسته‌شده» (کندل در حال شکل‌گیری حذف می‌شود: start_pos=1)."""
    rates = mt5.copy_rates_from_pos(broker_name, timeframe, 1, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df[["time", "open", "high", "low", "close"]].astype(
        {"open": float, "high": float, "low": float, "close": float})


def replay_state(base, broker_name):
    """بازپخش استراتژی روی تاریخچه‌ی اخیر → سفارش‌های در انتظاری که الان باید باشند."""
    h4 = fetch_df(broker_name, mt5.TIMEFRAME_H4, H4_BARS)
    d1 = fetch_df(broker_name, mt5.TIMEFRAME_D1, D1_BARS)
    w1 = fetch_df(broker_name, mt5.TIMEFRAME_W1, W1_BARS)
    if h4 is None or d1 is None or w1 is None:
        log("⚠️ دیتا از بروکر نیامد — این دور رد شد.", base)
        return None
    out = rb.backtest_one(base, h4, d1, w1, None, 0.0,
                          entry_off=ENTRY_OFF, rr=RR, m15=None, return_state=True)
    return out[6]


# ---------------- سفارش ----------------
def calc_volume(si, risk_amt, risk_dist):
    """حجم بر اساس ریسک ثابت: مبلغ ریسک ÷ ضرر هر لات در فاصله‌ی استاپ."""
    if risk_dist <= 0 or si.trade_tick_size <= 0 or si.trade_tick_value <= 0:
        return None
    loss_per_lot = risk_dist / si.trade_tick_size * si.trade_tick_value
    if loss_per_lot <= 0:
        return None
    vol = risk_amt / loss_per_lot
    step = si.volume_step or 0.01
    vol = math.floor(vol / step) * step
    vol = max(si.volume_min, min(vol, si.volume_max))
    return round(vol, 8)


def place_pending(base, broker_name, p):
    si = mt5.symbol_info(broker_name)
    tick = mt5.symbol_info_tick(broker_name)
    acc = mt5.account_info()
    if si is None or tick is None or acc is None:
        log("⚠️ اطلاعات نماد/قیمت نیامد — سفارش گذاشته نشد.", base)
        return

    entry = round(p["entry"], si.digits)
    sl = round(p["sl"], si.digits)
    tp = round(p["tp"], si.digits)

    # اعتبار قیمت: بای‌لیمیت باید زیر قیمت فعلی باشد و سل‌لیمیت بالای آن
    if p["direction"] == "BUY" and entry >= tick.ask:
        log(f"⏭️ {p['zone_id']}: قیمت از نقطه‌ی ورود خرید رد شده (ask={tick.ask} <= entry={entry}) — گذاشته نشد.", base)
        return
    if p["direction"] == "SELL" and entry <= tick.bid:
        log(f"⏭️ {p['zone_id']}: قیمت از نقطه‌ی ورود فروش رد شده (bid={tick.bid} >= entry={entry}) — گذاشته نشد.", base)
        return

    risk_amt = acc.equity * (1.0 - RESERVE) * RISK_PER_TRADE
    vol = calc_volume(si, risk_amt, abs(entry - sl))
    if vol is None:
        log(f"⚠️ {p['zone_id']}: حجم قابل محاسبه نبود — رد شد.", base)
        return

    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": broker_name,
        "volume": vol,
        "type": mt5.ORDER_TYPE_BUY_LIMIT if p["direction"] == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT,
        "price": entry, "sl": sl, "tp": tp,
        "magic": MAGIC,
        "comment": str(p["zone_id"])[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    res = mt5.order_send(req)
    if res is None:
        log(f"❌ {p['zone_id']}: order_send جواب نداد: {mt5.last_error()}", base)
        return
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"🟢 سفارش ثبت شد: {p['zone_id']} | {p['direction']} {vol} lot @ {entry} | SL={sl} TP={tp} | تیکت {res.order}", base)
    else:
        log(f"❌ سفارش رد شد: {p['zone_id']} | کد {res.retcode} | {res.comment}", base)


def cancel_order(base, o):
    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
    if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"🗑️ سفارش لغو شد (طبق قوانین استراتژی): {o.comment} | تیکت {o.ticket}", base)
    else:
        log(f"⚠️ لغو سفارش {o.ticket} نشد: {getattr(res, 'retcode', mt5.last_error())}", base)


def sync_symbol(base, broker_name):
    """همگام‌سازی سفارش‌های متاتریدر با چیزی که استراتژی می‌گوید باید باشد."""
    state = replay_state(base, broker_name)
    if state is None:
        return
    desired = {str(p["zone_id"]): p for p in state["pending"]}

    existing_orders = [o for o in (mt5.orders_get(symbol=broker_name) or ()) if o.magic == MAGIC]
    existing = {o.comment: o for o in existing_orders}

    my_positions = [p for p in (mt5.positions_get() or ()) if p.magic == MAGIC]

    # ۱) لغو سفارش‌هایی که استراتژی دیگر نمی‌خواهد
    for cm, o in existing.items():
        if cm not in desired:
            cancel_order(base, o)

    # ۲) گذاشتن سفارش‌های جاافتاده (با رعایت سقف کل پوزیشن‌ها)
    for zid, p in desired.items():
        if zid in existing:
            continue
        if len(my_positions) >= MAX_OPEN_TOTAL:
            log(f"⏸️ {zid}: سقف {MAX_OPEN_TOTAL} پوزیشن باز پر است — این دور گذاشته نشد.", base)
            continue
        place_pending(base, broker_name, p)

    npend = len(desired)
    log(f"همگام شد | سفارش موردنیاز استراتژی: {npend} | پوزیشن باز ربات (کل حساب): {len(my_positions)}", base)


# ---------------- حلقه‌ی اصلی ----------------
def main():
    log("========== شروع ربات (نسخه ۱ — دمو) ==========")
    connect_or_die()

    symbols = {}
    for b in BASKET:
        name = resolve_symbol(b)
        if name is None:
            log(f"⚠️ نماد نزد بروکر پیدا نشد و از سبد حذف شد!", b)
        else:
            symbols[b] = name
    log(f"سبد فعال: {len(symbols)} نماد | ریسک {RISK_PER_TRADE*100:.1f}% | RR={RR} | ورود {abs(ENTRY_OFF)*100:.0f}% داخل زون")

    last_bar = {b: None for b in symbols}

    # پردازش اولیه‌ی همه‌ی نمادها در شروع
    for b, name in symbols.items():
        try:
            sync_symbol(b, name)
            bar = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H4, 1, 1)
            if bar is not None and len(bar):
                last_bar[b] = int(bar[0]["time"])
        except Exception as e:
            log(f"❌ خطا در پردازش اولیه: {e}", b)

    log("منتظر کندل‌های ۴ ساعته‌ی جدید... (توقف: Ctrl+C)")
    while True:
        try:
            if mt5.terminal_info() is None:
                log("🛑 اتصال به متاتریدر قطع شد! تلاش برای اتصال دوباره...")
                heartbeat("RECONNECTING")
                mt5.shutdown()
                _time.sleep(5)
                connect_or_die()

            for b, name in symbols.items():
                bar = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H4, 1, 1)
                if bar is None or len(bar) == 0:
                    continue
                t = int(bar[0]["time"])
                if last_bar[b] is None or t > last_bar[b]:
                    last_bar[b] = t
                    log(f"کندل ۴ ساعته‌ی جدید بسته شد ({dt.datetime.utcfromtimestamp(t)}) — بازپخش استراتژی...", b)
                    sync_symbol(b, name)

            heartbeat("OK")
            _time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("توقف دستی (Ctrl+C). سفارش‌ها و پوزیشن‌ها در متاتریدر دست‌نخورده می‌مانند.")
            break
        except Exception as e:
            log(f"❌ خطای غیرمنتظره در حلقه‌ی اصلی: {e} — ربات ادامه می‌دهد.")
            heartbeat(f"ERROR: {e}")
            _time.sleep(POLL_SECONDS)

    mt5.shutdown()


if __name__ == "__main__":
    main()
