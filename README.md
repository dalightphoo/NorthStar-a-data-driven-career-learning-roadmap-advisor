# NorthStar

NorthStar is a data-driven career and learning roadmap advisor for graduates and career changers. It includes a Python/Flet client, a FastAPI backend, curated career and learning datasets, career-comparison analysis, and an optional live job-market data integration.

The client has responsive layouts and safe-area handling, but Android packaging and release are not completed yet.

## What NorthStar does

- Creates user accounts with education and optional career experience.
- Builds a day-by-day learning roadmap with skills, sources, and portfolio projects.
- Tracks progress and completed roadmaps.
- Compares careers using salary, job-market, and growth indicators.
- Lets users find friends, chat, receive notifications, and ask NorthStar AI for guidance.
- Provides a separate administrator dashboard for editing fields, careers, skills, market data, and learning sources.
- Supports light and dark themes.
- Remembers the selected theme and signed-in session in device storage across app restarts. Access tokens renew automatically; logging out revokes the saved session.

## Technologies and where they are used

- **Python** runs the client and backend logic.
- **Flet** builds the client interface in `client/`. Its screens are written in Python.
- **FastAPI** provides the HTTP API in `backend/`; the Flet client calls it for login, roadmaps, career comparisons, chat, and other features.
- **SQLAlchemy** manages database connections and application records. The project includes the PostgreSQL driver `psycopg2-binary`.
- **PostgreSQL** stores application data when the configured database is reachable. The app falls back to a local SQLite database if it cannot connect to the configured database.
- **Pandas** loads and works with the CSV career, skill, project, resource, and market datasets.
- **NumPy** calculates comparison scores and supports roadmap scheduling calculations.
- **Matplotlib** creates the career-comparison chart.
- **HTTPX** makes requests to Adzuna for optional live market data.
- **NorthStar AI** answers from NorthStar's teaching datasets by default. An optional external AI API can be configured with an API key.
- **Docker Compose** runs the PostgreSQL database for local development. Docker is not a Python package, and it does not currently run the API or Flet client in containers.

Python package dependencies are listed in `requirements.txt`. Docker Engine/Desktop with the Docker Compose command is installed separately; do not add Docker to `requirements.txt`.

## Run locally

### Prerequisites

- Python 3.12 (the project has been developed and checked with Python 3.12).
- Docker Desktop or Docker Engine with Docker Compose, if you want to use PostgreSQL.
- PostgreSQL can be skipped: if the configured PostgreSQL database is unreachable, the app uses local SQLite.

### Start the PostgreSQL database

From the project directory:

```powershell
docker compose up -d
```

The Compose file starts PostgreSQL 16 as `northstar-postgres`, exposes port `5432` to the host, and stores its data in the persistent `northstar_pg` volume. The credentials in `docker-compose.yml` are for local development only; change them before using this setup in a shared or production environment.

To stop the database without removing its stored data:

```powershell
docker compose stop
```

### Install Python packages

```powershell
python -m pip install -r requirements.txt
```

### Configure the database

The default `docker-compose.yml` credentials are intended for local development. To use that database, set `DATABASE_URL` in the project-root `.env` to a PostgreSQL connection URL matching the Compose credentials. Keep `.env` private and never commit real passwords or API keys.

If PostgreSQL is not configured or is unavailable when the backend starts, NorthStar selects `northstar.db` (SQLite) in the project directory instead. The database choice is made at startup.

### Start the API and client

Start the API in one terminal:

```powershell
python run_server.py
```

Then start the Flet client in a second terminal:

```powershell
python run_app.py
```

Register an account to begin. Education is required; career experience may be left empty for new graduates. Demo accounts are also seeded: `maya`, `kenji`, `aisha`, and `omar`, each with the development password `NorthStar123`. Do not use demo credentials outside local development.

## Career data and analysis

NorthStar uses curated CSV datasets in `data/` for fields, careers, skills, projects, learning resources, and historical/estimated job-market information. The administrator dashboard can update the supported datasets; updates are versioned and generate in-app notifications. Existing database installations receive newly added career records on startup.

Compare Careers reads the stored career statistics (with a bundled career catalog fallback), then compares careers within the selected field. It computes a **relative composite score** from:

- Salary: **40%**
- Job-openings index: **35%**
- Five-year growth: **25%**

Each measure is standardized as a z-score against the careers in that field before applying the weights. This makes different units comparable within the selected field. A higher composite score means the career ranks better on this chosen weighted mix relative to its peers; it is not a hiring probability, a promise of salary, or a universal measure of career quality. The weights are transparent project rules, not a trained predictive model.

The page also reports the top salary, openings index, and growth values, compares salary with the field median, plots salary against the openings index, and shows the stored yearly trend. The openings index is an index, not necessarily a count of current vacancies.

### Curated baseline and optional live market data

Compare Careers always shows NorthStar's curated global baseline in USD. If valid Adzuna credentials are configured and the provider has data, selecting a region and country adds live country-specific salary estimates in the country's local currency and a count of matching job ads. Salary percentiles come from Adzuna's salary histogram of advertised salaries; they are not official salary-survey figures.

Live results are cached for 30 minutes. Missing credentials, provider errors, or unavailable salary data leave the curated baseline available. **The live data does not replace the baseline or feed into the composite ranking, openings index, growth, or historical trend.** Do not compare local-currency amounts across countries without currency conversion.

To enable Adzuna, add credentials to the project-root `.env` and restart the backend:

```text
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
```

Adzuna documents its [job search API](https://developer.adzuna.com/docs/search) and [salary histogram API](https://developer.adzuna.com/docs/histogram).

### Roadmap rules

Roadmaps are generated from the selected career's curated skills, learning-hour estimates, sources, and projects. The learner's available hours per day, days per week, and chosen duration determine the schedule. Related prior experience can skip some introductory skills, and up to three projects may be selected for a plan. These are dataset-driven planning rules and estimates, not a machine-learning prediction of an individual's learning speed.

When available, roadmap plans add up to three live web-search suggestions for their first few skills alongside the curated sources. These suggestions are labeled as unreviewed web results; they do not add skills, change learning-hour estimates, or affect project selection. If search is unavailable, the curated plan still works and reports that live resource search was unavailable.

For broader and more dependable coverage, NorthStar uses a hybrid approach: keep career definitions, skill maps, learning-hour estimates, and projects curated and reviewable; use live search for supplementary, changing references; and expand curated datasets with verified records when adding career coverage. Search volume alone should not be treated as dataset quality.

## Optional AI configuration

NorthStar AI searches the public web for relevant source snippets and displays links with its answer. If `OPENAI_API_KEY` is configured, the external AI provider uses those results together with NorthStar's curated data to answer; without a key, NorthStar shows the search excerpts directly. Search results are starting points, not independently verified conclusions. Search is enabled by default and can be disabled with `WEB_SEARCH_ENABLED=false`. Only the question used for the search is sent to DuckDuckGo; do not include sensitive information in it. Restart the backend after changing environment settings.

To enable the configured external AI provider, set `OPENAI_API_KEY` in `.env`; `OPENAI_BASE_URL` and `OPENAI_MODEL` can also be configured.

## Administrator setup

Set a fixed administrator username and password in the project-root `.env`:

```text
NORTHSTAR_ADMIN_USERNAME=your_admin_username
NORTHSTAR_ADMIN_PASSWORD=use_a_private_password_at_least_12_characters_long
```

Use a unique password of at least 12 characters. Restart the backend to create the configured administrator account if needed, then sign in through the app. Admin accounts open a dedicated Dataset Admin dashboard instead of user-facing pages. Admin changes are saved to the bundled datasets, recorded in version history, and announced to users in-app.

## Data and security notes

- Keep `.env` private; it may contain database, administrator, AI-provider, or Adzuna credentials.
- The default PostgreSQL credentials in `docker-compose.yml` and seeded demo-user password are development conveniences, not production credentials.
- Career salary and market values are educational estimates. Live market data is optional and limited to Compare Careers.
- Android packaging and store release are not part of the current project version.
