# -*- coding: utf-8 -*-
import os, glob, zipfile, io, json
import re
import numpy as np

from analysis_distribution import distribution_sheets
import pandas as pd

BACKTEST_START = pd.Timestamp("2023-01-01")

# هزینه‌های معاملاتی تقریبی (نسبت به اسپرد هر نماد؛ در صورت نیاز این دو عدد را ویرایش کن)
COMMISSION_SPREAD_MULT = 0.5       # کمیسیون رفت‌وبرگشت ≈ نصف اسپرد
SWAP_SPREAD_MULT_PER_NIGHT = 0.2   # سواپ ≈ ۲۰٪ اسپرد به ازای هر شب نگهداری پوزیشن

# مقایسه‌ی حالت‌های نقطه‌ی ورود در یک اجرا (شیت «مقایسه_نقطه_ورود» در خلاصه_نتایج.xlsx)
# اگر نمی‌خواهی و اجرا سریع‌تر شود، این را False کن.
COMPARE_ENTRY_MODES = True
ENTRY_MODES = {
    "+10% نزدیک قیمت (بیرون زون)": 0.10,
    "0% روی پراکسیمال": 0.0,
    "-10% داخل زون (دور از قیمت)": -0.10,
}
DEFAULT_ENTRY_OFF = 0.10  # حالت اصلی که گزارش‌های کامل با آن ساخته می‌شود

# (خروجی PDF/ژورنال در نسخه 1.9 تولید نمی‌شود)
# این وابستگی‌ها اختیاری هستند؛ اگر نصب نبودند، بک‌تست همچنان اجرا می‌شود.
canvas = None
A4 = (595.27, 841.89)
pdfmetrics = None
TTFont = None
arabic_reshaper = None


def get_display(x):  # type: ignore
    return x


try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    pass

try:
    import arabic_reshaper
except ImportError:
    arabic_reshaper = None

try:
    from bidi.algorithm import get_display as _bidi_get_display
    get_display = _bidi_get_display  # type: ignore
except ImportError:
    pass
# ---------------- Persian helpers ----------------
def fa(s: str) -> str:
    s = str(s)
    if arabic_reshaper is None:
        return s
    return get_display(arabic_reshaper.reshape(s))
def _find_fa_font_path():
    candidates = [
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\Tahoma.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]

    for fp in candidates:
        if os.path.exists(fp):
            return fp

    local_fonts = glob.glob(os.path.join(os.getcwd(), "fonts", "*.ttf"))
    if local_fonts:
        return local_fonts[0]

    return None


def register_fa_font():
    if pdfmetrics is None or TTFont is None:
        raise RuntimeError("کتابخانه reportlab نصب نیست.")

    font_path = _find_fa_font_path()
    if not font_path:
        raise RuntimeError("فونت مناسب فارسی پیدا نشد (tahoma/dejavu/arial یا fonts/*.ttf).")

    pdfmetrics.registerFont(TTFont("FA", font_path))
    return "FA"

def wrap_text(s: str, max_chars=80):
    words = str(s).split()
    lines = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines

# ------------- CSV reader (MetaTrader no header) -------------
def read_mt_csv_from_bytes(b: bytes) -> pd.DataFrame:
    if b is None or len(b) == 0:
        raise ValueError("فایل CSV خالی است.")

    df = pd.read_csv(io.BytesIO(b), header=None)
    # Date, Time, Open, High, Low, Close, Volume
    if df.shape[1] < 6:
        raise ValueError("فرمت CSV غیرمنتظره است (ستون کم).")
    if df.shape[1] >= 7:
        df = df.iloc[:, :7]
        df.columns = ["date", "time", "open", "high", "low", "close", "volume"]
    else:
        df = df.iloc[:, :6]
        df.columns = ["date", "time", "open", "high", "low", "close"]

    df["time"] = pd.to_datetime(
        df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip(),
        errors="coerce"
    )
    df = df.dropna(subset=["time"]).sort_values("time").drop_duplicates("time").reset_index(drop=True)
    df = df[["time", "open", "high", "low", "close"]].copy()
    return df

def load_timeframes_from_zip(zip_path: str):
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"فایل ZIP پیدا نشد: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        if not names:
            raise ValueError(f"فایل ZIP خالی است: {zip_path}")

        f240_list = [n for n in names if n.endswith("-240.csv")]
        f1d_list  = [n for n in names if n.endswith("-1D.csv")]
        f1w_list  = [n for n in names if n.endswith("-1W.csv")]

        if not f240_list or not f1d_list or not f1w_list:
            raise ValueError(
                f"داخل ZIP فایل‌های لازم پیدا نشد: {zip_path} | "
                f"240={len(f240_list)} 1D={len(f1d_list)} 1W={len(f1w_list)}"
            )

        f240 = f240_list[0]
        f1d = f1d_list[0]
        f1w = f1w_list[0]

        h4 = read_mt_csv_from_bytes(z.read(f240))
        d1 = read_mt_csv_from_bytes(z.read(f1d))
        w1 = read_mt_csv_from_bytes(z.read(f1w))

    if h4.empty or d1.empty or w1.empty:
        raise ValueError(
            f"داده‌ی یکی از تایم‌فریم‌ها داخل ZIP خالی است: {zip_path} | "
            f"h4={len(h4)} d1={len(d1)} w1={len(w1)}"
        )

    return h4, d1, w1

# ---------------- Indicators ----------------
def atr(df: pd.DataFrame, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def range_filter(df: pd.DataFrame, atr_s: pd.Series, lookback=20, k=3.0):
    hh = df["high"].rolling(lookback, min_periods=lookback).max()
    ll = df["low"].rolling(lookback, min_periods=lookback).min()
    return (hh - ll) < (k * atr_s)



def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility helper for live strategy engine.

    Uses the same indicator primitives already defined in this module.
    """
    out = df.copy()
    out["atr"] = atr(out)
    out["range"] = range_filter(out, out["atr"])
    return out
def swing_points(df: pd.DataFrame, n=1):
    highs = df["high"].values
    lows  = df["low"].values
    sh = np.zeros(len(df), dtype=bool)
    sl = np.zeros(len(df), dtype=bool)
    for i in range(n, len(df)-n):
        if np.all(highs[i] > highs[i-n:i]) and np.all(highs[i] > highs[i+1:i+n+1]):
            sh[i] = True
        if np.all(lows[i] < lows[i-n:i]) and np.all(lows[i] < lows[i+1:i+n+1]):
            sl[i] = True
    return sh, sl

def trend_from_swings(df: pd.DataFrame, n=1):
    """
    نسخه بدون lookahead:
    swing_points همچنان با همان منطقِ قبلی سوئینگ‌ها را تعیین می‌کند،
    اما سیگنال سوئینگ فقط بعد از n کندل (یعنی وقتی قابل تایید است) وارد trend می‌شود.
    """
    sh, sl = swing_points(df, n=n)

    last_hi = np.nan
    last_lo = np.nan
    cur = 0
    out = np.zeros(len(df), dtype=int)

    for i in range(len(df)):
        # تأیید سوئینگ با تأخیر n کندل
        j = i - n
        if j >= 0:
            if sh[j]:
                last_hi = df["high"].iloc[j]
            if sl[j]:
                last_lo = df["low"].iloc[j]

        c = df["close"].iloc[i]
        if (not np.isnan(last_hi)) and c > last_hi:
            cur = 1
        elif (not np.isnan(last_lo)) and c < last_lo:
            cur = -1

        out[i] = cur

    return pd.Series(out, index=df.index)
# ---------------- Base/Doji rules ----------------
def is_base_candle(row):
    rng = row["high"] - row["low"]
    if rng <= 0: return False
    body = abs(row["close"] - row["open"])
    return body <= 0.5 * rng

def is_doji_small(row, atr_v, body_ratio_max=0.20, range_atr_max=0.80):
    rng = row["high"] - row["low"]
    if rng <= 0 or atr_v is None or np.isnan(atr_v) or atr_v <= 0:
        return False
    body = abs(row["close"] - row["open"])
    return (body / rng) <= body_ratio_max and (rng <= (range_atr_max * atr_v))

def strong_close(row):
    rng = row["high"] - row["low"]
    if rng <= 0: return False
    body = abs(row["close"] - row["open"])
    return body > 0.5 * rng

# ---------------- Zone structure ----------------
class Zone:
    def __init__(self, symbol, tf, direction, proximal, distal, created_time, base_start, base_end, doji_shadow):
        self.symbol=symbol
        self.tf=tf
        self.direction=direction
        self.proximal=float(proximal)
        self.distal=float(distal)
        self.created_time=created_time
        self.base_start=base_start
        self.base_end=base_end
        self.doji_shadow=bool(doji_shadow)
        self.touch_count=0
        self.last_touch_i=None
        self.clean_after_touch=999
        self.expired=False
        self.zone_id=None
        self.superseded_time=None  # زمانی که زون جدیدِ هم‌پوشان جای این زون را می‌گیرد

    def low(self): return min(self.proximal, self.distal)
    def high(self): return max(self.proximal, self.distal)

def build_zones(df, symbol, tf, max_base_len, atr_s):
    zones=[]
    i=0
    while i < len(df)-3:
        made=None
        for L in range(1, max_base_len+1):
            if i+L >= len(df): break
            base=df.iloc[i:i+L]
            if not base.apply(is_base_candle, axis=1).all():
                break

            base_high=base["high"].max()
            base_low =base["low"].min()

            conf=df.iloc[i+L]
            if not strong_close(conf):
                continue

            bull = conf["close"] > base_high
            bear = conf["close"] < base_low
            if not (bull or bear):
                continue

            doji_flags=[is_doji_small(r, atr_s.iloc[idx]) for idx, r in base.iterrows()]
            doji_shadow = bool(all(doji_flags))

            if bull:
                direction="BUY"
                if doji_shadow:
                    proximal=base_high
                    distal=base_low
                else:
                    proximal=float(max(base[["open","close"]].max(axis=1)))
                    distal=float(base_low)
            else:
                direction="SELL"
                if doji_shadow:
                    proximal=base_low
                    distal=base_high
                else:
                    proximal=float(min(base[["open","close"]].min(axis=1)))
                    distal=float(base_high)

            z=Zone(symbol, tf, direction, proximal, distal,
                   df["time"].iloc[i+L], df["time"].iloc[i], df["time"].iloc[i+L-1], doji_shadow)
            made=(L, z)
            break

        if made:
            zones.append(made[1])
            i += made[0] + 1
        else:
            i += 1
    return zones

def overlap_ratio(a_low,a_high,b_low,b_high):
    inter=max(0.0, min(a_high,b_high)-max(a_low,b_low))
    uni=max(a_high,b_high)-min(a_low,b_low)
    return inter/uni if uni>0 else 0.0

def dedup_zones(zones, thr=0.55):
    zones=sorted(zones, key=lambda z: z.created_time)
    clusters=[]
    for z in zones:
        placed=False
        for cl in clusters:
            rep=cl[-1]
            if overlap_ratio(z.low(),z.high(),rep.low(),rep.high()) >= thr:
                cl.append(z); placed=True; break
        if not placed:
            clusters.append([z])
    out=[]
    for cl in clusters:
        rep=cl[-1]
        low=max(c.low() for c in cl)
        high=min(c.high() for c in cl)
        if low < high:
            if rep.direction=="BUY":
                rep.proximal=high; rep.distal=low
            else:
                rep.proximal=low; rep.distal=high
        out.append(rep)
    return out

def dedup_zones_pit(zones, thr=0.55):
    """حذف زون‌های هم‌پوشان بدون نگاه به آینده:
    هر زون جدید، زون‌های هم‌پوشانِ قبلی را فقط از «زمان ایجاد خودش» به بعد جایگزین می‌کند
    و محدوده‌اش با زون‌های قبلی (که در آن لحظه معلوم‌اند) تنگ‌تر می‌شود."""
    zones = sorted(zones, key=lambda z: z.created_time)
    active = []
    for z in zones:
        for old in active:
            if overlap_ratio(z.low(), z.high(), old.low(), old.high()) >= thr:
                old.superseded_time = z.created_time
                low = max(z.low(), old.low()); high = min(z.high(), old.high())
                if low < high:
                    if z.direction == "BUY":
                        z.proximal = high; z.distal = low
                    else:
                        z.proximal = low; z.distal = high
        active = [a for a in active if a.superseded_time is None]
        active.append(z)
    return zones

def body_overlaps_zone(o,c,z:Zone):
    bl=min(o,c); bh=max(o,c)
    return (bh >= z.low()) and (bl <= z.high())

# ---------------- Reporting helpers ----------------
def init_zone_table(h_z):
    rows=[]
    for z in h_z:
        rows.append({
            "ZoneID": z.zone_id,
            "نماد": z.symbol,
            "تایم‌فریم": z.tf,
            "جهت": "خرید" if z.direction=="BUY" else "فروش",
            "تاریخ_ایجاد": z.created_time,
            "پراکسیمال": z.proximal,
            "دیستال": z.distal,
            "بیس_شروع": z.base_start,
            "بیس_پایان": z.base_end,
            "دوجی_شدو": z.doji_shadow,
            "Touch1": None,
            "Touch2": None,
            "تعداد_تست": 0,
            "FinalStatus": "",
            "FinalReason": "",
            "FinalTime": None,
            "زمان_ثبت_سفارش": None,
            "زمان_پرشدن": None,
            "زمان_خروج": None,
            "نتیجه_R": None
        })
    return pd.DataFrame(rows)

def set_final(zone_df, zid, status, reason, t):
    mask = zone_df["ZoneID"]==zid
    if not mask.any(): return
    if str(zone_df.loc[mask, "FinalStatus"].iloc[0]).strip() != "":
        return
    zone_df.loc[mask, "FinalStatus"] = status
    zone_df.loc[mask, "FinalReason"] = reason
    zone_df.loc[mask, "FinalTime"] = t

def log_event(events, t, symbol, zid, etype, detail=""):
    events.append({
        "زمان": t,
        "نماد": symbol,
        "ZoneID": zid,
        "نوع_رویداد": etype,
        "جزئیات": detail
    })

# ---------------- Backtest (logic unchanged; reporting upgraded) ----------------
def backtest_one(symbol, h4, d1, w1, years, spread,
                 entry_off=0.10, sl_off=0.25, rr=3.0,
                 reserve=0.15, risk_per_trade=0.01, max_orders=3):

    bt_start = BACKTEST_START

    h4 = h4.copy(); d1 = d1.copy(); w1 = w1.copy()
    for df in (h4, d1, w1):
        df["open"]=df["open"].astype(float)
        df["high"]=df["high"].astype(float)
        df["low"]=df["low"].astype(float)
        df["close"]=df["close"].astype(float)

    # ATR warmup روی کل دیتا
    h4["atr"] = atr(h4)
    d1["atr"] = atr(d1)
    w1["atr"] = atr(w1)

    # کات اولیه از 2023 به بعد (برای منطق، نه ATR)
    h4_ = h4[h4["time"] >= bt_start].copy()
    d1_ = d1[d1["time"] >= bt_start].copy()
    w1_ = w1[w1["time"] >= bt_start].copy()

    if h4_.empty or d1_.empty or w1_.empty:
        metrics_df = pd.DataFrame([{
            "نماد":symbol,"تعداد":0,"درصد_برد":0.0,"فاکتور_سود":0.0,
            "بازده_خالص٪":0.0,"حداکثر_افت٪":0.0,"میانگین_R":0.0
        }])
        reasons_df = pd.DataFrame([{"نماد":symbol,"دلیل":"دیتا ناکافی بعد از 2023", "تعداد":1}])
        return metrics_df, reasons_df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # شروع واقعی بک‌تست = جایی که هر سه تایم‌فریم بعد از 2023 دیتا دارند
    global_start = max(bt_start, h4_["time"].min(), d1_["time"].min(), w1_["time"].min())

    h4 = h4[h4["time"] >= global_start].reset_index(drop=True)
    d1 = d1[d1["time"] >= global_start].reset_index(drop=True)
    w1 = w1[w1["time"] >= global_start].reset_index(drop=True)

    if h4.empty or d1.empty or w1.empty:
        metrics_df = pd.DataFrame([{
            "نماد":symbol,"تعداد":0,"درصد_برد":0.0,"فاکتور_سود":0.0,
            "بازده_خالص٪":0.0,"حداکثر_افت٪":0.0,"میانگین_R":0.0
        }])
        reasons_df = pd.DataFrame([{"نماد":symbol,"دلیل":"دیتا ناکافی بعد از sync", "تعداد":1}])
        return metrics_df, reasons_df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # range/trend روی دیتای کات‌شده
    h4["range"] = range_filter(h4, h4["atr"])
    d1["range"] = range_filter(d1, d1["atr"])
    h4["trend"] = trend_from_swings(h4, n=1)  # همین حالا بدون lookahead شده چون trend_from_swings را عوض کردی
    d1["trend"] = trend_from_swings(d1, n=1)

    w_z = dedup_zones_pit(build_zones(w1, symbol, "W1", 12, w1["atr"]))
    h_z = dedup_zones_pit(build_zones(h4, symbol, "H4", 6,  h4["atr"]))

    # ZoneID
    h_z = sorted(h_z, key=lambda z: z.created_time)
    for idx, z in enumerate(h_z, start=1):
        z.zone_id = f"{symbol}_H4_{idx:05d}"

    zone_df = init_zone_table(h_z)
    events = []

    d_times = d1["time"].values
    def last_idx_leq(times, t):
        return np.searchsorted(times, t, side="right") - 1

    equity=100000.0; peak=equity; max_dd=0.0
    pending=[]    # سفارش در انتظار
    open_pos=[]   # پوزیشن باز
    trades=[]

    reasons={
        "زون_چهارساعته_کل": len(h_z),
        "رد_به_خاطر_رنج": 0,
        "رد_به_خاطر_روند": 0,
        "رد_به_خاطر_سقف_سفارش": 0,
        "لغو_به_خاطر_هفتگی": 0,
        "لغو_به_خاطر_تست_سوم": 0,
        "انقضا_زون": 0,
        "جایگزینی_زون": 0,
        "ورود_انجام_شد": 0,
    }

    # هزینه‌های تقریبی این نماد (برحسب قیمت)
    commission_cost = COMMISSION_SPREAD_MULT * float(spread)
    swap_per_night = SWAP_SPREAD_MULT_PER_NIGHT * float(spread)

    def make_order(z:Zone, t_now, test_no):
        height = z.high()-z.low()
        if height<=0: height=1e-9
        # ورود = پراکسیمال + entry_off × ارتفاع بیس، به سمت قیمت.
        # entry_off مثبت = بیرون زون نزدیک قیمت (جبران اسپرد)، منفی = داخل زون دورتر از قیمت.
        # اسپرد جداگانه دوباره حساب نمی‌شود.
        if z.direction=="BUY":
            entry = z.proximal + entry_off*height
            sl    = z.distal  - sl_off*height
            eff_entry = entry
            risk = eff_entry - sl
            tp = eff_entry + rr*risk
        else:
            entry = z.proximal - entry_off*height
            sl    = z.distal  + sl_off*height
            eff_entry = entry
            risk = sl - eff_entry
            tp = eff_entry - rr*risk

        zone_df.loc[zone_df["ZoneID"]==z.zone_id, "زمان_ثبت_سفارش"] = t_now

        return {"z":z,"entry":float(entry),"sl":float(sl),"tp":float(tp),
                "eff_entry":float(eff_entry),"t":t_now,"test":test_no,
                "active":True,"filled":False,"fill_time":None,"cancel":None,
                "risk": float(risk)}

    def check_exit(direction, sl, tp, bar_high, bar_low):
        if direction == "BUY":
            hit_sl = bar_low <= sl
            hit_tp = bar_high >= tp
        else:
            hit_sl = bar_high >= sl
            hit_tp = bar_low <= tp

        if hit_sl and hit_tp:
            return True, sl, "هر دو در یک کندل: حدضرر"
        if hit_sl:
            return True, sl, "حدضرر"
        if hit_tp:
            return True, tp, "حدسود"
        return False, None, None

    def finalize_trade(pos, exit_time, exit_price, reason):
        nonlocal equity, peak, max_dd
        direction = pos["direction"]
        eff_entry = pos["eff_entry"]
        risk = pos["risk"]
        if risk <= 0:
            return

        result_r = (exit_price - eff_entry)/risk if direction=="BUY" else (eff_entry - exit_price)/risk

        # کسر هزینه‌های تقریبی: کمیسیون + سواپ به ازای هر شب نگهداری
        try:
            nights = max(0, int((pd.Timestamp(exit_time).normalize() - pd.Timestamp(pos["fill_time"]).normalize()).days))
        except Exception:
            nights = 0
        result_r = float(result_r) - (commission_cost + swap_per_night * nights) / risk

        equity += pos["risk_amt"] * float(result_r)
        peak=max(peak,equity)
        dd=(peak-equity)/peak if peak>0 else 0.0
        max_dd=max(max_dd,dd)

        z = pos["z"]
        trades.append({
            "نماد":symbol,"جهت":("خرید" if direction=="BUY" else "فروش"),
            "زمان_ورود":pos["fill_time"],"ورود":eff_entry,"حدضرر":pos["sl"],"حدسود":pos["tp"],
            "زمان_خروج":exit_time,"قیمت_خروج":float(exit_price),"نتیجه_R":float(result_r),
            "برد": (result_r>0), "علت_خروج":reason, "تست":pos["test"],
            "ZoneID": pos["ZoneID"],
            "پراکسیمال":z.proximal,"دیستال":z.distal,
            "بیس_شروع":z.base_start,"بیس_پایان":z.base_end,
            "دوجی_شدو":z.doji_shadow
        })

        zone_df.loc[zone_df["ZoneID"]==pos["ZoneID"], ["زمان_خروج","نتیجه_R"]] = [exit_time, float(result_r)]
        final = "پر شد: برد" if result_r>0 else "پر شد: باخت"
        set_final(zone_df, pos["ZoneID"], final, reason, exit_time)
        log_event(events, exit_time, symbol, pos["ZoneID"], "Exit", final)

    used=set()

    for i in range(len(h4)):
        t=h4["time"].iloc[i]

        o=float(h4["open"].iloc[i]); h=float(h4["high"].iloc[i])
        l=float(h4["low"].iloc[i]);  c=float(h4["close"].iloc[i])

        di=last_idx_leq(d_times, t.to_datetime64())
        if di<1 or i<1:
            continue

        # فیلترها فقط از کندل‌های «بسته‌شده» خوانده می‌شوند (بدون نگاه به آینده):
        # کندل H4 قبلی و آخرین کندل روزانه‌ی کامل‌شده (di-1)
        dtr=int(d1["trend"].iloc[di-1])
        htr=int(h4["trend"].iloc[i-1])

        drg=bool(d1["range"].iloc[di-1]) if not pd.isna(d1["range"].iloc[di-1]) else False
        hrg=bool(h4["range"].iloc[i-1])  if not pd.isna(h4["range"].iloc[i-1])  else False

        # بدنه‌ی کندل بسته‌شده‌ی قبلی برای چک لغو هفتگی
        o_prev=float(h4["open"].iloc[i-1]); c_prev=float(h4["close"].iloc[i-1])

        # ---------- exits for already-open positions ----------
        still_open=[]
        for pos in open_pos:
            exited, exit_price, reason = check_exit(pos["direction"], pos["sl"], pos["tp"], h, l)
            if exited:
                finalize_trade(pos, t, float(exit_price), reason)
            else:
                still_open.append(pos)
        open_pos = still_open

        # ---------- touches + expiry (همان) ----------
        for z in h_z:
            # زون از کندلِ بعد از تأییدش فعال می‌شود (کندل تأیید باید اول بسته شود)
            if z.created_time>=t or z.expired:
                continue

            # اگر زون جدیدِ هم‌پوشان آمده باشد، این زون از همان لحظه کنار می‌رود
            if z.superseded_time is not None and t >= z.superseded_time:
                z.expired=True
                reasons["جایگزینی_زون"] += 1
                set_final(zone_df, z.zone_id, "منقضی شد", "زون جدید هم‌پوشان جایگزین شد", t)
                log_event(events, t, symbol, z.zone_id, "Superseded", "")
                continue

            touched = (h >= z.low() and l <= z.high())
            if touched:
                if z.touch_count==0:
                    z.touch_count=1; z.last_touch_i=i; z.clean_after_touch=0
                    zone_df.loc[zone_df["ZoneID"]==z.zone_id, ["Touch1","تعداد_تست"]] = [t, 1]
                    log_event(events, t, symbol, z.zone_id, "Touch1", "")
                else:
                    if z.clean_after_touch>=3 and z.last_touch_i is not None and (i - z.last_touch_i) <= 50:
                        z.touch_count += 1
                        z.last_touch_i=i; z.clean_after_touch=0
                        zone_df.loc[zone_df["ZoneID"]==z.zone_id, ["Touch2","تعداد_تست"]] = [t, z.touch_count]
                        log_event(events, t, symbol, z.zone_id, "Touch2", f"تست={z.touch_count}")
                    else:
                        z.clean_after_touch=0
            else:
                if z.touch_count>0:
                    z.clean_after_touch += 1

            if z.touch_count==1 and z.last_touch_i is not None and (i - z.last_touch_i) > 50:
                z.expired=True
                reasons["انقضا_زون"] += 1
                set_final(zone_df, z.zone_id, "منقضی شد", "Touch2 تا ۵۰ کندل نیامد", t)
                log_event(events, t, symbol, z.zone_id, "Expired", "")

        # ---------- place orders (همان) ----------
        for z in h_z:
            if z.created_time>=t or z.expired or id(z) in used:
                continue
            if z.touch_count>=3:
                reasons["لغو_به_خاطر_تست_سوم"] += 1
                set_final(zone_df, z.zone_id, "رد شد", "تست سوم ممنوع", t)
                log_event(events, t, symbol, z.zone_id, "Rejected", "تست سوم")
                used.add(id(z)); continue
            if z.touch_count==0:
                continue

            if drg or hrg:
                reasons["رد_به_خاطر_رنج"] += 1
                set_final(zone_df, z.zone_id, "رد شد", "رنج", t)
                log_event(events, t, symbol, z.zone_id, "Rejected", "رنج")
                used.add(id(z)); continue

            if dtr==0 or htr==0 or dtr!=htr:
                reasons["رد_به_خاطر_روند"] += 1
                set_final(zone_df, z.zone_id, "رد شد", "عدم هم‌جهتی روند D1 و H4", t)
                log_event(events, t, symbol, z.zone_id, "Rejected", "روند")
                used.add(id(z)); continue

            if len([p for p in pending if p["active"] and not p["filled"]]) >= max_orders:
                reasons["رد_به_خاطر_سقف_سفارش"] += 1
                set_final(zone_df, z.zone_id, "رد شد", "سقف سفارش هم‌زمان", t)
                log_event(events, t, symbol, z.zone_id, "Rejected", "سقف سفارش")
                used.add(id(z)); continue

            test_no = 1 if z.touch_count==1 else 2
            pending.append(make_order(z, t, test_no))
            set_final(zone_df, z.zone_id, "سفارش ثبت شد", "در انتظار پر شدن", t)
            log_event(events, t, symbol, z.zone_id, "OrderPlaced", f"تست={test_no}")
            used.add(id(z))

        # ---------- weekly cancel BEFORE fill (همان) ----------
        # زون هفتگی فقط بعد از بسته‌شدن کندل هفتگیِ تأیید (حدود ۷ روز بعد) معتبر است
        wz_now=[wz for wz in w_z
                if wz.created_time + pd.Timedelta(days=7) <= t
                and (wz.superseded_time is None or t < wz.superseded_time)]
        for p in pending:
            if not p["active"] or p["filled"]:
                continue
            opp_dir = "SELL" if p["z"].direction=="BUY" else "BUY"
            opp=[wz for wz in wz_now if wz.direction==opp_dir]
            if any(body_overlaps_zone(o_prev,c_prev,wz) for wz in opp):
                p["active"]=False
                p["cancel"]="لغو: برخورد بدنه با زون مخالف هفتگی"
                reasons["لغو_به_خاطر_هفتگی"] += 1
                set_final(zone_df, p["z"].zone_id, "لغو شد", "زون مخالف هفتگی (بدنه)", t)
                log_event(events, t, symbol, p["z"].zone_id, "Canceled", "WeeklyOpp")

        # ---------- fills + (NEW) exit-same-bar ----------
        new_open_positions = []
        for p in pending:
            if not p["active"] or p["filled"]:
                continue

            if drg or hrg or dtr==0 or htr==0 or dtr!=htr:
                p["active"]=False
                p["cancel"]="لغو: عدم هم‌جهتی/رنج در لحظه ورود"
                reasons["رد_به_خاطر_روند"] += 1
                set_final(zone_df, p["z"].zone_id, "لغو شد", "عدم هم‌جهتی/رنج در لحظه ورود", t)
                log_event(events, t, symbol, p["z"].zone_id, "Canceled", "Trend/Range at Fill")
                continue

            filled_now = False
            direction = p["z"].direction

            if direction=="BUY" and l <= p["entry"]:
                filled_now = True
            elif direction=="SELL" and h >= p["entry"]:
                filled_now = True

            if not filled_now:
                continue

            p["filled"]=True; p["fill_time"]=t
            reasons["ورود_انجام_شد"] += 1
            zone_df.loc[zone_df["ZoneID"]==p["z"].zone_id, "زمان_پرشدن"] = t
            log_event(events, t, symbol, p["z"].zone_id, "Filled", "")

            usable = equity*(1.0 - reserve)
            risk_amt = usable*risk_per_trade

            pos = {
                "ZoneID": p["z"].zone_id,
                "direction": direction,
                "eff_entry": float(p["eff_entry"]),
                "sl": float(p["sl"]),
                "tp": float(p["tp"]),
                "risk": float(p["risk"]),
                "risk_amt": float(risk_amt),
                "fill_time": t,
                "test": p["test"],
                "z": p["z"]
            }

            # NEW: همان کندل ورود را هم برای خروج چک کن
            exited, exit_price, reason = check_exit(direction, pos["sl"], pos["tp"], h, l)
            if exited:
                finalize_trade(pos, t, float(exit_price), reason)
            else:
                new_open_positions.append(pos)

            p["active"] = False

        open_pos.extend(new_open_positions)
        pending=[x for x in pending if x["active"] and (not x["filled"])]

    # ---------- پایان دیتا ----------
    endt = h4["time"].iloc[-1] if len(h4)>0 else None
    if endt is not None:
        # بستن پوزیشن‌های باز با close آخر
        c_last = float(h4["close"].iloc[-1])
        for pos in open_pos:
            finalize_trade(pos, endt, c_last, "پایان دیتا")

        # finalize zones
        for zid in zone_df["ZoneID"].tolist():
            if str(zone_df.loc[zone_df["ZoneID"]==zid, "FinalStatus"].iloc[0]).strip()=="":
                set_final(zone_df, zid, "بدون لمس", "تا پایان دیتا لمس نشد", endt)

        for p in pending:
            if p["active"] and (not p["filled"]):
                set_final(zone_df, p["z"].zone_id, "سفارش پر نشد", "تا پایان دیتا پر نشد", endt)
                log_event(events, endt, symbol, p["z"].zone_id, "Unfilled", "")

    tdf=pd.DataFrame(trades)
    if tdf.empty:
        metrics={
            "نماد":symbol,"تعداد":0,"درصد_برد":0.0,"فاکتور_سود":0.0,
            "بازده_خالص٪":0.0,"حداکثر_افت٪":0.0,"میانگین_R":0.0
        }
    else:
        wins=tdf.loc[tdf["نتیجه_R"]>0,"نتیجه_R"].sum()
        loss=tdf.loc[tdf["نتیجه_R"]<0,"نتیجه_R"].abs().sum()
        pf=float(wins/loss) if loss>0 else 999.0
        winrate=float((tdf["نتیجه_R"]>0).mean()*100.0)
        net=float((equity-100000.0)/100000.0*100.0)
        # max_dd همینجا محاسبه شده
        metrics={
            "نماد":symbol,"تعداد":int(len(tdf)),"درصد_برد":round(winrate,2),
            "فاکتور_سود":round(pf,3),"بازده_خالص٪":round(net,2),
            "حداکثر_افت٪":round(max_dd*100.0,2),"میانگین_R":round(float(tdf["نتیجه_R"].mean()),3)
        }

    reasons_df=pd.DataFrame([{"نماد":symbol,"دلیل":k,"تعداد":int(v)} for k,v in reasons.items()])
    metrics_df=pd.DataFrame([metrics])
    events_df=pd.DataFrame(events)

    z_reason = zone_df.groupby(["نماد","FinalStatus","FinalReason"]).size().reset_index(name="تعداد")
    z_reason["درصد"] = z_reason.groupby("نماد")["تعداد"].transform(lambda s: (s/s.sum()*100.0).round(2))

    return metrics_df, reasons_df, tdf, zone_df, events_df, z_reason

# ---------------- PDFs ----------------
def write_journal_pdf(out_path, version_name, changes, upgrades, q_answers):
    font=register_fa_font()
    W,H=A4; m=40
    c=canvas.Canvas(out_path, pagesize=A4)
    y=H-m

    def line(txt, size=10, gap=12):
        nonlocal y
        if y < m+60:
            c.showPage(); y=H-m
        c.setFont(font, size)
        c.drawRightString(W-m, y, fa(txt))
        y -= gap

    line(f"ژورنال ورژن {version_name}", 14, 20)
    line(" ", 10, 6)

    line("چه تغییری ایجاد کردم؟", 12, 16)
    for u in upgrades:
        for ln in wrap_text("• "+u, 80):
            line(ln, 10, 12)

    line(" ", 10, 10)
    line("موارد ارتقا یافته در گزارش‌دهی:", 12, 16)
    for u in upgrades:
        for ln in wrap_text("• "+u, 80):
            line(ln, 10, 12)

    line(" ", 10, 10)
    line("سه سؤال اصلی + سؤال جدید:", 12, 16)
    for k,v in q_answers.items():
        line(k, 11, 14)
        for ln in wrap_text(v, 80):
            line("— "+ln, 10, 12)
        line(" ", 10, 6)

    c.save()


# ---------------- Comparison Helpers ----------------
def _parse_version_tuple(name: str):
    """
    تبدیل Z_v1.4 -> (1,4) برای مرتب‌سازی نسخه‌ها
    اگر قابل تشخیص نبود None برمی‌گرداند.
    """
    m = re.search(r'Z_v(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?', name)
    if not m:
        return None
    nums = [int(x) for x in m.groups() if x is not None]
    return tuple(nums) if nums else None

def _find_baseline_metrics_path(current_dir: str):
    """
    تلاش می‌کند نتایج نسخه قبلی را پیدا کند:
    - در پوشه والد، فولدرهای Z_v* را پیدا می‌کند
    - نزدیک‌ترین نسخه کوچک‌تر از نسخه فعلی را انتخاب می‌کند
    - سپس مسیر خروجی/نتایج_اعدادی.xlsx را برمی‌گرداند اگر وجود داشته باشد
    """
    parent = os.path.dirname(current_dir)
    cur_name = os.path.basename(current_dir)
    cur_ver = _parse_version_tuple(cur_name)

    candidates = []
    for d in os.listdir(parent):
        p = os.path.join(parent, d)
        if d == cur_name or (not os.path.isdir(p)):
            continue
        if not d.startswith("Z_v"):
            continue
        vt = _parse_version_tuple(d)
        if vt is None:
            continue
        candidates.append((vt, d))

    if not candidates or cur_ver is None:
        return None

    # انتخاب بزرگ‌ترین نسخه‌ای که از نسخه فعلی کوچک‌تر باشد
    smaller = [c for c in candidates if c[0] < cur_ver]
    if not smaller:
        return None
    smaller.sort(key=lambda x: x[0])
    prev_dir = smaller[-1][1]
    baseline_new = os.path.join(parent, prev_dir, "خروجی", "خلاصه_نتایج.xlsx")
    baseline_old = os.path.join(parent, prev_dir, "خروجی", "نتایج_اعدادی.xlsx")
    if os.path.isfile(baseline_new):
        return baseline_new
    return baseline_old if os.path.isfile(baseline_old) else None

def augment_metrics_with_change_review(metrics_df: pd.DataFrame, current_dir: str, years: int):
    """
    به metrics_df ستون‌های مقایسه با نسخه قبلی اضافه می‌کند (اگر پیدا شود).
    همچنین یک ردیف «کل» اضافه می‌کند که KPIهای وزنی را نشان می‌دهد.
    """
    df = metrics_df.copy()

    # KPI کل (وزنی بر اساس تعداد معاملات)
    total_trades = int(df["تعداد"].sum()) if "تعداد" in df.columns else 0
    if total_trades > 0:
        est_wins = (df["تعداد"] * df["درصد_برد"] / 100.0).sum()
        win_all = float(est_wins / total_trades * 100.0)
        pf_w = float((df["فاکتور_سود"] * df["تعداد"]).sum() / total_trades)
        r_w = float((df["میانگین_R"] * df["تعداد"]).sum() / total_trades)
        worst_dd = float(df["حداکثر_افت٪"].max())
        # تقریب بازده پرتفوی وزن مساوی
        wealth = (1.0 + df["بازده_خالص٪"] / 100.0).mean()
        port_return = (wealth - 1.0) * 100.0
        port_monthly = (wealth ** (1.0 / (years * 12.0)) - 1.0) * 100.0
    else:
        win_all = pf_w = r_w = worst_dd = port_return = port_monthly = 0.0

    summary_row = {
        "نماد": "کل",
        "تعداد": total_trades,
        "درصد_برد": round(win_all, 2),
        "فاکتور_سود": round(pf_w, 3),
        "بازده_خالص٪": round(port_return, 2),
        "حداکثر_افت٪": round(worst_dd, 2),
        "میانگین_R": round(r_w, 3),
        "CAGR_ماهانه_% (تقریب وزن‌مساوی)": round(port_monthly, 2),
    }

    # Baseline
    baseline_path = _find_baseline_metrics_path(current_dir)
    if baseline_path:
        try:
            base = pd.read_excel(baseline_path)
            # merge on symbol
            m = df.merge(base, on="نماد", how="left", suffixes=("", "_Baseline"))
            # اضافه کردن نمادهای حذف‌شده (در Baseline بوده‌اند ولی در این نسخه نیستند)
            removed_syms = [x for x in base["نماد"].unique().tolist() if x not in df["نماد"].unique().tolist()]
            if removed_syms:
                removed_rows = base[base["نماد"].isin(removed_syms)].copy()
                # ستون‌های فعلی را خالی می‌کنیم و فقط ستون‌های Baseline را نگه می‌داریم
                for col in df.columns:
                    if col != "نماد":
                        removed_rows[col] = np.nan
                # نام ستون‌های Baseline را با پسوند هماهنگ می‌کنیم
                for col in list(base.columns):
                    if col != "نماد":
                        removed_rows.rename(columns={col: f"{col}_Baseline"}, inplace=True)
                removed_rows["نتیجه_تغییر"] = "حذف شد"
                # هم‌ستون‌سازی با m
                for col in m.columns:
                    if col not in removed_rows.columns:
                        removed_rows[col] = np.nan
                removed_rows = removed_rows[m.columns]
                m = pd.concat([m, removed_rows], ignore_index=True)

            # deltas
            for col in ["درصد_برد", "فاکتور_سود", "بازده_خالص٪", "حداکثر_افت٪", "میانگین_R", "تعداد"]:
                bcol = f"{col}_Baseline"
                if bcol in m.columns:
                    m[f"Δ{col}"] = m[col] - m[bcol]
            # status
            def status_row(r):
                if pd.isna(r.get("درصد_برد_Baseline")):
                    return "جدید/بدون مقایسه"
                score = 0
                score += 1 if r.get("Δدرصد_برد", 0) >= 0 else -1
                score += 1 if r.get("Δفاکتور_سود", 0) >= 0 else -1
                # دراودان کمتر بهتر است
                score += 1 if r.get("Δحداکثر_افت٪", 0) <= 0 else -1
                score += 1 if r.get("Δبازده_خالص٪", 0) >= 0 else -1
                if score >= 2:
                    return "بهتر"
                if score <= -2:
                    return "بدتر"
                return "مخلوط/نامشخص"
            m["نتیجه_تغییر"] = m.apply(status_row, axis=1)

            # baseline portfolio KPI
            if "تعداد" in base.columns and base["تعداد"].sum() > 0:
                bt = int(base["تعداد"].sum())
                bw = (base["تعداد"] * base["درصد_برد"] / 100.0).sum()
                bwin = float(bw / bt * 100.0)
                bpf = float((base["فاکتور_سود"] * base["تعداد"]).sum() / bt)
                br = float((base["میانگین_R"] * base["تعداد"]).sum() / bt)
                bdd = float(base["حداکثر_افت٪"].max())
                bwealth = (1.0 + base["بازده_خالص٪"] / 100.0).mean()
                bret = (bwealth - 1.0) * 100.0
                bmon = (bwealth ** (1.0 / (years * 12.0)) - 1.0) * 100.0
            else:
                bt=bwin=bpf=br=bdd=bret=bmon=0.0

            # attach baseline numbers into summary row
            summary_row.update({
                "تعداد_Baseline": bt,
                "درصد_برد_Baseline": round(bwin, 2),
                "فاکتور_سود_Baseline": round(bpf, 3),
                "بازده_خالص٪_Baseline": round(bret, 2),
                "حداکثر_افت٪_Baseline": round(bdd, 2),
                "میانگین_R_Baseline": round(br, 3),
                "CAGR_ماهانه_% (تقریب وزن‌مساوی)_Baseline": round(bmon, 2),
                "Δدرصد_برد": round(win_all - bwin, 2),
                "Δفاکتور_سود": round(pf_w - bpf, 3),
                "Δبازده_خالص٪": round(port_return - bret, 2),
                "Δحداکثر_افت٪": round(worst_dd - bdd, 2),
                "Δمیانگین_R": round(r_w - br, 3),
            })
            # overall status
            overall_score = 0
            overall_score += 1 if (win_all - bwin) >= 0 else -1
            overall_score += 1 if (pf_w - bpf) >= 0 else -1
            overall_score += 1 if (worst_dd - bdd) <= 0 else -1
            overall_score += 1 if (port_return - bret) >= 0 else -1
            summary_row["نتیجه_تغییر"] = "بهتر" if overall_score >= 2 else ("بدتر" if overall_score <= -2 else "مخلوط/نامشخص")
            summary_row["BaselineFile"] = os.path.basename(os.path.dirname(baseline_path))
            df_out = m
        except Exception:
            df_out = df
            summary_row["نتیجه_تغییر"] = "Baseline یافت شد ولی خوانده نشد"
    else:
        df_out = df
        summary_row["نتیجه_تغییر"] = "Baseline یافت نشد"

    # اضافه کردن ردیف کل
    df_out = pd.concat([df_out, pd.DataFrame([summary_row])], ignore_index=True)
    return df_out, baseline_path

# ---------------- Main ----------------
def main():
    version_name = os.path.basename(os.getcwd())
    outdir = os.path.join(os.getcwd(), "خروجی")
    os.makedirs(outdir, exist_ok=True)

    years = None  # از 2023 تا پایان داده، به‌صورت پویا محاسبه می‌شود

    # Spread estimates (edit if needed)
    spreads = {
        "EURUSD":0.00012, "GBPUSD":0.00018, "AUDUSD":0.00014, "NZDUSD":0.00016,
        "USDCAD":0.00015, "USDCHF":0.00014,
        "EURAUD":0.00025, "EURCAD":0.00022, "EURGBP":0.00018, "EURNZD":0.00025,
        "GBPAUD":0.00030, "GBPCAD":0.00028, "GBPNZD":0.00032,
        "AUDCAD":0.00022, "AUDNZD":0.00024, "CADJPY":0.020, "CHFJPY":0.020,
        "EURJPY":0.020, "GBPJPY":0.025, "USDJPY":0.020, "AUDJPY":0.020,
        "NZDCAD":0.00025, "NZDUSD":0.00016,
        "XAUUSD":0.30, "XAGUSD":0.03
    }

    changes = [
        "نماد EURUSD به‌دلیل دراودان بالا حذف شد و نماد GBPJPY اضافه شد.",
        "خروجی‌ها محدود شد: فقط تنظیمات_بکتست.json، ژورنال.txt، ژورنال_این_ورژن.pdf، نتایج_اعدادی.xlsx",
        "نتایج_اعدادی.xlsx شامل ستون‌های مقایسه با نسخه قبلی (اگر پیدا شود) است."
    ]
    upgrades = [
        "گزارش زون‌محور: برای هر زون فقط یک نتیجه نهایی (FinalStatus/FinalReason)",
        "گزارش رویدادها: Touch1/Touch2/ثبت سفارش/لغو/پر شدن/خروج با زمان دقیق",
        "دلایل حذف برحسب زون با درصد واقعی (نه شمارش رویداد تکراری)",
        "خروجی‌ها محدود شد: فقط نتایج_اعدادی.xlsx + ژورنال (txt/pdf) + تنظیمات_بکتست.json"
    ]

    q_answers = {
        "چرا تغییری ایجاد کردم؟": "برای اینکه اندازه‌گیری علمی و قابل اعتماد شود؛ اول اندازه‌گیری را دقیق می‌کنیم، بعد تصمیم روی قوانین می‌گیریم.",
        "انتظارم چی بود؟": "اینکه بفهمیم دقیقاً از کل زون‌ها چند درصد در هر مرحله حذف می‌شوند و گلوگاه اصلی کجاست.",
        "چه نتیجه‌ای رخ داد؟": "در فایل نتایج_اعدادی.xlsx ستون «نتیجه_تغییر» و ستون‌های Δ (اختلاف) نشان می‌دهد حذف EURUSD و اضافه شدن GBPJPY نسبت به نسخه قبلی بهتر/بدتر شده است. اگر نسخه قبلی پیدا نشود، در همان فایل درج می‌شود: Baseline یافت نشد.",
        "چه تغییری ایجاد کردم؟": "نماد EURUSD به‌دلیل دراودان بالا حذف شد و نماد GBPJPY اضافه شد."
    }

    # DATA DIR: folder '0' on Desktop (your screenshot)
    datadir = os.path.join(os.path.expandvars(r"%USERPROFILE%"), "Desktop", "0")

    zip_files = sorted(glob.glob(os.path.join(datadir, "*.zip")))
    if not zip_files:
        raise FileNotFoundError(f"هیچ فایل ZIP در مسیر دیتا پیدا نشد: {datadir}")

    all_metrics=[]
    all_reasons=[]
    all_trades=[]
    all_zones=[]
    all_events=[]
    all_zone_reasons=[]
    entry_mode_rows=[]
    max_data_time = None
    for zp in zip_files:
        base=os.path.basename(zp)
        symbol = base.split(".")[0]  # e.g. USDJPY.W.D.H4.zip => USDJPY
        h4,d1,w1 = load_timeframes_from_zip(zp)
        if not h4.empty:
            end_t = pd.to_datetime(h4["time"].max(), errors="coerce")
            if pd.notna(end_t):
                max_data_time = end_t if max_data_time is None else max(max_data_time, end_t)

        mdf, rdf, tdf, zdf, edf, zreason = backtest_one(symbol, h4,d1,w1, years, spreads.get(symbol, 0.0),
                                                        entry_off=DEFAULT_ENTRY_OFF)

        # اجرای حالت‌های دیگر نقطه‌ی ورود فقط برای مقایسه (بقیه‌ی گزارش‌ها با حالت اصلی است)
        if COMPARE_ENTRY_MODES:
            for mode_name, eoff in ENTRY_MODES.items():
                if abs(eoff - DEFAULT_ENTRY_OFF) < 1e-12:
                    m_mode = mdf.copy()
                else:
                    m_mode = backtest_one(symbol, h4, d1, w1, years, spreads.get(symbol, 0.0),
                                          entry_off=eoff)[0].copy()
                m_mode["حالت_ورود"] = mode_name
                entry_mode_rows.append(m_mode)

        all_metrics.append(mdf)
        all_reasons.append(rdf)
        all_trades.append(tdf)
        all_zones.append(zdf)
        all_events.append(edf)
        all_zone_reasons.append(zreason)
        # (خروجی معاملات_*.csv غیرفعال شد: طبق درخواست فقط ۴ فایل خروجی)

    metrics_df=pd.concat(all_metrics, ignore_index=True)
    reasons_df=pd.concat(all_reasons, ignore_index=True)
    trades_df=pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    zones_df=pd.concat(all_zones, ignore_index=True)
    events_df=pd.concat(all_events, ignore_index=True)
    zone_reasons_df=pd.concat(all_zone_reasons, ignore_index=True)

    # مدت واقعی بک‌تست: از شروع 2023 تا انتهای دیتای موجود
    if max_data_time is not None:
        years = max((max_data_time - BACKTEST_START).days / 365.25, 1.0 / 12.0)
    else:
        years = 1.0 / 12.0

    # --- Review change impact (compares with previous version if available) ---
    metrics_df, baseline_path = augment_metrics_with_change_review(metrics_df, os.getcwd(), years)

    
    # --- خروجی‌ها: فقط دو فایل در پوشه «خروجی» ---
    # 1) فایل خلاصه
    summary_path = os.path.join(outdir, "خلاصه_نتایج.xlsx")
    # 2) فایل جزئیات حرفه‌ای
    detailed_path = os.path.join(outdir, "جزئیات_حرفه‌ای.xlsx")

    try:

        # آماده‌سازی زمان‌ها
        if not trades_df.empty:
            for c in ["زمان_ورود", "زمان_خروج"]:
                if c in trades_df.columns:
                    trades_df[c] = pd.to_datetime(trades_df[c], errors="coerce")

        # --- جداول پایه ---
        # خلاصه‌ی نمادها (همان نتایج اعدادی)
        sym_metrics = metrics_df.copy()

        # خلاصه کلی (پورتفوی تقریب وزن‌مساوی روی نمادها)
        _m = sym_metrics[sym_metrics["نماد"] != "کل"].copy() if "کل" in sym_metrics.get("نماد", pd.Series()).astype(str).values else sym_metrics.copy()
        overview = {}
        overview["نسخه"] = version_name
        overview["years"] = round(float(years), 4)
        overview["datadir"] = datadir
        overview["ReserveCapitalPercent"] = 15
        overview["RiskPerTradePercent"] = 1
        overview["MaxOrders"] = 3
        overview["EntryOffsetPct"] = 10
        overview["StopOffsetPct"] = 25
        overview["RR"] = 3
        overview["SymbolsCount"] = int(len(_m))
        overview["TotalTrades"] = int(_m["تعداد"].fillna(0).sum()) if "تعداد" in _m.columns else (int(len(trades_df)) if not trades_df.empty else 0)
        overview["AvgWinRatePct"] = float(_m["درصد_برد"].mean()) if "درصد_برد" in _m.columns else np.nan
        overview["AvgProfitFactor"] = float(_m["فاکتور_سود"].mean()) if "فاکتور_سود" in _m.columns else np.nan
        overview["AvgNetReturnPct"] = float(_m["بازده_خالص٪"].mean()) if "بازده_خالص٪" in _m.columns else np.nan
        overview["MedianNetReturnPct"] = float(_m["بازده_خالص٪"].median()) if "بازده_خالص٪" in _m.columns else np.nan
        overview["AvgMaxDrawdownPct"] = float(_m["حداکثر_افت٪"].mean()) if "حداکثر_افت٪" in _m.columns else np.nan

        # بهترین/بدترین نماد بر اساس بازده
        if "بازده_خالص٪" in _m.columns and "نماد" in _m.columns and len(_m) > 0:
            best_row = _m.sort_values("بازده_خالص٪", ascending=False).iloc[0]
            worst_row = _m.sort_values("بازده_خالص٪", ascending=True).iloc[0]
            overview["BestSymbol"] = str(best_row["نماد"])
            overview["BestNetReturnPct"] = float(best_row["بازده_خالص٪"])
            overview["WorstSymbol"] = str(worst_row["نماد"])
            overview["WorstNetReturnPct"] = float(worst_row["بازده_خالص٪"])
        else:
            overview["BestSymbol"] = ""
            overview["BestNetReturnPct"] = np.nan
            overview["WorstSymbol"] = ""
            overview["WorstNetReturnPct"] = np.nan

        overview_df = pd.DataFrame([overview])

        # --- معاملات: تست 1/2، شمارش‌ها ---
        if trades_df.empty:
            test_counts = pd.DataFrame(columns=["تست", "تعداد"])
            trades_by_symbol = pd.DataFrame(columns=["نماد", "تعداد"])
            trades_by_year_symbol = pd.DataFrame(columns=["نماد", "سال", "تعداد"])
        else:
            test_counts = trades_df.groupby("تست").size().reset_index(name="تعداد").sort_values("تست")
            trades_by_symbol = trades_df.groupby("نماد").size().reset_index(name="تعداد").sort_values("تعداد", ascending=False)
            trades_df["سال"] = trades_df["زمان_خروج"].dt.year.fillna(trades_df["زمان_ورود"].dt.year)
            trades_by_year_symbol = trades_df.groupby(["نماد", "سال"]).size().reset_index(name="تعداد").sort_values(["نماد", "سال"])

        # --- زون‌ها: تعداد ساخته‌شده/تریدشده ---
        if zones_df.empty:
            zone_stats = pd.DataFrame(columns=["نماد", "TotalZonesBuilt", "UniqueZonesTraded"])
        else:
            built = zones_df.groupby("نماد").size().reset_index(name="TotalZonesBuilt")
            traded = (trades_df.groupby("نماد")["ZoneID"].nunique().reset_index(name="UniqueZonesTraded")
                      if (not trades_df.empty and "ZoneID" in trades_df.columns) else
                      pd.DataFrame({"نماد": built["نماد"], "UniqueZonesTraded": 0}))
            zone_stats = built.merge(traded, on="نماد", how="left").fillna(0).sort_values("TotalZonesBuilt", ascending=False)

        # --- بازده سالانه/ماهانه برای هر نماد (با بازسازی اکویتی همان فرمول کد) ---
        def _equity_series_for_symbol(sym_trades: pd.DataFrame, reserve=0.15, risk_per_trade=0.01, start_equity=100000.0):
            if sym_trades.empty:
                return pd.DataFrame(columns=["زمان", "اکویتی"])
            t = sym_trades.copy()
            # ترتیب بر اساس زمان خروج
            t = t.sort_values("زمان_خروج")
            eq = start_equity
            rows = []
            for _, r in t.iterrows():
                res_r = float(r.get("نتیجه_R", 0.0))
                usable = eq * (1.0 - reserve)
                risk_amt = usable * risk_per_trade
                eq = eq + risk_amt * res_r
                rows.append({"زمان": r["زمان_خروج"], "اکویتی": eq})
            return pd.DataFrame(rows)

        annual_rows=[]
        monthly_rows=[]
        avg_rows=[]
        if not trades_df.empty:
            for sym, g in trades_df.groupby("نماد"):
                es = _equity_series_for_symbol(g, reserve=0.15, risk_per_trade=0.01, start_equity=100000.0)
                if es.empty:
                    continue
                es = es.dropna(subset=["زمان"])
                if es.empty:
                    continue
                es = es.sort_values("زمان")
                es["سال"] = es["زمان"].dt.year
                es["ماه"] = es["زمان"].dt.to_period("M").astype(str)

                # سالانه
                for y, gy in es.groupby("سال"):
                    eq_end = float(gy["اکویتی"].iloc[-1])
                    # equity start = last equity before this year, or 100000 if first year
                    prev = es[es["زمان"].dt.year < y]
                    eq_start = float(prev["اکویتی"].iloc[-1]) if not prev.empty else 100000.0
                    ret = (eq_end - eq_start) / eq_start * 100.0 if eq_start != 0 else 0.0
                    annual_rows.append({"نماد": sym, "سال": int(y), "بازده_سالانه٪": round(ret, 2), "اکویتی_شروع": round(eq_start, 2), "اکویتی_پایان": round(eq_end, 2)})

                # ماهانه
                for mth, gm in es.groupby("ماه"):
                    eq_end = float(gm["اکویتی"].iloc[-1])
                    # equity start = last equity before this month, or 100000 if first month
                    prev = es[es["زمان"] < pd.to_datetime(mth + "-01")]
                    eq_start = float(prev["اکویتی"].iloc[-1]) if not prev.empty else 100000.0
                    ret = (eq_end - eq_start) / eq_start * 100.0 if eq_start != 0 else 0.0
                    monthly_rows.append({"نماد": sym, "ماه": mth, "بازده_ماهانه٪": round(ret, 2), "اکویتی_شروع": round(eq_start, 2), "اکویتی_پایان": round(eq_end, 2)})

        annual_df = pd.DataFrame(annual_rows).sort_values(["نماد","سال"]) if annual_rows else pd.DataFrame(columns=["نماد","سال","بازده_سالانه٪","اکویتی_شروع","اکویتی_پایان"])
        monthly_df = pd.DataFrame(monthly_rows).sort_values(["نماد","ماه"]) if monthly_rows else pd.DataFrame(columns=["نماد","ماه","بازده_ماهانه٪","اکویتی_شروع","اکویتی_پایان"])

        # میانگین‌ها (سالانه/ماهانه برای هر نماد)
        if not annual_df.empty:
            a = annual_df.groupby("نماد")["بازده_سالانه٪"].mean().reset_index(name="میانگین_بازده_سالانه٪")
        else:
            a = pd.DataFrame(columns=["نماد","میانگین_بازده_سالانه٪"])
        if not monthly_df.empty:
            m = monthly_df.groupby("نماد")["بازده_ماهانه٪"].mean().reset_index(name="میانگین_بازده_ماهانه٪")
        else:
            m = pd.DataFrame(columns=["نماد","میانگین_بازده_ماهانه٪"])
        avg_df = a.merge(m, on="نماد", how="outer").sort_values("نماد")

        # --- دلایل (از reasons_df) ---
        reasons_out = reasons_df.copy() if not reasons_df.empty else pd.DataFrame(columns=["نماد","دلیل","تعداد"])

        # --- تحلیل حرفه‌ای توزیع/زمان معاملات ---
        dist_sheets = distribution_sheets(trades_df)

        # --- فایل خلاصه (فقط شاخص‌های کلیدی درخواستی) ---
        summary_df = metrics_df.copy()
        if "درصد_برد" in summary_df.columns:
            summary_df["درصد_لاس"] = 100.0 - pd.to_numeric(summary_df["درصد_برد"], errors="coerce").fillna(0.0)
        else:
            summary_df["درصد_لاس"] = np.nan

        summary_cols = [
            "نماد", "درصد_برد", "درصد_لاس", "بازده_خالص٪", "میانگین_R", "حداکثر_افت٪", "فاکتور_سود", "تعداد"
        ]
        for c in summary_cols:
            if c not in summary_df.columns:
                summary_df[c] = np.nan
        summary_out = summary_df[summary_cols].copy()

        # --- شیت مقایسه‌ی حالت‌های نقطه‌ی ورود ---
        cmp_out = None
        if COMPARE_ENTRY_MODES and entry_mode_rows:
            cmp_df = pd.concat(entry_mode_rows, ignore_index=True)
            agg_rows=[]
            for mode, g in cmp_df.groupby("حالت_ورود", sort=False):
                n = float(g["تعداد"].sum())
                w = g["تعداد"].astype(float)
                wr = float((g["درصد_برد"]*w).sum()/n) if n>0 else 0.0
                ar = float((g["میانگین_R"]*w).sum()/n) if n>0 else 0.0
                agg_rows.append({
                    "حالت_ورود": mode, "نماد": "کل", "تعداد": int(n),
                    "درصد_برد": round(wr,2), "میانگین_R": round(ar,3),
                    "بازده_خالص٪": round(float(g["بازده_خالص٪"].mean()),2),
                    "حداکثر_افت٪": round(float(g["حداکثر_افت٪"].max()),2),
                    "فاکتور_سود": round(float(g["فاکتور_سود"].mean()),3),
                })
            cmp_out = pd.concat([cmp_df, pd.DataFrame(agg_rows)], ignore_index=True)
            cmp_cols=["حالت_ورود","نماد","تعداد","درصد_برد","میانگین_R","بازده_خالص٪","حداکثر_افت٪","فاکتور_سود"]
            cmp_out = cmp_out[[c for c in cmp_cols if c in cmp_out.columns]]
            cmp_out = cmp_out.sort_values(["حالت_ورود","نماد"]).reset_index(drop=True)

        with pd.ExcelWriter(summary_path, engine="openpyxl") as sw:
            summary_out.to_excel(sw, sheet_name="خلاصه", index=False)
            if cmp_out is not None:
                cmp_out.to_excel(sw, sheet_name="مقایسه_نقطه_ورود", index=False)

        # --- خروجی نهایی (جزئیات کامل) ---
        with pd.ExcelWriter(detailed_path, engine="openpyxl") as writer:
            overview_df.to_excel(writer, sheet_name="خلاصه_کلی", index=False)
            sym_metrics.to_excel(writer, sheet_name="نتایج_اعدادی", index=False)
            trades_by_symbol.to_excel(writer, sheet_name="معاملات_هر_نماد", index=False)
            trades_by_year_symbol.to_excel(writer, sheet_name="معاملات_سال_نماد", index=False)
            test_counts.to_excel(writer, sheet_name="تست1_تست2", index=False)
            zone_stats.to_excel(writer, sheet_name="زون‌ها", index=False)
            annual_df.to_excel(writer, sheet_name="بازده_سالانه", index=False)
            monthly_df.to_excel(writer, sheet_name="بازده_ماهانه", index=False)
            avg_df.to_excel(writer, sheet_name="میانگین_بازده", index=False)
            reasons_out.to_excel(writer, sheet_name="دلایل", index=False)
            for sheet_name, ddf in dist_sheets.items():
                safe_name = ("تحلیل_" + str(sheet_name))[:31]
                ddf.to_excel(writer, sheet_name=safe_name, index=False)

        print("جزئیات_حرفه‌ای.xlsx ساخته شد ✅")
    except Exception as e:
        print("⚠️ ساخت جزئیات_حرفه‌ای.xlsx ناموفق بود:", str(e))

    print("تمام شد ✅")
    print("خلاصه_نتایج.xlsx ساخته شد ✅ |", summary_path)
    print("جزئیات_حرفه‌ای.xlsx ساخته شد ✅ |", detailed_path)
    print("مسیر خروجی:", outdir)

if __name__ == "__main__":
    main()