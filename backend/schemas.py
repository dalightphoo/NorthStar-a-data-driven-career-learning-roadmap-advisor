from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class EducationIn(BaseModel):
    school: str = Field(min_length=2, max_length=160)
    level: str = Field(min_length=2, max_length=80)
    field_of_study: str = Field(default="", max_length=120)

    @field_validator("school", "level")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

    @model_validator(mode="after")
    def school_matches_level(self):
        school = self.school.casefold()
        level = self.level.casefold()
        is_high_school = "high school" in level or "secondary" in level
        is_higher_education = any(
            word in level for word in ("bachelor", "master", "phd", "college", "university")
        )
        school_is_higher_education = any(
            word in school for word in ("university", "college")
        )
        school_is_high_school = "high school" in school or "secondary school" in school
        if is_high_school and school_is_higher_education:
            raise ValueError("This school name looks like a college or university. Choose a higher education level.")
        if is_higher_education and school_is_high_school:
            raise ValueError("This school name looks like a high school. Choose High School as the education level.")
        return self


class ExperienceIn(BaseModel):
    career: str = Field(min_length=2, max_length=80)
    years: float | None = None
    is_current: bool = False

    @field_validator("career")
    @classmethod
    def strip_career(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Career name cannot be empty.")
        return value

    @field_validator("years")
    @classmethod
    def years_ok(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0 or value > 60:
            raise ValueError("Years of experience must be between 0 and 60.")
        return value

    @model_validator(mode="after")
    def require_years_for_past_roles(self):
        if not self.is_current and self.years is None:
            raise ValueError("Give years of experience, or mark the role as current.")
        return self


class RegisterIn(BaseModel):
    username: str
    age: int
    gender: str
    educations: list[EducationIn]
    experiences: list[ExperienceIn] = Field(default_factory=list)
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def username_ok(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or len(value) > 32:
            raise ValueError("Username must be 3 to 32 characters.")
        if not all(ch.isalnum() or ch in "._" for ch in value):
            raise ValueError("Username can only use letters, numbers, dots, and underscores.")
        return value

    @field_validator("age")
    @classmethod
    def age_ok(cls, value: int) -> int:
        if value < 16 or value > 80:
            raise ValueError("Age must be between 16 and 80.")
        return value

    @field_validator("gender")
    @classmethod
    def gender_ok(cls, value: str) -> str:
        allowed = {"Female", "Male", "Non-binary", "Prefer not to say"}
        if value not in allowed:
            raise ValueError("Please choose a gender option.")
        return value

    @field_validator("password")
    @classmethod
    def password_ok(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password should mix letters and numbers or symbols.")
        return value


class LoginIn(BaseModel):
    username: str
    password: str


class RoadmapGenerateIn(BaseModel):
    field: str = Field(min_length=1, max_length=80)
    career: str = Field(min_length=1, max_length=80)
    hours_per_day: float
    days_per_week: int
    duration_value: float
    duration_unit: str = "months"
    regenerate: bool = False

    @field_validator("field", "career")
    @classmethod
    def strip_required_selection(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Choose a field and a career.")
        return value

    @field_validator("hours_per_day")
    @classmethod
    def hours_ok(cls, value: float) -> float:
        if value < 1 or value > 12:
            raise ValueError("Hours per day must be between 1 and 12.")
        return value

    @field_validator("days_per_week")
    @classmethod
    def days_ok(cls, value: int) -> int:
        if value < 1 or value > 7:
            raise ValueError("Days per week must be between 1 and 7.")
        return value

    @field_validator("duration_unit")
    @classmethod
    def unit_ok(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"months", "years"}:
            raise ValueError("Duration must be months or years.")
        return value

    @field_validator("duration_value")
    @classmethod
    def duration_ok(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Duration must be greater than 0.")
        return value


class SkillCheckIn(BaseModel):
    skill_id: int
    checked: bool


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_ok(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("New password must be at least 8 characters.")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password should mix letters and numbers or symbols.")
        return value


class ProfileUpdateIn(BaseModel):
    username: str | None = None
    age: int | None = None
    gender: str | None = None
    current_career: str | None = None
    educations: list[EducationIn] | None = None
    experiences: list[ExperienceIn] | None = None

    @field_validator("username")
    @classmethod
    def username_ok(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 3 or len(value) > 32:
            raise ValueError("Username must be 3 to 32 characters.")
        if not all(ch.isalnum() or ch in "._" for ch in value):
            raise ValueError("Username can only use letters, numbers, dots, and underscores.")
        return value

    @field_validator("age")
    @classmethod
    def age_ok(cls, value: int | None) -> int | None:
        if value is not None and (value < 16 or value > 80):
            raise ValueError("Age must be between 16 and 80.")
        return value

    @field_validator("gender")
    @classmethod
    def gender_ok(cls, value: str | None) -> str | None:
        allowed = {"Female", "Male", "Non-binary", "Prefer not to say"}
        if value is not None and value not in allowed:
            raise ValueError("Please choose a gender option.")
        return value

    @field_validator("current_career")
    @classmethod
    def career_ok(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value or len(value) > 80:
            raise ValueError("Current career must be between 1 and 80 characters.")
        return value


class ChatIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class AdvisorTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AdvisorIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    history: list[AdvisorTurn] = Field(default_factory=list, max_length=12)


class EducationOut(BaseModel):
    id: int | None = None
    school: str
    level: str
    field_of_study: str = ""

    class Config:
        from_attributes = True


class ExperienceOut(BaseModel):
    id: int | None = None
    career: str
    years: float | None
    is_current: bool

    class Config:
        from_attributes = True


class UserPublic(BaseModel):
    id: int
    northstar_id: str
    username: str
    age: int
    gender: str
    current_career: str
    profile_photo: str | None
    is_admin: bool = False
    educations: list[EducationOut]
    experiences: list[ExperienceOut]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=128)


class SkillOut(BaseModel):
    id: int
    skill: str
    category: str
    checked: bool

    class Config:
        from_attributes = True


class RoadmapOut(BaseModel):
    id: int
    field: str
    career: str
    hours_per_day: float
    days_per_week: int
    duration_months: int
    status: str
    plan: dict
    skills: list[SkillOut]
    got_career: bool | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    body: str
    created_at: datetime
    read: bool

    class Config:
        from_attributes = True


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    created_at: datetime
    read: bool
    extra: dict | None

    class Config:
        from_attributes = True
