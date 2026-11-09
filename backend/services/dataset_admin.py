from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

import pandas as pd
from sqlalchemy.orm import Session

from backend.config import DATA_DIR
from fastapi import HTTPException

from backend.models import DatasetVersion, Notification, User
from backend.services import catalog

DATASET_FILES = {
    "fields": "fields.csv",
    "careers": "careers.csv",
    "skills": "skills.csv",
    "resources": "learning_resources.csv",
    "projects": "projects.csv",
    "job_market": "job_market.csv",
    "knowledge_base": "knowledge_base.csv",
}


def load_datasets() -> dict[str, pd.DataFrame]:
    return {
        key: pd.read_csv(DATA_DIR / filename)
        for key, filename in DATASET_FILES.items()
    }


def dataset_snapshot(datasets: dict[str, pd.DataFrame]) -> dict[str, list[dict]]:
    return {
        key: json.loads(frame.to_json(orient="records", force_ascii=False))
        for key, frame in datasets.items()
    }


def validate_datasets(datasets: dict[str, pd.DataFrame]) -> None:
    fields = datasets["fields"]["field"].astype(str).str.strip()
    if fields.empty or fields.eq("").any() or fields.str.casefold().duplicated().any():
        raise ValueError("Fields must be non-empty and unique.")
    careers = datasets["careers"]
    career_names = set(careers["career"])
    if not set(careers["field"]).issubset(set(fields)):
        raise ValueError("Every career must belong to a listed field.")
    if careers[["field", "career"]].duplicated().any():
        raise ValueError("Each field and career combination must be unique.")
    if careers["career"].str.casefold().duplicated().any():
        raise ValueError("Career names must be unique across fields.")
    if (careers["p25_salary"] > careers["median_salary_usd"]).any() or (
        careers["median_salary_usd"] > careers["p75_salary"]
    ).any():
        raise ValueError("Salary percentiles must satisfy P25 ≤ median ≤ P75.")
    if not careers["difficulty"].between(1, 5).all():
        raise ValueError("Career difficulty must be between 1 and 5.")
    for column in ("job_openings_index", "growth_5y_pct", "remote_share_pct"):
        if not pd.to_numeric(careers[column], errors="coerce").notna().all():
            raise ValueError(f"{column} must contain numeric values.")
    if not careers["remote_share_pct"].between(0, 100).all():
        raise ValueError("Remote-work share must be between 0 and 100.")

    skills = datasets["skills"]
    if not set(skills["career"]).issubset(career_names):
        raise ValueError("Every skill must belong to a career in the career dataset.")
    if skills.assign(skill=skills["skill"].str.casefold())[["career", "skill"]].duplicated().any():
        raise ValueError("A career cannot contain the same skill more than once.")
    if not skills["importance"].between(1, 5).all():
        raise ValueError("Skill importance must be between 1 and 5.")
    if not (pd.to_numeric(skills["hours_to_learn"], errors="coerce") > 0).all():
        raise ValueError("Skill learning hours must be greater than zero.")

    for key in ("projects", "job_market"):
        frame = datasets[key]
        if not set(frame["career"]).issubset(career_names):
            raise ValueError(f"Every {key.replace('_', ' ')} row must belong to a listed career.")
    if datasets["job_market"][["career", "year"]].duplicated().any():
        raise ValueError("Each career can have only one job-market row per year.")


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=".tmp",
        dir=path.parent, delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            frame.to_csv(handle, index=False)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _restore_files(originals: dict[Path, bytes]) -> None:
    for path, content in originals.items():
        handle = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".tmp", dir=path.parent, delete=False
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                handle.write(content)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()


def _clear_catalog_cache() -> None:
    for loader in (
        catalog.careers_df,
        catalog.fields_df,
        catalog.skills_df,
        catalog.resources_df,
        catalog.projects_df,
        catalog.job_market_df,
        catalog.knowledge_df,
    ):
        loader.cache_clear()


def commit_dataset_change(
    db: Session,
    *,
    changed_by: str,
    action: str,
    summary: str,
    mutate: Callable[[dict[str, pd.DataFrame]], None],
) -> DatasetVersion:
    datasets = load_datasets()
    originals = {
        DATA_DIR / filename: (DATA_DIR / filename).read_bytes()
        for filename in DATASET_FILES.values()
    }
    try:
        mutate(datasets)
        validate_datasets(datasets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    version_number = (db.query(DatasetVersion.version).order_by(DatasetVersion.version.desc()).first() or (0,))[0] + 1
    version = DatasetVersion(
        version=version_number,
        action=action,
        summary=summary,
        changed_by=changed_by,
        snapshot=dataset_snapshot(datasets),
    )
    db.add(version)
    db.flush()
    for user in db.query(User).all():
        db.add(
            Notification(
                user_id=user.id,
                kind="dataset_update",
                title="NorthStar dataset updated",
                body=summary,
                extra={"version": version_number, "action": action},
            )
        )
    try:
        for key, filename in DATASET_FILES.items():
            _write_csv(DATA_DIR / filename, datasets[key])
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        _restore_files(originals)
        _clear_catalog_cache()
        raise
    _clear_catalog_cache()
    return version


def ensure_initial_version(db: Session) -> None:
    if db.query(DatasetVersion.id).first():
        return
    datasets = load_datasets()
    db.add(
        DatasetVersion(
            version=1,
            action="initial",
            summary="Initial bundled career, skills, learning resources, projects, and job-market datasets.",
            changed_by="system",
            snapshot=dataset_snapshot(datasets),
        )
    )
    db.commit()
