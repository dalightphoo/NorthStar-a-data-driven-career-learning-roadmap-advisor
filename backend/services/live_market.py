from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx

from backend.config import ADZUNA_APP_ID, ADZUNA_APP_KEY

LOCATIONS = {
    "Africa": [
        {"code": "za", "name": "South Africa", "currency": "ZAR"},
    ],
    "Asia": [
        {"code": "in", "name": "India", "currency": "INR"},
        {"code": "sg", "name": "Singapore", "currency": "SGD"},
    ],
    "Europe": [
        {"code": "at", "name": "Austria", "currency": "EUR"},
        {"code": "be", "name": "Belgium", "currency": "EUR"},
        {"code": "ch", "name": "Switzerland", "currency": "CHF"},
        {"code": "de", "name": "Germany", "currency": "EUR"},
        {"code": "es", "name": "Spain", "currency": "EUR"},
        {"code": "fr", "name": "France", "currency": "EUR"},
        {"code": "gb", "name": "United Kingdom", "currency": "GBP"},
        {"code": "it", "name": "Italy", "currency": "EUR"},
        {"code": "nl", "name": "Netherlands", "currency": "EUR"},
        {"code": "pl", "name": "Poland", "currency": "PLN"},
    ],
    "Latin America": [
        {"code": "br", "name": "Brazil", "currency": "BRL"},
        {"code": "mx", "name": "Mexico", "currency": "MXN"},
    ],
    "North America": [
        {"code": "ca", "name": "Canada", "currency": "CAD"},
        {"code": "us", "name": "United States", "currency": "USD"},
    ],
    "Oceania": [
        {"code": "au", "name": "Australia", "currency": "AUD"},
        {"code": "nz", "name": "New Zealand", "currency": "NZD"},
    ],
}

_CACHE_TTL = timedelta(minutes=30)
_cache: dict[tuple[str, str], tuple[datetime, dict | None]] = {}
_cache_lock = Lock()


def regions_and_countries() -> dict:
    return {
        "regions": [
            {"region": region, "countries": countries}
            for region, countries in LOCATIONS.items()
        ],
        "provider": "Adzuna",
    }


def country_for_code(country_code: str) -> dict:
    return _country(country_code)


def live_market_for_career(career: str, country_code: str) -> dict:
    country = _country(country_code)
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return {
            "status": "baseline",
            "message": "Live figures are not configured. Add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env.",
            "currency": country["currency"],
        }

    cache_key = (country_code, career.casefold())
    now = datetime.now(timezone.utc)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1] or {
                "status": "unavailable",
                "message": "No salary-disclosed job ads were found for this career and country.",
                "currency": country["currency"],
            }

    cacheable = True
    try:
        response = httpx.get(
            f"https://api.adzuna.com/v1/api/jobs/{country_code}/histogram",
            params={
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "what": career,
                "content-type": "application/json",
            },
            timeout=12,
        )
        response.raise_for_status()
        histogram = response.json().get("histogram", {})
        bins = sorted(
            (
                (float(salary), int(count))
                for salary, count in histogram.items()
                if int(count) > 0
            ),
            key=lambda item: item[0],
        )
        total = sum(count for _, count in bins)
        if not total:
            result = None
        else:
            result = {
                "status": "live",
                "source": "Adzuna salary histogram",
                "retrieved_at": now.isoformat(),
                "currency": country["currency"],
                "sample_size": total,
                "p25_salary": _weighted_salary_quantile(bins, total, 0.25),
                "median_salary": _weighted_salary_quantile(bins, total, 0.50),
                "p75_salary": _weighted_salary_quantile(bins, total, 0.75),
                "job_ads_count": None,
            }
            try:
                search = httpx.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/1",
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "what": career,
                        "results_per_page": 1,
                        "content-type": "application/json",
                    },
                    timeout=12,
                )
                search.raise_for_status()
                count = search.json().get("count")
                if count is not None:
                    result["job_ads_count"] = int(count)
            except (httpx.HTTPError, ValueError, TypeError):
                result["job_ads_message"] = "Live job-ad count is unavailable; salary distribution is still shown."
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        cacheable = False
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        message = (
            f"Adzuna returned HTTP {status}."
            if status is not None
            else "The live market provider could not be reached or returned invalid data."
        )
        result = {"status": "unavailable", "message": message, "currency": country["currency"]}

    if cacheable:
        with _cache_lock:
            _cache[cache_key] = (now, result)
    if result is None:
        return {
            "status": "unavailable",
            "message": "No salary-disclosed job ads were found for this career and country.",
            "currency": country["currency"],
        }
    return result


def live_market_for_careers(careers: list[str], country_code: str) -> dict[str, dict]:
    _country(country_code)
    results = {}
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(careers)))) as executor:
        futures = {
            executor.submit(live_market_for_career, career, country_code): career
            for career in careers
        }
        for future in as_completed(futures):
            career = futures[future]
            results[career] = future.result()
    return results


def _country(country_code: str) -> dict:
    for countries in LOCATIONS.values():
        for country in countries:
            if country["code"] == country_code:
                return country
    raise ValueError(f"Unsupported country code: {country_code}")


def _weighted_salary_quantile(
    bins: list[tuple[float, int]],
    total: int,
    quantile: float,
) -> int:
    target = max(1, int((total - 1) * quantile) + 1)
    cumulative = 0
    for lower_bound, count in bins:
        cumulative += count
        if cumulative >= target:
            return int(round(lower_bound))
    return int(round(bins[-1][0]))
