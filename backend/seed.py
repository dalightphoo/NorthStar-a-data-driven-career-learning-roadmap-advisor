from sqlalchemy.orm import Session

from backend.config import NORTHSTAR_ADMIN_PASSWORD, NORTHSTAR_ADMIN_USERNAME
from backend.models import CareerStat, User
from backend.security import hash_password
from backend.services.catalog import careers_df
from backend.services.ids import northstar_id_from_pk
from backend.models import CareerExperience, Education


def seed_catalog(db: Session) -> None:
    existing = {
        (field, career)
        for field, career in db.query(CareerStat.field, CareerStat.career).all()
    }
    for row in careers_df().to_dict(orient="records"):
        key = (row["field"], row["career"])
        if key not in existing:
            db.add(CareerStat(**row))
    db.commit()


def seed_demo_users(db: Session) -> None:
    if db.query(User).count():
        return
    demos = [
        {
            "username": "maya",
            "age": 24,
            "gender": "Female",
            "current_career": "Data Analyst",
            "educations": [("State University", "Bachelor", "Statistics")],
            "experiences": [("Data Analyst", 2.0, True)],
        },
        {
            "username": "kenji",
            "age": 29,
            "gender": "Male",
            "current_career": "Aerospace Engineer",
            "educations": [("Tech Institute", "Bachelor", "Aerospace Engineering")],
            "experiences": [("Aerospace Engineer", 4.0, True), ("Mechanical Engineer", 1.5, False)],
        },
        {
            "username": "aisha",
            "age": 22,
            "gender": "Female",
            "current_career": "New Graduate",
            "educations": [("City High School", "High School", "Science"), ("City College", "Bachelor", "Computer Science")],
            "experiences": [],
        },
        {
            "username": "omar",
            "age": 31,
            "gender": "Male",
            "current_career": "Product Manager",
            "educations": [("Business School", "Master", "Business Administration")],
            "experiences": [("Business Analyst", 3.0, False), ("Product Manager", None, True)],
        },
    ]
    password = hash_password("NorthStar123")
    for demo in demos:
        user = User(
            username=demo["username"],
            password_hash=password,
            age=demo["age"],
            gender=demo["gender"],
            current_career=demo["current_career"],
            northstar_id="pending",
        )
        db.add(user)
        db.flush()
        user.northstar_id = northstar_id_from_pk(user.id)
        for school, level, field in demo["educations"]:
            db.add(Education(user_id=user.id, school=school, level=level, field_of_study=field))
        for career, years, current in demo["experiences"]:
            db.add(
                CareerExperience(
                    user_id=user.id, career=career, years=years, is_current=current
                )
            )
    db.commit()


def ensure_admin_user(db: Session) -> None:
    if not NORTHSTAR_ADMIN_USERNAME and not NORTHSTAR_ADMIN_PASSWORD:
        return
    if not NORTHSTAR_ADMIN_USERNAME or not NORTHSTAR_ADMIN_PASSWORD:
        raise ValueError(
            "Configure both NORTHSTAR_ADMIN_USERNAME and NORTHSTAR_ADMIN_PASSWORD."
        )
    if len(NORTHSTAR_ADMIN_PASSWORD) < 12:
        raise ValueError("NORTHSTAR_ADMIN_PASSWORD must be at least 12 characters.")
    if len(NORTHSTAR_ADMIN_USERNAME) < 3 or len(NORTHSTAR_ADMIN_USERNAME) > 32:
        raise ValueError("NORTHSTAR_ADMIN_USERNAME must be 3 to 32 characters.")

    user = (
        db.query(User)
        .filter(User.username.ilike(NORTHSTAR_ADMIN_USERNAME))
        .first()
    )
    if user:
        if user.username != NORTHSTAR_ADMIN_USERNAME:
            user.username = NORTHSTAR_ADMIN_USERNAME
            db.commit()
        return

    user = User(
        username=NORTHSTAR_ADMIN_USERNAME,
        password_hash=hash_password(NORTHSTAR_ADMIN_PASSWORD),
        age=18,
        gender="Prefer not to say",
        current_career="Dataset Administrator",
        northstar_id="pending",
    )
    db.add(user)
    db.flush()
    user.northstar_id = northstar_id_from_pk(user.id)
    db.commit()
