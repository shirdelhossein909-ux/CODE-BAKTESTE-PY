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
import json
import time as _time
import datetime as dt
import urllib.request

import pandas as pd

import run_backtest as rb

# ================== تنظیمات ==================
# فقط همین نمادها — سبد انتخابی. ربات سراغ هیچ نماد دیگری نمی‌رود.
BASKET = ["XAUUSD", "AUDJPY", "AUDUSD", "CHFJPY", "EURCAD", "EURNZD",
          "GBPJPY", "GBPNZD", "NZDCAD", "NZDUSD", "USDCAD", "USDCHF"]

RISK_PER_TRADE = 0.005    # ریسک هر معامله: نیم درصد از اکویتی
RESERVE = 0.15            # سرمایه‌ی رزرو (مثل بک‌تست)
MAX_OPEN_TOTAL = 8        # سقف تریدهای باز هم‌زمان کل حساب — پر شود، اوردرهای در انتظار موقتاً جمع می‌شوند
MAX_PENDING_TOTAL = 8     # سقف کل اوردرهای در انتظار روی کل حساب (هر نماد حداکثر ۳)
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

# --- خبررسانی به پیام‌رسان «بله» ---
BALE_TOKEN = ""           # توکن رباتی که در بله ساختی (خالی = خبررسانی خاموش)
BALE_CHAT_ID = ""         # خالی بگذار تا خودش پیدا کند (فقط اول یک پیام به ربات بله‌ات بده)
DAILY_REPORT_HOUR = 12    # ساعت ارسال گزارش‌های روزانه/هفتگی/ماهانه (به وقت VPS)
START_BALANCE = 100000.0  # سرمایه‌ی اولیه — برای محاسبه‌ی «سود کل حساب از شروع» (روی حساب جدید عوضش کن)
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

def log(msg, symbol="", bale=True):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {symbol + ' | ' if symbol else ''}{msg}"
    print(line, flush=True)
    fname = os.path.join(LOG_DIR, "گزارش_" + dt.datetime.now().strftime("%Y%m%d") + ".txt")
    try:
        with open(fname, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # خط‌های لاگ به بله هم فرستاده می‌شوند (مگر آن‌هایی که در پیام ترکیبی می‌روند)
    if bale:
        bale_send(line)


# ---------------- خبررسانی به بله ----------------
from collections import deque

_bale_chat_id = None
_bale_fail_logged = False
_bale_queue = deque(maxlen=500)  # پیام‌های نرفته نگه داشته می‌شوند تا ارتباط برگردد

def _bale_detect_chat():
    """اگر چت‌آیدی تنظیم نشده باشد، از آخرین پیامی که به ربات بله داده‌ای پیدایش می‌کند."""
    try:
        with urllib.request.urlopen(
                f"https://tapi.bale.ai/bot{BALE_TOKEN}/getUpdates", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        for u in reversed(data.get("result", [])):
            chat = (u.get("message") or {}).get("chat") or {}
            if chat.get("id"):
                print(f"[بله] چت‌آیدی شناسایی شد: {chat['id']} — برای اطمینان همین را در BALE_CHAT_ID بگذار.")
                return str(chat["id"])
        print("[بله] هنوز پیامی به ربات بله‌ات نداده‌ای — اول در بله به رباتت «سلام» بفرست.")
    except Exception as e:
        print(f"[بله] شناسایی چت‌آیدی ناموفق: {e}")
    return None


def bale_send(text):
    """پیام را در صف می‌گذارد و تلاش می‌کند صف را بفرستد؛ نرفته‌ها گم نمی‌شوند."""
    if not BALE_TOKEN:
        return
    _bale_queue.append(text)
    bale_flush()


def bale_flush():
    """ارسال پیام‌های مانده در صف، به ترتیب؛ اگر ارتباط نبود، صف می‌ماند برای بعد."""
    global _bale_chat_id, _bale_fail_logged
    if not BALE_TOKEN or not _bale_queue:
        return
    if _bale_chat_id is None:
        _bale_chat_id = BALE_CHAT_ID or _bale_detect_chat()
    if not _bale_chat_id:
        return
    while _bale_queue:
        txt = _bale_queue[0]
        try:
            data = json.dumps({"chat_id": _bale_chat_id, "text": txt}).encode("utf-8")
            req = urllib.request.Request(
                f"https://tapi.bale.ai/bot{BALE_TOKEN}/sendMessage",
                data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            _bale_queue.popleft()
            if _bale_fail_logged:
                _bale_fail_logged = False
                print("[بله] ارتباط با بله برگشت — پیام‌های مانده ارسال شدند.")
        except Exception as e:
            if not _bale_fail_logged:
                _bale_fail_logged = True
                print(f"[بله] ارسال فعلاً ناموفق ({e}) — {len(_bale_queue)} پیام در صف می‌ماند و بعداً می‌رود.")
            break

def heartbeat(status="سالم"):
    try:
        with open(os.path.join(LOG_DIR, "heartbeat.txt"), "w", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | وضعیت: {status}\n")
    except Exception:
        pass


# ---------------- اتصال ضدضربه ----------------
def connect_with_retry(bale_notify=True):
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
            f"موجودی {acc.balance:,.2f} {acc.currency}", bale=bale_notify)
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
    """بازپخش استراتژی روی همه‌ی نمادها + سهمیه‌بندی منصفانه‌ی اوردرها:
    دور اول به هر نماد یک اوردر (بهترین زونش)، بعد دور دوم و سوم —
    تا سقف کل (MAX_PENDING_TOTAL). طبق بک‌تست: هر چارت تا ۳، سقف کل ۸."""

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

    # ۲) سهمیه‌بندی منصفانه (طبق نتیجه‌ی بک‌تست «هر چارت ۳ + سقف ۸»):
    # دور اول به هر نماد یک اوردر، بعد دور دوم و سوم — تا سقف کل
    alloc = {}
    total = 0
    for r in range(3):  # حداکثر ۳ اوردر برای هر نماد
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


# ---------------- سلامت‌سنجی و اعلام وضعیت ----------------
def console(msg):
    """چاپ فقط در CMD (بدون نوشتن در فایل — که فایل لاگ شلوغ نشود)."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def health_check():
    """همه‌ی پیش‌نیازها را می‌سنجد؛ لیست مشکلات را برمی‌گرداند (خالی = همه‌چیز سالم)."""
    ti = mt5.terminal_info()
    if ti is None:
        return None  # اتصال به خود متاتریدر قطع است — ensure_connected حلش می‌کند
    problems = []
    if not ti.connected:
        problems.append("متاتریدر به سرور بروکر وصل نیست (اینترنت یا سرور بروکر قطع است)!")
    if not ti.trade_allowed:
        problems.append("دکمه‌ی Algo Trading خاموش شده! تا روشنش نکنی هیچ سفارشی ارسال نمی‌شود!")
    if mt5.account_info() is None:
        problems.append("اطلاعات حساب در دسترس نیست — لاگین حساب قطع شده؟")
    return problems


_status_cycle = 0

def report_status():
    """هر ۳۰ ثانیه در CMD اعلام سلامت می‌کند؛ هر ~۵ دقیقه یک بار هم در فایل لاگ."""
    global _status_cycle
    try:
        n_orders = len([o for o in (mt5.orders_get() or ()) if o.magic == MAGIC])
        n_open = len([p for p in (mt5.positions_get() or ()) if p.magic == MAGIC])
        msg = (f"🟢 ربات در حال اجراست | همه‌چیز سالم است | "
               f"اوردرهای در انتظار: {n_orders} | تریدهای باز: {n_open}")
        console(msg)
        _status_cycle += 1
        if _status_cycle >= 10:
            _status_cycle = 0
            log(msg)
    except Exception:
        pass


# ---------------- گزارش روزانه‌ی درصدی ----------------
_daily_file = os.path.join(LOG_DIR, "last_daily.txt")

def _pct_txt(pct):
    if pct > 0.005:
        return f"{pct:+.2f}٪ در سود"
    if pct < -0.005:
        return f"{pct:+.2f}٪ در ضرر"
    return "سربه‌سر (0.0٪)"


def daily_report(symbols_rev):
    """وضعیت همه‌ی تریدهای باز به «درصدِ حساب» + برایند کل — در یک پیام."""
    acc = mt5.account_info()
    if acc is None or acc.balance <= 0:
        return
    poss = [p for p in (mt5.positions_get() or ()) if p.magic == MAGIC]
    lines = ["📊 گزارش روزانه‌ی حساب"]

    if poss:
        for p in poss:
            b = symbols_rev.get(p.symbol, p.symbol)
            side = "خرید" if p.type == mt5.POSITION_TYPE_BUY else "فروش"
            pct = (p.profit + p.swap) / acc.balance * 100.0
            lines.append(f"{b} ({side}): {_pct_txt(pct)}")
    else:
        lines.append("هیچ ترید بازی نیست.")

    total_open = (acc.equity - acc.balance) / acc.balance * 100.0
    lines.append(f"— برایند تریدهای باز: {_pct_txt(total_open)}")

    # معاملات بسته‌شده‌ی ۲۴ ساعت اخیر
    try:
        frm = dt.datetime.now() - dt.timedelta(days=1)
        deals = mt5.history_deals_get(frm, dt.datetime.now() + dt.timedelta(days=1)) or ()
        outs = [d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT]
        if outs:
            pnl = sum(d.profit + d.swap + d.commission for d in outs)
            lines.append(f"— بسته‌شده‌های ۲۴ ساعت اخیر: {len(outs)} معامله ({_pct_txt(pnl / acc.balance * 100.0)})")
    except Exception:
        pass

    n_orders = len([o for o in (mt5.orders_get() or ()) if o.magic == MAGIC])
    lines.append(f"— اوردرهای در انتظار: {n_orders}")
    lines.append(f"— بالانس: {acc.balance:,.0f} | اکویتی: {acc.equity:,.0f} {acc.currency}")
    log("\n".join(lines))


def _marker_differs(fname, key):
    """جلوگیری از ارسال تکراری گزارش‌ها (حتی بعد از ری‌استارت)."""
    path = os.path.join(LOG_DIR, fname)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read().strip() == key:
                return False
    except Exception:
        pass
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return True


def period_report(symbols_rev, since, title):
    """همه‌ی معاملات بسته‌شده‌ی یک دوره در یک پیام: نماد، تاریخ، خرید/فروش،
    نتیجه (حد سود/حد ضرر)، درصد سود/ضرر — و در آخر برایند دوره و کل حساب."""
    acc = mt5.account_info()
    if acc is None or acc.balance <= 0:
        return
    try:
        deals = mt5.history_deals_get(since, dt.datetime.now() + dt.timedelta(days=1)) or ()
    except Exception:
        deals = ()
    outs = sorted([d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT],
                  key=lambda d: d.time)

    lines = [title]
    wins = losses = 0
    total_pct = 0.0
    best = worst = None
    for d in outs:
        b = symbols_rev.get(d.symbol, d.symbol)
        when = dt.datetime.fromtimestamp(d.time).strftime("%m/%d")
        # معامله‌ی بستن، برعکسِ جهت پوزیشن است
        side = "فروش" if d.type == mt5.DEAL_TYPE_BUY else "خرید"
        if d.reason == mt5.DEAL_REASON_TP:
            res = "حد سود ✅"
        elif d.reason == mt5.DEAL_REASON_SL:
            res = "حد ضرر ❌"
        else:
            res = "بسته شد"
        pct = (d.profit + d.swap + d.commission) / acc.balance * 100.0
        total_pct += pct
        if pct > 0: wins += 1
        else: losses += 1
        if best is None or pct > best[1]: best = (b, pct)
        if worst is None or pct < worst[1]: worst = (b, pct)
        lines.append(f"{when} | {b} | {side} | {res} | {pct:+.2f}٪")

    if not outs:
        lines.append("در این دوره هیچ معامله‌ای بسته نشد.")
    else:
        lines.append(f"— تعداد: {len(outs)} | برد: {wins} | باخت: {losses}")
        if best:
            lines.append(f"— بهترین: {best[0]} ({best[1]:+.2f}٪) | بدترین: {worst[0]} ({worst[1]:+.2f}٪)")
    lines.append(f"— برایند دوره: {_pct_txt(total_pct)}")
    floating = (acc.equity - acc.balance) / acc.balance * 100.0
    lines.append(f"— تریدهای بازِ فعلی: {_pct_txt(floating)}")
    total_acc = (acc.equity - START_BALANCE) / START_BALANCE * 100.0
    lines.append(f"— کل حساب از شروع: {_pct_txt(total_acc)} (اکویتی {acc.equity:,.0f} {acc.currency})")

    text = "\n".join(lines)
    log(text, bale=False)  # در فایل و CMD کامل ثبت شود
    # ارسال به بله؛ اگر خیلی بلند بود چند تکه می‌شود که قیچی نشود
    chunk = []
    size = 0
    for ln in lines:
        if size + len(ln) > 3000 and chunk:
            bale_send("\n".join(chunk))
            chunk, size = [], 0
        chunk.append(ln)
        size += len(ln) + 1
    if chunk:
        bale_send("\n".join(chunk))


def maybe_periodic_reports(symbols_rev):
    """گزارش هفتگی (شنبه‌ها) و ماهانه (روز اول ماه)، رأس همان ساعت گزارش روزانه."""
    now = dt.datetime.now()
    if now.hour != DAILY_REPORT_HOUR:
        return
    if now.weekday() == 5:  # شنبه — هفته‌ی معاملاتی تمام شده
        if _marker_differs("last_weekly.txt", now.strftime("%G-W%V")):
            period_report(symbols_rev, now - dt.timedelta(days=7), "🗓 گزارش هفتگی معاملات")
    if now.day == 1:
        if _marker_differs("last_monthly.txt", now.strftime("%Y-%m")):
            prev_month_start = (now.replace(day=1) - dt.timedelta(days=1)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            period_report(symbols_rev, prev_month_start, "📅 گزارش ماهانه معاملات")


def maybe_daily_report(symbols_rev):
    """هر روز رأس ساعت تعیین‌شده، فقط یک بار (حتی بعد از ری‌استارت)."""
    now = dt.datetime.now()
    if now.hour != DAILY_REPORT_HOUR:
        return
    today = now.strftime("%Y-%m-%d")
    try:
        with open(_daily_file, encoding="utf-8") as f:
            if f.read().strip() == today:
                return
    except Exception:
        pass
    try:
        with open(_daily_file, "w", encoding="utf-8") as f:
            f.write(today)
    except Exception:
        pass
    daily_report(symbols_rev)


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
    log("========== شروع ربات (نسخه ۲ — دمو) ==========", bale=False)
    log(f"سبد انتخابی ({len(BASKET)} نماد): {', '.join(BASKET)} — ربات فقط روی همین‌ها کار می‌کند.", bale=False)
    acc = connect_with_retry(bale_notify=False)

    symbols = {}
    for b in BASKET:
        name = resolve_symbol(b)
        if name is None:
            log("⚠️ این نماد نزد بروکر پیدا نشد و کنار گذاشته شد!", b)
        else:
            symbols[b] = name
            if name != b:
                log(f"اسم نماد نزد بروکر: {name}", b, bale=False)
    symbols_rev = {v: k for k, v in symbols.items()}
    log(f"آماده | {len(symbols)} نماد فعال | ریسک هر معامله {RISK_PER_TRADE*100:.1f}٪ | "
        f"حد سود {RR:g} برابر ریسک | ورود {abs(ENTRY_OFF)*100:.0f}٪ داخل زون | سقف {MAX_OPEN_TOTAL} پوزیشن", bale=False)

    # همه‌ی اطلاعات راه‌اندازی، در «یک» پیام بله
    bale_send(
        "🤖 ربات روشن شد\n"
        f"حساب: {acc.login} ({acc.server}) | {'دمو' if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else 'واقعی'}\n"
        f"بالانس: {acc.balance:,.0f} | اکویتی: {acc.equity:,.0f} {acc.currency}\n"
        f"سبد: {len(symbols)} نماد ({', '.join(symbols)})\n"
        f"ریسک {RISK_PER_TRADE*100:.1f}٪ | حد سود {RR:g}R | ورود {abs(ENTRY_OFF)*100:.0f}٪ زون | "
        f"سقف: هر چارت ۳، کل {MAX_OPEN_TOTAL}"
    )

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
    _last_problems = [set()]
    while True:
        try:
            ensure_connected()

            # سلامت‌سنجی هر دور: مشکل جدید → داد بلند (لاگ + بله)؛ مشکل تکراری → فقط CMD
            problems = health_check()
            if problems:
                pset = set(problems)
                if pset != _last_problems[0]:
                    for pr in problems:
                        log(f"🚨 {pr}")
                    _last_problems[0] = pset
                else:
                    for pr in problems:
                        console(f"🚨 {pr}")
                heartbeat("مشکل: " + " | ".join(problems))
                _time.sleep(POLL_SECONDS)
                continue
            elif _last_problems[0]:
                _last_problems[0] = set()
                log("🟢 مشکل برطرف شد — همه‌چیز دوباره سالم است و ربات ادامه می‌دهد.")

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
            maybe_daily_report(symbols_rev)
            maybe_periodic_reports(symbols_rev)
            report_status()
            bale_flush()  # پیام‌های مانده در صف بله، هر دور دوباره تلاش می‌شوند
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
