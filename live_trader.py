# -*- coding: utf-8 -*-
"""ربات معامله‌گر لایو (نسخه ۲) — استراتژی زون عرضه/تقاضا روی متاتریدر ۵.

ویژگی‌ها:
  - مغز ربات همان backtest_one از run_backtest.py است (یک مغز برای بک‌تست و لایو).
  - سفارش‌ها «از قبل» گذاشته می‌شوند: زونی که فیلترهایش سبز است، سفارش لیمیتش داخل
    متاتریدر آماده است؛ اگر وسط کندل قیمت برسد، سرور بروکر همان لحظه پر می‌کند
    (جا ماندن به‌خاطر انتظار برای کلوز کندل وجود ندارد).
  - حد ضرر و حد سود روی خود سفارش ست می‌شود — اجرا با سرور بروکر است، حتی اگر
    کامپیوتر خاموش شود پوزیشن‌ها بی‌محافظ نمی‌مانند.
  - فقط روی نمادهای سبد انتخابی کار می‌کند و فقط به سفارش‌های خودش (امضای MAGIC)
    دست می‌زند — با معاملات دستی یا ربات‌های دیگر هیچ کاری ندارد.
  - لاگ کامل فارسی: دلیل هر سفارش، دلیل سفارش نگذاشتن، پر شدن، بسته شدن با سود/ضرر،
    قطع و وصل ارتباط — هم در CMD هم در فایل (پوشه‌ی logs کنار همین فایل).
  - ضدضربه: قطع ارتباط → اخطار + تلاش دوباره هر چند ثانیه تا وصل شود؛ هیچ خطایی
    ربات را ساکت نمی‌کند؛ فایل ضربان قلب (logs/heartbeat.txt) هر دور به‌روز می‌شود.

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
# فقط همین نمادها — سبد انتخابی. ربات سراغ هیچ نماد دیگری نمی‌رود.
BASKET = ["AUDJPY", "AUDUSD", "CHFJPY", "EURCAD", "EURNZD", "GBPJPY",
          "GBPNZD", "NZDCAD", "NZDUSD", "USDCAD", "USDCHF", "XAUUSD"]

RISK_PER_TRADE = 0.005    # ریسک هر معامله: نیم درصد از اکویتی
RESERVE = 0.15            # سرمایه‌ی رزرو (مثل بک‌تست)
MAX_OPEN_TOTAL = 5        # سقف تریدهای باز هم‌زمان کل حساب — پر شود، اوردرهای در انتظار موقتاً جمع می‌شوند
MAX_PENDING_TOTAL = 8     # سقف کل اوردرهای در انتظار روی کل حساب (هر نماد حداکثر ۳ — در خود موتور)
MAX_RISK_HARD_CAP = 0.01  # قفل ایمنی: ریسک واقعی هیچ معامله‌ای از ۱٪ اکویتی بیشتر نشود
ENTRY_OFF = -0.50         # ورود وسط زون (مثل بک‌تست)
RR = 3.0                  # حد سود = ۳ برابر ریسک

POLL_SECONDS = 30         # هر چند ثانیه وضعیت را چک کند
RECONNECT_SECONDS = 5     # فاصله‌ی تلاش‌های اتصال دوباره
H4_BARS = 2000            # عمق تاریخچه برای بازپخش استراتژی
D1_BARS = 500
W1_BARS = 300

MAGIC = 777001            # امضای سفارش‌های این ربات
ALLOW_REAL = False        # قفل ایمنی: فقط حساب دمو
LOG_DIR = "logs"          # پوشه‌ی لاگ، کنار همین فایل ساخته می‌شود
# =============================================

# بازپخش لایو باید کل پنجره‌ی دیتا را ببیند (بدون برش تاریخ بک‌تست)
rb.BACKTEST_START = pd.Timestamp("2000-01-01")
rb.BACKTEST_END = None
rb.USE_M15 = False

try:
    import MetaTrader5 as mt5
except ImportError:
    print("پکیج MetaTrader5 نصب نیست. نصب:  pip install MetaTrader5")
    sys.exit(1)


# ---------------- لاگ و ضربان قلب ----------------
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg, symbol=""):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {symbol + ' | ' if symbol else ''}{msg}"
    print(line, flush=True)
    fname = os.path.join(LOG_DIR, "گزارش_" + dt.datetime.now().strftime("%Y%m%d") + ".txt")
    try:
        with open(fname, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def heartbeat(status="سالم"):
    try:
        with open(os.path.join(LOG_DIR, "heartbeat.txt"), "w", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | وضعیت: {status}\n")
    except Exception:
        pass


# ---------------- اتصال ضدضربه ----------------
def connect_with_retry():
    """آن‌قدر تلاش می‌کند تا وصل شود؛ هر مشکل را با زبان ساده گزارش می‌دهد."""
    attempt = 0
    while True:
        attempt += 1
        if not mt5.initialize():
            log(f"⛔ اتصال به متاتریدر برقرار نشد (تلاش {attempt}): {mt5.last_error()} — "
                f"متاتریدر ۵ باید باز و لاگین باشد. {RECONNECT_SECONDS} ثانیه دیگر دوباره تلاش می‌کنم...")
            heartbeat("قطع — در حال تلاش برای اتصال")
            _time.sleep(RECONNECT_SECONDS)
            continue

        ti = mt5.terminal_info()
        if ti is None or not ti.trade_allowed:
            log(f"⛔ دکمه‌ی Algo Trading در متاتریدر خاموش است! روشنش کن (تلاش {attempt}). "
                f"{RECONNECT_SECONDS} ثانیه دیگر دوباره چک می‌کنم...")
            heartbeat("منتظر روشن شدن Algo Trading")
            mt5.shutdown()
            _time.sleep(RECONNECT_SECONDS)
            continue

        acc = mt5.account_info()
        if acc is None:
            log(f"⛔ اطلاعات حساب نیامد — در متاتریدر لاگین نیستی؟ (تلاش {attempt})")
            heartbeat("منتظر لاگین حساب")
            mt5.shutdown()
            _time.sleep(RECONNECT_SECONDS)
            continue

        if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and not ALLOW_REAL:
            log(f"🛑 حساب {acc.login} دمو نیست! این نسخه فقط روی دمو کار می‌کند. ربات خاموش شد.")
            mt5.shutdown()
            sys.exit(1)

        log(f"✅ اتصال برقرار شد | حساب {acc.login} ({acc.server}) | "
            f"{'دمو' if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else 'واقعی'} | "
            f"موجودی {acc.balance:,.2f} {acc.currency}")
        heartbeat("سالم")
        return acc


def ensure_connected():
    """اگر وسط کار ارتباط قطع شد: اخطار بده و تا وصل شدن تلاش کن."""
    ti = mt5.terminal_info()
    if ti is None:
        log("⚠️ ارتباط با متاتریدر قطع شد! تلاش خودکار برای اتصال دوباره شروع شد...")
        heartbeat("قطع — در حال تلاش برای اتصال")
        try:
            mt5.shutdown()
        except Exception:
            pass
        connect_with_retry()
        log("🔄 ارتباط دوباره برقرار شد — ادامه می‌دهیم.")


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


# ---------------- دیتا و بازپخش استراتژی ----------------
def fetch_df(broker_name, timeframe, count):
    """فقط کندل‌های بسته‌شده (کندل در حال شکل‌گیری حذف می‌شود)."""
    rates = mt5.copy_rates_from_pos(broker_name, timeframe, 1, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df[["time", "open", "high", "low", "close"]].astype(
        {"open": float, "high": float, "low": float, "close": float})


def replay_state(base, broker_name):
    """بازپخش استراتژی روی تاریخچه‌ی بروکر → سفارش‌هایی که همین الان باید وجود داشته باشند."""
    h4 = fetch_df(broker_name, mt5.TIMEFRAME_H4, H4_BARS)
    d1 = fetch_df(broker_name, mt5.TIMEFRAME_D1, D1_BARS)
    w1 = fetch_df(broker_name, mt5.TIMEFRAME_W1, W1_BARS)
    if h4 is None or d1 is None or w1 is None:
        log("⚠️ دیتا از بروکر نیامد — این دور بررسی نشد.", base)
        return None
    out = rb.backtest_one(base, h4, d1, w1, None, 0.0,
                          entry_off=ENTRY_OFF, rr=RR, m15=None, return_state=True)
    return out[6]


# ---------------- سفارش‌گذاری ----------------
def calc_volume(broker_name, si, direction, entry, sl, risk_amt, equity):
    """حجم از روی ریسک ثابت — محاسبه‌ی ضرر با تابع رسمی خود متاتریدر (order_calc_profit)
    که برای هر نمادی (طلا، ین، ...) مشخصات قرارداد همان بروکر را دقیق حساب می‌کند.
    + قفل ایمنی دوبل: ریسک واقعی حجم نهایی دوباره چک می‌شود."""
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    loss_1lot = mt5.order_calc_profit(order_type, broker_name, 1.0, entry, sl)
    if loss_1lot is None or loss_1lot >= 0:
        return None, "متاتریدر ضررِ یک لات را حساب نکرد"
    loss_1lot = abs(loss_1lot)

    vol = risk_amt / loss_1lot
    step = si.volume_step or 0.01
    vol = math.floor(vol / step) * step
    if vol < si.volume_min:
        return None, f"حجم لازم ({vol}) از حداقل مجاز نماد ({si.volume_min}) کمتر است"
    vol = min(vol, si.volume_max)
    vol = round(vol, 8)

    # قفل ایمنی دوبل: ریسک واقعی این حجم چقدر است؟
    real_loss = mt5.order_calc_profit(order_type, broker_name, vol, entry, sl)
    if real_loss is None:
        return None, "چک نهایی ریسک ممکن نشد"
    real_loss = abs(real_loss)
    if real_loss > risk_amt * 1.2:
        return None, f"ریسک واقعی ({real_loss:,.0f}$) از حد مجاز ({risk_amt:,.0f}$) بیشتر شد — سفارش رد شد"
    if real_loss > equity * MAX_RISK_HARD_CAP:
        return None, f"ریسک واقعی ({real_loss:,.0f}$) از قفل ایمنی {MAX_RISK_HARD_CAP*100:g}٪ حساب بیشتر است — سفارش رد شد"
    return vol, f"ریسک واقعی {real_loss:,.0f}$"


def place_pending(base, broker_name, p):
    si = mt5.symbol_info(broker_name)
    tick = mt5.symbol_info_tick(broker_name)
    acc = mt5.account_info()
    if si is None or tick is None or acc is None or tick.bid <= 0:
        log(f"⚠️ زون {p['zone_id']}: قیمت/مشخصات نماد نیامد — سفارش گذاشته نشد (بازار بسته؟).", base)
        return

    entry = round(p["entry"], si.digits)
    sl = round(p["sl"], si.digits)
    tp = round(p["tp"], si.digits)

    if p["direction"] == "BUY" and entry >= tick.ask:
        log(f"⏭️ زون {p['zone_id']}: قیمت الان ({tick.ask}) پایین‌تر از نقطه‌ی ورود خرید ({entry}) است — سفارش معنا ندارد.", base)
        return
    if p["direction"] == "SELL" and entry <= tick.bid:
        log(f"⏭️ زون {p['zone_id']}: قیمت الان ({tick.bid}) بالاتر از نقطه‌ی ورود فروش ({entry}) است — سفارش معنا ندارد.", base)
        return

    risk_amt = acc.equity * (1.0 - RESERVE) * RISK_PER_TRADE
    vol, vol_msg = calc_volume(broker_name, si, p["direction"], entry, sl, risk_amt, acc.equity)
    if vol is None:
        log(f"⚠️ زون {p['zone_id']}: سفارش گذاشته نشد — {vol_msg}", base)
        return False

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
    side = "خرید" if p["direction"] == "BUY" else "فروش"
    if res is None:
        log(f"❌ زون {p['zone_id']}: پاسخ ارسال سفارش نیامد: {mt5.last_error()}", base)
        return False
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"🟢 سفارش {side} گذاشته شد | زون {p['zone_id']} | حجم {vol} لات ({vol_msg}) | "
            f"ورود {entry} | استاپ {sl} | تارگت {tp} | تیکت {res.order}", base)
        return True
    elif res.retcode == 10018:
        log(f"🌙 بازار بسته است — سفارش زون {p['zone_id']} بعداً گذاشته می‌شود.", base)
    else:
        log(f"❌ سفارش زون {p['zone_id']} رد شد | کد {res.retcode} | {res.comment}", base)
    return False


def cancel_order(base, o, why="طبق قوانین استراتژی دیگر معتبر نیست"):
    res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
    if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"🗑️ سفارش لغو شد | زون {o.comment} | دلیل: {why}", base)
    else:
        log(f"⚠️ لغو سفارش {o.ticket} (زون {o.comment}) موفق نبود: {getattr(res, 'retcode', mt5.last_error())}", base)


def sync_all(symbols, reason_txt="بازبینی"):
    """بازپخش استراتژی روی همه‌ی نمادها + توزیع «عادلانه»‌ی سهمیه‌ی اوردرها:
    دور اول: به هر نماد یک اوردر (بهترین زونش)؛ بعد دور دوم و سوم —
    تا سقف کل (MAX_PENDING_TOTAL). این‌طوری هیچ نمادی همیشه بی‌سهم نمی‌ماند."""

    # ۱) خواسته‌های استراتژی برای هر نماد (به ترتیب اولویت خود نماد)
    all_wanted = {}
    notes = {}
    for b, name in symbols.items():
        try:
            st = replay_state(b, name)
        except Exception as e:
            log(f"❌ خطا در بازپخش استراتژی: {e}", b)
            st = None
        if st is None:
            continue
        all_wanted[b] = list(st["pending"]) + list(st.get("armed", []))
        notes[b] = st.get("فیلتر_توضیح", "")

    # ۲) سهمیه‌بندی دور به دور (round-robin) تا سقف کل
    alloc = {}
    total = 0
    for r in range(3):  # سقف هر نماد ۳ اوردر
        for b in symbols:
            lst = all_wanted.get(b, [])
            if len(lst) > r and total < MAX_PENDING_TOTAL:
                alloc.setdefault(b, {})[str(lst[r]["zone_id"])] = lst[r]
                total += 1

    # ۳) همگام‌سازی هر نماد با سهمیه‌اش
    my_positions = [p for p in (mt5.positions_get() or ()) if p.magic == MAGIC]
    for b, name in symbols.items():
        desired = alloc.get(b, {})
        existing = {o.comment: o for o in (mt5.orders_get(symbol=name) or ()) if o.magic == MAGIC}

        for cm, o in existing.items():
            if cm not in desired:
                cancel_order(b, o, why="طبق قوانین استراتژی یا سهمیه‌بندی عادلانه، دیگر در لیست نیست")

        placed_something = False
        for zid, p in desired.items():
            if zid in existing:
                continue
            if len(my_positions) >= MAX_OPEN_TOTAL:
                log(f"⏸️ زون {zid}: سقف {MAX_OPEN_TOTAL} ترید باز حساب پر است — فعلاً سفارش جدید نمی‌گذارم.", b)
                continue
            if place_pending(b, name, p):
                placed_something = True

        if not all_wanted.get(b):
            log(f"معامله‌ای لازم نیست. دلیل: یا زون تازه‌ای نزدیک قیمت نیست، یا فیلترها اجازه نمی‌دهند ({notes.get(b, '')})", b)
        elif desired and not placed_something and all(z in existing for z in desired):
            log(f"وضعیت بدون تغییر | اوردرهای فعال: {len(existing)}", b)

    log(f"همگام‌سازی کامل شد ({reason_txt}) | اوردرهای تخصیص‌یافته: {total} از سقف {MAX_PENDING_TOTAL}")


# ---------------- سقف تریدهای باز: پر شد → اوردرها موقتاً جمع می‌شوند ----------------
_cap_active = False

def enforce_open_cap(symbols_rev):
    """اگر تعداد تریدهای باز به سقف رسید، همه‌ی اوردرهای در انتظار جمع می‌شوند؛
    وقتی دوباره زیر سقف آمد، اعلام می‌کند تا اوردرها دوباره چیده شوند."""
    global _cap_active
    my_open = [p for p in (mt5.positions_get() or ()) if p.magic == MAGIC]
    my_orders = [o for o in (mt5.orders_get() or ()) if o.magic == MAGIC]

    if len(my_open) >= MAX_OPEN_TOTAL:
        if my_orders:
            log(f"🚧 سقف {MAX_OPEN_TOTAL} ترید باز پر شد — {len(my_orders)} اوردر در انتظار موقتاً جمع می‌شود.")
            for o in my_orders:
                cancel_order(symbols_rev.get(o.symbol, o.symbol), o,
                             why=f"سقف {MAX_OPEN_TOTAL} ترید باز پر است (بعداً دوباره چیده می‌شود)")
        _cap_active = True
        return "capped"

    if _cap_active:
        _cap_active = False
        log(f"✅ تعداد تریدهای باز زیر {MAX_OPEN_TOTAL} برگشت — اوردرها دوباره چیده می‌شوند.")
        return "resync"
    return "ok"


# ---------------- رصد پر شدن و بسته شدن معاملات ----------------
_prev_positions = {}

def track_positions(symbols_rev):
    """پر شدن سفارش‌ها و بسته شدن پوزیشن‌ها را کشف و با دلیل لاگ می‌کند."""
    global _prev_positions
    cur = {p.ticket: p for p in (mt5.positions_get() or ()) if p.magic == MAGIC}

    # پوزیشن‌های تازه = سفارشی پر شده
    for tk, p in cur.items():
        if tk not in _prev_positions:
            base = symbols_rev.get(p.symbol, p.symbol)
            side = "خرید" if p.type == mt5.POSITION_TYPE_BUY else "فروش"
            log(f"🎯 سفارش پر شد! پوزیشن {side} باز شد | زون {p.comment} | حجم {p.volume} لات | "
                f"قیمت ورود {p.price_open} | استاپ {p.sl} | تارگت {p.tp}", base)

    # پوزیشن‌های حذف‌شده = معامله بسته شده
    for tk, p in _prev_positions.items():
        if tk not in cur:
            base = symbols_rev.get(p.symbol, p.symbol)
            profit_txt, why = "", "بسته شد"
            try:
                frm = dt.datetime.now() - dt.timedelta(days=7)
                deals = mt5.history_deals_get(frm, dt.datetime.now() + dt.timedelta(days=1), position=tk)
                if deals:
                    outs = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
                    profit = sum(d.profit + d.swap + d.commission for d in outs)
                    profit_txt = f" | نتیجه: {'سود' if profit >= 0 else 'ضرر'} {abs(profit):,.2f} دلار"
                    if outs:
                        r = outs[-1].reason
                        if r == mt5.DEAL_REASON_SL: why = "حد ضرر خورد"
                        elif r == mt5.DEAL_REASON_TP: why = "حد سود خورد ✨"
            except Exception:
                pass
            log(f"🏁 معامله بسته شد ({why}) | زون {p.comment}{profit_txt}", base)

    _prev_positions = cur


# ---------------- حلقه‌ی اصلی ----------------
def main():
    log("========== شروع ربات (نسخه ۲ — دمو) ==========")
    log(f"سبد انتخابی ({len(BASKET)} نماد): {', '.join(BASKET)} — ربات فقط روی همین‌ها کار می‌کند.")
    connect_with_retry()

    symbols = {}
    for b in BASKET:
        name = resolve_symbol(b)
        if name is None:
            log("⚠️ این نماد نزد بروکر پیدا نشد و کنار گذاشته شد!", b)
        else:
            symbols[b] = name
            if name != b:
                log(f"اسم نماد نزد بروکر: {name}", b)
    symbols_rev = {v: k for k, v in symbols.items()}
    log(f"آماده | {len(symbols)} نماد فعال | ریسک هر معامله {RISK_PER_TRADE*100:.1f}٪ | "
        f"حد سود {RR:g} برابر ریسک | ورود {abs(ENTRY_OFF)*100:.0f}٪ داخل زون | سقف {MAX_OPEN_TOTAL} پوزیشن")

    last_bar = {b: None for b in symbols}

    sync_all(symbols, "شروع ربات")
    for b, name in symbols.items():
        try:
            bar = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H4, 1, 1)
            if bar is not None and len(bar):
                last_bar[b] = int(bar[0]["time"])
        except Exception as e:
            log(f"❌ خطا در بررسی اولیه: {e}", b)

    log("در حال کار... با هر کندل ۴ ساعته‌ی جدید همه‌چیز به‌روز می‌شود. (توقف: Ctrl+C)")
    while True:
        try:
            ensure_connected()

            cap_state = enforce_open_cap(symbols_rev)
            if cap_state == "resync":
                sync_all(symbols, "آزاد شدن سقف تریدهای باز")

            # کندل ۴ ساعته‌ی جدید در هر نمادی → یک همگام‌سازی کامل و عادلانه برای همه
            new_candle = []
            for b, name in symbols.items():
                try:
                    bar = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H4, 1, 1)
                    if bar is None or len(bar) == 0:
                        continue
                    t = int(bar[0]["time"])
                    if last_bar[b] is None or t > last_bar[b]:
                        last_bar[b] = t
                        new_candle.append(b)
                except Exception as e:
                    log(f"❌ خطا در چک کندل این نماد: {e}", b)
            if new_candle:
                log(f"کندل ۴ ساعته‌ی جدید بسته شد ({', '.join(new_candle)}) — بررسی دوباره‌ی همه‌ی زون‌ها و فیلترها...")
                sync_all(symbols, "کندل جدید")

            track_positions(symbols_rev)
            heartbeat("سالم")
            _time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("⏹️ توقف دستی (Ctrl+C). سفارش‌ها و پوزیشن‌ها داخل متاتریدر دست‌نخورده می‌مانند "
                "(استاپ و تارگت روی خود سفارش‌هاست و سرور بروکر اجرایشان می‌کند).")
            break
        except Exception as e:
            log(f"❌ خطای غیرمنتظره: {e} — ربات خاموش نمی‌شود و ادامه می‌دهد.")
            heartbeat(f"خطا: {e}")
            _time.sleep(POLL_SECONDS)

    mt5.shutdown()


if __name__ == "__main__":
    main()
