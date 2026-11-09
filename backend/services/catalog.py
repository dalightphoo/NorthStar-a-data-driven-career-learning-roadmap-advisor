from functools import lru_cache

import pandas as pd

from backend.config import DATA_DIR


@lru_cache(maxsize=1)
def careers_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "careers.csv")


@lru_cache(maxsize=1)
def fields_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "fields.csv")


@lru_cache(maxsize=1)
def skills_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "skills.csv")


@lru_cache(maxsize=1)
def resources_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "learning_resources.csv")


@lru_cache(maxsize=1)
def projects_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "projects.csv")


@lru_cache(maxsize=1)
def job_market_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "job_market.csv")


@lru_cache(maxsize=1)
def knowledge_df() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "knowledge_base.csv")


def fields() -> list[str]:
    return sorted(fields_df()["field"].tolist())


def careers_for(field: str) -> list[str]:
    frame = careers_df()
    return frame.loc[frame["field"] == field, "career"].tolist()


def field_for_career(career: str) -> str | None:
    frame = careers_df()
    hit = frame.loc[frame["career"] == career, "field"]
    if hit.empty:
        return None
    return str(hit.iloc[0])
