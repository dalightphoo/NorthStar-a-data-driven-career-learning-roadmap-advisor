from datetime import datetime, timedelta, timezone
import hmac

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.config import (
    ACCESS_TOKEN_HOURS,
    NORTHSTAR_ADMIN_PASSWORD,
    NORTHSTAR_ADMIN_USERNAME,
    SECRET_KEY,
)
from backend.db import get_db
from backend.models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return int(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_authenticated_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="Please log in first.")
    user_id = decode_token(creds.credentials)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Account not found.")
    return user


def is_admin_account(username: str) -> bool:
    return bool(
        NORTHSTAR_ADMIN_USERNAME
        and NORTHSTAR_ADMIN_PASSWORD
        and username.casefold() == NORTHSTAR_ADMIN_USERNAME.casefold()
    )


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    if is_admin_account(user.username):
        raise HTTPException(
            status_code=403,
            detail="Admin accounts can only access the dataset administration dashboard.",
        )
    return user


def get_admin_user(user: User = Depends(get_authenticated_user)) -> User:
    if not is_admin_account(user.username):
        raise HTTPException(status_code=403, detail="Dataset administration is not enabled for this account.")
    return user


def verify_admin_credentials(username: str, password: str) -> bool:
    return bool(
        NORTHSTAR_ADMIN_USERNAME
        and NORTHSTAR_ADMIN_PASSWORD
        and hmac.compare_digest(username.casefold(), NORTHSTAR_ADMIN_USERNAME.casefold())
        and hmac.compare_digest(password, NORTHSTAR_ADMIN_PASSWORD)
    )
