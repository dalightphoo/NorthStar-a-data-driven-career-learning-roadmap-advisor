from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import SEED_DEMO_USERS, UPLOAD_DIR
from backend.db import Base, engine, SessionLocal
from backend.routers import admin, advisor, auth, catalog, chat, compare, friends, roadmaps, users
from backend.seed import ensure_admin_user, seed_catalog, seed_demo_users
from backend.services.dataset_admin import ensure_initial_version

app = FastAPI(title="NorthStar", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(catalog.router)
app.include_router(roadmaps.router)
app.include_router(compare.router)
app.include_router(friends.router)
app.include_router(chat.router)
app.include_router(advisor.router)
app.mount("/uploads/profiles", StaticFiles(directory=str(UPLOAD_DIR)), name="profiles")


ABOUT = (
    "NorthStar helps you explore career options and make a learning plan for a career you want. "
    "You can follow your plan, compare careers, ask NorthStar AI questions, and connect with other learners.\n\n"
    "Getting started: On Dashboard, choose a field and career, then choose how many hours you can study "
    "each day, how many days each week, and how long you want to study. Your education details remain "
    "in your Profile and are not needed to create a roadmap. "
    "Select Produce roadmap to create your plan. Review the skills, learning sources, projects, and schedule. "
    "When you are ready, select Start the roadmap.\n\n"
    "Following your plan: Open In Progress to see your skills, learning sources, projects, and day-by-day "
    "schedule. Check off each skill as you complete it. When you finish every skill, the roadmap is saved "
    "under Past Roadmaps. You can also revisit a completed plan or confirm whether you reached your career goal.\n\n"
    "Exploring careers: Open Compare Careers, choose a field, region, and country, then select Compare. "
    "Review the career descriptions, salary estimates, job-market indicators, and ranking. When current "
    "country-specific figures are available, they appear alongside NorthStar's general estimates. "
    "All figures are estimates to help you compare options, not promises of a particular salary or job.\n\n"
    "Getting help and connecting: Ask NorthStar AI to explain a topic, offer career guidance, or suggest a "
    "project. It can use public web search results and show links to the sources; those results may be "
    "incomplete or out of date, so check important information with the linked source. Your question may "
    "be sent to a search provider, so do not include passwords, private information, or other sensitive details. "
    "In Find Friends, look someone up by NorthStar ID or search by field or career. Open a person's profile "
    "to start a conversation. Check Messages for your conversations and Notifications for updates.\n\n"
    "Use Profile to review or update your account information. You can switch between light and dark "
    "appearance using the theme button."
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_catalog(db)
        if SEED_DEMO_USERS:
            seed_demo_users(db)
        ensure_admin_user(db)
        ensure_initial_version(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/about")
def about():
    return {"title": "About NorthStar", "body": ABOUT}
