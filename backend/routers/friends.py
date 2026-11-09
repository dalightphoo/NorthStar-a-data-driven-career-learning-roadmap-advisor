from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from backend.db import get_db
from backend.helpers import public_user
from backend.models import User
from backend.security import get_current_user, is_admin_account
from backend.services.catalog import field_for_career

router = APIRouter(prefix="/friends", tags=["friends"])


@router.get("/search")
def search(
    northstar_id: str | None = None,
    field: str | None = None,
    career: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(User).options(joinedload(User.experiences), joinedload(User.educations)).filter(User.id != user.id)
    code = (northstar_id or "").strip()
    field = (field or "").strip()
    career = (career or "").strip()
    if code:
        found = query.filter(User.northstar_id == code).all()
        found = [item for item in found if not is_admin_account(item.username)]
        if not found:
            raise HTTPException(status_code=404, detail="No user has that NorthStar ID.")
        return {"people": [public_user(item) for item in found]}

    if not field and not career:
        raise HTTPException(
            status_code=400,
            detail="Enter a NorthStar ID or choose a field or career to search.",
        )

    people = query.all()
    out = []
    for person in people:
        if is_admin_account(person.username):
            continue
        careers = {exp.career for exp in person.experiences} | {person.current_career}
        person_fields = {field_for_career(name) for name in careers}
        person_fields.discard(None)
        if career and career not in careers:
            continue
        if field and field not in person_fields:
            continue
        out.append(public_user(person))
    return {"people": out}


@router.get("/{user_id}")
def detail(user_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    person = db.get(User, user_id)
    if not person or is_admin_account(person.username):
        raise HTTPException(status_code=404, detail="Person not found.")
    return public_user(person)
