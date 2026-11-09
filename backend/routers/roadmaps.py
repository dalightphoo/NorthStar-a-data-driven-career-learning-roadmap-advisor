from datetime import datetime
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.db import get_db
from backend.helpers import public_user
from backend.models import CareerExperience, Notification, Roadmap, RoadmapSkill, User
from backend.schemas import RoadmapGenerateIn, RoadmapOut, SkillCheckIn, SkillOut
from backend.security import get_current_user
from backend.services.roadmap_engine import generate_plan

router = APIRouter(prefix="/roadmaps", tags=["roadmaps"])


def _out(item: Roadmap) -> RoadmapOut:
    return RoadmapOut(
        id=item.id,
        field=item.field,
        career=item.career,
        hours_per_day=item.hours_per_day,
        days_per_week=item.days_per_week,
        duration_months=item.duration_months,
        status=item.status,
        plan=item.plan,
        skills=[SkillOut.model_validate(skill) for skill in item.skills],
        got_career=item.got_career,
        created_at=item.created_at,
        started_at=item.started_at,
        completed_at=item.completed_at,
    )


def duration_months(value: float, unit: str) -> int:
    months = int(round(value * 12)) if unit == "years" else int(round(value))
    if months < 1 or months > 60:
        raise HTTPException(status_code=400, detail="Learning duration must be 1 month to 5 years.")
    return months


@router.get("/mine")
def mine(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = (
        db.query(Roadmap)
        .options(joinedload(Roadmap.skills))
        .filter(Roadmap.user_id == user.id)
        .order_by(Roadmap.created_at.desc())
        .all()
    )
    current = next((item for item in items if item.status == "in_progress"), None)
    generated = next((item for item in items if item.status == "generated"), None)
    past = [item for item in items if item.status == "past"]
    return {
        "current": _out(current) if current else None,
        "generated": _out(generated) if generated else None,
        "past": [_out(item) for item in past],
    }


@router.post("/generate", response_model=RoadmapOut)
def generate(payload: RoadmapGenerateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    months = duration_months(payload.duration_value, payload.duration_unit)
    existing = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id, Roadmap.status == "generated")
        .all()
    )
    previous_plan = existing[-1].plan if existing else None
    try:
        if payload.regenerate:
            for _ in range(32):
                seed = secrets.randbelow(2**31)
                if existing and seed == existing[-1].seed:
                    continue
                plan = generate_plan(
                    field=payload.field.strip(),
                    career=payload.career.strip(),
                    hours_per_day=payload.hours_per_day,
                    days_per_week=payload.days_per_week,
                    duration_months=months,
                    experiences=[
                        {"career": exp.career, "years": exp.years, "is_current": exp.is_current}
                        for exp in user.experiences
                    ],
                    seed=seed,
                )
                if plan != previous_plan:
                    break
            else:
                raise HTTPException(
                    status_code=500,
                    detail="NorthStar could not create a different roadmap. Please try again.",
                )
        else:
            seed = user.id + months + int(payload.hours_per_day * 10)
            plan = generate_plan(
                field=payload.field.strip(),
                career=payload.career.strip(),
                hours_per_day=payload.hours_per_day,
                days_per_week=payload.days_per_week,
                duration_months=months,
                experiences=[
                    {"career": exp.career, "years": exp.years, "is_current": exp.is_current}
                    for exp in user.experiences
                ],
                seed=seed,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for item in existing:
        db.delete(item)

    roadmap = Roadmap(
        user_id=user.id,
        field=payload.field.strip(),
        career=payload.career.strip(),
        hours_per_day=payload.hours_per_day,
        days_per_week=payload.days_per_week,
        duration_months=months,
        status="generated",
        seed=seed,
        plan=plan,
    )
    db.add(roadmap)
    db.flush()
    for skill in plan["skill_plan"]:
        db.add(RoadmapSkill(roadmap_id=roadmap.id, skill=skill["skill"], category=skill["category"]))
    db.commit()
    db.refresh(roadmap)
    return _out(roadmap)


@router.post("/{roadmap_id}/start", response_model=RoadmapOut)
def start(roadmap_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(status_code=404, detail="Roadmap not found.")
    if roadmap.status == "in_progress":
        return _out(roadmap)
    current = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id, Roadmap.status == "in_progress")
        .first()
    )
    if current:
        raise HTTPException(
            status_code=400,
            detail="Finish or pause the current In Progress roadmap before starting another.",
        )
    roadmap.status = "in_progress"
    roadmap.started_at = datetime.utcnow()
    db.commit()
    db.refresh(roadmap)
    return _out(roadmap)


@router.post("/{roadmap_id}/skills", response_model=RoadmapOut)
def check_skill(roadmap_id: int, payload: SkillCheckIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(status_code=404, detail="Roadmap not found.")
    if roadmap.status != "in_progress":
        raise HTTPException(status_code=400, detail="Skills can only be checked on the current roadmap.")
    skill = db.get(RoadmapSkill, payload.skill_id)
    if not skill or skill.roadmap_id != roadmap.id:
        raise HTTPException(status_code=404, detail="Skill not found.")
    skill.checked = payload.checked
    db.flush()
    if roadmap.skills and all(item.checked for item in roadmap.skills):
        roadmap.status = "past"
        roadmap.completed_at = datetime.utcnow()
        db.add(
            Notification(
                user_id=user.id,
                kind="roadmap",
                title="Roadmap complete",
                body=f"Congratulations, you finished the {roadmap.career} roadmap.",
                extra={"roadmap_id": roadmap.id},
            )
        )
    db.commit()
    db.refresh(roadmap)
    return _out(roadmap)


@router.post("/{roadmap_id}/got-career")
def got_career(roadmap_id: int, yes: bool, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(status_code=404, detail="Roadmap not found.")
    if roadmap.status != "past":
        raise HTTPException(status_code=400, detail="Only a finished roadmap can confirm a career.")
    roadmap.got_career = yes
    message = None
    if yes:
        matching = [
            exp
            for exp in user.experiences
            if exp.career.strip().casefold() == roadmap.career.strip().casefold()
        ]
        current_exp = next((exp for exp in matching if exp.is_current), None)
        for exp in user.experiences:
            exp.is_current = False
        if matching:
            current_exp = current_exp or matching[0]
            for duplicate in matching:
                if duplicate is current_exp:
                    continue
                user.experiences.remove(duplicate)
            current_exp.career = roadmap.career
            current_exp.is_current = True
        else:
            user.experiences.append(
                CareerExperience(career=roadmap.career, years=None, is_current=True)
            )
        user.current_career = roadmap.career
        message = f"Congratulations our {roadmap.career}, {user.username}"
    db.commit()
    return {"yes": yes, "message": message, "user": public_user(user)}


@router.post("/{roadmap_id}/restart", response_model=RoadmapOut)
def restart(roadmap_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(status_code=404, detail="Roadmap not found.")
    current = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id, Roadmap.status == "in_progress")
        .first()
    )
    if current and current.id != roadmap.id:
        raise HTTPException(status_code=400, detail="You already have a current roadmap.")
    for skill in roadmap.skills:
        skill.checked = False
    roadmap.status = "in_progress"
    roadmap.got_career = None
    roadmap.completed_at = None
    roadmap.started_at = datetime.utcnow()
    db.commit()
    db.refresh(roadmap)
    return _out(roadmap)
