from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from backend.db import SessionLocal, get_db
from backend.models import Message, Notification, User
from backend.schemas import ChatIn, MessageOut, NotificationOut
from backend.security import decode_token, get_current_user, is_admin_account

router = APIRouter(tags=["chat"])
sockets: dict[int, list[WebSocket]] = {}


class Hub:
    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        sockets.setdefault(user_id, []).append(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        sockets[user_id] = [item for item in sockets.get(user_id, []) if item is not ws]

    async def send(self, user_id: int, payload: dict):
        for ws in list(sockets.get(user_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(user_id, ws)


hub = Hub()


@router.get("/messages/threads")
def threads(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Message)
        .filter(or_(Message.sender_id == user.id, Message.receiver_id == user.id))
        .order_by(Message.created_at.desc())
        .all()
    )
    latest: dict[int, Message] = {}
    unread: dict[int, int] = {}
    for row in rows:
        other = row.receiver_id if row.sender_id == user.id else row.sender_id
        latest.setdefault(other, row)
        if row.receiver_id == user.id and not row.read:
            unread[other] = unread.get(other, 0) + 1
    people = db.query(User).filter(User.id.in_(latest.keys())).all() if latest else []
    people = [person for person in people if not is_admin_account(person.username)]
    people_map = {item.id: item for item in people}
    out = []
    for other_id, msg in latest.items():
        person = people_map.get(other_id)
        if not person:
            continue
        out.append(
            {
                "user_id": person.id,
                "username": person.username,
                "northstar_id": person.northstar_id,
                "current_career": person.current_career,
                "last_message": msg.body,
                "last_at": msg.created_at.isoformat(),
                "unread": unread.get(other_id, 0),
            }
        )
    return {"threads": out}


@router.get("/messages/{other_id}")
def history(other_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    other = db.get(User, other_id)
    if not other or is_admin_account(other.username):
        raise HTTPException(status_code=404, detail="Person not found.")
    rows = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == user.id, Message.receiver_id == other_id),
                and_(Message.sender_id == other_id, Message.receiver_id == user.id),
            )
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    for row in rows:
        if row.receiver_id == user.id:
            row.read = True
    db.commit()
    return {"messages": [MessageOut.model_validate(row) for row in rows], "other": other.username}


@router.post("/messages/{other_id}")
async def send(other_id: int, payload: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    other = db.get(User, other_id)
    if not other or is_admin_account(other.username):
        raise HTTPException(status_code=404, detail="Person not found.")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    msg = Message(sender_id=user.id, receiver_id=other_id, body=body)
    note = Notification(
        user_id=other_id,
        kind="message",
        title=f"New message from {user.username}",
        body=body[:140],
        extra={"from_id": user.id, "from_name": user.username},
    )
    db.add(msg)
    db.add(note)
    db.commit()
    db.refresh(msg)
    packet = {
        "type": "message",
        "message": MessageOut.model_validate(msg).model_dump(mode="json"),
        "notification": NotificationOut.model_validate(note).model_dump(mode="json"),
    }
    await hub.send(other_id, packet)
    await hub.send(user.id, packet)
    return packet


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    unread = sum(1 for row in rows if not row.read)
    return {"unread": unread, "items": [NotificationOut.model_validate(row) for row in rows]}


@router.post("/notifications/read")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update({"read": True})
    db.commit()
    return {"ok": True}


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if note is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    note.read = True
    db.commit()
    return {"ok": True}


@router.websocket("/ws")
async def ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        user_id = decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            await websocket.close(code=4401)
            return
        if is_admin_account(user.username):
            await websocket.close(code=4403)
            return
    await hub.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(user_id, websocket)
