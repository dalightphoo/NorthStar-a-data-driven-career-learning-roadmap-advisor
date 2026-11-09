from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.security import get_current_user
from backend.services.analysis import compare_field
from backend.services.catalog import fields
from backend.services.live_market import (
    LOCATIONS,
    country_for_code,
    live_market_for_careers,
    regions_and_countries,
)

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("")
def compare(
    field: str,
    region: str | None = None,
    country: str | None = None,
    dark_mode: bool = False,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    field = field.strip()
    if not field:
        raise HTTPException(status_code=400, detail="Choose a field to compare careers.")
    known = {item.lower(): item for item in fields()}
    if field.lower() not in known:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field. Try one of: {', '.join(fields())}",
        )
    result = compare_field(db, known[field.lower()], dark_mode=dark_mode)
    if not country:
        result["market_context"] = {
            "status": "baseline",
            "message": "Showing NorthStar's curated global baseline in USD.",
        }
        return result
    if not region or region not in LOCATIONS:
        raise HTTPException(status_code=400, detail="Choose a valid region and country.")
    if country not in {item["code"] for item in LOCATIONS[region]}:
        raise HTTPException(status_code=400, detail="Choose a country within the selected region.")

    country_info = country_for_code(country)
    live_by_career = live_market_for_careers(
        [item["career"] for item in result["careers"]],
        country,
    )
    statuses = {item["status"] for item in live_by_career.values()}
    status = "live" if statuses == {"live"} else "partial" if "live" in statuses else (
        "baseline" if statuses == {"baseline"} else "unavailable"
    )
    if status == "baseline":
        message = (
            f"Showing NorthStar's curated global baseline in USD. Add Adzuna API credentials "
            f"to .env to load live {country_info['name']} salary data."
        )
    elif status == "live":
        message = (
            f"Live, salary-disclosed job-ad estimates from Adzuna for {country_info['name']}. "
            "Curated global estimates remain available as the baseline."
        )
    elif status == "partial":
        message = (
            f"Live Adzuna salary data is available for some careers in {country_info['name']}; "
            "other careers use the curated baseline only."
        )
    else:
        message = (
            f"Adzuna live data is unavailable for {country_info['name']}. "
            "The curated global baseline is still shown."
        )
    for career in result["careers"]:
        career["live_market"] = live_by_career[career["career"]]
    result["market_context"] = {
        "region": region,
        "country": country_info["name"],
        "country_code": country,
        "currency": country_info["currency"],
        "status": status,
        "source": "Adzuna salary histogram" if "live" in statuses else "NorthStar curated dataset",
        "message": message,
    }
    return result


@router.get("/locations")
def compare_locations(_: object = Depends(get_current_user)):
    return regions_and_countries()
