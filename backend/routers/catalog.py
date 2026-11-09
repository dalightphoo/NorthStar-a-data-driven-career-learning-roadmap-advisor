from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import CareerStat
from backend.security import get_current_user
from backend.services.catalog import careers_for, fields

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/fields")
def list_fields(_: object = Depends(get_current_user)):
    return {"fields": fields()}


@router.get("/careers")
def list_careers(field: str, db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    rows = db.query(CareerStat).filter(CareerStat.field == field).all()
    if rows:
        return {
            "field": field,
            "careers": [
                {"career": row.career, "description": row.description, "difficulty": row.difficulty}
                for row in rows
            ],
        }
    return {"field": field, "careers": [{"career": name, "description": "", "difficulty": 3} for name in careers_for(field)]}
