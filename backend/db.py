from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import DATABASE_URL, NORTHSTAR_ENV, ROOT

def _make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _reachable(url: str) -> bool:
    engine = _make_engine(url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


SQLITE_URL = f"sqlite:///{(ROOT / 'northstar.db').as_posix()}"
ACTIVE_URL = (
    DATABASE_URL
    if NORTHSTAR_ENV == "production" or _reachable(DATABASE_URL)
    else SQLITE_URL
)

engine = _make_engine(ACTIVE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
