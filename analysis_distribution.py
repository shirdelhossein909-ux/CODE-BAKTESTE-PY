# -*- coding: utf-8 -*-
"""Distribution and time-behavior analytics for backtest outputs.

This module intentionally does **not** change strategy logic.
It only consumes generated trade tables and produces extra statistical views.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
except Exception:  # optional plotting dependency
    plt = None


WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_ORDER = list(range(1, 13))
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
MONTH_PERIOD_ORDER = ["EarlyMonth", "MidMonth", "LateMonth"]


@dataclass
class DistributionArtifacts:
    summary: pd.DataFrame
    by_symbol: pd.DataFrame
    by_test: pd.DataFrame
    r_histogram: pd.DataFrame
    hold_time: pd.DataFrame
    streaks: pd.DataFrame
    weekday_distribution: pd.DataFrame
    hour_distribution: pd.DataFrame
    weekday_hour_heatmap: pd.DataFrame
    monthly_distribution: pd.DataFrame
    season_distribution: pd.DataFrame
    year_period_distribution: pd.DataFrame
    intertrade_hours: pd.DataFrame
    time_behavior_summary: pd.DataFrame
    rolling_3m: pd.DataFrame
    activity_metrics: pd.DataFrame
    stability_score: pd.DataFrame
    managerial_summary: pd.DataFrame


def _safe_quantiles(s: pd.Series, q: List[float]) -> Dict[str, float]:
    if s.empty:
        return {f"q{int(x * 100)}": np.nan for x in q}
    out: Dict[str, float] = {}
    qs = s.quantile(q)
    for x in q:
        out[f"q{int(x * 100)}"] = float(qs.loc[x])
    return out


def _streak_table(r_values: pd.Series) -> pd.DataFrame:
    if r_values.empty:
        return pd.DataFrame(columns=["نوع", "بیشترین_رشته"])

    wins = (r_values > 0).tolist()
    max_win = max_loss = cur_win = cur_loss = 0

    for is_win in wins:
        if is_win:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_win = max(max_win, cur_win)
        max_loss = max(max_loss, cur_loss)

    return pd.DataFrame(
        [
            {"نوع": "برد", "بیشترین_رشته": int(max_win)},
            {"نوع": "باخت/غیربرد", "بیشترین_رشته": int(max_loss)},
        ]
    )


def _time_columns(tdf: pd.DataFrame) -> pd.DataFrame:
    out = tdf.copy()
    if "زمان_ورود" in out.columns:
        out["زمان_ورود"] = pd.to_datetime(out["زمان_ورود"], errors="coerce")
    if "زمان_خروج" in out.columns:
        out["زمان_خروج"] = pd.to_datetime(out["زمان_خروج"], errors="coerce")

    if "زمان_ورود" in out.columns:
        out = out.dropna(subset=["زمان_ورود"]).copy()
        out["entry_weekday"] = out["زمان_ورود"].dt.day_name()
        out["entry_hour"] = out["زمان_ورود"].dt.hour
        out["entry_month"] = out["زمان_ورود"].dt.month
        out["entry_day"] = out["زمان_ورود"].dt.day
        out["entry_year"] = out["زمان_ورود"].dt.year
        out["entry_period"] = np.where(
            out["entry_day"] <= 10,
            "EarlyMonth",
            np.where(out["entry_day"] >= 21, "LateMonth", "MidMonth"),
        )

        season_map = {
            12: "Winter", 1: "Winter", 2: "Winter",
            3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer",
            9: "Autumn", 10: "Autumn", 11: "Autumn",
        }
        out["season"] = out["entry_month"].map(season_map)
        out["entry_month_period"] = out["زمان_ورود"].dt.to_period("M")
        out["entry_date"] = out["زمان_ورود"].dt.floor("D")

    if {"زمان_ورود", "زمان_خروج"}.issubset(out.columns):
        out["مدت_نگهداری_ساعت"] = (
            (out["زمان_خروج"] - out["زمان_ورود"]).dt.total_seconds() / 3600.0
        )

    return out


def _distribution_table(series: pd.Series, order: Optional[List] = None, label: str = "bucket") -> pd.DataFrame:
    if series.empty:
        return pd.DataFrame(columns=[label, "تعداد", "درصد"])

    counts = series.value_counts(dropna=False)
    if order is not None:
        counts = counts.reindex(order, fill_value=0)

    total = counts.sum()
    return pd.DataFrame(
        {
            label: counts.index,
            "تعداد": counts.values,
            "درصد": np.where(total > 0, counts.values / total * 100.0, 0.0),
        }
    )


def _seasonality_interpretation(
    monthly: pd.DataFrame,
    season: pd.DataFrame,
    period: pd.DataFrame,
    weekday: pd.DataFrame,
    hour: pd.DataFrame,
) -> pd.DataFrame:
    def _top_msg(df: pd.DataFrame, key_col: str, title: str) -> str:
        if df.empty or df["تعداد"].sum() == 0:
            return f"{title}: داده‌ای موجود نیست"
        row = df.sort_values("تعداد", ascending=False).iloc[0]
        return (
            f"{title}: بیشترین در {row[key_col]} با {int(row['تعداد'])} ترید "
            f"({row['درصد']:.2f}%)"
        )

    def _spread_msg(df: pd.DataFrame, title: str) -> str:
        if df.empty or df["تعداد"].sum() == 0:
            return f"{title}: داده‌ای موجود نیست"
        mx = df["تعداد"].max()
        mn = df["تعداد"].replace(0, np.nan).min()
        spread = (mx / mn) if (pd.notna(mn) and mn > 0) else np.inf
        level = "بالا" if spread >= 2.0 else ("متوسط" if spread >= 1.4 else "کم")
        return f"{title}: نسبت بیشینه به کمینه={spread:.2f} (تمرکز {level})"

    rows = [
        {"موضوع": "ماه", "نتیجه": _top_msg(monthly, "month", "فعالیت ماهانه")},
        {"موضوع": "ماه", "نتیجه": _spread_msg(monthly, "پراکندگی ماهانه")},
        {"موضوع": "فصل", "نتیجه": _top_msg(season, "season", "فعالیت فصلی")},
        {"موضوع": "فصل", "نتیجه": _spread_msg(season, "پراکندگی فصلی")},
        {"موضوع": "اوایل/اواخر ماه", "نتیجه": _top_msg(period, "period", "رفتار ماه")},
        {"موضوع": "روز هفته", "نتیجه": _top_msg(weekday, "weekday", "فعالیت روزانه")},
        {"موضوع": "ساعت", "نتیجه": _top_msg(hour, "hour", "فعالیت ساعتی")},
    ]
    return pd.DataFrame(rows)


def _rolling_3m_stats(tdf: pd.DataFrame) -> pd.DataFrame:
    if "entry_month_period" not in tdf.columns or tdf.empty:
        return pd.DataFrame(columns=["window_end", "trade_count_3m", "win_rate_pct_3m", "avg_r_3m"])

    monthly = (
        tdf.groupby("entry_month_period")
        .agg(
            trade_count=("entry_month_period", "size"),
            win_rate_pct=("نتیجه_R", lambda s: (pd.to_numeric(s, errors="coerce") > 0).mean() * 100.0),
            avg_r=("نتیجه_R", lambda s: pd.to_numeric(s, errors="coerce").mean()),
        )
        .sort_index()
    )

    if monthly.empty:
        return pd.DataFrame(columns=["window_end", "trade_count_3m", "win_rate_pct_3m", "avg_r_3m"])

    all_months = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    monthly = monthly.reindex(all_months, fill_value=0.0)

    monthly["win_w"] = monthly["win_rate_pct"] * monthly["trade_count"]
    monthly["r_w"] = monthly["avg_r"].fillna(0.0) * monthly["trade_count"]

    roll_count = monthly["trade_count"].rolling(3, min_periods=1).sum()
    roll_win_w = monthly["win_w"].rolling(3, min_periods=1).sum()
    roll_r_w = monthly["r_w"].rolling(3, min_periods=1).sum()

    out = pd.DataFrame(
        {
            "window_end": all_months.astype(str),
            "trade_count_3m": roll_count.values,
            "win_rate_pct_3m": np.where(roll_count.values > 0, roll_win_w.values / roll_count.values, np.nan),
            "avg_r_3m": np.where(roll_count.values > 0, roll_r_w.values / roll_count.values, np.nan),
        }
    )

    first = out.iloc[0]
    last = out.iloc[-1]
    trade_trend = "افزایشی" if last["trade_count_3m"] > first["trade_count_3m"] else ("کاهشی" if last["trade_count_3m"] < first["trade_count_3m"] else "خنثی")
    out["activity_trend"] = trade_trend
    return out


def _activity_metrics(tdf: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "AverageTradesPerMonth",
        "AverageTradesPerWeek",
        "AverageTradesPerDay",
        "TradeActiveDaysPct",
        "LongestNoTradeDays",
    ]
    if "زمان_ورود" not in tdf.columns or tdf.empty:
        return pd.DataFrame([{c: np.nan for c in cols}])

    et = pd.to_datetime(tdf["زمان_ورود"], errors="coerce").dropna().sort_values()
    if et.empty:
        return pd.DataFrame([{c: np.nan for c in cols}])

    start = et.min().floor("D")
    end = et.max().floor("D")
    total_days = int((end - start).days + 1)
    total_weeks = max(total_days / 7.0, 1e-9)
    month_index = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M")
    total_months = max(len(month_index), 1)

    daily_counts = et.dt.floor("D").value_counts().sort_index()
    active_days = int((daily_counts > 0).sum())

    all_days = pd.date_range(start, end, freq="D")
    zero_mask = ~all_days.isin(daily_counts.index)

    longest_no_trade = 0
    cur = 0
    for z in zero_mask:
        if z:
            cur += 1
            longest_no_trade = max(longest_no_trade, cur)
        else:
            cur = 0

    row = {
        "AverageTradesPerMonth": float(len(et) / float(total_months)),
        "AverageTradesPerWeek": float(len(et) / float(total_weeks)),
        "AverageTradesPerDay": float(len(et) / float(total_days)),
        "TradeActiveDaysPct": float(active_days / float(total_days) * 100.0),
        "LongestNoTradeDays": int(longest_no_trade),
    }
    return pd.DataFrame([row])


def _stability_score(rolling_3m: pd.DataFrame, intertrade_hours: pd.DataFrame) -> pd.DataFrame:
    # Components are normalized into [0,100], higher is better.
    if rolling_3m.empty:
        return pd.DataFrame(
            [{
                "MonthlyTradeUniformityScore": np.nan,
                "WinRateStabilityScore": np.nan,
                "IntertradeGapStabilityScore": np.nan,
                "StabilityScore": np.nan,
                "StabilityClass": "unknown",
                "Predictability": "نامشخص",
                "RealCapitalReadiness": "نیاز به داده بیشتر",
            }]
        )

    trade_counts = pd.to_numeric(rolling_3m["trade_count_3m"], errors="coerce").replace(0, np.nan)
    win_rates = pd.to_numeric(rolling_3m["win_rate_pct_3m"], errors="coerce")

    def _cv_to_score(s: pd.Series, cap: float = 1.5) -> float:
        s = s.dropna()
        if len(s) <= 1:
            return 50.0
        m = float(s.mean())
        if m == 0:
            return 30.0
        cv = float(s.std(ddof=0) / abs(m))
        cv_norm = min(cv / cap, 1.0)
        return float((1.0 - cv_norm) * 100.0)

    monthly_uniformity = _cv_to_score(trade_counts)
    winrate_stability = _cv_to_score(win_rates, cap=0.8)

    gaps = pd.to_numeric(intertrade_hours.get("gap_hours", pd.Series(dtype=float)), errors="coerce")
    gap_stability = _cv_to_score(gaps, cap=2.0)

    final_score = float(np.nanmean([monthly_uniformity, winrate_stability, gap_stability]))

    if final_score >= 75:
        cls = "stable"
        predict = "قابل پیش‌بینی"
        readiness = "مناسب (با رعایت مدیریت ریسک)"
    elif final_score >= 55:
        cls = "moderate"
        predict = "نیمه‌قابل پیش‌بینی"
        readiness = "مشروط"
    else:
        cls = "unstable"
        predict = "نامنظم"
        readiness = "فعلاً نامناسب"

    return pd.DataFrame(
        [
            {
                "MonthlyTradeUniformityScore": round(monthly_uniformity, 2),
                "WinRateStabilityScore": round(winrate_stability, 2),
                "IntertradeGapStabilityScore": round(gap_stability, 2),
                "StabilityScore": round(final_score, 2),
                "StabilityClass": cls,
                "Predictability": predict,
                "RealCapitalReadiness": readiness,
            }
        ]
    )


def _managerial_summary(
    time_behavior_summary: pd.DataFrame,
    rolling_3m: pd.DataFrame,
    activity_metrics: pd.DataFrame,
    stability_score: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    trend = "نامشخص"
    if not rolling_3m.empty and "activity_trend" in rolling_3m.columns:
        trend = str(rolling_3m["activity_trend"].iloc[-1])

    rows.append({"Topic": "روند فعالیت 3ماهه", "Conclusion": f"روند تعداد معاملات در پنجره‌های 3ماهه: {trend}"})

    if not activity_metrics.empty:
        m = activity_metrics.iloc[0]
        rows.append(
            {
                "Topic": "میانگین فعالیت",
                "Conclusion": (
                    f"میانگین ماهانه={m.get('AverageTradesPerMonth', np.nan):.2f} | "
                    f"هفتگی={m.get('AverageTradesPerWeek', np.nan):.2f} | روزانه={m.get('AverageTradesPerDay', np.nan):.3f}"
                ),
            }
        )
        rows.append(
            {
                "Topic": "پوشش زمانی",
                "Conclusion": (
                    f"درصد روزهای دارای معامله={m.get('TradeActiveDaysPct', np.nan):.2f}% | "
                    f"طولانی‌ترین وقفه بدون معامله={int(m.get('LongestNoTradeDays', 0))} روز"
                ),
            }
        )

    if not stability_score.empty:
        s = stability_score.iloc[0]
        rows.append(
            {
                "Topic": "امتیاز پایداری",
                "Conclusion": (
                    f"StabilityScore={s.get('StabilityScore', np.nan)} از 100 | "
                    f"وضعیت={s.get('StabilityClass', 'unknown')} | پیش‌بینی‌پذیری={s.get('Predictability', 'نامشخص')}"
                ),
            }
        )
        rows.append(
            {
                "Topic": "مناسبت اجرای واقعی",
                "Conclusion": str(s.get("RealCapitalReadiness", "نامشخص")),
            }
        )

    if not time_behavior_summary.empty:
        for _, r in time_behavior_summary.head(3).iterrows():
            rows.append({"Topic": f"رفتار زمانی/{r['موضوع']}", "Conclusion": str(r["نتیجه"])})

    return pd.DataFrame(rows)


def _plot_bar(df: pd.DataFrame, x_col: str, y_col: str, title: str, out_path: str) -> Optional[str]:
    if plt is None or df.empty:
        return None
    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.bar(df[x_col].astype(str), df[y_col].astype(float))
    ax.set_title(title)
    ax.set_ylabel(y_col)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def _plot_hist(series: pd.Series, title: str, out_path: str, bins: int = 30) -> Optional[str]:
    if plt is None or series.empty:
        return None
    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.hist(series.astype(float), bins=bins)
    ax.set_title(title)
    ax.set_xlabel("Hours")
    ax.set_ylabel("Count")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def _plot_timeline(entry_times: pd.Series, out_path: str) -> Optional[str]:
    if plt is None or entry_times.empty:
        return None
    t = pd.to_datetime(entry_times, errors="coerce").dropna().sort_values()
    if t.empty:
        return None
    timeline_df = t.to_frame(name="time")
    timeline_df["cum"] = np.arange(1, len(timeline_df) + 1)
    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(111)
    ax.plot(timeline_df["time"], timeline_df["cum"])
    ax.set_title("Trades timeline (cumulative)")
    ax.set_xlabel("Entry time")
    ax.set_ylabel("Cumulative trades")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def build_distribution_artifacts(trades_df: pd.DataFrame) -> DistributionArtifacts:
    if trades_df is None or trades_df.empty:
        empty = pd.DataFrame()
        return DistributionArtifacts(*(empty for _ in range(18)))

    tdf = _time_columns(trades_df)
    r = pd.to_numeric(tdf.get("نتیجه_R", pd.Series(dtype=float)), errors="coerce").dropna()

    q = _safe_quantiles(r, [0.05, 0.25, 0.5, 0.75, 0.95])
    summary = pd.DataFrame(
        [
            {
                "TotalTrades": int(len(tdf)),
                "Wins": int((r > 0).sum()),
                "LossesOrNonWins": int((r <= 0).sum()),
                "WinRatePct": float((r > 0).mean() * 100.0) if len(r) else np.nan,
                "MeanR": float(r.mean()) if len(r) else np.nan,
                "StdR": float(r.std(ddof=0)) if len(r) else np.nan,
                "SkewR": float(r.skew()) if len(r) > 2 else np.nan,
                "KurtosisR": float(r.kurt()) if len(r) > 3 else np.nan,
                **q,
            }
        ]
    )

    by_symbol = pd.DataFrame()
    if "نماد" in tdf.columns:
        by_symbol = (
            tdf.groupby("نماد")["نتیجه_R"]
            .agg(
                [
                    ("تعداد", "size"),
                    ("میانگین_R", "mean"),
                    ("میانه_R", "median"),
                    ("انحراف_معیار_R", "std"),
                ]
            )
            .reset_index()
            .sort_values("تعداد", ascending=False)
        )

    by_test = pd.DataFrame()
    if "تست" in tdf.columns:
        by_test = (
            tdf.groupby("تست")["نتیجه_R"]
            .agg(
                [
                    ("تعداد", "size"),
                    ("میانگین_R", "mean"),
                    ("WinRatePct", lambda s: (s > 0).mean() * 100.0),
                ]
            )
            .reset_index()
            .sort_values("تست")
        )

    bins = [-np.inf, -2, -1, -0.5, 0, 0.5, 1, 2, np.inf]
    labels = ["<-2R", "-2 تا -1R", "-1 تا -0.5R", "-0.5 تا 0R", "0 تا 0.5R", "0.5 تا 1R", "1 تا 2R", ">2R"]
    r_histogram = pd.DataFrame(columns=["بازه_R", "تعداد"])
    if len(r):
        binned = pd.cut(r, bins=bins, labels=labels, include_lowest=True, right=True)
        r_histogram = binned.value_counts(dropna=False).reindex(labels, fill_value=0).reset_index()
        r_histogram.columns = ["بازه_R", "تعداد"]

    hold_time = pd.DataFrame()
    if "مدت_نگهداری_ساعت" in tdf.columns:
        hs = pd.to_numeric(tdf["مدت_نگهداری_ساعت"], errors="coerce").dropna()
        hq = _safe_quantiles(hs, [0.25, 0.5, 0.75, 0.95])
        hold_time = pd.DataFrame(
            [
                {
                    "Count": int(len(hs)),
                    "MeanHours": float(hs.mean()) if len(hs) else np.nan,
                    "MinHours": float(hs.min()) if len(hs) else np.nan,
                    "MaxHours": float(hs.max()) if len(hs) else np.nan,
                    **hq,
                }
            ]
        )

    streaks = _streak_table(r)

    weekday_distribution = _distribution_table(tdf.get("entry_weekday", pd.Series(dtype=object)), WEEKDAY_ORDER, "weekday")
    hour_distribution = _distribution_table(tdf.get("entry_hour", pd.Series(dtype=float)), list(range(24)), "hour")
    monthly_distribution = _distribution_table(tdf.get("entry_month", pd.Series(dtype=float)), MONTH_ORDER, "month")
    season_distribution = _distribution_table(tdf.get("season", pd.Series(dtype=object)), SEASON_ORDER, "season")
    year_period_distribution = _distribution_table(tdf.get("entry_period", pd.Series(dtype=object)), MONTH_PERIOD_ORDER, "period")

    weekday_hour_heatmap = pd.DataFrame()
    if "entry_weekday" in tdf.columns and "entry_hour" in tdf.columns:
        hm = (
            tdf.groupby(["entry_weekday", "entry_hour"]).size().unstack(fill_value=0)
            .reindex(index=WEEKDAY_ORDER, fill_value=0)
            .reindex(columns=list(range(24)), fill_value=0)
        )
        weekday_hour_heatmap = hm.reset_index().rename(columns={"entry_weekday": "weekday"})

    intertrade_hours = pd.DataFrame(columns=["gap_hours"])
    if "زمان_ورود" in tdf.columns:
        et = pd.to_datetime(tdf["زمان_ورود"], errors="coerce").dropna().sort_values()
        if len(et) >= 2:
            gaps = et.diff().dt.total_seconds().dropna() / 3600.0
            intertrade_hours = pd.DataFrame({"gap_hours": gaps.values})

    time_behavior_summary = _seasonality_interpretation(
        monthly_distribution,
        season_distribution,
        year_period_distribution,
        weekday_distribution,
        hour_distribution,
    )

    rolling_3m = _rolling_3m_stats(tdf)
    activity_metrics = _activity_metrics(tdf)
    stability_score = _stability_score(rolling_3m, intertrade_hours)
    managerial_summary = _managerial_summary(time_behavior_summary, rolling_3m, activity_metrics, stability_score)

    return DistributionArtifacts(
        summary=summary,
        by_symbol=by_symbol,
        by_test=by_test,
        r_histogram=r_histogram,
        hold_time=hold_time,
        streaks=streaks,
        weekday_distribution=weekday_distribution,
        hour_distribution=hour_distribution,
        weekday_hour_heatmap=weekday_hour_heatmap,
        monthly_distribution=monthly_distribution,
        season_distribution=season_distribution,
        year_period_distribution=year_period_distribution,
        intertrade_hours=intertrade_hours,
        time_behavior_summary=time_behavior_summary,
        rolling_3m=rolling_3m,
        activity_metrics=activity_metrics,
        stability_score=stability_score,
        managerial_summary=managerial_summary,
    )



def distribution_sheets(trades_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    artifacts = build_distribution_artifacts(trades_df)
    if artifacts.summary.empty and artifacts.by_symbol.empty and artifacts.r_histogram.empty:
        return {}
    return {
        "summary": artifacts.summary,
        "by_symbol": artifacts.by_symbol,
        "by_test": artifacts.by_test,
        "r_histogram": artifacts.r_histogram,
        "hold_time": artifacts.hold_time,
        "streaks": artifacts.streaks,
        "weekday_dist": artifacts.weekday_distribution,
        "hour_dist": artifacts.hour_distribution,
        "weekday_hour_heatmap": artifacts.weekday_hour_heatmap,
        "monthly_dist": artifacts.monthly_distribution,
        "season_dist": artifacts.season_distribution,
        "month_period_dist": artifacts.year_period_distribution,
        "intertrade_gaps": artifacts.intertrade_hours,
        "time_behavior_summary": artifacts.time_behavior_summary,
        "rolling_3m": artifacts.rolling_3m,
        "activity_metrics": artifacts.activity_metrics,
        "stability_score": artifacts.stability_score,
        "managerial_summary": artifacts.managerial_summary,
    }

def write_distribution_report(outdir: str, trades_df: pd.DataFrame) -> Optional[str]:
    artifacts = build_distribution_artifacts(trades_df)
    if artifacts.summary.empty and artifacts.by_symbol.empty and artifacts.r_histogram.empty:
        return None

    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "analysis_distribution.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        artifacts.summary.to_excel(writer, sheet_name="summary", index=False)
        artifacts.by_symbol.to_excel(writer, sheet_name="by_symbol", index=False)
        artifacts.by_test.to_excel(writer, sheet_name="by_test", index=False)
        artifacts.r_histogram.to_excel(writer, sheet_name="r_histogram", index=False)
        artifacts.hold_time.to_excel(writer, sheet_name="hold_time", index=False)
        artifacts.streaks.to_excel(writer, sheet_name="streaks", index=False)
        artifacts.weekday_distribution.to_excel(writer, sheet_name="weekday_dist", index=False)
        artifacts.hour_distribution.to_excel(writer, sheet_name="hour_dist", index=False)
        artifacts.weekday_hour_heatmap.to_excel(writer, sheet_name="weekday_hour_heatmap", index=False)
        artifacts.monthly_distribution.to_excel(writer, sheet_name="monthly_dist", index=False)
        artifacts.season_distribution.to_excel(writer, sheet_name="season_dist", index=False)
        artifacts.year_period_distribution.to_excel(writer, sheet_name="month_period_dist", index=False)
        artifacts.intertrade_hours.to_excel(writer, sheet_name="intertrade_gaps", index=False)
        artifacts.time_behavior_summary.to_excel(writer, sheet_name="time_behavior_summary", index=False)
        artifacts.rolling_3m.to_excel(writer, sheet_name="rolling_3m", index=False)
        artifacts.activity_metrics.to_excel(writer, sheet_name="activity_metrics", index=False)
        artifacts.stability_score.to_excel(writer, sheet_name="stability_score", index=False)
        artifacts.managerial_summary.to_excel(writer, sheet_name="managerial_summary", index=False)

    # optional charts (if matplotlib is installed)
    _plot_bar(
        artifacts.monthly_distribution,
        "month",
        "تعداد",
        "Monthly trade distribution",
        os.path.join(outdir, "analysis_monthly_distribution.png"),
    )
    _plot_bar(
        artifacts.weekday_distribution,
        "weekday",
        "تعداد",
        "Weekday trade distribution",
        os.path.join(outdir, "analysis_weekday_distribution.png"),
    )
    _plot_hist(
        artifacts.intertrade_hours.get("gap_hours", pd.Series(dtype=float)),
        "Histogram of inter-trade gaps",
        os.path.join(outdir, "analysis_intertrade_gap_hist.png"),
        bins=24,
    )

    entry_times = pd.Series(dtype="datetime64[ns]")
    if trades_df is not None and ("زمان_ورود" in trades_df.columns):
        entry_times = pd.to_datetime(trades_df["زمان_ورود"], errors="coerce")
    _plot_timeline(entry_times, os.path.join(outdir, "analysis_trade_timeline.png"))

    return path