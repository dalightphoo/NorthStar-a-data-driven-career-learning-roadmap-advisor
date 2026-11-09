import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.catalog import careers_df, job_market_df


def compare_field(db: Session, field: str, dark_mode: bool = False) -> dict:
    sql = text(
        """
        SELECT field, career, median_salary_usd, p25_salary, p75_salary,
               job_openings_index, growth_5y_pct, remote_share_pct,
               typical_education, difficulty, description
        FROM career_stats
        WHERE field = :field
        ORDER BY median_salary_usd DESC
        """
    )
    rows = db.execute(sql, {"field": field}).mappings().all()
    if not rows:
        frame = careers_df()
        frame = frame.loc[frame["field"] == field].copy()
        if frame.empty:
            return {"field": field, "careers": [], "insights": ["No careers found for that field."], "chart": None}
        records = frame.to_dict(orient="records")
    else:
        records = [dict(r) for r in rows]
        frame = pd.DataFrame(records)

    salaries = frame["median_salary_usd"].astype(float).to_numpy()
    openings = frame["job_openings_index"].astype(float).to_numpy()
    growth = frame["growth_5y_pct"].astype(float).to_numpy()

    salary_z = _z(salaries)
    demand_z = _z(openings)
    growth_z = _z(growth)
    composite = 0.4 * salary_z + 0.35 * demand_z + 0.25 * growth_z

    frame = frame.copy()
    frame["salary_z"] = salary_z
    frame["demand_z"] = demand_z
    frame["growth_z"] = growth_z
    frame["composite_score"] = np.round(composite, 2)
    frame["salary_vs_field_pct"] = np.round(100 * (salaries / np.median(salaries) - 1), 1)
    ranked = frame.sort_values("composite_score", ascending=False)

    insights = _insights(ranked)
    chart = _chart(ranked, field, dark_mode)
    careers = []
    for _, row in ranked.iterrows():
        careers.append(
            {
                "career": row["career"],
                "median_salary_usd": int(row["median_salary_usd"]),
                "p25_salary": int(row["p25_salary"]),
                "p75_salary": int(row["p75_salary"]),
                "job_openings_index": int(row["job_openings_index"]),
                "growth_5y_pct": float(row["growth_5y_pct"]),
                "remote_share_pct": float(row["remote_share_pct"]),
                "typical_education": row["typical_education"],
                "difficulty": int(row["difficulty"]),
                "description": row["description"],
                "composite_score": float(row["composite_score"]),
                "salary_vs_field_pct": float(row["salary_vs_field_pct"]),
                "trend": _trend(field, row["career"]),
            }
        )
    return {"field": field, "careers": careers, "insights": insights, "chart": chart}


def _z(values: np.ndarray) -> np.ndarray:
    std = values.std()
    if std == 0:
        return np.zeros_like(values)
    return (values - values.mean()) / std


def _insights(frame: pd.DataFrame) -> list[str]:
    top_pay = frame.sort_values("median_salary_usd", ascending=False).iloc[0]
    top_demand = frame.sort_values("job_openings_index", ascending=False).iloc[0]
    top_growth = frame.sort_values("growth_5y_pct", ascending=False).iloc[0]
    balanced = frame.iloc[0]
    spread = int(frame["median_salary_usd"].max() - frame["median_salary_usd"].min())
    return [
        f"{top_pay['career']} has the highest median salary in this field at ${int(top_pay['median_salary_usd']):,}.",
        f"{top_demand['career']} currently shows the strongest job-openings index ({int(top_demand['job_openings_index'])}).",
        f"{top_growth['career']} has the fastest 5-year growth signal ({float(top_growth['growth_5y_pct'])}%).",
        f"A balanced composite (salary + demand + growth) currently favors {balanced['career']}.",
        f"Median pay across these roles spans about ${spread:,}. Use the range, not only the peak.",
    ]


def _trend(field: str, career: str) -> list[dict]:
    market = job_market_df()
    slice_ = market[(market["field"] == field) & (market["career"] == career)].sort_values("year")
    return slice_[["year", "openings_index", "avg_salary"]].to_dict(orient="records")


def _chart(frame: pd.DataFrame, field: str, dark_mode: bool = False) -> str:
    labels = frame["career"].tolist()
    x = np.arange(len(labels))
    width = 0.36
    colors = (
        {
            "figure": "#111315",
            "axes": "#202428",
            "text": "#F0EEE8",
            "muted": "#B2ADA3",
            "salary": "#D6AE78",
            "openings": "#A9B6A1",
            "grid": "#343A3D",
        }
        if dark_mode
        else {
            "figure": "#FFF8DC",
            "axes": "#F7F4EF",
            "text": "#302A24",
            "muted": "#756D64",
            "salary": "#C4A484",
            "openings": "#6B8E9F",
            "grid": "#E7E1D9",
        }
    )
    fig, ax1 = plt.subplots(figsize=(10, 4.6), dpi=140)
    fig.patch.set_facecolor(colors["figure"])
    ax1.set_facecolor(colors["axes"])
    ax1.bar(
        x - width / 2,
        frame["median_salary_usd"] / 1000,
        width,
        color=colors["salary"],
        label="Median salary ($k)",
    )
    ax2 = ax1.twinx()
    ax2.set_facecolor("none")
    ax2.bar(
        x + width / 2,
        frame["job_openings_index"],
        width,
        color=colors["openings"],
        label="Job openings index",
    )
    ax1.set_xticks(x, labels, rotation=18, ha="right")
    ax1.set_ylabel("Median salary ($ thousands)")
    ax2.set_ylabel("Job openings index")
    ax1.set_title(f"Career comparison · {field}")
    if dark_mode:
        for axis in (ax1, ax2):
            axis.tick_params(colors=colors["muted"])
            axis.xaxis.label.set_color(colors["muted"])
            axis.yaxis.label.set_color(colors["muted"])
            for spine in axis.spines.values():
                spine.set_color(colors["grid"])
        ax1.title.set_color(colors["text"])
        ax1.grid(axis="y", color=colors["grid"], alpha=0.55, linewidth=0.7)
        ax2.grid(False)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    legend = ax1.legend(h1 + h2, l1 + l2, loc="upper right", frameon=False)
    if dark_mode:
        for text in legend.get_texts():
            text.set_color(colors["text"])
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")
