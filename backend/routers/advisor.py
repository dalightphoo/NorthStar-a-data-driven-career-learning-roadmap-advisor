from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from backend.db import get_db
from backend.models import AdvisorConversation, AdvisorMessage, Roadmap, User
from backend.schemas import AdvisorIn
from backend.security import get_current_user
from backend.services.ai_advisor import advise

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(AdvisorConversation)
        .filter(AdvisorConversation.user_id == user.id)
        .order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc())
        .all()
    )
    return {
        "conversations": [
            {
                "id": item.id,
                "title": item.title,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in rows
        ]
    }


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = (
        db.query(AdvisorConversation)
        .options(selectinload(AdvisorConversation.messages))
        .filter(
            AdvisorConversation.id == conversation_id,
            AdvisorConversation.user_id == user.id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="AI conversation not found.")
    return {
        "id": item.id,
        "title": item.title,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "web_sources": message.web_sources or [],
                "created_at": message.created_at.isoformat(),
            }
            for message in sorted(item.messages, key=lambda message: message.id)
        ],
    }


@router.post("/ask")
def ask(payload: AdvisorIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.conversation_id is None:
        item = AdvisorConversation(user_id=user.id, title=payload.message.strip()[:120])
        db.add(item)
        db.flush()
    else:
        item = (
            db.query(AdvisorConversation)
            .filter(
                AdvisorConversation.id == payload.conversation_id,
                AdvisorConversation.user_id == user.id,
            )
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="AI conversation not found.")

    current = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id, Roadmap.status == "in_progress")
        .first()
    )
    profile = {
        "username": user.username,
        "age": user.age,
        "current_career": user.current_career,
        "educations": [f"{e.level} · {e.school}" for e in user.educations],
        "experiences": [
            f"{e.career} ({'current' if e.is_current else str(e.years) + ' years'})" for e in user.experiences
        ],
    }
    roadmap = None
    if current:
        roadmap = {"field": current.field, "career": current.career, "duration_months": current.duration_months}
    turns = (
        db.query(AdvisorMessage)
        .filter(AdvisorMessage.conversation_id == item.id)
        .order_by(AdvisorMessage.id.desc())
        .limit(12)
        .all()
    )
    turns.reverse()
    history = [
        {"role": turn.role, "content": turn.content}
        for turn in turns
    ]
    result = advise(
        payload.message,
        profile,
        roadmap,
        history,
    )
    now = datetime.utcnow()
    db.add_all(
        [
            AdvisorMessage(
                conversation_id=item.id,
                role="user",
                content=payload.message.strip(),
                web_sources=[],
            ),
            AdvisorMessage(
                conversation_id=item.id,
                role="assistant",
                content=result.get("reply", ""),
                web_sources=result.get("web_sources") or [],
            ),
        ]
    )
    item.updated_at = now
    db.commit()
    result["conversation_id"] = item.id
    return result
