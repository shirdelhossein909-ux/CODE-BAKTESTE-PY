# CODE-BAKTESTE-PY

A multi-timeframe **supply/demand zone backtester** for forex pairs and metals (XAUUSD, XAGUSD), built with pandas/NumPy. It reads MetaTrader-exported price history, simulates a zone-based limit-order strategy, and produces detailed Excel reports (in Persian) including distribution and time-behavior analytics.

## How it works

The strategy operates on three timeframes per symbol:

- **Weekly (W1)** — builds higher-timeframe supply/demand zones used as a filter.
- **Daily (D1)** — trend detection (from swing points) and range filter (ATR-based).
- **4-hour (H4)** — builds the tradeable zones, places pending limit orders, and manages positions candle by candle.

Zones are detected from base/consolidation candles, deduplicated by overlap, and tracked through a full lifecycle (touch 1, touch 2, order placement, fill, cancel, expiry) with an event log and a final status/reason per zone.

Key parameters (see `backtest_one` in `run_backtest.py`):

| Parameter | Default |
|---|---|
| Backtest start | 2023-01-01 (through end of available data) |
| Starting equity | 100,000 |
| Risk per trade | 1% of usable equity |
| Reserve capital | 15% |
| Reward:risk | 3.0 |
| Entry offset | default 10% of zone height inside the zone (past the proximal line); the summary report also compares −10%/−25%/−50% entries side by side |
| Stop-loss offset | 25% of zone height beyond the distal line, away from price |
| Max simultaneous orders | 3 |
| Costs | commission ≈ 0.5×spread (round-trip) + swap ≈ 0.2×spread per night held; per-symbol spreads defined in `main()` |

The backtest avoids look-ahead bias: trend/range filters and the weekly-cancel check use only closed candles, zones activate after their confirmation candle closes, and overlapping-zone dedup is point-in-time (a newer zone replaces older ones only from its own creation time).

## Files

- **`run_backtest.py`** — main script: data loading, indicators (ATR, swing trend, range filter), zone construction, the backtest engine, portfolio/equity accounting, versioned change review against a previous run's baseline, and Excel report generation.
- **`analysis_distribution.py`** — post-trade analytics only (no strategy logic): R-multiple histograms, win/loss streaks, hold-time stats, weekday/hour/month/season distributions, weekday×hour heatmap, rolling 3-month performance, activity metrics, a stability score, and a managerial summary. Consumed by `run_backtest.py` via `distribution_sheets()`.

## Input data

The script expects one ZIP file per symbol in `%USERPROFILE%\Desktop\0` (e.g. `USDJPY.W.D.H4.zip` — the symbol is taken from the part before the first dot). Each ZIP must contain three MetaTrader CSV exports (no header row; columns: date, time, open, high, low, close[, volume]):

- `*-240.csv` — H4
- `*-1D.csv` — daily
- `*-1W.csv` — weekly

Change the `datadir` path in `main()` if your data lives elsewhere.

## Output

Reports are written to a `خروجی` ("output") folder next to the script:

- **`خلاصه_نتایج.xlsx`** — per-symbol summary: win %, net return %, average R, max drawdown %, profit factor, trade count.
- **`جزئیات_حرفه‌ای.xlsx`** — multi-sheet detailed report: overview, per-symbol metrics, trades by symbol/year, zone statistics, annual/monthly returns, rejection reasons, plus all distribution-analysis sheets.

If a previous version's results are found in a sibling folder, the metrics sheet also includes delta columns comparing this run against that baseline.

## Requirements

- Python 3.9+
- Required: `pandas`, `numpy`, `openpyxl`
- Optional: `matplotlib` (plots), `reportlab` + `arabic-reshaper` + `python-bidi` (Persian PDF journal — not produced in the current version)

```bash
pip install pandas numpy openpyxl
python run_backtest.py
```

---

## معرفی (فارسی)

این پروژه یک بک‌تستر چندتایم‌فریمی مبتنی بر **زون‌های عرضه و تقاضا** برای جفت‌ارزهای فارکس و فلزات است. داده‌های خروجی متاتریدر (H4، روزانه و هفتگی) به‌صورت ZIP از پوشه‌ی `Desktop\0` خوانده می‌شود، استراتژی از ابتدای ۲۰۲۳ شبیه‌سازی می‌شود و نتایج در پوشه‌ی «خروجی» در دو فایل اکسل ذخیره می‌گردد:

- **خلاصه_نتایج.xlsx** — شاخص‌های کلیدی هر نماد (درصد برد، بازده خالص، میانگین R، حداکثر افت، فاکتور سود، تعداد معاملات)
- **جزئیات_حرفه‌ای.xlsx** — گزارش کامل شامل نتایج اعدادی، معاملات، زون‌ها، بازده سالانه/ماهانه، دلایل حذف زون‌ها و تحلیل‌های توزیع و رفتار زمانی معاملات

پارامترهای اصلی: ریسک هر معامله ۱٪، سرمایه‌ی رزرو ۱۵٪، نسبت سود به ضرر ۳، حداکثر ۳ سفارش هم‌زمان.
