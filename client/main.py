from __future__ import annotations

import base64
import json
import threading
import time

import flet as ft

from client.api import API_BASE_URL, Api, ApiError
from client.theme import DARK, LIGHT

LEVELS = ["High School", "Bachelor", "Master", "PhD", "College", "Bootcamp", "Other"]
GENDERS = ["Female", "Male", "Non-binary", "Prefer not to say"]
NAV = [
    ("dashboard", "Dashboard"),
    ("progress", "In Progress"),
    ("compare", "Compare Careers"),
    ("friends", "Find Friends"),
    ("advisor", "NorthStar AI"),
    ("notifications", "Notifications"),
    ("about", "About"),
    ("profile", "Profile"),
]
THEME_KEY = "northstar.dark_mode"


class NorthStarApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.storage = getattr(page, "client_storage", None)
        self.api = Api(self.storage)
        self.dark = bool(self.storage.get(THEME_KEY)) if self.storage is not None else False
        self.route = "dashboard"
        self.palette = LIGHT
        self.error = ""
        self.notice = ""
        self.fields: list[str] = []
        self.roadmaps = {"current": None, "generated": None, "past": []}
        self.compare_data = None
        self.people = []
        self.person = None
        self.chat_id = None
        self.chat_name = ""
        self.messages = []
        self.threads = []
        self.notifications = []
        self.unread = 0
        self.advisor_log: list[tuple[str, str, list[dict]]] = []
        self.advisor_conversation_id: int | None = None
        self.advisor_initialized = False
        self.about_text = ""
        self.last_seen_note = 0
        self.stop_poll = False
        self._setup_page()
        if self.api.token:
            try:
                try:
                    self.api.request("GET", "/admin/me")
                    if self.api.user is not None:
                        self.api.user["is_admin"] = True
                        self.api._save()
                except ApiError as exc:
                    if exc.status != 403:
                        raise
                    self.api.me()
                if not self.api.refresh_token:
                    self.api.establish_session()
                self.open_app()
            except ApiError as exc:
                if exc.status == 401:
                    self.api.clear()
                self.show_auth()
                if exc.status != 401:
                    self.snack(exc.message, True)
        else:
            self.show_auth()

    def c(self, key: str) -> str:
        return self.palette[key]

    def _setup_page(self):
        p = self.page
        p.title = "NorthStar"
        p.padding = 0
        p.fonts = {}
        self._apply_theme()

    def _apply_theme(self):
        palette = DARK if self.dark else LIGHT
        self.palette = palette
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        self.page.bgcolor = palette["bg"]
        self.page.window_bgcolor = palette["bg"]
        self.page.theme = (
            ft.Theme(
                use_material3=True,
                color_scheme=ft.ColorScheme(
                    primary=palette["primary"],
                    on_primary=palette["on_primary"],
                    primary_container=palette["surface"],
                    on_primary_container=palette["text"],
                    secondary=palette["accent"],
                    on_secondary=palette["bg"],
                    error=palette["danger"],
                    on_error=palette["bg"],
                    background=palette["bg"],
                    on_background=palette["text"],
                    surface=palette["card"],
                    on_surface=palette["text"],
                    surface_variant=palette["surface"],
                    on_surface_variant=palette["muted"],
                    outline=palette["border"],
                    outline_variant=palette["border"],
                ),
            )
            if self.dark
            else None
        )

    def _mount_view(self, view: ft.Control):
        self.page.controls.clear()
        self.page.add(
            ft.SafeArea(
                content=view,
                left=True,
                top=True,
                right=True,
                bottom=True,
                expand=True,
            )
        )

    def snack(self, text: str, error: bool = False):
        self.page.snack_bar = ft.SnackBar(
            ft.Text(text, color="#FFF8DC" if error else self.c("on_primary")),
            bgcolor=self.c("danger") if error else self.c("primary"),
        )
        self.page.snack_bar.open = True
        self.page.update()

    def os_notify(self, title: str, body: str):
        try:
            from plyer import notification

            notification.notify(title=title, message=body, timeout=8, app_name="NorthStar")
        except Exception:
            pass

    def show_auth(self):
        self._apply_theme()
        if getattr(self.page, "drawer", None):
            self.page.drawer.open = False
        self.page.drawer = None
        if getattr(self.page, "dialog", None):
            self.page.dialog.open = False
        self.page.dialog = None
        self._mount_view(self.auth_view())
        self.page.update()

    def open_app(self):
        self.stop_poll = False
        threading.Thread(target=self._poll, daemon=True).start()
        if (self.api.user or {}).get("is_admin"):
            self.route = "admin"
        self.refresh_shell()

    def refresh_shell(self):
        try:
            if self.api.token:
                if (self.api.user or {}).get("is_admin"):
                    self.route = "admin"
                else:
                    self.api.me()
                    self.roadmaps = self.api.request("GET", "/roadmaps/mine")
                    notes = self.api.request("GET", "/notifications")
                    self.unread = notes.get("unread", 0)
                    self.notifications = notes.get("items", [])
        except ApiError as exc:
            self.error = exc.message
        self._apply_theme()
        self._mount_view(self.shell())
        self.page.update()

    def _poll(self):
        while not self.stop_poll:
            time.sleep(6)
            if not self.api.token or (self.api.user or {}).get("is_admin"):
                continue
            try:
                notes = self.api.request("GET", "/notifications")
                items = notes.get("items", [])
                unread = notes.get("unread", 0)
                newest = items[0]["id"] if items else 0
                if (
                    newest
                    and newest != self.last_seen_note
                    and items
                    and items[0]["kind"] in {"message", "dataset_update"}
                ):
                    if self.last_seen_note:
                        self.os_notify(items[0]["title"], items[0]["body"])
                        self.snack(items[0]["title"])
                    self.last_seen_note = newest
                elif not self.last_seen_note and newest:
                    self.last_seen_note = newest
                self.unread = unread
                self.notifications = items
                if self.page.controls:
                    self.page.update()
            except Exception:
                pass

    def header_title(self) -> str:
        user = self.api.user or {}
        career = user.get("current_career") or "Future Star"
        if career == "New Graduate":
            career = "Future Star"
        name = user.get("username") or ""
        return f"Welcome Our {career}, {name}"

    def card(self, *controls, padding=16):
        return ft.Container(
            content=ft.Column(list(controls), spacing=10, tight=True),
            bgcolor=self.c("card"),
            border=ft.border.all(1, self.c("border")),
            border_radius=14,
            padding=padding,
        )

    def field(self, label, value="", password=False, hint=""):
        return ft.TextField(
            label=label,
            value=value,
            password=password,
            can_reveal_password=password,
            hint_text=hint,
            border_color=self.c("border"),
            color=self.c("text"),
            label_style=ft.TextStyle(color=self.c("muted")),
            hint_style=ft.TextStyle(color=self.c("hint"), size=12),
            focused_border_color=self.c("primary"),
            bgcolor=self.c("input"),
            border_radius=10,
            dense=True,
        )

    def btn(self, text, on_click, filled=True):
        if filled:
            return ft.ElevatedButton(
                text,
                on_click=on_click,
                bgcolor=self.c("primary"),
                color=self.c("on_primary"),
            )
        return ft.TextButton(text, on_click=on_click, style=ft.ButtonStyle(color=self.c("primary_dark")))

    def auth_view(self):
        username = self.field("Username")
        age = self.field("Age", hint="16–80")
        gender = ft.Dropdown(label="Gender", options=[ft.dropdown.Option(g) for g in GENDERS], dense=True)
        password = self.field("Password", password=True)
        confirm = self.field("Confirm Password", password=True)
        login_user = self.field("Username")
        login_pass = self.field("Password", password=True)
        edu_rows: list[dict] = []
        exp_rows: list[dict] = []
        lists = ft.Column(spacing=8)
        exp_lists = ft.Column(spacing=8)
        err = ft.Text("", color=self.c("danger"), size=12)

        def add_edu(_=None, school="", level="Bachelor", field_of_study=""):
            school_f = self.field("School / University / High school", school)
            level_f = ft.Dropdown(
                label="Education level",
                options=[ft.dropdown.Option(x) for x in LEVELS],
                value=level,
                dense=True,
            )
            study_f = self.field("Field of study (optional)", field_of_study)
            row = {"school": school_f, "level": level_f, "field": study_f}
            box = ft.Container(
                content=ft.Column(
                    [
                        school_f,
                        level_f,
                        study_f,
                        ft.TextButton("Remove education", on_click=lambda e, r=row: remove_edu(r)),
                    ]
                ),
                padding=8,
                border=ft.border.all(1, self.c("primary")),
                border_radius=10,
            )
            row["box"] = box
            edu_rows.append(row)
            lists.controls.append(box)
            self.page.update()

        def remove_edu(row):
            if len(edu_rows) <= 1:
                err.value = "Keep at least one education."
                self.page.update()
                return
            edu_rows.remove(row)
            lists.controls.remove(row["box"])
            self.page.update()

        def add_exp(_=None):
            career_f = self.field("Career")
            years_f = self.field("Years", hint="Leave empty if current")
            current_f = ft.Checkbox(label="I work here currently")
            row = {"career": career_f, "years": years_f, "current": current_f}

            def select_current(e):
                if e.control.value:
                    for other in exp_rows:
                        if other is not row:
                            other["current"].value = False
                    self.page.update()

            current_f.on_change = select_current
            box = ft.Container(
                content=ft.Column(
                    [
                        career_f,
                        years_f,
                        current_f,
                        ft.TextButton("Remove experience", on_click=lambda e, r=row: remove_exp(r)),
                    ]
                ),
                padding=8,
                border=ft.border.all(1, self.c("primary")),
                border_radius=10,
            )
            row["box"] = box
            exp_rows.append(row)
            exp_lists.controls.append(box)
            self.page.update()

        def remove_exp(row):
            exp_rows.remove(row)
            exp_lists.controls.remove(row["box"])
            self.page.update()

        add_edu()

        def do_register(_):
            err.value = ""
            try:
                educations = []
                for row in edu_rows:
                    educations.append(
                        {
                            "school": row["school"].value or "",
                            "level": row["level"].value or "",
                            "field_of_study": row["field"].value or "",
                        }
                    )
                experiences = []
                for row in exp_rows:
                    years = row["years"].value
                    experiences.append(
                        {
                            "career": row["career"].value or "",
                            "years": float(years) if years not in (None, "") else None,
                            "is_current": bool(row["current"].value),
                        }
                    )
                self.api.register(
                    {
                        "username": username.value,
                        "age": int(age.value or 0),
                        "gender": gender.value,
                        "educations": educations,
                        "experiences": experiences,
                        "password": password.value,
                        "confirm_password": confirm.value,
                    }
                )
                self.open_app()
            except (ApiError, ValueError) as exc:
                err.value = getattr(exc, "message", str(exc))
                self.page.update()

        def do_login(_):
            err.value = ""
            try:
                self.api.login(login_user.value or "", login_pass.value or "")
                self.open_app()
            except ApiError as exc:
                err.value = exc.message
                self.page.update()

        register_tab = ft.Column(
            [
                ft.Text("Create your NorthStar login", size=18, weight=ft.FontWeight.W_600, color=self.c("text")),
                ft.Text("Every field is checked before you can enter the app.", size=12, color=self.c("muted")),
                username,
                age,
                gender,
                ft.Text("Education", weight=ft.FontWeight.W_600),
                lists,
                self.btn("Add another education", add_edu, filled=False),
                ft.Text("Career experiences", weight=ft.FontWeight.W_600),
                ft.Text("New graduates can skip this. Add years, or mark a role as current.", size=12, color=self.c("muted")),
                exp_lists,
                self.btn("Add a career", add_exp, filled=False),
                password,
                confirm,
                self.btn("Create account", do_register),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        login_tab = ft.Column(
            [
                ft.Text("Log in", size=18, weight=ft.FontWeight.W_600, color=self.c("text")),
                ft.Text("You need an account before using NorthStar.", size=12, color=self.c("muted")),
                login_user,
                login_pass,
                self.btn("Enter", do_login),
            ],
            spacing=10,
        )
        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Register", content=register_tab),
                ft.Tab(text="Log in", content=login_tab),
            ],
            expand=True,
        )
        return ft.Container(
            expand=True,
            bgcolor=self.c("bg"),
            padding=20,
            content=ft.Column(
                [
                    ft.Text("NorthStar", size=32, weight=ft.FontWeight.W_700, color=self.c("primary_dark")),
                    ft.Text("A career & learning roadmap advisor", color=self.c("muted")),
                    err,
                    ft.Container(content=tabs, expand=True),
                ],
                expand=True,
            ),
        )

    def shell(self):
        if (self.api.user or {}).get("is_admin"):
            return self.admin_shell()
        user = self.api.user or {}
        badge = f" ({self.unread})" if self.unread else ""
        header = ft.Container(
            bgcolor=self.c("surface"),
            padding=ft.padding.only(12, 14, 12, 12),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(
                                ft.icons.MENU,
                                icon_color=self.c("text"),
                                on_click=lambda e: self.open_drawer(),
                            ),
                            ft.Text("NorthStar", weight=ft.FontWeight.W_700, color=self.c("primary_dark")),
                            ft.Container(expand=True),
                            ft.IconButton(
                                ft.icons.DARK_MODE if not self.dark else ft.icons.LIGHT_MODE,
                                icon_color=self.c("text"),
                                tooltip="Theme",
                                on_click=self.toggle_theme,
                            ),
                            ft.IconButton(
                                ft.icons.CHAT_BUBBLE_OUTLINE,
                                icon_color=self.c("text"),
                                tooltip="Messages",
                                on_click=lambda e: self.go("messages"),
                            ),
                            ft.IconButton(
                                ft.icons.NOTIFICATIONS,
                                icon_color=self.c("text"),
                                tooltip=f"Notifications{badge}",
                                on_click=lambda e: self.go("notifications"),
                            ),
                        ]
                    ),
                    ft.Text(self.header_title(), size=14, color=self.c("text")),
                    ft.Text(user.get("northstar_id", ""), size=11, color=self.c("muted")),
                ],
                spacing=4,
            ),
        )
        body = {
            "dashboard": self.dashboard_page,
            "progress": self.progress_page,
            "compare": self.compare_page,
            "friends": self.friends_page,
            "advisor": self.advisor_page,
            "about": self.about_page,
            "profile": self.profile_page,
            "messages": self.messages_page,
            "notifications": self.notifications_page,
            "chat": self.chat_page,
            "admin": self.admin_page,
        }.get(self.route, self.dashboard_page)()
        return ft.Column(
            [
                header,
                ft.Container(content=body, expand=True, padding=14, bgcolor=self.c("bg")),
            ],
            expand=True,
            spacing=0,
        )

    def admin_shell(self):
        header = ft.Container(
            bgcolor=self.c("surface"),
            padding=ft.padding.only(12, 14, 12, 12),
            content=ft.Row(
                [
                    ft.Text(
                        "NorthStar Dataset Admin",
                        weight=ft.FontWeight.W_700,
                        color=self.c("primary_dark"),
                    ),
                    ft.Container(expand=True),
                    ft.IconButton(
                        ft.icons.DARK_MODE if not self.dark else ft.icons.LIGHT_MODE,
                        icon_color=self.c("text"),
                        tooltip="Theme",
                        on_click=self.toggle_theme,
                    ),
                    ft.TextButton(
                        "Log out",
                        on_click=self.logout,
                        style=ft.ButtonStyle(color=self.c("danger")),
                    ),
                ]
            ),
        )
        return ft.Column(
            [
                header,
                ft.Container(
                    content=self.admin_page(),
                    expand=True,
                    padding=14,
                    bgcolor=self.c("bg"),
                ),
            ],
            expand=True,
            spacing=0,
        )

    def open_drawer(self):
        items = []
        nav_items = list(NAV)
        if (self.api.user or {}).get("is_admin"):
            nav_items.append(("admin", "Dataset Admin"))
        for key, label in nav_items:
            items.append(
                ft.ListTile(
                    title=ft.Text(
                        label,
                        color=self.c("primary_dark") if key == self.route else self.c("text"),
                        weight=ft.FontWeight.W_600 if key == self.route else ft.FontWeight.NORMAL,
                    ),
                    on_click=lambda e, k=key: self.go(k),
                )
            )
        items.extend(
            [
                ft.Divider(color=self.c("surface")),
                ft.ListTile(
                    title=ft.Text("Log out", color=self.c("danger")),
                    on_click=self.logout,
                ),
            ]
        )
        self.page.drawer = ft.NavigationDrawer(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("NorthStar", size=20, weight=ft.FontWeight.W_700, color=self.c("primary_dark")),
                            ft.Text("Career & learning", size=12, color=self.c("muted")),
                        ],
                        spacing=3,
                    ),
                    padding=ft.padding.only(left=20, top=24, right=16, bottom=16),
                ),
                *items,
            ],
            bgcolor=self.c("card"),
            indicator_color=self.c("surface"),
            elevation=8,
        )
        self.page.drawer.open = True
        self.page.update()

    def go(self, route: str):
        if (self.api.user or {}).get("is_admin") and route != "admin":
            route = "admin"
        self.route = route
        if getattr(self.page, "drawer", None):
            self.page.drawer.open = False
        self.refresh_shell()

    def toggle_theme(self, _=None):
        self.dark = not self.dark
        if self.storage is not None and not self.storage.set(THEME_KEY, self.dark):
            self.dark = not self.dark
            self.snack("Could not save your theme preference on this device.", True)
            return
        self.refresh_shell()

    def logout(self, _=None):
        self.stop_poll = True
        self.advisor_conversation_id = None
        self.advisor_log = []
        self.advisor_initialized = False
        error = None
        try:
            self.api.logout()
        except ApiError as exc:
            error = exc
        self.show_auth()
        if error:
            self.snack(error.message, True)

    def dashboard_page(self):
        generated = self.roadmaps.get("generated")
        field_dd = ft.Dropdown(
            label="Field",
            options=[],
            value=generated.get("field") if generated else None,
            dense=True,
        )
        career_dd = ft.Dropdown(label="Career you want", options=[], dense=True)
        hours = self.field(
            "Hours you can give each day",
            str(generated["hours_per_day"]) if generated else "2",
        )
        days = self.field(
            "Days in a week",
            str(generated["days_per_week"]) if generated else "5",
        )
        duration = self.field(
            "How long to learn",
            str(generated["duration_months"]) if generated else "8",
        )
        unit = ft.Dropdown(
            label="Unit",
            options=[ft.dropdown.Option("months"), ft.dropdown.Option("years")],
            value="months",
            dense=True,
        )
        def load_fields():
            try:
                data = self.api.request("GET", "/catalog/fields")
                self.fields = data["fields"]
                field_dd.options = [ft.dropdown.Option(x) for x in self.fields]
                self.page.update()
            except ApiError as exc:
                self.snack(exc.message, True)

        def load_careers(e=None):
            if not field_dd.value:
                return
            try:
                data = self.api.request("GET", "/catalog/careers", params={"field": field_dd.value})
                career_dd.options = [ft.dropdown.Option(item["career"]) for item in data["careers"]]
                career_dd.value = (
                    generated.get("career")
                    if generated and generated.get("field") == field_dd.value
                    else None
                )
                self.page.update()
            except ApiError as exc:
                self.snack(exc.message, True)

        field_dd.on_change = load_careers

        def generate(regen=False):
            try:
                field_value = field_dd.value or (generated or {}).get("field")
                saved_career = (
                    (generated or {}).get("career")
                    if generated and field_value == generated.get("field")
                    else None
                )
                career_value = career_dd.value or saved_career
                if not field_value or not career_value:
                    self.snack("Choose a field and career before generating a roadmap.", True)
                    return
                payload = {
                    "field": field_value,
                    "career": career_value,
                    "hours_per_day": float(hours.value),
                    "days_per_week": int(days.value),
                    "duration_value": float(duration.value),
                    "duration_unit": unit.value,
                    "regenerate": regen,
                }
                self.api.request("POST", "/roadmaps/generate", json=payload)
                self.snack("Roadmap ready.")
                self.refresh_shell()
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def start_rm(_):
            item = self.roadmaps.get("generated")
            if not item:
                self.snack("Generate a roadmap first.", True)
                return
            try:
                self.api.request("POST", f"/roadmaps/{item['id']}/start")
                self.snack("Started. Open In Progress to work through skills.")
                self.refresh_shell()
            except ApiError as exc:
                self.snack(exc.message, True)

        current = self.roadmaps.get("current")
        past = self.roadmaps.get("past") or []

        def roadmap_card(title, item):
            if not item:
                return self.card(ft.Text(title, weight=ft.FontWeight.W_600), ft.Text("None yet.", color=self.c("muted")))
            return self.card(
                ft.Text(title, weight=ft.FontWeight.W_600),
                ft.Text(f"{item['career']} · {item['field']}", color=self.c("text")),
                ft.Text(
                    f"{item['hours_per_day']} h/day · {item['days_per_week']} days/week · {item['duration_months']} months",
                    size=12,
                    color=self.c("muted"),
                ),
            )

        preview = []
        if generated:
            routine = (generated.get("plan") or {}).get("days", [])
            days_preview = routine[:5]
            preview = [
                ft.Text("First days", weight=ft.FontWeight.W_600),
                *[
                    ft.Text(f"Day {d['day']}: {d['focus']}", size=12, color=self.c("text"))
                    for d in days_preview
                ],
            ]
            if routine:
                preview.append(
                    ft.ExpansionTile(
                        title=ft.Text(f"Full day-by-day routine ({len(routine)} days)"),
                        controls=[
                            ft.ListTile(
                                title=ft.Text(f"Day {day['day']} · {day['hours']}h · {day['skill']}"),
                                subtitle=ft.Text(day["focus"]),
                            )
                            for day in routine
                        ],
                    )
                )
            projects = (generated.get("plan") or {}).get("projects") or []
            if projects:
                preview.append(ft.Text("Projects", weight=ft.FontWeight.W_600))
                preview.extend([ft.Text(f"• {p['title']}: {p['description']}", size=12) for p in projects])

        load_fields()
        if field_dd.value:
            load_careers()
        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("Build a roadmap", size=18, weight=ft.FontWeight.W_600),
                    ft.Text("Choose a field and career, then set the time you can study.", size=12, color=self.c("muted")),
                    field_dd,
                    career_dd,
                    hours,
                    days,
                    duration,
                    unit,
                    ft.Row(
                        [
                            self.btn("Produce roadmap", lambda e: generate(False)),
                            self.btn("Regenerate", lambda e: generate(True), filled=False),
                        ]
                    ),
                    self.btn("Start the roadmap", start_rm),
                    *preview,
                ),
                roadmap_card("In Progress", current),
                self.card(
                    ft.Text("Past Roadmaps", weight=ft.FontWeight.W_600),
                    *(
                        [ft.Text(f"{item['career']} · {item['field']}", size=13) for item in past]
                        or [ft.Text("No past roadmaps yet.", color=self.c("muted"))]
                    ),
                    ft.Text("Open In Progress to check skills or confirm a career.", size=11, color=self.c("muted")),
                ),
            ],
            expand=True,
            spacing=12,
        )

    def progress_page(self):
        current = self.roadmaps.get("current")
        past = self.roadmaps.get("past") or []
        blocks = []
        if current:
            plan = current.get("plan") or {}
            skills = current.get("skills") or []
            done = all(s["checked"] for s in skills) if skills else False

            def make_check(skill):
                def toggle(e):
                    try:
                        updated = self.api.request(
                            "POST",
                            f"/roadmaps/{current['id']}/skills",
                            json={"skill_id": skill["id"], "checked": e.control.value},
                        )
                        self.roadmaps["current"] = updated if updated.get("status") == "in_progress" else None
                        if updated.get("status") == "past":
                            self.snack(f"Congratulations, you finished the {updated['career']} roadmap.")
                        self.refresh_shell()
                    except ApiError as exc:
                        self.snack(exc.message, True)

                return ft.Checkbox(
                    label=f"{skill['skill']}  ({skill['category']})",
                    value=skill["checked"],
                    on_change=toggle,
                )

            source_groups = []
            source_count = 0
            for skill in plan.get("skill_plan") or []:
                resource_rows = []
                for res in skill.get("resources") or []:
                    if source_count >= 12:
                        break
                    title = res.get("title") or res.get("url") or "Learning resource"
                    details = " · ".join(
                        part
                        for part in (
                            res.get("source_type") or "Resource",
                            res.get("level"),
                        )
                        if part
                    )
                    url = res.get("url")
                    valid_url = url and url.startswith(("https://", "http://"))
                    resource_title = ft.Text(
                        title,
                        size=13,
                        color=self.c("primary_dark") if valid_url else self.c("text"),
                    )
                    resource_content = ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.OPEN_IN_NEW if valid_url else ft.Icons.MENU_BOOK,
                                size=16,
                                color=self.c("primary_dark") if valid_url else self.c("muted"),
                            ),
                            resource_title,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                    resource_rows.append(
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.TextButton(
                                        content=resource_content,
                                        url=url if valid_url else None,
                                        style=ft.ButtonStyle(
                                            padding=ft.padding.symmetric(vertical=4, horizontal=0),
                                            alignment=ft.alignment.center_left,
                                        ),
                                        disabled=not valid_url,
                                    ),
                                    ft.Text(
                                        details,
                                        size=11,
                                        color=self.c("muted"),
                                    ),
                                ],
                                spacing=2,
                                tight=True,
                            ),
                            padding=ft.padding.only(top=4, bottom=4),
                            border=ft.border.only(
                                bottom=ft.BorderSide(1, self.c("bg"))
                            )
                        )
                    )
                    source_count += 1
                if resource_rows:
                    source_groups.append(
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text(
                                        skill["skill"],
                                        size=13,
                                        weight=ft.FontWeight.W_600,
                                        color=self.c("text"),
                                    ),
                                    *resource_rows,
                                ],
                                spacing=4,
                                tight=True,
                            ),
                            bgcolor=self.c("surface"),
                            border=ft.border.all(1, self.c("bg")),
                            border_radius=10,
                            padding=12,
                        )
                    )
            projects = [
                ft.Text(f"{p['title']}: {p['description']}", size=12) for p in plan.get("projects") or []
            ]
            routine = plan.get("days") or []
            days = [
                ft.ListTile(
                    title=ft.Text(f"Day {day['day']} · {day['hours']}h · {day['skill']}"),
                    subtitle=ft.Text(day["focus"], size=12),
                )
                for day in routine
            ]
            blocks.append(
                self.card(
                    ft.Text(f"Current: {current['career']}", size=18, weight=ft.FontWeight.W_600),
                    ft.Text(plan.get("summary", ""), size=12, color=self.c("muted")),
                    ft.Text(plan.get("warning") or "", color=self.c("danger"), size=12),
                    ft.Text("Skills", weight=ft.FontWeight.W_600),
                    *[make_check(s) for s in skills],
                    ft.Text("Learning sources", weight=ft.FontWeight.W_600),
                    ft.Text(
                        "Sources are grouped by skill. Tap a linked title to open it; type and level appear underneath.",
                        size=12,
                        color=self.c("muted"),
                    ),
                    *(
                        source_groups
                        or [ft.Text("Sources appear with the generated plan.", color=self.c("muted"))]
                    ),
                    ft.Text("Projects", weight=ft.FontWeight.W_600),
                    *(projects or [ft.Text("No project yet.", color=self.c("muted"))]),
                    ft.ExpansionTile(
                        title=ft.Text(f"Day-by-day routine ({len(routine)} days)"),
                        controls=days,
                    ),
                    ft.Text("Check every skill to complete this roadmap.", size=11, color=self.c("muted")),
                )
            )
            if done:
                blocks.append(self.card(ft.Text("Congratulations — this roadmap is complete.")))
        else:
            blocks.append(self.card(ft.Text("No current roadmap. Produce one on the Dashboard, then start it.")))

        def past_card(item):
            def yes(_):
                try:
                    res = self.api.request("POST", f"/roadmaps/{item['id']}/got-career", params={"yes": True})
                    self.snack(res.get("message") or "Updated.")
                    self.refresh_shell()
                except ApiError as exc:
                    self.snack(exc.message, True)

            def no(_):
                def restart(_e):
                    try:
                        self.api.request("POST", f"/roadmaps/{item['id']}/restart")
                        self.snack("This goal is current again.")
                        self.go("progress")
                    except ApiError as exc:
                        self.snack(exc.message, True)

                def regen(_e):
                    self.go("dashboard")

                self.page.dialog = ft.AlertDialog(
                    title=ft.Text("Restart this goal?"),
                    content=ft.Text("Bring the same roadmap back, or regenerate a new one from Dashboard."),
                    actions=[
                        ft.TextButton("Restart same plan", on_click=restart),
                        ft.TextButton("Regenerate instead", on_click=regen),
                    ],
                )
                self.page.dialog.open = True
                self.page.update()

            status = "Career confirmed" if item.get("got_career") else "Finished"
            controls = [
                ft.Text(f"{item['career']} · {status}", weight=ft.FontWeight.W_600),
            ]
            if item.get("got_career") is True:
                controls.append(
                    ft.Text(
                        f"Congratulations our {item['career']}, {(self.api.user or {}).get('username', '')}.",
                        size=12,
                        color=self.c("ok"),
                    )
                )
            else:
                controls.extend(
                    [
                        ft.Text("Have you got this career?", size=12),
                        ft.Row([self.btn("Yes", yes), self.btn("Not yet", no, filled=False)]),
                    ]
                )
            return self.card(*controls)

        blocks.append(ft.Text("Past Roadmaps", size=16, weight=ft.FontWeight.W_600, color=self.c("text")))
        if past:
            blocks.extend(past_card(item) for item in past)
        else:
            blocks.append(self.card(ft.Text("No past roadmaps yet.")))
        return ft.ListView(controls=blocks, expand=True, spacing=12)

    def compare_page(self):
        field = self.field("Field")
        try:
            location_data = self.api.request("GET", "/compare/locations")
            countries_by_region = {
                item["region"]: item["countries"]
                for item in location_data["regions"]
            }
        except ApiError as exc:
            countries_by_region = {}
            self.snack(exc.message, True)
        region = ft.Dropdown(
            label="Region",
            options=[ft.dropdown.Option(name) for name in countries_by_region],
            value="North America" if "North America" in countries_by_region else None,
            dense=True,
        )

        def country_options(region_name):
            return [
                ft.dropdown.Option(item["code"], item["name"])
                for item in countries_by_region.get(region_name, [])
            ]

        initial_countries = country_options(region.value)
        country = ft.Dropdown(
            label="Country",
            options=initial_countries,
            value=(
                "us"
                if any(option.key == "us" for option in initial_countries)
                else initial_countries[0].key if initial_countries else None
            ),
            dense=True,
        )
        result = ft.Column(spacing=10)

        def change_region(_):
            country.options = country_options(region.value)
            country.value = country.options[0].key if country.options else None
            result.controls.clear()
            self.page.update()

        def run(_):
            try:
                if not region.value or not country.value:
                    self.snack("Choose a region and country.", True)
                    return
                data = self.api.request(
                    "GET",
                    "/compare",
                    params={
                        "field": field.value,
                        "region": region.value,
                        "country": country.value,
                        "dark_mode": self.dark,
                    },
                )
                self.compare_data = data
                result.controls.clear()
                result.controls.append(ft.Text(f"Careers in {data['field']}", size=16, weight=ft.FontWeight.W_600))
                context = data.get("market_context") or {}
                result.controls.append(
                    self.card(
                        ft.Text(
                            f"Market data · {context.get('country', 'Global baseline')}",
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(context.get("message", ""), size=12, color=self.c("muted")),
                        ft.Text(
                            "Curated salary estimates are in USD. Live salary estimates use the "
                            "selected country's local currency and salary-disclosed job ads. "
                            "Career ranking, openings, growth, and trend remain based on the curated global baseline.",
                            size=11,
                            color=self.c("muted"),
                        ),
                    )
                )
                for line in data.get("insights") or []:
                    result.controls.append(ft.Text("• " + line, size=12))
                chart = data.get("chart")
                if chart:
                    result.controls.append(
                        ft.Image(
                            src_base64=chart,
                            width=max(160, min(360, (self.page.width or 400) - 88)),
                            fit=ft.ImageFit.CONTAIN,
                        )
                    )
                for row in data.get("careers") or []:
                    live = row.get("live_market") or {}
                    live_text = (
                        f"Live median {live['currency']} {live['median_salary']:,.0f} "
                        f"(P25 {live['p25_salary']:,.0f} · P75 {live['p75_salary']:,.0f}) "
                        f"from {live['sample_size']:,} salary-disclosed job ads"
                        + (
                            f" · {live['job_ads_count']:,} current matching job ads"
                            if live.get("job_ads_count") is not None
                            else ""
                        )
                        + " "
                        f"(Adzuna histogram range estimate; retrieved "
                        f"{live.get('retrieved_at', '')[:10]})."
                        if live.get("status") == "live"
                        else live.get("message", "No live country-specific salary estimate.")
                    )
                    result.controls.append(
                        self.card(
                            ft.Text(row["career"], weight=ft.FontWeight.W_600),
                            ft.Text(row["description"], size=12, color=self.c("muted")),
                            ft.Text(
                                f"Median ${row['median_salary_usd']:,}  ·  p25 ${row['p25_salary']:,}  ·  p75 ${row['p75_salary']:,}",
                                size=12,
                            ),
                            ft.Text(
                                f"Openings {row['job_openings_index']}  ·  5y growth {row['growth_5y_pct']}%  ·  remote {row['remote_share_pct']}%",
                                size=12,
                            ),
                            ft.Text(
                                f"Typical education: {row['typical_education']}  ·  composite {row['composite_score']}",
                                size=12,
                            ),
                            ft.Text(live_text, size=12, color=self.c("muted")),
                        )
                    )
                self.page.update()
            except ApiError as exc:
                self.snack(exc.message, True)

        region.on_change = change_region
        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("Compare careers", size=18, weight=ft.FontWeight.W_600),
                    ft.Text(
                        "Compare careers using NorthStar's curated baseline and, when configured, "
                        "live country-specific salary data.",
                        size=12,
                        color=self.c("muted"),
                    ),
                    field,
                    region,
                    country,
                    self.btn("Compare", run),
                ),
                result,
            ],
            expand=True,
            spacing=12,
        )

    def friends_page(self):
        nsid = self.field("NorthStar ID", hint="Interstellar-0000-0001")
        field = self.field("Field")
        career = self.field("Career")
        results = ft.Column(
            [ft.Text("Search by NorthStar ID, or enter a field or career to find people.", color=self.c("muted"))],
            spacing=8,
        )

        def show_person(person):
            self.person = person
            exps = person.get("experiences") or []
            exp_txt = ", ".join(
                f"{e['career']} ({'current' if e['is_current'] else str(e['years']) + 'y'})" for e in exps
            ) or "New graduate"
            self.page.dialog = ft.AlertDialog(
                title=ft.Text(person["username"]),
                content=ft.Column(
                    [
                        ft.Text(person["northstar_id"]),
                        ft.Text(f"Age {person['age']} · {person['gender']}"),
                        ft.Text(f"Current title: {person['current_career']}"),
                        ft.Text(exp_txt),
                    ],
                    tight=True,
                    width=280,
                ),
                actions=[
                    ft.TextButton(
                        "Cancel",
                        on_click=lambda e: self.close_person_dialog(),
                    ),
                    ft.ElevatedButton(
                        "Chat",
                        bgcolor=self.c("primary"),
                        color=self.c("on_primary"),
                        on_click=lambda e, pid=person["id"], name=person["username"]: self.open_chat(pid, name),
                    )
                ],
            )
            self.page.dialog.open = True
            self.page.update()

        def paint(people):
            results.controls.clear()
            if not people:
                results.controls.append(ft.Text("No people matched.", color=self.c("muted")))
            for person in people:
                results.controls.append(
                    ft.ListTile(
                        title=ft.Text(person["username"]),
                        subtitle=ft.Text(f"{person['current_career']} · {person['northstar_id']}"),
                        on_click=lambda e, p=person: show_person(p),
                    )
                )
            self.page.update()

        def search_id(_):
            code = (nsid.value or "").strip()
            if not code:
                self.snack("Enter a NorthStar ID to look up someone.", True)
                return
            try:
                data = self.api.request("GET", "/friends/search", params={"northstar_id": code})
                paint(data["people"])
            except ApiError as exc:
                self.snack(exc.message, True)

        def search_filter(_):
            params = {}
            selected_field = (field.value or "").strip()
            selected_career = (career.value or "").strip()
            if selected_field:
                params["field"] = selected_field
            if selected_career:
                params["career"] = selected_career
            if not params:
                paint([])
                results.controls[0].value = "Choose a field or enter a career before searching."
                self.page.update()
                return
            try:
                data = self.api.request("GET", "/friends/search", params=params)
                paint(data["people"])
            except ApiError as exc:
                self.snack(exc.message, True)

        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("Find friends", size=18, weight=ft.FontWeight.W_600),
                    nsid,
                    self.btn("Look up ID", search_id),
                    field,
                    career,
                    self.btn("Search field / career", search_filter),
                    ft.Text(
                        "You can search by NorthStar ID, field, or career. Choose or enter at least one filter.",
                        size=12,
                        color=self.c("muted"),
                    ),
                ),
                self.card(ft.Text("People", weight=ft.FontWeight.W_600), results),
            ],
            expand=True,
            spacing=12,
        )

    def close_person_dialog(self):
        if getattr(self.page, "dialog", None):
            self.page.dialog.open = False
            self.page.update()

    def open_chat(self, user_id: int, name: str):
        self.chat_id = user_id
        self.chat_name = name
        if getattr(self.page, "dialog", None):
            self.page.dialog.open = False
        self.go("chat"        )

    def admin_page(self):
        if not (self.api.user or {}).get("is_admin"):
            return self.card(ft.Text("Dataset administration is available only to the configured admin account."))
        try:
            data = self.api.request("GET", "/admin/datasets")
            history = self.api.request("GET", "/admin/history").get("versions", [])
        except ApiError as exc:
            return self.card(ft.Text(exc.message, color=self.c("danger")))

        datasets = data["datasets"]
        records = data["career_records"]
        careers = { (row["field"], row["career"]): row for row in datasets["careers"] }
        field_names = [row["field"] for row in datasets["fields"]]
        by_id = {str(row["id"]): row for row in records}
        default_id = str(records[0]["id"]) if records else None
        career_choice = ft.Dropdown(
            label="Career to edit",
            options=[
                ft.dropdown.Option(str(row["id"]), f"{row['career']} · {row['field']}")
                for row in records
            ],
            value=default_id,
            dense=True,
        )
        field_input = self.field("Field")
        new_field_input = self.field("New field name")
        new_field_list = ft.Column(
            [
                ft.Text(item, size=12, color=self.c("muted"))
                for item in sorted(field_names, key=str.casefold)
            ],
            spacing=2,
        )
        name_input = self.field("Career")
        median_input = self.field("Median salary (USD)")
        p25_input = self.field("P25 salary (USD)")
        p75_input = self.field("P75 salary (USD)")
        openings_input = self.field("Job openings index (0–100)")
        growth_input = self.field("Five-year growth (%)")
        remote_input = self.field("Remote share (%)")
        education_input = self.field("Typical education")
        difficulty_input = self.field("Difficulty (1–5)")
        description_input = self.field("Career description")
        required_input = ft.TextField(
            label="Required skills (one per line: skill | category | importance | hours)",
            multiline=True,
            min_lines=4,
            max_lines=10,
            border_color=self.c("primary"),
        )
        version_dataset_choice = ft.Dropdown(
            label="Dataset to inspect",
            options=[
                ft.dropdown.Option(name, name.replace("_", " ").title())
                for name in datasets
            ],
            value="careers",
            dense=True,
        )
        selected_snapshot = [None]
        market_input = ft.TextField(
            label="Job-market rows (one per line: year | openings index | average salary)",
            multiline=True,
            min_lines=3,
            max_lines=8,
            border_color=self.c("primary"),
        )
        skill_input = self.field("New skill")
        skill_category_input = self.field("Skill category", "Foundations")
        skill_importance_input = self.field("Importance (1–5)", "3")
        skill_hours_input = self.field("Hours to learn", "20")
        resource_skill_input = self.field("Learning resource skill")
        resource_title_input = self.field("Learning source title")
        resource_type_input = self.field("Source type", "Course")
        resource_url_input = self.field("Learning source URL")
        resource_level_input = self.field("Level", "Beginner")
        resource_choice = ft.Dropdown(label="Learning source to remove", options=[], dense=True)
        current_data = ft.Column(spacing=4)
        current_sources = ft.Column(spacing=4)
        version_choice = ft.Dropdown(
            label="Dataset version",
            options=[
                ft.dropdown.Option(str(item["version"]), f"v{item['version']} · {item['summary']}")
                for item in history
            ],
            value=str(history[0]["version"]) if history else None,
            dense=True,
        )
        version_preview = ft.TextField(
            label="Selected version contents",
            read_only=True,
            multiline=True,
            min_lines=5,
            max_lines=12,
            border_color=self.c("primary"),
        )
        selected_id = [default_id]

        def set_text(control, value):
            control.value = "" if value is None else str(value)

        def selected_career():
            return by_id.get(selected_id[0]) if selected_id[0] else None

        def paint_current():
            record = selected_career()
            current_data.controls.clear()
            current_sources.controls.clear()
            if not record:
                return
            career = careers.get((record["field"], record["career"]))
            skill_rows = [item for item in datasets["skills"] if item["career"] == record["career"]]
            skill_names = {item["skill"] for item in skill_rows}
            sources = [
                (index, item) for index, item in enumerate(datasets["resources"])
                if item["skill"] in skill_names
            ]
            current_data.controls.append(
                ft.Text(
                    f"{record['field']} · {record['career']} · "
                    f"${career['median_salary_usd']:,} median · {len(skill_rows)} skills",
                    size=12,
                    color=self.c("text"),
                )
            )
            current_data.controls.extend(
                ft.Text(f"• {item['skill']} ({item['category']})", size=12, color=self.c("muted"))
                for item in skill_rows
            )
            current_sources.controls.extend(
                ft.TextButton(
                    f"{item['title']} · {item['source_type']} · {item['level']} — {item['skill']}",
                    url=item["url"],
                )
                for _, item in sources
            )
            resource_choice.options = [
                ft.dropdown.Option(str(index), f"{item['title']} · {item['skill']}")
                for index, item in sources
            ]
            if resource_choice.options:
                resource_choice.value = resource_choice.options[0].key
            else:
                resource_choice.value = None

        def fill_selected(_=None):
            selected_id[0] = career_choice.value
            record = selected_career()
            if not record:
                return
            career = careers.get((record["field"], record["career"]))
            if not career:
                return
            for control, key in (
                (field_input, "field"), (name_input, "career"),
                (median_input, "median_salary_usd"), (p25_input, "p25_salary"),
                (p75_input, "p75_salary"), (openings_input, "job_openings_index"),
                (growth_input, "growth_5y_pct"), (remote_input, "remote_share_pct"),
                (education_input, "typical_education"), (difficulty_input, "difficulty"),
                (description_input, "description"),
            ):
                set_text(control, career[key])
            skill_rows = sorted(
                [item for item in datasets["skills"] if item["career"] == record["career"]],
                key=lambda item: item["sort_order"],
            )
            required_input.value = "\n".join(
                f"{item['skill']} | {item['category']} | {item['importance']} | {item['hours_to_learn']}"
                for item in skill_rows
            )
            market_rows = sorted(
                [item for item in datasets["job_market"] if item["career"] == record["career"]],
                key=lambda item: item["year"],
            )
            market_input.value = "\n".join(
                f"{item['year']} | {item['openings_index']} | {item['avg_salary']}"
                for item in market_rows
            )
            resource_skill_input.value = skill_rows[0]["skill"] if skill_rows else ""
            paint_current()
            if _ is not False:
                self.page.update()

        def begin_new_career(_=None):
            selected_id[0] = None
            career_choice.value = None
            for control in (
                field_input, name_input, median_input, p25_input, p75_input,
                openings_input, growth_input, remote_input, education_input,
                difficulty_input, description_input, required_input, market_input,
            ):
                control.value = ""
            current_data.controls.clear()
            current_sources.controls.clear()
            self.page.update()

        def number(control, kind):
            value = (control.value or "").strip()
            return kind(value)

        def save_career(_=None):
            try:
                payload = {
                    "field": field_input.value or "",
                    "career": name_input.value or "",
                    "median_salary_usd": number(median_input, int),
                    "p25_salary": number(p25_input, int),
                    "p75_salary": number(p75_input, int),
                    "job_openings_index": number(openings_input, int),
                    "growth_5y_pct": number(growth_input, float),
                    "remote_share_pct": number(remote_input, float),
                    "typical_education": education_input.value or "",
                    "difficulty": number(difficulty_input, int),
                    "description": description_input.value or "",
                }
                if selected_id[0]:
                    result = self.api.request(
                        "PUT", f"/admin/careers/{selected_id[0]}", json=payload
                    )
                else:
                    result = self.api.request("POST", "/admin/careers", json=payload)
                self.refresh_shell()
                self.snack(f"Career saved as dataset version {result['version']}.")
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def add_field(_=None):
            try:
                result = self.api.request(
                    "POST",
                    "/admin/fields",
                    json={"field": new_field_input.value or ""},
                )
                self.refresh_shell()
                self.snack(
                    f"Field added in dataset version {result['version']}. "
                    "You can now add careers to it."
                )
            except ApiError as exc:
                self.snack(exc.message, True)

        def save_skills(_=None):
            if not selected_id[0]:
                self.snack("Save the career before editing its required skills.", True)
                return
            record = selected_career()
            try:
                parsed = []
                for order, line in enumerate((required_input.value or "").splitlines(), 1):
                    if not line.strip():
                        continue
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) != 4:
                        raise ValueError(f"Skill line {order} must have four | separated values.")
                    parsed.append({
                        "career": record["career"], "skill": parts[0], "category": parts[1],
                        "importance": int(parts[2]), "hours_to_learn": float(parts[3]),
                        "sort_order": order,
                    })
                result = self.api.request(
                    "PUT", f"/admin/careers/{selected_id[0]}/skills",
                    json={"skills": parsed},
                )
                self.refresh_shell()
                self.snack(f"Required skills updated in dataset version {result['version']}.")
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def add_skill(_=None):
            record = selected_career()
            if not record:
                self.snack("Choose or save a career first.", True)
                return
            try:
                existing_count = sum(item["career"] == record["career"] for item in datasets["skills"])
                result = self.api.request(
                    "POST", "/admin/skills",
                    json={
                        "career": record["career"], "skill": skill_input.value or "",
                        "category": skill_category_input.value or "Foundations",
                        "importance": number(skill_importance_input, int),
                        "hours_to_learn": number(skill_hours_input, float),
                        "sort_order": existing_count + 1,
                    },
                )
                self.refresh_shell()
                self.snack(f"Skill added in dataset version {result['version']}.")
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def save_market(_=None):
            if not selected_id[0]:
                self.snack("Save the career before editing job-market data.", True)
                return
            try:
                points = []
                for line_number, line in enumerate((market_input.value or "").splitlines(), 1):
                    if not line.strip():
                        continue
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) != 3:
                        raise ValueError(f"Market row {line_number} must have year | openings | salary.")
                    points.append({
                        "year": int(parts[0]), "openings_index": int(parts[1]),
                        "avg_salary": int(parts[2]),
                    })
                result = self.api.request(
                    "PUT", f"/admin/careers/{selected_id[0]}/job-market",
                    json={"points": points},
                )
                self.refresh_shell()
                self.snack(f"Job-market data updated in dataset version {result['version']}.")
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def add_resource(_=None):
            try:
                result = self.api.request(
                    "POST", "/admin/resources",
                    json={
                        "skill": resource_skill_input.value or "",
                        "title": resource_title_input.value or "",
                        "source_type": resource_type_input.value or "Course",
                        "url": resource_url_input.value or "",
                        "level": resource_level_input.value or "Beginner",
                    },
                )
                self.refresh_shell()
                self.snack(f"Learning source added in dataset version {result['version']}.")
            except ApiError as exc:
                self.snack(exc.message, True)

        def remove_resource(_=None):
            try:
                index = int(resource_choice.value)
                item = datasets["resources"][index]
                result = self.api.request(
                    "DELETE", "/admin/resources",
                    json={"skill": item["skill"], "title": item["title"], "url": item["url"]},
                )
                self.refresh_shell()
                self.snack(f"Learning source removed in dataset version {result['version']}.")
            except (ApiError, ValueError, TypeError, IndexError) as exc:
                self.snack(getattr(exc, "message", str(exc)) or "Choose a learning source to remove.", True)

        def show_version_dataset(_=None):
            snapshot = selected_snapshot[0]
            if not snapshot:
                return
            dataset_name = version_dataset_choice.value
            version_preview.value = json.dumps(
                {
                    "version": snapshot["version"],
                    "action": snapshot["action"],
                    "changed_by": snapshot["changed_by"],
                    "summary": snapshot["summary"],
                    "dataset": dataset_name,
                    "records": snapshot["datasets"][dataset_name],
                },
                ensure_ascii=False,
                indent=2,
            )
            self.page.update()

        def inspect_version(_=None):
            if not version_choice.value:
                self.snack("There is no dataset history to inspect yet.", True)
                return
            try:
                selected_snapshot[0] = self.api.request(
                    "GET", f"/admin/history/{version_choice.value}"
                )
                show_version_dataset()
            except ApiError as exc:
                self.snack(exc.message, True)

        career_choice.on_change = fill_selected
        version_dataset_choice.on_change = show_version_dataset
        if default_id:
            fill_selected(False)
        career_list = ft.Column(
            [
                ft.Text(f"{item['field']} · {item['career']}", size=12, color=self.c("muted"))
                for item in sorted(records, key=lambda row: (row["field"], row["career"]))
            ],
            spacing=2,
        )
        history_list = ft.Column(
            [
                ft.Text(
                    f"v{item['version']} · {item['summary']} · by {item['changed_by']}",
                    size=12,
                    color=self.c("muted"),
                )
                for item in history
            ] or [ft.Text("No dataset changes have been recorded yet.")],
            spacing=4,
        )
        source_fields = [
            resource_skill_input, resource_title_input, resource_type_input,
            resource_url_input, resource_level_input,
        ]
        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("Dataset administration", size=18, weight=ft.FontWeight.W_600),
                    ft.Text(
                        f"Current version: v{data['version']} · "
                        f"{len(field_names)} fields · "
                        f"{len(datasets['careers'])} careers · "
                        f"{len(datasets['skills'])} skills · "
                        f"{len(datasets['resources'])} learning sources",
                        size=12,
                        color=self.c("muted"),
                    ),
                        ft.Text("Fields", size=13, weight=ft.FontWeight.W_600),
                        new_field_list,
                        new_field_input,
                        self.btn("Add field", add_field),
                        self.btn("Add a new career", begin_new_career, filled=False),
                    career_choice,
                    field_input,
                    name_input,
                    median_input,
                    p25_input,
                    p75_input,
                    openings_input,
                    growth_input,
                    remote_input,
                    education_input,
                    difficulty_input,
                    description_input,
                    self.btn("Save career / salary statistics", save_career),
                ),
                self.card(
                    ft.Text("Required skills", weight=ft.FontWeight.W_600),
                    required_input,
                    self.btn("Replace required skills", save_skills),
                    ft.Text("Add one skill", size=13, weight=ft.FontWeight.W_600),
                    skill_input,
                    skill_category_input,
                    skill_importance_input,
                    skill_hours_input,
                    self.btn("Add skill", add_skill),
                ),
                self.card(
                    ft.Text("Job-market information", weight=ft.FontWeight.W_600),
                    market_input,
                    self.btn("Replace job-market rows", save_market),
                ),
                self.card(
                    ft.Text("Learning sources", weight=ft.FontWeight.W_600),
                    ft.Text("Sources for the selected career:", size=12, color=self.c("muted")),
                    current_sources,
                    resource_choice,
                    self.btn("Remove selected source", remove_resource, filled=False),
                    ft.Text("Add a learning source", size=13, weight=ft.FontWeight.W_600),
                    *source_fields,
                    self.btn("Add learning source", add_resource),
                ),
                self.card(
                    ft.Text("Current career dataset", weight=ft.FontWeight.W_600),
                    career_list,
                    current_data,
                ),
                self.card(
                    ft.Text("Dataset version history", weight=ft.FontWeight.W_600),
                    history_list,
                    version_choice,
                    self.btn("Inspect selected version", inspect_version, filled=False),
                    version_dataset_choice,
                    version_preview,
                ),
            ],
            expand=True,
            spacing=12,
        )

    def messages_page(self):
        try:
            data = self.api.request("GET", "/messages/threads")
            self.threads = data.get("threads") or []
        except ApiError as exc:
            self.snack(exc.message, True)
            self.threads = []
        tiles = []
        for th in self.threads:
            unread = f"  · {th['unread']} new" if th.get("unread") else ""
            tiles.append(
                ft.ListTile(
                    title=ft.Text(th["username"] + unread),
                    subtitle=ft.Text(th.get("last_message", "")[:80]),
                    on_click=lambda e, t=th: self.open_chat(t["user_id"], t["username"]),
                )
            )
        return ft.ListView(
            controls=[
                self.card(ft.Text("Messages", size=18, weight=ft.FontWeight.W_600), *(tiles or [ft.Text("No chats yet.")])),
            ],
            expand=True,
            spacing=12,
        )

    def load_notifications(self):
        try:
            data = self.api.request("GET", "/notifications")
            self.notifications = data.get("items") or []
            self.unread = data.get("unread", 0)
        except ApiError as exc:
            self.notifications = []
            self.unread = 0
            self.snack(exc.message, True)

    def notifications_page(self):
        self.load_notifications()
        items = []
        for note in self.notifications:
            created = note.get("created_at", "")
            timestamp = created.replace("T", " ")[:16] if created else ""
            message_sender = (note.get("extra") or {}).get("from_id")

            def open_notification_chat(_=None, item=note, sender_id=message_sender):
                if not sender_id:
                    return
                try:
                    self.api.request("POST", f"/notifications/{item['id']}/read")
                    self.open_chat(sender_id, (item.get("extra") or {}).get("from_name", "Friend"))
                except ApiError as exc:
                    self.snack(exc.message, True)

            items.append(
                ft.ListTile(
                    leading=ft.Icon(
                        ft.icons.CIRCLE if not note.get("read") else ft.icons.CIRCLE_OUTLINED,
                        color=self.c("primary") if not note.get("read") else self.c("muted"),
                        size=12,
                    ),
                    title=ft.Text(note["title"], weight=ft.FontWeight.W_600 if not note.get("read") else ft.FontWeight.NORMAL),
                    subtitle=ft.Text(
                        f"{note['body']}\n{timestamp}",
                        color=self.c("muted"),
                        size=12,
                    ),
                    is_three_line=True,
                    on_click=open_notification_chat if note.get("kind") == "message" and message_sender else None,
                )
            )

        def mark_all_read(_):
            try:
                self.api.request("POST", "/notifications/read")
                self.load_notifications()
                self.refresh_shell()
            except ApiError as exc:
                self.snack(exc.message, True)

        controls = [
            ft.Row(
                [
                    ft.Text("Notifications", size=18, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    self.btn("Mark all as read", mark_all_read, filled=False),
                ]
            ),
            ft.Text(
                f"{self.unread} unread",
                size=12,
                color=self.c("muted"),
            ),
            *(items or [ft.Text("You’re all caught up.", color=self.c("muted"))]),
        ]
        return ft.ListView(
            controls=[self.card(*controls)],
            expand=True,
            spacing=12,
        )

    def chat_page(self):
        if not self.chat_id:
            return self.card(ft.Text("Pick someone in Find Friends."))
        try:
            data = self.api.request("GET", f"/messages/{self.chat_id}")
            self.messages = data.get("messages") or []
        except ApiError as exc:
            return self.card(ft.Text(exc.message, color=self.c("danger")))
        bubbles = []
        me = (self.api.user or {}).get("id")
        max_bubble_width = max(120, min(280, (self.page.width or 360) - 96))
        for msg in self.messages:
            mine = msg["sender_id"] == me
            bubble_width = min(max(len(msg["body"]) * 7 + 28, 72), max_bubble_width)
            bubbles.append(
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text(
                                msg["body"],
                                color=self.c("chat_mine_text") if mine else self.c("chat_theirs_text"),
                                size=13,
                                width=bubble_width - 24,
                            ),
                            bgcolor=self.c("chat_mine") if mine else self.c("chat_theirs"),
                            padding=ft.padding.symmetric(horizontal=12, vertical=9),
                            border_radius=16,
                            width=bubble_width,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START,
                )
            )
        box = self.field("Write a message")

        def send(_):
            body = (box.value or "").strip()
            if not body:
                self.snack("Write a message first.", True)
                return
            try:
                self.api.request("POST", f"/messages/{self.chat_id}", json={"body": body})
                box.value = ""
                self.refresh_shell()
            except ApiError as exc:
                self.snack(exc.message, True)

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(
                            ft.icons.ARROW_BACK,
                            tooltip="Back to messages",
                            icon_color=self.c("text"),
                            on_click=lambda e: self.go("messages"),
                        ),
                        ft.Text(f"Chat with {self.chat_name}", size=16, weight=ft.FontWeight.W_600),
                    ],
                    spacing=4,
                ),
                ft.ListView(controls=bubbles, expand=True, spacing=10, auto_scroll=True),
                ft.Container(
                    content=ft.Row(
                        [ft.Container(content=box, expand=True), self.btn("Send", send)],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=self.c("surface"),
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=14,
                ),
            ],
            expand=True,
            spacing=10,
        )

    def advisor_page(self):
        conversations = []
        try:
            conversations = self.api.request("GET", "/advisor/conversations").get("conversations") or []
            if not self.advisor_initialized:
                self.advisor_conversation_id = conversations[0]["id"] if conversations else None
                self.advisor_initialized = True
            if self.advisor_conversation_id is not None:
                selected = self.api.request(
                    "GET", f"/advisor/conversations/{self.advisor_conversation_id}"
                )
                self.advisor_log = [
                    (
                        "user" if message["role"] == "user" else "ai",
                        message["content"],
                        message.get("web_sources") or [],
                    )
                    for message in selected.get("messages", [])
                ]
        except ApiError as exc:
            self.snack(exc.message, True)

        box = self.field("Ask about careers, goals, or a skill you do not understand")
        log = ft.Column(spacing=8)
        for role, text, sources in self.advisor_log:
            controls = [
                ft.Text("You" if role == "user" else "NorthStar AI", weight=ft.FontWeight.W_600),
                ft.Text(text, size=13),
            ]
            valid_sources = [
                source
                for source in sources
                if source.get("url", "").startswith(("https://", "http://"))
            ]
            if valid_sources:
                controls.append(ft.Text("External sources", size=12, weight=ft.FontWeight.W_600))
                for source in valid_sources:
                    controls.extend(
                        [
                            ft.TextButton(
                                source.get("title") or source["url"],
                                url=source["url"],
                                style=ft.ButtonStyle(
                                    padding=ft.padding.symmetric(vertical=2, horizontal=0),
                                    alignment=ft.alignment.center_left,
                                ),
                            ),
                            ft.Text(
                                source.get("snippet", ""),
                                size=11,
                                color=self.c("muted"),
                            ),
                        ]
                    )
            log.controls.append(self.card(*controls))

        def new_conversation(_):
            self.advisor_conversation_id = None
            self.advisor_log = []
            self.advisor_initialized = True
            self.go("advisor")

        def select_conversation(conversation_id):
            self.advisor_conversation_id = conversation_id
            self.advisor_initialized = True
            self.go("advisor")

        history_controls = [
            ft.TextButton(
                f"{'Current · ' if item['id'] == self.advisor_conversation_id else ''}{item['title']}",
                on_click=lambda e, conversation_id=item["id"]: select_conversation(conversation_id),
            )
            for item in conversations
        ]
        history_card = self.card(
            ft.Row(
                [
                    ft.Text("Previous conversations", weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    self.btn("New chat", new_conversation, filled=False),
                ]
            ),
            *(
                history_controls
                or [
                    ft.Text(
                        "Your saved conversations will appear here.",
                        size=12,
                        color=self.c("muted"),
                    )
                ]
            ),
        )

        def ask(_):
            msg = (box.value or "").strip()
            if not msg:
                self.snack("Write a question first.", True)
                return
            try:
                res = self.api.request(
                    "POST",
                    "/advisor/ask",
                    json={
                        "message": msg,
                        "conversation_id": self.advisor_conversation_id,
                    },
                )
                self.advisor_conversation_id = res["conversation_id"]
                self.advisor_log.append(("user", msg, []))
                self.advisor_log.append(("ai", res.get("reply", ""), res.get("web_sources", [])))
                box.value = ""
                self.refresh_shell()
            except ApiError as exc:
                self.snack(exc.message, True)

        def preset_project(_):
            box.value = "Suggest a project I can finish in two weeks."
            ask(None)

        def preset_sql(_):
            box.value = "Explain SQL in an easy way."
            ask(None)

        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("NorthStar AI", size=18, weight=ft.FontWeight.W_600),
                    ft.Text(
                        "Ask for career advice, an easy explanation, or a project idea. "
                        "Your conversations are saved to your account. Questions may be sent to a public "
                        "web search; avoid sensitive details.",
                        size=12,
                        color=self.c("muted"),
                    ),
                    box,
                    self.btn("Ask", ask),
                    ft.TextButton("Suggest a project", on_click=preset_project),
                    ft.TextButton("Explain SQL simply", on_click=preset_sql),
                ),
                history_card,
                log,
            ],
            expand=True,
            spacing=10,
            auto_scroll=True,
        )

    def about_page(self):
        try:
            data = self.api.request("GET", "/about")
            body = data.get("body", "")
        except ApiError as exc:
            body = exc.message
        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("About NorthStar", size=20, weight=ft.FontWeight.W_600),
                    ft.Text(body, size=13, color=self.c("text")),
                )
            ],
            expand=True,
        )

    def profile_page(self):
        user = self.api.user or {}
        username = self.field("Username", user.get("username", ""))
        age = self.field("Age", str(user.get("age", "")))
        gender = ft.Dropdown(
            label="Gender",
            options=[ft.dropdown.Option(g) for g in GENDERS],
            value=user.get("gender"),
            dense=True,
        )
        photo = ft.CircleAvatar(
            radius=36,
            content=ft.Text((user.get("username") or "?")[:1].upper()),
        )
        if user.get("profile_photo"):
            photo = ft.CircleAvatar(radius=36, foreground_image_src=API_BASE_URL + user["profile_photo"])
        edu_box = ft.Column()
        exp_box = ft.Column()
        edu_state: list[dict] = []
        exp_state: list[dict] = []

        def add_edu_row(item=None):
            item = item or {"school": "", "level": "Bachelor", "field_of_study": ""}
            school = self.field("School", item.get("school", ""))
            level = ft.Dropdown(
                label="Level",
                options=[ft.dropdown.Option(x) for x in LEVELS],
                value=item.get("level") if item.get("level") in LEVELS else "Other",
                dense=True,
            )
            study = self.field("Field of study", item.get("field_of_study", ""))
            row = {"school": school, "level": level, "field": study}
            wrap = ft.Column([school, level, study])
            row["wrap"] = wrap
            edu_state.append(row)
            edu_box.controls.append(wrap)

        def add_exp_row(item=None):
            item = item or {"career": "", "years": None, "is_current": False}
            career = self.field("Career", item.get("career", ""))
            years = self.field(
                "Years of experience",
                "" if item.get("years") is None else str(item.get("years")),
                hint="Leave blank for a new current role",
            )
            current = ft.Checkbox(
                label="Current role",
                value=bool(item.get("is_current")) and not any(
                    row["current"].value for row in exp_state
                ),
            )
            row = {"career": career, "years": years, "current": current}

            def select_current(e):
                if e.control.value:
                    for other in exp_state:
                        if other is not row:
                            other["current"].value = False
                    self.page.update()

            current.on_change = select_current
            def remove_experience(_):
                exp_state.remove(row)
                exp_box.controls.remove(wrap)
                self.page.update()

            wrap = ft.Column(
                [
                    career,
                    years,
                    current,
                    ft.TextButton("Remove experience", on_click=remove_experience),
                ]
            )
            row["wrap"] = wrap
            exp_state.append(row)
            exp_box.controls.append(wrap)

        for item in user.get("educations") or []:
            add_edu_row(item)
        experience_items = []
        experience_positions = {}
        for item in user.get("experiences") or []:
            key = item["career"].strip().casefold()
            if key not in experience_positions:
                experience_positions[key] = len(experience_items)
                experience_items.append(item)
            else:
                index = experience_positions[key]
                if item.get("is_current") and not experience_items[index].get("is_current"):
                    experience_items[index] = item
        for item in experience_items:
            add_exp_row(item)

        picker = ft.FilePicker()
        if picker not in self.page.overlay:
            self.page.overlay.append(picker)

        def on_photo(e: ft.FilePickerResultEvent):
            if not e.files:
                return
            path = e.files[0].path
            try:
                with open(path, "rb") as handle:
                    self.api.request(
                        "POST",
                        "/users/me/photo",
                        files={"file": (e.files[0].name, handle, "application/octet-stream")},
                    )
                self.api.me()
                self.refresh_shell()
            except ApiError as exc:
                self.snack(exc.message, True)

        picker.on_result = on_photo

        def save(_):
            try:
                payload = {
                    "username": username.value,
                    "age": int(age.value),
                    "gender": gender.value,
                    "educations": [
                        {
                            "school": r["school"].value,
                            "level": r["level"].value,
                            "field_of_study": r["field"].value or "",
                        }
                        for r in edu_state
                    ],
                    "experiences": [
                        {
                            "career": r["career"].value,
                            "years": float(r["years"].value.strip())
                            if (r["years"].value or "").strip()
                            else None,
                            "is_current": bool(r["current"].value),
                        }
                        for r in exp_state
                    ],
                }
                self.api.request("PUT", "/users/me", json=payload)
                self.api.me()
                self.snack("Profile saved.")
                self.refresh_shell()
            except (ApiError, ValueError) as exc:
                self.snack(getattr(exc, "message", str(exc)), True)

        def change_pw(_):
            current = self.field("Current password", password=True)
            new = self.field("New password", password=True)
            confirm = self.field("Confirm new password", password=True)

            def submit(__):
                try:
                    self.api.request(
                        "POST",
                        "/users/me/password",
                        json={
                            "current_password": current.value,
                            "new_password": new.value,
                            "confirm_password": confirm.value,
                        },
                    )
                    self.page.dialog.open = False
                    self.snack("Password changed.")
                    self.page.update()
                except ApiError as exc:
                    self.snack(exc.message, True)

            def cancel(_):
                self.page.dialog.open = False
                self.page.update()

            self.page.dialog = ft.AlertDialog(
                title=ft.Text("Change password"),
                content=ft.Column([current, new, confirm], tight=True, width=300),
                actions=[
                    ft.TextButton("Cancel", on_click=cancel),
                    ft.TextButton("Save", on_click=submit),
                ],
            )
            self.page.dialog.open = True
            self.page.update()

        return ft.ListView(
            controls=[
                self.card(
                    ft.Text("Profile", size=18, weight=ft.FontWeight.W_600),
                    ft.Row([photo, ft.TextButton("Change photo", on_click=lambda e: picker.pick_files())]),
                    ft.Text(f"NorthStar ID: {user.get('northstar_id')}", color=self.c("muted")),
                    ft.Text("The ID is assigned at login time and cannot be edited.", size=11, color=self.c("muted")),
                    username,
                    age,
                    gender,
                    ft.Text("Education", weight=ft.FontWeight.W_600),
                    edu_box,
                    self.btn("Add education", lambda e: (add_edu_row(), self.page.update()), filled=False),
                    ft.Text("Career experiences", weight=ft.FontWeight.W_600),
                    exp_box,
                    self.btn("Add career", lambda e: (add_exp_row(), self.page.update()), filled=False),
                    ft.Text("Password", weight=ft.FontWeight.W_600),
                    ft.Text("••••••••"),
                    self.btn("Edit password", change_pw, filled=False),
                    self.btn("Save profile", save),
                )
            ],
            expand=True,
            spacing=12,
        )


def main(page: ft.Page):
    NorthStarApp(page)


if __name__ == "__main__":
    ft.app(target=main)
