import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.helpers import current_title, public_user
from backend.models import AuthSession, CareerExperience, Education, User
from backend.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut
from backend.config import NORTHSTAR_ADMIN_USERNAME
from backend.security import (
    create_token,
    get_authenticated_user,
    hash_password,
    verify_admin_credentials,
    verify_password,
)
from backend.services.ids import northstar_id_from_pk

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User, db: Session) -> TokenOut:
    refresh_token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            token_hash=hashlib.sha256(refresh_token.encode("utf-8")).hexdigest(),
            user_id=user.id,
        )
    )
    db.commit()
    return TokenOut(
        access_token=create_token(user.id),
        refresh_token=refresh_token,
        user=public_user(user),
    )


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Password and confirm password must match.")
    if not payload.educations:
        raise HTTPException(status_code=400, detail="Add at least one education (high school is OK).")
    currents = [item for item in payload.experiences if item.is_current]
    if len(currents) > 1:
        raise HTTPException(status_code=400, detail="Only one career can be marked as current.")
    for item in payload.experiences:
        if not item.is_current and item.years is None:
            raise HTTPException(
                status_code=400,
                detail="Give years of experience, or mark the role as current.",
            )
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="That username is already taken.")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        age=payload.age,
        gender=payload.gender,
        northstar_id="pending",
        current_career=currents[0].career if currents else "New Graduate",
    )
    db.add(user)
    db.flush()
    user.northstar_id = northstar_id_from_pk(user.id)
    for edu in payload.educations:
        db.add(
            Education(
                user_id=user.id,
                school=edu.school,
                level=edu.level,
                field_of_study=edu.field_of_study,
            )
        )
    for exp in payload.experiences:
        db.add(
            CareerExperience(
                user_id=user.id,
                career=exp.career,
                years=exp.years,
                is_current=exp.is_current,
            )
        )
    db.commit()
    db.refresh(user)
    user.current_career = current_title(user)
    db.commit()
    db.refresh(user)
    return _token_response(user, db)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    if NORTHSTAR_ADMIN_USERNAME and payload.username.casefold() == NORTHSTAR_ADMIN_USERNAME.casefold():
        if not verify_admin_credentials(payload.username, payload.password):
            raise HTTPException(status_code=400, detail="Username or password is incorrect.")
        user = db.query(User).filter(User.username.ilike(NORTHSTAR_ADMIN_USERNAME)).first()
        if not user:
            raise HTTPException(
                status_code=503,
                detail="Admin account is not initialized. Restart the NorthStar server.",
            )
        return _token_response(user, db)

    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Username or password is incorrect.")
    return _token_response(user, db)


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
    session = db.get(AuthSession, token_hash)
    if not session:
        raise HTTPException(status_code=401, detail="Your saved login has expired. Please log in again.")
    user = db.get(User, session.user_id)
    if not user:
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="Account not found. Please log in again.")
    return TokenOut(
        access_token=create_token(user.id),
        refresh_token=payload.refresh_token,
        user=public_user(user),
    )


@router.post("/logout")
def logout(payload: RefreshIn, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
    session = db.get(AuthSession, token_hash)
    if session:
        db.delete(session)
        db.commit()
    return {"ok": True}


@router.post("/session", response_model=TokenOut)
def establish_session(user: User = Depends(get_authenticated_user), db: Session = Depends(get_db)):
    return _token_response(user, db)
