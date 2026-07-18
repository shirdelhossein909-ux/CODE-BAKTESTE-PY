# -*- coding: utf-8 -*-
import os, glob, zipfile, io, json
import re
import numpy as np

from analysis_distribution import distribution_sheets
import pandas as pd

# استفاده از M15 برای رفع ابهام داخل کندل — طبق تصمیم: خاموش.
# معاملات مبهم (TP و استاپ در یک کندل H4) بدبینانه استاپ حساب می‌شوند
# و تعداد/اثرشان در ستون‌های «مبهم_...» گزارش می‌شود.
USE_M15 = False

# بازه‌ی بک‌تست: در صورت نیاز این دو خط را تغییر بده
BACKTEST_START = pd.Timestamp("2022-11-22")  # شروع دیتای FXCM
BACKTEST_END = None  # نمونه: pd.Timestamp("2024-12-31")؛ None یعنی تا انتهای دیتا

# هزینه‌های معاملاتی تقریبی (نسبت به اسپرد هر نماد؛ در صورت نیاز این دو عدد را ویرایش کن)
COMMISSION_SPREAD_MULT = 0.5       # کمیسیون رفت‌وبرگشت ≈ نصف اسپرد
SWAP_SPREAD_MULT_PER_NIGHT = 0.2   # سواپ ≈ ۲۰٪ اسپرد به ازای هر شب نگهداری پوزیشن

# مقایسه‌ی حالت‌های نقطه‌ی ورود در یک اجرا (شیت «مقایسه_نقطه_ورود» در خلاصه_نتایج.xlsx)
# اگر نمی‌خواهی و اجرا سریع‌تر شود، این را False کن.
COMPARE_ENTRY_MODES = False  # مقایسه‌ی نقطه‌ی ورود تمام شد؛ حالت نهایی: -50% وسط زون
ENTRY_MODES = {
    "-50% وسط زون": -0.50,
}
DEFAULT_ENTRY_OFF = -0.50  # حالت اصلی که گزارش‌های کامل با آن ساخته می‌شود

# مقایسه‌ی نسبت سود به ضرر (RR) — تمام شد؛ RR نهایی: 3
COMPARE_RR_MODES = False
RR_MODES = {
    "RR=3": 3.0,
}
DEFAULT_RR = 3.0  # حالت اصلی گزارش‌های کامل

# قانون «لغو سفارش در صورت دور شدن قیمت»: اگر قیمت بدون فعال کردن سفارش،
# به اندازه‌ی چند برابرِ ریسک از نقطه‌ی ورود دور شد، سفارش لغو و زون بی‌اعتبار می‌شود.
# چند آستانه در یک اجرا مقایسه می‌شود — شیت «مقایسه_لغو_دور»
COMPARE_DISTCANCEL_MODES = False  # نتیجه: قانون لغو دور شدن برایند را بدتر کرد؛ بدون قانون می‌مانیم
DISTCANCEL_MODES = {
    "بدون قانون": 0.0,
    "دور شدن 3R": 3.0,
    "دور شدن 4R": 4.0,
    "دور شدن 5R": 5.0,
}
DEFAULT_DIST_CANCEL_R = 0.0  # حالت اصلی گزارش‌های کامل (فعلاً بدون قانون تا مقایسه را ببینیم)

# فیلتر «حداقل اندازه‌ی زون»: اگر فاصله‌ی ورود تا استاپ کمتر از این ضریب از ATR باشد، معامله نمی‌شود.
# چند آستانه در یک اجرا مقایسه می‌شود — شیت «مقایسه_حداقل_زون»
COMPARE_MINRISK_MODES = False  # نتیجه: فیلتر کمکی نکرد؛ بدون فیلتر می‌مانیم
MINRISK_MODES = {
    "بدون فیلتر": 0.0,
    "ملایم 0.5xATR": 0.5,
    "متوسط 0.75xATR": 0.75,
    "سختگیر 1.0xATR": 1.0,
}
DEFAULT_MIN_RISK_ATR = 0.0  # حالت اصلی گزارش‌های کامل (فعلاً بدون فیلتر تا مقایسه را ببینیم)

# --- بک‌تست پرتفویی: شبیه‌سازی یک حساب مشترک برای همه‌ی نمادها (شیت‌های «پرتفوی») ---
PORTFOLIO_MAX_OPEN = 5              # حداکثر پوزیشن باز هم‌زمان در کل حساب
PORTFOLIO_RISK_PER_TRADE = 0.005    # ریسک هر معامله از اکویتی حساب (0.005 = نیم درصد، 0.01 = یک درصد)
PORTFOLIO_SYMBOLS = []              # خالی = همه‌ی نمادها؛ نمونه: ["AUDCAD","EURUSD","CHFJPY","XAUUSD","GBPCAD"]

# فایل «جزئیات_حرفه‌ای.xlsx» ساخته بشود یا نه (False = فقط خلاصه؛ سریع‌تر)
WRITE_DETAILS = False

# مقایسه‌ی «سقف اجرا» (شبیه ربات لایو): هر چارت حداکثر ۱ ترید باز + سقف کل.
# نتایج در شیت «مقایسه_سقف_اجرا»
COMPARE_EXECCAP_MODES = True
EXECCAP_MODES = {
    "بدون محدودیت": (0, 0),          # (سقف کل تریدهای باز, سقف هر چارت)
    "هر چارت 1 + سقف 3": (3, 1),
    "هر چارت 1 + سقف 5": (5, 1),
}

# مقایسه‌ی «محدودیت ضرر» — نتیجه: کمکی نکرد (فقط سود کمتر)؛ بدون محدودیت می‌مانیم
COMPARE_LOSSLIMIT_MODES = False
LOSSLIMIT_MODES = {
    "بدون محدودیت": (0, 0),
    "3 ضرر روز / 7 هفته": (3, 7),
    "2 ضرر روز / 5 هفته": (2, 5),
    "3 ضرر روز / 5 هفته": (3, 5),
}

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
def _smart_dt(d, t=None):
    """تبدیل تاریخ به datetime با تشخیص خودکار ترتیب روز/ماه (برای فرمت‌های مختلف بروکرها)."""
    s = d.astype(str).str.strip()
    if t is not None:
        s = s + " " + t.astype(str).str.strip()
    samp = s.head(500).str.extract(r"^(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})")
    dayfirst = False
    try:
        first = pd.to_numeric(samp[0], errors="coerce")
        if first.notna().any() and first.max() <= 31 and (first > 12).any():
            dayfirst = True
    except Exception:
        pass
    return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)


def read_mt_csv_from_bytes(b: bytes) -> pd.DataFrame:
    """خواندن CSV قیمت با تشخیص خودکار فرمت:
    - متاتریدر بدون سطر عنوان (date,time,o,h,l,c[,v])
    - فایل‌های دارای سطر عنوان (مثل FXCM): ستون‌های Open/High/Low/Close یا BidOpen/BidHigh/...
      و تاریخ به‌صورت دو ستون Date/Time یا یک ستون DateTime"""
    if b is None or len(b) == 0:
        raise ValueError("فایل CSV خالی است.")

    head = b[:2048].decode("utf-8", "ignore")
    first_line = head.splitlines()[0].lower() if head else ""
    has_header = any(k in first_line for k in ("open", "high", "low", "close"))

    if has_header:
        df = pd.read_csv(io.BytesIO(b))
        df.columns = [str(c).strip().lower().replace(" ", "") for c in df.columns]

        def pick(*names):
            for nm in names:
                if nm in df.columns:
                    return df[nm]
            return None

        o = pick("open", "bidopen"); h = pick("high", "bidhigh")
        l = pick("low", "bidlow");   c = pick("close", "bidclose")
        if o is None or h is None or l is None or c is None:
            raise ValueError("ستون‌های قیمت (Open/High/Low/Close یا BidOpen/...) پیدا نشد.")

        dcol = pick("date"); tcol = pick("time", "datetime", "timestamp", "gmttime")
        if dcol is not None and tcol is not None:
            tser = _smart_dt(dcol, tcol)
        elif dcol is not None:
            tser = _smart_dt(dcol)
        elif tcol is not None:
            tser = _smart_dt(tcol)
        else:
            tser = _smart_dt(df.iloc[:, 0])
    else:
        df = pd.read_csv(io.BytesIO(b), header=None)
        if df.shape[1] < 5:
            raise ValueError("فرمت CSV غیرمنتظره است (ستون کم).")
        c1 = pd.to_numeric(df.iloc[:, 1], errors="coerce")
        if c1.notna().mean() > 0.9:
            # ستون اول تاریخ+ساعت یکجا است
            tser = _smart_dt(df.iloc[:, 0])
            o, h, l, c = (df.iloc[:, k] for k in (1, 2, 3, 4))
        else:
            # فرمت کلاسیک متاتریدر: date,time,o,h,l,c
            if df.shape[1] < 6:
                raise ValueError("فرمت CSV غیرمنتظره است (ستون کم).")
            tser = _smart_dt(df.iloc[:, 0], df.iloc[:, 1])
            o, h, l, c = (df.iloc[:, k] for k in (2, 3, 4, 5))

    out = pd.DataFrame({
        "time": tser,
        "open": pd.to_numeric(o, errors="coerce"),
        "high": pd.to_numeric(h, errors="coerce"),
        "low":  pd.to_numeric(l, errors="coerce"),
        "close": pd.to_numeric(c, errors="coerce"),
    })
    out = out.dropna().sort_values("time").drop_duplicates("time").reset_index(drop=True)
    if out.empty:
        raise ValueError("هیچ سطر معتبری در CSV پیدا نشد (فرمت ناشناخته).")
    return out

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
        f15_list  = [n for n in names if n.endswith("-15.csv") or n.endswith("-M15.csv")]  # اختیاری

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
        m15 = read_mt_csv_from_bytes(z.read(f15_list[0])) if f15_list else None

    if h4.empty or d1.empty or w1.empty:
        raise ValueError(
            f"داده‌ی یکی از تایم‌فریم‌ها داخل ZIP خالی است: {zip_path} | "
            f"h4={len(h4)} d1={len(d1)} w1={len(w1)}"
        )

    return h4, d1, w1, m15

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
                 reserve=0.15, risk_per_trade=0.01, max_orders=3,
                 m15=None, min_risk_atr=0.0, dist_cancel_r=0.0, return_state=False):

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

    # برش انتهای بازه‌ی بک‌تست (اگر BACKTEST_END تنظیم شده باشد)
    if BACKTEST_END is not None:
        h4 = h4[h4["time"] <= BACKTEST_END].copy()
        d1 = d1[d1["time"] <= BACKTEST_END].copy()
        w1 = w1[w1["time"] <= BACKTEST_END].copy()
        if m15 is not None:
            m15 = m15[m15["time"] <= BACKTEST_END].copy()

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
        "رد_به_خاطر_زون_کوچک": 0,
        "رد_به_خاطر_سقف_سفارش": 0,
        "لغو_به_خاطر_هفتگی": 0,
        "لغو_به_خاطر_دور_شدن": 0,
        "لغو_به_خاطر_تست_سوم": 0,
        "انقضا_زون": 0,
        "جایگزینی_زون": 0,
        "ورود_انجام_شد": 0,
        "خروج_همزمان_حل_با_M15": 0,
        "خروج_همزمان_بدون_M15_استاپ_فرض": 0,
        "کندل_ورود_حل_با_M15": 0,
        "TP_کندل_ورود_بدون_M15": 0,
    }

    # --- آماده‌سازی M15 برای رفع ابهام داخل کندل H4 ---
    m15_t = m15_h = m15_l = None
    if USE_M15 and m15 is not None and not m15.empty:
        m15_t = m15["time"].values
        m15_h = m15["high"].astype(float).values
        m15_l = m15["low"].astype(float).values

    H4_SPAN = np.timedelta64(4, "h")

    def _m15_range(t_bar):
        if m15_t is None:
            return None
        t0 = t_bar.to_datetime64()
        i0 = int(np.searchsorted(m15_t, t0, side="left"))
        i1 = int(np.searchsorted(m15_t, t0 + H4_SPAN, side="left"))
        if i1 <= i0:
            return None
        return i0, i1

    def resolve_both_hit_m15(direction, sl, tp, t_bar):
        """وقتی در یک کندل H4 هم استاپ و هم حدسود لمس شده،
        با M15 مشخص می‌کند کدام اول بوده. اگر هر دو در یک کندل M15 بود: بدبینانه استاپ."""
        rng = _m15_range(t_bar)
        if rng is None:
            return None
        for j in range(rng[0], rng[1]):
            hi = m15_h[j]; lo = m15_l[j]
            if direction == "BUY":
                if lo <= sl: return "sl"
                if hi >= tp: return "tp"
            else:
                if hi >= sl: return "sl"
                if lo <= tp: return "tp"
        return None

    def resolve_entry_candle_m15(direction, entry, sl, tp, t_bar):
        """در کندل ورود: اول لحظه‌ی پر شدن سفارش را در M15 پیدا می‌کند،
        بعد فقط اتفاقات بعد از آن را می‌شمارد (سقف/کف قبل از ورود حساب نمی‌شود).
        در خودِ کندلِ پر شدن فقط استاپ پذیرفته می‌شود (بدبینانه).
        خروجی: sl / tp / open / nofill / None(=M15 نیست)"""
        rng = _m15_range(t_bar)
        if rng is None:
            return None
        filled = False
        for j in range(rng[0], rng[1]):
            hi = m15_h[j]; lo = m15_l[j]
            if not filled:
                if direction == "BUY" and lo <= entry:
                    filled = True
                    if lo <= sl:
                        return "sl"
                elif direction == "SELL" and hi >= entry:
                    filled = True
                    if hi >= sl:
                        return "sl"
                continue
            if direction == "BUY":
                if lo <= sl: return "sl"
                if hi >= tp: return "tp"
            else:
                if hi >= sl: return "sl"
                if lo <= tp: return "tp"
        return "open" if filled else "nofill"

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
        # تا وقتی فیلتر رنج «گرم» نشده (۲۰ کندل اول)، معامله ممنوع است
        if pd.isna(d1["range"].iloc[di-1]) or pd.isna(h4["range"].iloc[i-1]):
            continue

        dtr=int(d1["trend"].iloc[di-1])
        htr=int(h4["trend"].iloc[i-1])

        drg=bool(d1["range"].iloc[di-1])
        hrg=bool(h4["range"].iloc[i-1])

        # کندل بسته‌شده‌ی قبلی برای چک‌های لغو (هفتگی و دور شدن قیمت)
        o_prev=float(h4["open"].iloc[i-1]); c_prev=float(h4["close"].iloc[i-1])
        h_prev=float(h4["high"].iloc[i-1]); l_prev=float(h4["low"].iloc[i-1])

        # ---------- exits for already-open positions ----------
        still_open=[]
        for pos in open_pos:
            if pos["direction"] == "BUY":
                hit_sl = l <= pos["sl"]; hit_tp = h >= pos["tp"]
            else:
                hit_sl = h >= pos["sl"]; hit_tp = l <= pos["tp"]

            if hit_sl and hit_tp:
                # ابهام: هر دو در یک کندل H4 — با M15 ترتیب واقعی را پیدا کن
                res = resolve_both_hit_m15(pos["direction"], pos["sl"], pos["tp"], t)
                if res == "tp":
                    reasons["خروج_همزمان_حل_با_M15"] += 1
                    finalize_trade(pos, t, float(pos["tp"]), "هر دو در یک کندل: M15 → حدسود")
                elif res == "sl":
                    reasons["خروج_همزمان_حل_با_M15"] += 1
                    finalize_trade(pos, t, float(pos["sl"]), "هر دو در یک کندل: M15 → حدضرر")
                else:
                    reasons["خروج_همزمان_بدون_M15_استاپ_فرض"] += 1
                    finalize_trade(pos, t, float(pos["sl"]), "هر دو در یک کندل: حدضرر")
            elif hit_sl:
                finalize_trade(pos, t, float(pos["sl"]), "حدضرر")
            elif hit_tp:
                finalize_trade(pos, t, float(pos["tp"]), "حدسود")
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

            # فیلتر حداقل اندازه‌ی زون: فاصله‌ی ورود تا استاپ باید حداقل min_risk_atr برابر ATR باشد
            # (ATR از کندل قبلیِ بسته‌شده — بدون نگاه به آینده)
            if min_risk_atr > 0:
                atr_ref = h4["atr"].iloc[i-1]
                height = z.high() - z.low()
                risk_est = height * (1.0 + entry_off + sl_off)
                if pd.isna(atr_ref) or risk_est < min_risk_atr * float(atr_ref):
                    reasons["رد_به_خاطر_زون_کوچک"] += 1
                    set_final(zone_df, z.zone_id, "رد شد", "زون خیلی کوچک (استاپ نزدیک)", t)
                    log_event(events, t, symbol, z.zone_id, "Rejected", "SmallZone")
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

        # ---------- لغو به‌خاطر دور شدن قیمت بدون فعال شدن سفارش (اختیاری) ----------
        if dist_cancel_r > 0:
            for p in pending:
                if not p["active"] or p["filled"]:
                    continue
                if p["z"].direction == "BUY":
                    far = h_prev >= p["entry"] + dist_cancel_r * p["risk"]
                else:
                    far = l_prev <= p["entry"] - dist_cancel_r * p["risk"]
                if far:
                    p["active"] = False
                    p["cancel"] = "لغو: دور شدن قیمت"
                    reasons["لغو_به_خاطر_دور_شدن"] += 1
                    set_final(zone_df, p["z"].zone_id, "لغو شد",
                              f"قیمت {dist_cancel_r:g}R دور شد بدون ورود", t)
                    log_event(events, t, symbol, p["z"].zone_id, "Canceled", "FarAway")

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

            # کندل ورود: با M15 لحظه‌ی پر شدن و ترتیب استاپ/حدسود دقیق مشخص می‌شود
            res = resolve_entry_candle_m15(direction, p["entry"], pos["sl"], pos["tp"], t)
            if res == "sl":
                reasons["کندل_ورود_حل_با_M15"] += 1
                finalize_trade(pos, t, float(pos["sl"]), "حدضرر (کندل ورود، M15)")
            elif res == "tp":
                reasons["کندل_ورود_حل_با_M15"] += 1
                finalize_trade(pos, t, float(pos["tp"]), "حدسود (کندل ورود، M15)")
            elif res == "open":
                new_open_positions.append(pos)
            else:
                # M15 در دسترس نیست: رفتار قبلی (اگر هر دو لمس شد، بدبینانه استاپ)
                exited, exit_price, reason = check_exit(direction, pos["sl"], pos["tp"], h, l)
                if exited:
                    if reason == "حدسود":
                        reasons["TP_کندل_ورود_بدون_M15"] += 1
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
            "بازده_خالص٪":0.0,"حداکثر_افت٪":0.0,"میانگین_R":0.0,
            "مبهم_تعداد":0,"مبهم_درصد":0.0,
            "بازده٪_اگر_مبهم_TP":0.0,"بازده٪_اگر_مبهم_استاپ":0.0,
            "فاصله_استاپ_پیپ":0.0,"فاصله_TP_پیپ":0.0,
            "برد_همان_کندل_تعداد":0,"بازده٪_اگر_برد_همان_کندل_استاپ":0.0
        }
    else:
        wins=tdf.loc[tdf["نتیجه_R"]>0,"نتیجه_R"].sum()
        loss=tdf.loc[tdf["نتیجه_R"]<0,"نتیجه_R"].abs().sum()
        pf=float(wins/loss) if loss>0 else 999.0
        winrate=float((tdf["نتیجه_R"]>0).mean()*100.0)
        net=float((equity-100000.0)/100000.0*100.0)

        # --- تحلیل معاملات مبهم (TP و استاپ هر دو در یک کندل H4 لمس شده) ---
        amb = tdf["علت_خروج"].astype(str).str.contains("هر دو در یک کندل")
        n_amb = int(amb.sum())

        def _net_with(r_series):
            eq = 100000.0
            for r in r_series:
                eq += eq * (1.0 - reserve) * risk_per_trade * float(r)
            return round((eq - 100000.0) / 100000.0 * 100.0, 2)

        risk_d = (tdf["ورود"] - tdf["حدضرر"]).abs().replace(0, np.nan)
        r_if_tp = (tdf["حدسود"] - tdf["ورود"]).abs() / risk_d - commission_cost / risk_d
        rs_if_tp = tdf["نتیجه_R"].where(~amb, r_if_tp).fillna(tdf["نتیجه_R"])
        net_if_tp = _net_with(rs_if_tp)      # اگر همه‌ی مبهم‌ها TP بودند
        net_if_sl = _net_with(tdf["نتیجه_R"])  # مبهم‌ها همین حالا استاپ حساب شده‌اند

        # --- فاصله‌ی استاپ و حدسود به پیپ ---
        if symbol.endswith("JPY"):
            pip = 0.01
        elif symbol == "XAUUSD":
            pip = 0.1
        elif symbol == "XAGUSD":
            pip = 0.01
        else:
            pip = 0.0001
        sl_pips = float(((tdf["ورود"] - tdf["حدضرر"]).abs() / pip).mean())
        tp_pips = float(((tdf["حدسود"] - tdf["ورود"]).abs() / pip).mean())

        # --- بردهای همان‌کندل (خروج در همان کندل ورود) و سناریوی کف: همه استاپ ---
        same_win = (pd.to_datetime(tdf["زمان_ورود"]) == pd.to_datetime(tdf["زمان_خروج"])) & (tdf["نتیجه_R"] > 0)
        n_sw = int(same_win.sum())
        r_if_sl = -1.0 - commission_cost / risk_d
        rs_floor = tdf["نتیجه_R"].where(~same_win, r_if_sl).fillna(tdf["نتیجه_R"])
        net_floor = _net_with(rs_floor)

        metrics={
            "نماد":symbol,"تعداد":int(len(tdf)),"درصد_برد":round(winrate,2),
            "فاکتور_سود":round(pf,3),"بازده_خالص٪":round(net,2),
            "حداکثر_افت٪":round(max_dd*100.0,2),"میانگین_R":round(float(tdf["نتیجه_R"].mean()),3),
            "مبهم_تعداد":n_amb,"مبهم_درصد":round(n_amb/len(tdf)*100.0,2),
            "بازده٪_اگر_مبهم_TP":net_if_tp,"بازده٪_اگر_مبهم_استاپ":net_if_sl,
            "فاصله_استاپ_پیپ":round(sl_pips,1),"فاصله_TP_پیپ":round(tp_pips,1),
            "برد_همان_کندل_تعداد":n_sw,"بازده٪_اگر_برد_همان_کندل_استاپ":net_floor
        }

    reasons_df=pd.DataFrame([{"نماد":symbol,"دلیل":k,"تعداد":int(v)} for k,v in reasons.items()])
    metrics_df=pd.DataFrame([metrics])
    events_df=pd.DataFrame(events)

    z_reason = zone_df.groupby(["نماد","FinalStatus","FinalReason"]).size().reset_index(name="تعداد")
    z_reason["درصد"] = z_reason.groupby("نماد")["تعداد"].transform(lambda s: (s/s.sum()*100.0).round(2))

    if return_state:
        # وضعیت «همین الان» برای ربات لایو: سفارش‌های در انتظارِ فعال و پوزیشن‌های باز
        state = {
            "pending": [{
                "zone_id": p["z"].zone_id, "direction": p["z"].direction,
                "entry": float(p["entry"]), "sl": float(p["sl"]), "tp": float(p["tp"]),
                "placed_time": p["t"], "test": p["test"],
            } for p in pending if p["active"] and not p["filled"]],
            "open": [{
                "zone_id": pos["ZoneID"], "direction": pos["direction"],
                "entry": float(pos["eff_entry"]), "sl": float(pos["sl"]), "tp": float(pos["tp"]),
                "fill_time": pos["fill_time"],
            } for pos in open_pos],
            "armed": [],
            "فیلتر_توضیح": "",
        }

        # زون‌های «آماده‌باش» برای لایو: هنوز تاچ نشده‌اند ولی اگر قیمت وسط کندل بیاید،
        # سفارش از قبل داخل متاتریدر هست و جا نمی‌مانیم (معادل پر شدن داخل کندل در بک‌تست).
        if len(h4) >= 2 and len(d1) >= 2:
            t_last = h4["time"].iloc[-1]
            o_last = float(h4["open"].iloc[-1]); c_last = float(h4["close"].iloc[-1])
            drg_now = d1["range"].iloc[-1]; hrg_now = h4["range"].iloc[-1]
            dtr_now = int(d1["trend"].iloc[-1]); htr_now = int(h4["trend"].iloc[-1])
            warm = (not pd.isna(drg_now)) and (not pd.isna(hrg_now))
            filters_ok = warm and (not bool(drg_now)) and (not bool(hrg_now)) \
                and dtr_now != 0 and htr_now == dtr_now

            trend_txt = {1: "صعودی", -1: "نزولی", 0: "بدون روند"}
            state["فیلتر_توضیح"] = (
                f"روند روزانه: {trend_txt.get(dtr_now)} | روند H4: {trend_txt.get(htr_now)} | "
                f"رنج روزانه: {'بله' if warm and bool(drg_now) else 'خیر'} | "
                f"رنج H4: {'بله' if warm and bool(hrg_now) else 'خیر'}"
            )

            if filters_ok:
                wz_now = [wz for wz in w_z
                          if wz.created_time + pd.Timedelta(days=7) <= t_last
                          and (wz.superseded_time is None or t_last < wz.superseded_time)]
                armed = []
                for z in h_z:
                    if z.created_time >= t_last or z.expired or id(z) in used:
                        continue
                    if z.superseded_time is not None and t_last >= z.superseded_time:
                        continue
                    if z.touch_count != 0:
                        continue
                    opp_dir = "SELL" if z.direction == "BUY" else "BUY"
                    if any(body_overlaps_zone(o_last, c_last, wz) for wz in wz_now if wz.direction == opp_dir):
                        continue
                    height = z.high() - z.low()
                    if height <= 0:
                        continue
                    if z.direction == "BUY":
                        entry = z.proximal + entry_off * height
                        sl = z.distal - sl_off * height
                        risk = entry - sl
                        tp = entry + rr * risk
                    else:
                        entry = z.proximal - entry_off * height
                        sl = z.distal + sl_off * height
                        risk = sl - entry
                        tp = entry - rr * risk
                    if risk <= 0:
                        continue
                    armed.append({"zone_id": z.zone_id, "direction": z.direction,
                                  "entry": float(entry), "sl": float(sl), "tp": float(tp),
                                  "placed_time": t_last, "test": 0,
                                  "dist": float(abs(c_last - z.proximal))})
                # نزدیک‌ترین زون‌ها به قیمت، تا سقف سفارش هم‌زمانِ هر نماد
                armed.sort(key=lambda a: a["dist"])
                n_slots = max(0, max_orders - len(state["pending"]))
                state["armed"] = armed[:n_slots]

        return metrics_df, reasons_df, tdf, zone_df, events_df, z_reason, state

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
def _aggregate_mode_rows(rows, mode_col):
    """جدول مقایسه‌ی حالت‌ها: ردیف هر نماد + ردیف «کل» برای هر حالت."""
    cmp_df = pd.concat(rows, ignore_index=True)
    agg_rows = []
    for mode, g in cmp_df.groupby(mode_col, sort=False):
        n = float(g["تعداد"].sum())
        w = g["تعداد"].astype(float)
        wr = float((g["درصد_برد"] * w).sum() / n) if n > 0 else 0.0
        ar = float((g["میانگین_R"] * w).sum() / n) if n > 0 else 0.0
        agg_rows.append({
            mode_col: mode, "نماد": "کل", "تعداد": int(n),
            "درصد_برد": round(wr, 2), "میانگین_R": round(ar, 3),
            "بازده_خالص٪": round(float(g["بازده_خالص٪"].mean()), 2),
            "حداکثر_افت٪": round(float(g["حداکثر_افت٪"].max()), 2),
            "فاکتور_سود": round(float(g["فاکتور_سود"].mean()), 3),
        })
    out = pd.concat([cmp_df, pd.DataFrame(agg_rows)], ignore_index=True)
    cols = [mode_col, "نماد", "تعداد", "درصد_برد", "میانگین_R", "بازده_خالص٪", "حداکثر_افت٪", "فاکتور_سود"]
    out = out[[c for c in cols if c in out.columns]]
    return out.sort_values([mode_col, "نماد"]).reset_index(drop=True)

def portfolio_replay(trades_df, start_equity=100000.0, reserve=0.15, risk_per_trade=None,
                     max_open=None, symbols=None, max_losses_day=0, max_losses_week=0,
                     per_symbol_max_open=0):
    """شبیه‌سازی «یک حساب مشترک» روی معاملات همه‌ی نمادها:
    معامله‌ها به ترتیب زمان ورود اجرا می‌شوند، ریسک هر معامله ۱٪ از اکویتی لحظه‌ای حساب است،
    و اگر تعداد پوزیشن‌های باز به سقف برسد، معامله‌ی جدید گرفته نمی‌شود (رد می‌شود).
    منطق استراتژی را تغییر نمی‌دهد؛ فقط حساب را واقعی می‌کند."""
    import heapq

    if trades_df is None or trades_df.empty:
        return None
    t = trades_df.copy()
    if symbols:
        t = t[t["نماد"].isin(list(symbols))]
    if t.empty:
        return None

    t["زمان_ورود"] = pd.to_datetime(t["زمان_ورود"], errors="coerce")
    t["زمان_خروج"] = pd.to_datetime(t["زمان_خروج"], errors="coerce")
    t = t.dropna(subset=["زمان_ورود", "زمان_خروج", "نتیجه_R"]).sort_values("زمان_ورود")
    if t.empty:
        return None
    if max_open is None:
        max_open = PORTFOLIO_MAX_OPEN
    open_cap = max_open if (max_open and max_open > 0) else 10**9  # 0 = بدون سقف
    if risk_per_trade is None:
        risk_per_trade = PORTFOLIO_RISK_PER_TRADE

    from collections import deque

    eq = float(start_equity); peak = eq; max_dd = 0.0
    open_heap = []   # (زمان_خروج, ردیف, مبلغ_ریسک, R)
    curve = []
    taken = skipped = 0
    skipped_losslimit = 0
    skipped_persym = 0
    win_amt = loss_amt = 0.0
    rs = []
    seq = 0
    loss_times = deque()  # زمان بسته شدن ضررها (برای محدودیت روز/هفته)
    open_by_sym = {}      # تعداد ترید باز هر نماد (برای سقف هر چارت)

    def close_until(t_now):
        nonlocal eq, peak, max_dd, win_amt, loss_amt
        while open_heap and open_heap[0][0] <= t_now:
            xt, _, ramt, r, sym_ = heapq.heappop(open_heap)
            open_by_sym[sym_] = max(0, open_by_sym.get(sym_, 0) - 1)
            pnl = ramt * r
            eq += pnl
            if pnl > 0: win_amt += pnl
            else:
                loss_amt += -pnl
                loss_times.append(xt)
            rs.append(r)
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            curve.append((xt, eq))

    for sym, entry_t, exit_t, r in zip(t["نماد"], t["زمان_ورود"], t["زمان_خروج"], t["نتیجه_R"]):
        close_until(entry_t)
        if len(open_heap) >= open_cap:
            skipped += 1
            continue
        # سقف «هر چارت»: مثل ربات لایو، هر نماد هم‌زمان فقط N ترید باز
        if per_symbol_max_open and open_by_sym.get(sym, 0) >= per_symbol_max_open:
            skipped_persym += 1
            continue

        # سپر ایمنی: بعد از N ضرر در روز/هفته، ورود جدید ممنوع تا دوره عوض شود
        if max_losses_day or max_losses_week:
            cutoff = entry_t - pd.Timedelta(days=8)
            while loss_times and loss_times[0] < cutoff:
                loss_times.popleft()
            blocked = False
            if max_losses_day:
                ld = sum(1 for lt in loss_times if lt.date() == entry_t.date())
                if ld >= max_losses_day:
                    blocked = True
            if not blocked and max_losses_week:
                iso = entry_t.isocalendar()
                lw = sum(1 for lt in loss_times
                         if lt.isocalendar()[0] == iso[0] and lt.isocalendar()[1] == iso[1])
                if lw >= max_losses_week:
                    blocked = True
            if blocked:
                skipped_losslimit += 1
                continue

        ramt = eq * (1.0 - reserve) * risk_per_trade
        seq += 1
        heapq.heappush(open_heap, (exit_t, seq, ramt, float(r), sym))
        open_by_sym[sym] = open_by_sym.get(sym, 0) + 1
        taken += 1
    close_until(pd.Timestamp.max)

    wins = sum(1 for r in rs if r > 0)
    stats = pd.DataFrame([{
        "تعداد_نماد": int(t["نماد"].nunique()),
        "سقف_پوزیشن_همزمان": int(max_open),
        "ریسک_هر_معامله٪": round(risk_per_trade * 100.0, 2),
        "معاملات_انجام‌شده": int(taken),
        "معاملات_ردشده_به_خاطر_سقف": int(skipped),
        "ردشده_سقف_هر_چارت": int(skipped_persym),
        "ردشده_محدودیت_ضرر": int(skipped_losslimit),
        "درصد_برد": round(wins / len(rs) * 100.0, 2) if rs else 0.0,
        "فاکتور_سود": round(win_amt / loss_amt, 3) if loss_amt > 0 else 999.0,
        "بازده_خالص٪": round((eq - start_equity) / start_equity * 100.0, 2),
        "حداکثر_افت٪": round(max_dd * 100.0, 2),
        "اکویتی_نهایی": round(eq, 2),
    }])

    curve_df = pd.DataFrame(curve, columns=["زمان", "اکویتی"])

    def _period_returns(fmt):
        rows = []
        prev = start_equity
        c = curve_df.copy()
        c["دوره"] = c["زمان"].dt.to_period(fmt).astype(str)
        for per, g in c.groupby("دوره"):
            e = float(g["اکویتی"].iloc[-1])
            rows.append({"دوره": per, "بازده٪": round((e - prev) / prev * 100.0, 2),
                         "اکویتی_پایان": round(e, 2)})
            prev = e
        return pd.DataFrame(rows)

    return {"stats": stats,
            "yearly": _period_returns("Y").rename(columns={"دوره": "سال"}),
            "monthly": _period_returns("M").rename(columns={"دوره": "ماه"})}

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
    rr_mode_rows=[]
    minrisk_mode_rows=[]
    distcancel_mode_rows=[]
    max_data_time = None
    for zp in zip_files:
        base=os.path.basename(zp)
        symbol = base.split(".")[0]  # e.g. USDJPY.W.D.H4.zip => USDJPY
        h4,d1,w1,m15 = load_timeframes_from_zip(zp)
        if m15 is None and USE_M15:
            print(f"⚠️ {symbol}: فایل M15 داخل ZIP نیست؛ ابهام‌های داخل کندل بدبینانه (استاپ) حساب می‌شود.")
        if not h4.empty:
            end_t = pd.to_datetime(h4["time"].max(), errors="coerce")
            if pd.notna(end_t):
                max_data_time = end_t if max_data_time is None else max(max_data_time, end_t)

        mdf, rdf, tdf, zdf, edf, zreason = backtest_one(symbol, h4,d1,w1, years, spreads.get(symbol, 0.0),
                                                        entry_off=DEFAULT_ENTRY_OFF, rr=DEFAULT_RR, m15=m15,
                                                        min_risk_atr=DEFAULT_MIN_RISK_ATR)

        # اجرای RR های دیگر فقط برای مقایسه (گزارش‌های کامل با DEFAULT_RR است)
        if COMPARE_RR_MODES:
            for mode_name, rrv in RR_MODES.items():
                if abs(rrv - DEFAULT_RR) < 1e-12:
                    m_rr = mdf.copy()
                else:
                    m_rr = backtest_one(symbol, h4, d1, w1, years, spreads.get(symbol, 0.0),
                                        entry_off=DEFAULT_ENTRY_OFF, rr=rrv, m15=m15)[0].copy()
                m_rr["حالت_RR"] = mode_name
                rr_mode_rows.append(m_rr)

        # مقایسه‌ی آستانه‌های «لغو در صورت دور شدن قیمت»
        if COMPARE_DISTCANCEL_MODES:
            for mode_name, dcr in DISTCANCEL_MODES.items():
                if abs(dcr - DEFAULT_DIST_CANCEL_R) < 1e-12:
                    m_dc = mdf.copy()
                else:
                    m_dc = backtest_one(symbol, h4, d1, w1, years, spreads.get(symbol, 0.0),
                                        entry_off=DEFAULT_ENTRY_OFF, rr=DEFAULT_RR, m15=m15,
                                        dist_cancel_r=dcr)[0].copy()
                m_dc["قانون_لغو_دور"] = mode_name
                distcancel_mode_rows.append(m_dc)

        # مقایسه‌ی آستانه‌های فیلتر «حداقل اندازه‌ی زون»
        if COMPARE_MINRISK_MODES:
            for mode_name, mra in MINRISK_MODES.items():
                if abs(mra - DEFAULT_MIN_RISK_ATR) < 1e-12:
                    m_mr = mdf.copy()
                else:
                    m_mr = backtest_one(symbol, h4, d1, w1, years, spreads.get(symbol, 0.0),
                                        entry_off=DEFAULT_ENTRY_OFF, rr=DEFAULT_RR, m15=m15,
                                        min_risk_atr=mra)[0].copy()
                m_mr["حداقل_زون"] = mode_name
                minrisk_mode_rows.append(m_mr)

        # اجرای حالت‌های دیگر نقطه‌ی ورود فقط برای مقایسه (بقیه‌ی گزارش‌ها با حالت اصلی است)
        if COMPARE_ENTRY_MODES:
            for mode_name, eoff in ENTRY_MODES.items():
                if abs(eoff - DEFAULT_ENTRY_OFF) < 1e-12:
                    m_mode = mdf.copy()
                else:
                    m_mode = backtest_one(symbol, h4, d1, w1, years, spreads.get(symbol, 0.0),
                                          entry_off=eoff, m15=m15)[0].copy()
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
        end_t = max_data_time if BACKTEST_END is None else min(max_data_time, BACKTEST_END)
        years = max((end_t - BACKTEST_START).days / 365.25, 1.0 / 12.0)
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

        # --- تحلیل حرفه‌ای توزیع/زمان معاملات (فقط اگر فایل جزئیات خواسته شده) ---
        dist_sheets = distribution_sheets(trades_df) if WRITE_DETAILS else {}

        # --- فایل خلاصه (فقط شاخص‌های کلیدی درخواستی) ---
        summary_df = metrics_df.copy()
        if "درصد_برد" in summary_df.columns:
            summary_df["درصد_لاس"] = 100.0 - pd.to_numeric(summary_df["درصد_برد"], errors="coerce").fillna(0.0)
        else:
            summary_df["درصد_لاس"] = np.nan

        summary_cols = [
            "نماد", "درصد_برد", "درصد_لاس", "بازده_خالص٪", "میانگین_R", "حداکثر_افت٪", "فاکتور_سود", "تعداد",
            "مبهم_تعداد", "مبهم_درصد", "بازده٪_اگر_مبهم_TP", "بازده٪_اگر_مبهم_استاپ",
            "فاصله_استاپ_پیپ", "فاصله_TP_پیپ",
            "برد_همان_کندل_تعداد", "بازده٪_اگر_برد_همان_کندل_استاپ"
        ]
        for c in summary_cols:
            if c not in summary_df.columns:
                summary_df[c] = np.nan
        summary_out = summary_df[summary_cols].copy()

        # --- شیت‌های مقایسه (نقطه‌ی ورود / RR) ---
        cmp_out = _aggregate_mode_rows(entry_mode_rows, "حالت_ورود") if (COMPARE_ENTRY_MODES and entry_mode_rows) else None
        rr_out = _aggregate_mode_rows(rr_mode_rows, "حالت_RR") if (COMPARE_RR_MODES and rr_mode_rows) else None
        mr_out = _aggregate_mode_rows(minrisk_mode_rows, "حداقل_زون") if (COMPARE_MINRISK_MODES and minrisk_mode_rows) else None
        dc_out = _aggregate_mode_rows(distcancel_mode_rows, "قانون_لغو_دور") if (COMPARE_DISTCANCEL_MODES and distcancel_mode_rows) else None

        # --- شبیه‌سازی حساب مشترک (پرتفوی) ---
        port = None
        try:
            port = portfolio_replay(trades_df, symbols=(PORTFOLIO_SYMBOLS or None))
        except Exception as e:
            print("⚠️ شبیه‌سازی پرتفوی ناموفق بود:", str(e))

        # --- مقایسه‌ی «سقف اجرا» (شبیه ربات لایو) روی همان حساب مشترک ---
        ec_out = None
        if COMPARE_EXECCAP_MODES:
            try:
                ec_rows = []
                for label, (mo, ps) in EXECCAP_MODES.items():
                    pr = portfolio_replay(trades_df, symbols=(PORTFOLIO_SYMBOLS or None),
                                          max_open=mo, per_symbol_max_open=ps)
                    if pr is None:
                        continue
                    s = pr["stats"].copy()
                    s.insert(0, "سقف_اجرا", label)
                    m = pr["monthly"]
                    s["بدترین_ماه٪"] = round(float(m["بازده٪"].min()), 2) if not m.empty else 0.0
                    s["ماه‌های_منفی"] = int((m["بازده٪"] < 0).sum()) if not m.empty else 0
                    ec_rows.append(s)
                if ec_rows:
                    ec_out = pd.concat(ec_rows, ignore_index=True)
            except Exception as e:
                print("⚠️ مقایسه‌ی سقف اجرا ناموفق بود:", str(e))

        # --- مقایسه‌ی محدودیت‌های ضرر (سپر ایمنی) روی همان حساب مشترک ---
        ll_out = None
        if COMPARE_LOSSLIMIT_MODES:
            try:
                ll_rows = []
                for label, (ld, lw) in LOSSLIMIT_MODES.items():
                    pr = portfolio_replay(trades_df, symbols=(PORTFOLIO_SYMBOLS or None),
                                          max_losses_day=ld, max_losses_week=lw)
                    if pr is None:
                        continue
                    s = pr["stats"].copy()
                    s.insert(0, "محدودیت", label)
                    # بدترین ماه هر حالت هم برای قضاوت مهم است
                    m = pr["monthly"]
                    s["بدترین_ماه٪"] = round(float(m["بازده٪"].min()), 2) if not m.empty else 0.0
                    s["ماه‌های_منفی"] = int((m["بازده٪"] < 0).sum()) if not m.empty else 0
                    ll_rows.append(s)
                if ll_rows:
                    ll_out = pd.concat(ll_rows, ignore_index=True)
            except Exception as e:
                print("⚠️ مقایسه‌ی محدودیت ضرر ناموفق بود:", str(e))

        with pd.ExcelWriter(summary_path, engine="openpyxl") as sw:
            summary_out.to_excel(sw, sheet_name="خلاصه", index=False)
            if cmp_out is not None:
                cmp_out.to_excel(sw, sheet_name="مقایسه_نقطه_ورود", index=False)
            if rr_out is not None:
                rr_out.to_excel(sw, sheet_name="مقایسه_RR", index=False)
            if mr_out is not None:
                mr_out.to_excel(sw, sheet_name="مقایسه_حداقل_زون", index=False)
            if dc_out is not None:
                dc_out.to_excel(sw, sheet_name="مقایسه_لغو_دور", index=False)
            if port is not None:
                port["stats"].to_excel(sw, sheet_name="پرتفوی", index=False)
                port["yearly"].to_excel(sw, sheet_name="پرتفوی_سالانه", index=False)
                port["monthly"].to_excel(sw, sheet_name="پرتفوی_ماهانه", index=False)
            if ec_out is not None:
                ec_out.to_excel(sw, sheet_name="مقایسه_سقف_اجرا", index=False)
            if ll_out is not None:
                ll_out.to_excel(sw, sheet_name="مقایسه_محدودیت_ضرر", index=False)

        # --- خروجی نهایی (جزئیات کامل) — فقط اگر WRITE_DETAILS روشن باشد ---
        if WRITE_DETAILS:
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