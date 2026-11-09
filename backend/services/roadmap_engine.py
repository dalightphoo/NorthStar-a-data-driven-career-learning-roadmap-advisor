from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backend.services.catalog import careers_df, projects_df, resources_df, skills_df
from backend.services.web_search import learning_resources_for_skills


RELATED = {
    "Data Analyst": ["Data Analyst", "Data Analyst (Finance)", "Business Analyst", "Health Data Analyst"],
    "Data Scientist": ["Data Analyst", "Data Scientist"],
    "Data Engineer": ["Data Analyst", "Software Engineer", "Data Engineer"],
    "AI Engineer": ["Data Scientist", "Machine Learning Engineer", "Software Engineer", "AI Engineer"],
    "Machine Learning Engineer": ["Data Scientist", "AI Engineer", "Software Engineer"],
    "Software Engineer": ["Software Engineer"],
    "Business Analyst": ["Business Analyst", "Data Analyst"],
    "Aerospace Engineer": ["Aerospace Engineer", "Mechanical Engineer"],
}


def generate_plan(
    *,
    field: str,
    career: str,
    hours_per_day: float,
    days_per_week: int,
    duration_months: int,
    experiences: list[dict],
    seed: int = 1,
) -> dict:
    catalog = careers_df()
    match = catalog[(catalog["field"] == field) & (catalog["career"] == career)]
    if match.empty:
        raise ValueError("That career is not in this field. Pick a listed career.")

    skills = skills_df()
    skills = skills.loc[skills["career"] == career].sort_values("sort_order")
    if skills.empty:
        raise ValueError("No skill map exists for that career yet.")

    skip = _skip_skills(career, experiences)
    skills = skills.loc[~skills["skill"].isin(skip)].copy()
    if skills.empty:
        skills = skills_df().loc[skills_df()["career"] == career].sort_values("sort_order").copy()

    rng = np.random.default_rng(seed)
    if len(skills) > 1:
        focus_index = int(rng.integers(0, min(3, len(skills))))
        if focus_index:
            focus = skills.iloc[[focus_index]]
            skills = pd.concat(
                [focus, skills.drop(skills.index[focus_index])],
                ignore_index=True,
            )
    weekly_hours = hours_per_day * days_per_week
    total_hours = weekly_hours * (duration_months * 4.345)
    difficulty = int(match.iloc[0]["difficulty"])
    warning = None
    if weekly_hours < 4 and difficulty >= 4:
        warning = "Weekly hours are low for a high-difficulty career. The plan still works, but expect a slower pace."

    hours_needed = skills["hours_to_learn"].astype(float).sum()
    scale = max(total_hours / max(hours_needed, 1), 0.6)
    skills["allocated"] = np.maximum(4, np.round(skills["hours_to_learn"] * scale, 1))
    jitter = rng.normal(1.0, 0.04, len(skills))
    skills["allocated"] = np.maximum(3, np.round(skills["allocated"] * jitter, 1))

    resources = resources_df()
    live_resources, search_failed = learning_resources_for_skills(skills["skill"].tolist())
    if search_failed:
        search_notice = (
            "Live resource search was unavailable or returned no suggestions; "
            "this roadmap includes curated resources."
        )
        warning = f"{warning} {search_notice}" if warning else search_notice
    days = []
    remaining = list(skills.itertuples(index=False))
    day_index = 1
    total_study_days = int(round(duration_months * 4.345 * days_per_week))
    skill_cursor = 0
    hours_left_on_skill = remaining[0].allocated if remaining else 0
    current_skill = remaining[0] if remaining else None

    while day_index <= total_study_days and current_skill is not None:
        chunk = min(hours_per_day, hours_left_on_skill)
        days.append(
            {
                "day": day_index,
                "week": math.ceil(day_index / days_per_week),
                "hours": round(float(chunk), 1),
                "skill": current_skill.skill,
                "category": current_skill.category,
                "focus": _focus_line(current_skill.skill, day_index),
                "resources": _resources_for(resources, current_skill.skill, live_resources),
                "is_project": False,
            }
        )
        hours_left_on_skill -= chunk
        if hours_left_on_skill <= 0.2:
            skill_cursor += 1
            if skill_cursor >= len(remaining):
                current_skill = None
            else:
                current_skill = remaining[skill_cursor]
                hours_left_on_skill = current_skill.allocated
        day_index += 1

    projects = _pick_projects(career, seed)
    milestone = max(days_per_week * 3, 8)
    for i, project in enumerate(projects):
        insert_at = min(len(days), milestone * (i + 1))
        if insert_at <= 0:
            continue
        days.insert(
            insert_at,
            {
                "day": insert_at + 1,
                "week": math.ceil((insert_at + 1) / days_per_week),
                "hours": hours_per_day,
                "skill": project["title"],
                "category": "Project",
                "focus": project["description"],
                "resources": [],
                "is_project": True,
                "project": project,
            },
        )
    for i, item in enumerate(days, start=1):
        item["day"] = i
        item["week"] = math.ceil(i / days_per_week)

    skill_list = [
        {
            "skill": row.skill,
            "category": row.category,
            "hours": float(row.allocated),
            "resources": _resources_for(resources, row.skill, live_resources),
        }
        for row in remaining
    ]

    return {
        "field": field,
        "career": career,
        "summary": match.iloc[0]["description"],
        "warning": warning,
        "weekly_hours": weekly_hours,
        "total_study_days": len(days),
        "skipped_skills": sorted(skip),
        "days": days,
        "projects": projects,
        "skill_plan": skill_list,
        "routine_template": {
            "review_minutes": 15,
            "learn_minutes": int(max(30, hours_per_day * 60 * 0.6)),
            "practice_minutes": int(max(20, hours_per_day * 60 * 0.3)),
        },
    }


def _skip_skills(target: str, experiences: list[dict]) -> set[str]:
    skip: set[str] = set()
    skills = skills_df()
    for exp in experiences:
        career = exp.get("career") or ""
        years = float(exp.get("years") or 0)
        current = bool(exp.get("is_current"))
        if years < 1 and not current:
            continue
        related = RELATED.get(target, [target])
        if career == target or career in related:
            overlap = skills.loc[skills["career"] == career]
            beginner = overlap.loc[overlap["importance"] >= 4].head(3 if years >= 2 or current else 2)
            skip.update(beginner["skill"].tolist())
    return skip


def _resources_for(
    resources: pd.DataFrame,
    skill: str,
    live_resources: dict[str, list[dict]] | None = None,
) -> list[dict]:
    hits = resources.loc[resources["skill"] == skill]
    if hits.empty:
        hits = resources.loc[resources["skill"].str.contains(skill.split()[0], case=False, na=False)]
    curated = hits.head(3).to_dict(orient="records")
    return curated + (live_resources or {}).get(skill, [])


def _pick_projects(career: str, seed: int) -> list[dict]:
    frame = projects_df()
    hits = frame.loc[frame["career"] == career]
    if hits.empty:
        return []
    rng = np.random.default_rng(seed)
    take = min(3, len(hits))
    idx = rng.choice(hits.index.to_numpy(), size=take, replace=False)
    rows = hits.loc[idx].to_dict(orient="records")
    for row in rows:
        row["skills"] = [part.strip() for part in str(row.get("skills", "")).split("|") if part.strip()]
    return rows


def _focus_line(skill: str, day: int) -> str:
    cycle = [
        f"Learn the core idea of {skill} and write it in one plain paragraph.",
        f"Do a small practice set for {skill} and note every mistake.",
        f"Apply {skill} to a tiny dataset or example from your target career.",
        f"Teach {skill} out loud for five minutes, then list remaining questions.",
    ]
    return cycle[(day - 1) % len(cycle)]
