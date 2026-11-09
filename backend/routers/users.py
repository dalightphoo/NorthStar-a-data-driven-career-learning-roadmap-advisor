from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import UPLOAD_DIR
from backend.db import get_db
from backend.helpers import current_title, public_user
from backend.models import CareerExperience, Education, User
from backend.schemas import PasswordChangeIn, ProfileUpdateIn, UserPublic
from backend.security import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)):
    return public_user(user)


@router.put("/me", response_model=UserPublic)
def update_me(payload: ProfileUpdateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.username and payload.username != user.username:
        taken = db.query(User).filter(User.username == payload.username, User.id != user.id).first()
        if taken:
            raise HTTPException(status_code=400, detail="That username is already taken.")
        if len(payload.username.strip()) < 3:
            raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
        user.username = payload.username.strip()
    if payload.age is not None:
        if payload.age < 16 or payload.age > 80:
            raise HTTPException(status_code=400, detail="Age must be between 16 and 80.")
        user.age = payload.age
    if payload.gender is not None:
        user.gender = payload.gender
    if payload.educations is not None:
        if not payload.educations:
            raise HTTPException(status_code=400, detail="Keep at least one education.")
        user.educations.clear()
        db.flush()
        for edu in payload.educations:
            user.educations.append(
                Education(school=edu.school, level=edu.level, field_of_study=edu.field_of_study)
            )
    if payload.experiences is not None:
        currents = [item for item in payload.experiences if item.is_current]
        if len(currents) > 1:
            raise HTTPException(status_code=400, detail="Only one career experience can be current.")
        unique_experiences = []
        positions = {}
        for experience in payload.experiences:
            key = experience.career.strip().casefold()
            if key not in positions:
                positions[key] = len(unique_experiences)
                unique_experiences.append(experience)
            else:
                index = positions[key]
                existing = unique_experiences[index]
                if experience.is_current and not existing.is_current:
                    unique_experiences[index] = experience
        user.experiences.clear()
        db.flush()
        for exp in unique_experiences:
            user.experiences.append(
                CareerExperience(career=exp.career, years=exp.years, is_current=exp.is_current)
            )
        user.current_career = (
            next((exp.career for exp in unique_experiences if exp.is_current), None)
            or payload.current_career
            or "New Graduate"
        )
    elif payload.current_career:
        user.current_career = payload.current_career
    else:
        user.current_career = current_title(user)
    db.commit()
    db.refresh(user)
    return public_user(user)


@router.post("/me/password")
def change_password(payload: PasswordChangeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password does not match.")
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="New password and confirm password must match.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


@router.post("/me/photo", response_model=UserPublic)
def photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "photo.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Use a JPG, PNG, or WEBP photo.")
    dest = UPLOAD_DIR / f"{user.id}{suffix}"
    dest.write_bytes(file.file.read())
    user.profile_photo = f"/uploads/profiles/{dest.name}"
    db.commit()
    db.refresh(user)
    return public_user(user)
