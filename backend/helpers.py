from backend.config import NORTHSTAR_ADMIN_PASSWORD, NORTHSTAR_ADMIN_USERNAME
from backend.models import User
from backend.schemas import EducationOut, ExperienceOut, UserPublic


def public_user(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        northstar_id=user.northstar_id,
        username=user.username,
        age=user.age,
        gender=user.gender,
        current_career=user.current_career or "New Graduate",
        profile_photo=user.profile_photo,
        is_admin=bool(
            NORTHSTAR_ADMIN_USERNAME
            and NORTHSTAR_ADMIN_PASSWORD
            and user.username.casefold() == NORTHSTAR_ADMIN_USERNAME.casefold()
        ),
        educations=[EducationOut.model_validate(item) for item in user.educations],
        experiences=[ExperienceOut.model_validate(item) for item in user.experiences],
    )


def current_title(user: User) -> str:
    for exp in user.experiences:
        if exp.is_current:
            return exp.career
    return user.current_career or "Future Star"
