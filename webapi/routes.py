"""
Authenticated JSON endpoints for the dashboard (all under /api, login required).
"""
import logging
import os
import tempfile
from typing import Literal

import excel_export
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from webapi import queries
from webapi.auth import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(current_user)])


def _require_game(game_id: int) -> dict:
    game = queries.load_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@router.get("/summary")
def summary():
    return {**queries.load_summary(), **queries.load_api_quota()}


@router.get("/summary/daily")
def summary_daily(days: int = Query(30, ge=1, le=365)):
    return queries.load_daily_counts(days)


@router.get("/filters")
def filters():
    return queries.load_filters()


@router.get("/games")
def games(
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    country: str | None = None,
    sofa: Literal["all", "matched", "unmatched"] = "all",
    q: str | None = Query(None, min_length=2, max_length=100),
):
    if date is None and q is None:
        raise HTTPException(400, "Provide a date or a search term (q).")
    return queries.load_games(date, country, sofa, q)


@router.get("/games/{game_id}")
def game(game_id: int):
    g = _require_game(game_id)
    return {k: v for k, v in g.items() if not k.startswith("_")}


@router.get("/games/{game_id}/odds")
def game_odds(game_id: int):
    _require_game(game_id)
    return queries.load_odds(game_id)


@router.get("/games/{game_id}/statistics")
def game_statistics(game_id: int):
    _require_game(game_id)
    return queries.load_statistics(game_id)


@router.post("/games/{game_id}/statistics/fetch")
def fetch_statistics(game_id: int):
    game = _require_game(game_id)
    sofa_id = game["sofa_event_id"]
    if not sofa_id:
        raise HTTPException(409, "This game is not matched to Sofasport.")

    import batch_match_sofa as bms  # lazy: module has import-time side effects

    if not bms.RAPIDAPI_KEY:
        raise HTTPException(503, "RAPIDAPI_KEY is not configured on the server.")
    used = bms.get_cycle_call_count(bms.get_billing_cycle_start())
    if used < 0:
        raise HTTPException(503, "Could not read api_call_log — refusing to call the API without a quota count.")
    if used >= bms.MONTHLY_CALL_LIMIT:
        raise HTTPException(429, f"RapidAPI quota reached ({used}/{bms.MONTHLY_CALL_LIMIT}). It resets on the 18th.")
    try:
        raw = bms.fetch_sofa_statistics(sofa_id)
    except Exception:
        logger.exception("[STATS] Sofasport statistics fetch failed for game %s", game_id)
        raise HTTPException(502, "Sofasport request failed. Try again later.")
    if raw:
        bms.store_statistics(game_id, sofa_id, raw, game["_kickoff_dt"].strftime("%Y-%m-%d"))
    return queries.load_statistics(game_id)


@router.get("/games/{game_id}/incidents")
def game_incidents(game_id: int):
    _require_game(game_id)
    return queries.load_incidents(game_id)


@router.get("/aliases")
def aliases(q: str = Query("", max_length=100)):
    return queries.load_aliases(q.strip())


@router.get("/market-types")
def market_types():
    return queries.load_market_types()


@router.get("/blown-leads")
def blown_leads(min_lead: int = Query(2, ge=1, le=5)):
    return queries.load_blown_leads(min_lead)


@router.get("/match-rates")
def match_rates():
    return queries.load_match_rates()


DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


def _export_filters(countries, leagues, umids, sheets) -> excel_export.ExportFilters:
    return excel_export.ExportFilters(tuple(countries), tuple(leagues), tuple(umids), tuple(sheets))


@router.get("/export/preview")
def export_preview(date_from: str = Query(..., pattern=DATE_RE), date_to: str = Query(..., pattern=DATE_RE),
                   include_odds: bool = True,
                   countries: list[str] = Query(default=[], max_length=300),
                   leagues: list[str] = Query(default=[], max_length=500),
                   umids: list[int] = Query(default=[], max_length=200),
                   sheets: list[str] = Query(default=[], max_length=20)):
    f = _export_filters(countries, leagues, umids, sheets)
    try:
        return excel_export.preview(date_from, date_to, include_odds, filters=f)
    except (excel_export.ExportRangeError, excel_export.ExportFilterError) as e:
        raise HTTPException(400, str(e))


@router.get("/export.xlsx")
def export_xlsx(date_from: str = Query(..., pattern=DATE_RE), date_to: str = Query(..., pattern=DATE_RE),
                include_odds: bool = True,
                countries: list[str] = Query(default=[], max_length=300),
                leagues: list[str] = Query(default=[], max_length=500),
                umids: list[int] = Query(default=[], max_length=200),
                sheets: list[str] = Query(default=[], max_length=20)):
    f = _export_filters(countries, leagues, umids, sheets)
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        excel_export.build_workbook(tmp, date_from, date_to, include_odds, filters=f)
    except (excel_export.ExportRangeError, excel_export.ExportFilterError) as e:
        os.unlink(tmp)
        raise HTTPException(400, str(e))
    except excel_export.ExportTooLarge as e:
        os.unlink(tmp)
        raise HTTPException(413, str(e))
    except Exception:
        os.unlink(tmp)
        raise
    return FileResponse(tmp, filename=excel_export.default_filename(date_from, date_to, include_odds,
                                                                    filtered=f.narrows_rows),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        background=BackgroundTask(os.unlink, tmp))
