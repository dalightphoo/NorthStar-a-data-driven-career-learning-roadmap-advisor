from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from urllib.parse import urlsplit

from backend.db import get_db
from backend.models import CareerStat, DatasetVersion, User
from backend.security import get_admin_user
from backend.services.dataset_admin import (
    commit_dataset_change,
    dataset_snapshot,
    load_datasets,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class CareerPayload(BaseModel):
    field: str = Field(min_length=2, max_length=80)
    career: str = Field(min_length=2, max_length=80)
    median_salary_usd: int = Field(gt=0)
    p25_salary: int = Field(gt=0)
    p75_salary: int = Field(gt=0)
    job_openings_index: int = Field(ge=0, le=100)
    growth_5y_pct: float = Field(ge=-100, le=1000)
    remote_share_pct: float = Field(ge=0, le=100)
    typical_education: str = Field(min_length=2, max_length=40)
    difficulty: int = Field(ge=1, le=5)
    description: str = Field(min_length=5, max_length=2000)

    @field_validator("field", "career", "typical_education", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

    @model_validator(mode="after")
    def salaries_are_ordered(self):
        if not self.p25_salary <= self.median_salary_usd <= self.p75_salary:
            raise ValueError("Salary percentiles must satisfy P25 ≤ median ≤ P75.")
        return self


class FieldPayload(BaseModel):
    field: str = Field(min_length=2, max_length=80)

    @field_validator("field")
    @classmethod
    def field_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field name cannot be empty.")
        return value


class SkillPayload(BaseModel):
    career: str = Field(min_length=2, max_length=80)
    skill: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    importance: int = Field(ge=1, le=5)
    hours_to_learn: float = Field(gt=0, le=10000)
    sort_order: int = Field(ge=1)

    @field_validator("career", "skill", "category")
    @classmethod
    def strip_skill_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Career, skill, and category are required.")
        return value


class RequiredSkillsPayload(BaseModel):
    skills: list[SkillPayload] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def skills_are_unique(self):
        names = [item.skill.casefold().strip() for item in self.skills]
        if len(set(names)) != len(names):
            raise ValueError("Required skills must have unique names.")
        return self


class JobMarketPoint(BaseModel):
    year: int = Field(ge=1900, le=2200)
    openings_index: int = Field(ge=0, le=100)
    avg_salary: int = Field(gt=0)


class JobMarketPayload(BaseModel):
    points: list[JobMarketPoint] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def years_are_unique(self):
        years = [item.year for item in self.points]
        if len(set(years)) != len(years):
            raise ValueError("Job-market years must be unique.")
        return self


class ResourcePayload(BaseModel):
    skill: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=2, max_length=200)
    source_type: str = Field(min_length=2, max_length=40)
    url: str = Field(min_length=8, max_length=2000)
    level: str = Field(min_length=2, max_length=40)

    @field_validator("skill", "title", "source_type", "url", "level")
    @classmethod
    def strip_resource_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("All learning-source fields are required.")
        return value


class ResourceDeletePayload(BaseModel):
    skill: str
    title: str
    url: str


def _career_payload(payload: CareerPayload) -> dict:
    data = payload.model_dump()
    data["field"] = data["field"].strip()
    data["career"] = data["career"].strip()
    data["typical_education"] = data["typical_education"].strip()
    data["description"] = data["description"].strip()
    return data


def _career_stat(db: Session, career_id: int) -> CareerStat:
    row = db.get(CareerStat, career_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Career not found.")
    return row


@router.get("/me")
def admin_me(user: User = Depends(get_admin_user)):
    return {"username": user.username, "is_admin": True}


@router.get("/datasets")
def current_datasets(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    latest = db.query(DatasetVersion).order_by(DatasetVersion.version.desc()).first()
    datasets = load_datasets()
    known_careers = {
        (row["field"], row["career"])
        for row in datasets["careers"].to_dict("records")
    }
    return {
        "version": latest.version if latest else 0,
        "datasets": dataset_snapshot(datasets),
        "career_records": [
            {"id": row.id, "field": row.field, "career": row.career}
            for row in db.query(CareerStat).order_by(CareerStat.field, CareerStat.career).all()
            if (row.field, row.career) in known_careers
        ],
    }


@router.post("/fields", status_code=201)
def add_field(
    payload: FieldPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    field_name = payload.field.strip()

    def mutate(datasets):
        if datasets["fields"]["field"].str.casefold().eq(field_name.casefold()).any():
            raise HTTPException(status_code=409, detail="That field already exists.")
        datasets["fields"] = pd.concat(
            [datasets["fields"], pd.DataFrame([{"field": field_name}])],
            ignore_index=True,
        )

    version = commit_dataset_change(
        db,
        changed_by=user.username,
        action="field_added",
        summary=f"Added the {field_name} field.",
        mutate=mutate,
    )
    return {"field": field_name, "version": version.version}


@router.get("/history")
def dataset_history(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    rows = db.query(DatasetVersion).order_by(DatasetVersion.version.desc()).all()
    return {
        "versions": [
            {
                "version": row.version,
                "action": row.action,
                "summary": row.summary,
                "changed_by": row.changed_by,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.get("/history/{version_number}")
def dataset_version(
    version_number: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    row = db.query(DatasetVersion).filter_by(version=version_number).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    return {
        "version": row.version,
        "action": row.action,
        "summary": row.summary,
        "changed_by": row.changed_by,
        "created_at": row.created_at,
        "datasets": row.snapshot,
    }


@router.post("/careers", status_code=201)
def add_career(
    payload: CareerPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    data = _career_payload(payload)
    datasets = load_datasets()
    if not datasets["fields"]["field"].str.casefold().eq(data["field"].casefold()).any():
        raise HTTPException(status_code=400, detail="Add this field before adding a career to it.")
    if datasets["careers"]["career"].str.casefold().eq(data["career"].casefold()).any():
        raise HTTPException(status_code=409, detail="That career already exists.")
    row = CareerStat(**data)
    db.add(row)
    db.flush()

    def mutate(frames):
        frames["careers"] = pd.concat(
            [frames["careers"], pd.DataFrame([data])], ignore_index=True
        )

    version = commit_dataset_change(
        db, changed_by=user.username, action="career_added",
        summary=f"Added {data['career']} to {data['field']}.", mutate=mutate,
    )
    return {"career_id": row.id, "version": version.version}


@router.put("/careers/{career_id}")
def edit_career(
    career_id: int,
    payload: CareerPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    row = _career_stat(db, career_id)
    data = _career_payload(payload)
    old_field, old_career = row.field, row.career
    frames = load_datasets()
    if (
        old_career.casefold() != data["career"].casefold()
        and frames["careers"]["career"].str.casefold().eq(data["career"].casefold()).any()
    ):
        raise HTTPException(status_code=409, detail="That career name already exists.")

    def mutate(datasets):
        career_mask = (datasets["careers"]["field"] == old_field) & (
            datasets["careers"]["career"] == old_career
        )
        if not career_mask.any():
            raise HTTPException(status_code=404, detail="Career not found in the dataset.")
        for key, value in data.items():
            datasets["careers"].loc[career_mask, key] = value
        if old_career != data["career"]:
            for key in ("skills", "projects", "job_market"):
                datasets[key].loc[datasets[key]["career"] == old_career, "career"] = data["career"]
        if old_field != data["field"]:
            datasets["job_market"].loc[
                datasets["job_market"]["career"] == data["career"], "field"
            ] = data["field"]

    for key, value in data.items():
        setattr(row, key, value)
    version = commit_dataset_change(
        db, changed_by=user.username, action="career_edited",
        summary=f"Updated {old_career} career information.", mutate=mutate,
    )
    return {"career_id": career_id, "version": version.version}


@router.post("/skills", status_code=201)
def add_skill(
    payload: SkillPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    data = payload.model_dump()
    data["career"] = data["career"].strip()
    data["skill"] = data["skill"].strip()
    if not any(row["career"] == data["career"] for row in load_datasets()["careers"].to_dict("records")):
        raise HTTPException(status_code=404, detail="Career not found.")

    def mutate(frames):
        if (
            frames["skills"]["career"].eq(data["career"])
            & frames["skills"]["skill"].str.casefold().eq(data["skill"].casefold())
        ).any():
            raise HTTPException(status_code=409, detail="That skill already exists for this career.")
        frames["skills"] = pd.concat([frames["skills"], pd.DataFrame([data])], ignore_index=True)

    version = commit_dataset_change(
        db, changed_by=user.username, action="skill_added",
        summary=f"Added the {data['skill']} skill to {data['career']}.", mutate=mutate,
    )
    return {"version": version.version}


@router.put("/careers/{career_id}/skills")
def replace_required_skills(
    career_id: int,
    payload: RequiredSkillsPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    row = _career_stat(db, career_id)
    rows = [item.model_dump() for item in payload.skills]
    if any(item["career"].strip() != row.career for item in rows):
        raise HTTPException(status_code=400, detail="Every skill must belong to the selected career.")
    for item in rows:
        item["career"] = row.career
        item["skill"] = item["skill"].strip()

    def mutate(frames):
        frames["skills"] = frames["skills"].loc[
            frames["skills"]["career"] != row.career
        ]
        frames["skills"] = pd.concat([frames["skills"], pd.DataFrame(rows)], ignore_index=True)

    version = commit_dataset_change(
        db, changed_by=user.username, action="required_skills_replaced",
        summary=f"Changed required skills for {row.career}.", mutate=mutate,
    )
    return {"version": version.version, "skill_count": len(rows)}


@router.put("/careers/{career_id}/job-market")
def replace_job_market(
    career_id: int,
    payload: JobMarketPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    row = _career_stat(db, career_id)
    points = [
        {
            "field": row.field,
            "career": row.career,
            **item.model_dump(),
        }
        for item in payload.points
    ]

    def mutate(frames):
        frames["job_market"] = frames["job_market"].loc[
            frames["job_market"]["career"] != row.career
        ]
        frames["job_market"] = pd.concat([frames["job_market"], pd.DataFrame(points)], ignore_index=True)

    version = commit_dataset_change(
        db, changed_by=user.username, action="job_market_replaced",
        summary=f"Updated job-market information for {row.career}.", mutate=mutate,
    )
    return {"version": version.version, "year_count": len(points)}


@router.post("/resources", status_code=201)
def add_learning_resource(
    payload: ResourcePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    data = payload.model_dump()
    data = {key: value.strip() for key, value in data.items()}
    parsed_url = urlsplit(data["url"])
    if parsed_url.scheme.casefold() not in {"https", "http"} or not parsed_url.netloc:
        raise HTTPException(status_code=400, detail="Learning source URL must start with http:// or https://.")

    def mutate(frames):
        if not frames["skills"]["skill"].eq(data["skill"]).any():
            raise HTTPException(status_code=404, detail="Add this skill to a career before linking a resource.")
        duplicate = (
            frames["resources"]["skill"].eq(data["skill"])
            & frames["resources"]["title"].eq(data["title"])
            & frames["resources"]["url"].eq(data["url"])
        ).any()
        if duplicate:
            raise HTTPException(status_code=409, detail="That learning resource already exists.")
        frames["resources"] = pd.concat([frames["resources"], pd.DataFrame([data])], ignore_index=True)

    version = commit_dataset_change(
        db, changed_by=user.username, action="learning_resource_added",
        summary=f"Added the {data['title']} learning source for {data['skill']}.", mutate=mutate,
    )
    return {"version": version.version}


@router.delete("/resources")
def remove_learning_resource(
    payload: ResourceDeletePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    data = payload.model_dump()
    removed = 0

    def mutate(frames):
        nonlocal removed
        match = (
            frames["resources"]["skill"].eq(data["skill"])
            & frames["resources"]["title"].eq(data["title"])
            & frames["resources"]["url"].eq(data["url"])
        )
        removed = int(match.sum())
        if not removed:
            raise HTTPException(status_code=404, detail="Learning resource not found.")
        frames["resources"] = frames["resources"].loc[~match]

    version = commit_dataset_change(
        db, changed_by=user.username, action="learning_resource_removed",
        summary=f"Removed the {data['title']} learning source for {data['skill']}.",
        mutate=mutate,
    )
    return {"version": version.version, "removed": removed}
