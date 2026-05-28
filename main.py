import logging
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import init_db, get_db
from models import Game, CompanyGame, PregameMarket, Selection, MarketType, TeamAlias
from schemas import GameIn, GameOut, GameSummary, IngestResponse
from normalizer import normalize

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAVE_FAILED_PAYLOADS = os.getenv("SAVE_FAILED_PAYLOADS", "true").lower() == "true"
SAVE_ALL_PAYLOADS    = os.getenv("SAVE_ALL_PAYLOADS", "false").lower() == "true"
PAYLOADS_DIR = Path("payloads")


def _save_payload(body: bytes, suffix: str = ""):
    PAYLOADS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = PAYLOADS_DIR / f"payload_{timestamp}{suffix}.json"
    filename.write_bytes(body)
    logger.info(f"Payload saved to {filename}")


def _save_failed_payload(body: bytes):
    if not SAVE_FAILED_PAYLOADS:
        return
    _save_payload(body, suffix="_FAILED")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised")
    yield


app = FastAPI(
    title="Pregames Snapshot API",
    description="Ingests game snapshots from System Two and stores them.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"500 error: {traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": traceback.format_exc()})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    for error in exc.errors():
        loc = " -> ".join(str(l) for l in error.get("loc", []))
        logger.error(f"422 | {loc} | {error.get('msg')}")
    try:
        body = await request.body()
        _save_failed_payload(body)
    except Exception:
        pass
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_existing_game(db: Session, payload: GameIn) -> Optional[Game]:
    return db.query(Game).filter(
        Game.home_team == payload.HomeTeam,
        Game.away_team == payload.AwayTeam,
        Game.date_time_starts_utc == payload.DateTimeStartsUTC,
        Game.league == payload.League,
    ).first()


def _upsert_market_type(db: Session, umid: int, canonical_name: Optional[str]):
    """
    Insert or update a market_types row keyed on umid.
    canonical_name comes from App_Umn and may be None.
    An existing non-null canonical_name is never overwritten by None.
    """
    if umid is None:
        return
    existing = db.query(MarketType).filter(MarketType.umid == umid).first()
    if not existing:
        db.add(MarketType(umid=umid, canonical_name=canonical_name))
        db.flush()
    else:
        if canonical_name is not None:
            existing.canonical_name = canonical_name
        existing.last_updated_at = datetime.utcnow()


def _upsert_team_alias(db: Session, canonical_name: str, company_name: str, company_team_name: str):
    """Record how a bookmaker names a team. Only inserts, never updates — first seen wins."""
    if not canonical_name or not company_team_name:
        return
    existing = db.query(TeamAlias).filter(
        TeamAlias.canonical_name == canonical_name,
        TeamAlias.company_name == company_name,
    ).first()
    if not existing:
        db.add(TeamAlias(
            canonical_name=canonical_name,
            company_name=company_name,
            company_team_name=company_team_name,
        ))


def _flatten_ladder(ladder, prefix: str) -> dict:
    """Extract up to 3 positions from a Bod or Lod ladder into flat columns."""
    result = {
        f"{prefix}_bpf_pos1": None, f"{prefix}_bsz_pos1": None,
        f"{prefix}_bpf_pos2": None, f"{prefix}_bsz_pos2": None,
        f"{prefix}_bpf_pos3": None, f"{prefix}_bsz_pos3": None,
    }
    if not ladder or not isinstance(ladder, dict):
        return result
    for entry in ladder.get("Ens", []):
        pos = str(entry.get("Pos", ""))
        bpf = entry.get("Bpf")
        bsz = entry.get("Bsz")
        if pos == "1":
            result[f"{prefix}_bpf_pos1"], result[f"{prefix}_bsz_pos1"] = bpf, bsz
        elif pos == "2":
            result[f"{prefix}_bpf_pos2"], result[f"{prefix}_bsz_pos2"] = bpf, bsz
        elif pos == "3":
            result[f"{prefix}_bpf_pos3"], result[f"{prefix}_bsz_pos3"] = bpf, bsz
    return result


def _flatten_best_odd(bod, lod) -> dict:
    """Flatten both back (Bod) and lay (Lod) ladders."""
    result = {}
    result.update(_flatten_ladder(bod, "back"))
    result.update(_flatten_ladder(lod, "lay"))
    return result


def _build_selections(mkt_in, home_team: str, away_team: str) -> List[Selection]:
    selections = []
    for sel_in in mkt_in.Slcs:
        norm = normalize(
            umid=mkt_in.Umid,
            osn=sel_in.Osn,
            usn=sel_in.Usn,
            home_team=home_team,
            away_team=away_team,
        )
        bod = _flatten_best_odd(sel_in.Bod, sel_in.Lod)
        selections.append(Selection(
            selection_id=sel_in.Id,
            canonical_outcome=norm["canonical_outcome"],
            line_value=norm["line_value"],
            raw_outcome=norm["raw_outcome"],
            odd=sel_in.Odd,
            **bod,
        ))
    return selections


def _upsert_company_game(db: Session, game: Game, cg_in, home_team: str, away_team: str):
    """Upsert a bookmaker's data for a game. Returns (company_game, was_updated)."""
    live = cg_in.LiveData

    existing = db.query(CompanyGame).filter(
        CompanyGame.game_id == game.id,
        CompanyGame.company_name == cg_in.CompanyName,
    ).first()

    if existing:
        existing.score_home = live.ScoreHome if live else None
        existing.score_away = live.ScoreAway if live else None
        existing.corners_home = live.CornersHome if live else None
        existing.corners_away = live.CornersAway if live else None
        existing.date_live_data_updated = cg_in.DateLiveDataUpdated
        existing.date_pregame_data_updated = cg_in.DatePregameDataUpdated

        # Bulk delete selections first, then markets (FK constraint order)
        market_ids = [m.id for m in db.query(PregameMarket.id).filter(
            PregameMarket.company_game_id == existing.id
        ).all()]

        if market_ids:
            db.query(Selection).filter(
                Selection.market_id.in_(market_ids)
            ).delete(synchronize_session=False)

        db.query(PregameMarket).filter(
            PregameMarket.company_game_id == existing.id
        ).delete(synchronize_session=False)
        db.flush()

        # Record bookmaker team name aliases
        if cg_in.HomeTeam:
            _upsert_team_alias(db, home_team, cg_in.CompanyName, cg_in.HomeTeam)
        if cg_in.AwayTeam:
            _upsert_team_alias(db, away_team, cg_in.CompanyName, cg_in.AwayTeam)

        seen_market_ids = set()
        for mkt_in in cg_in.PregameMarkets:
            if (mkt_in.Id, mkt_in.Umid) in seen_market_ids:
                logger.warning(f"Skipping duplicate market_id={mkt_in.Id} in payload")
                continue
            seen_market_ids.add((mkt_in.Id, mkt_in.Umid))
            _upsert_market_type(db, mkt_in.Umid, mkt_in.App_Umn)
            market = PregameMarket(
                company_game_id=existing.id,
                market_id=mkt_in.Id,
                umid=mkt_in.Umid,
            )
            market.selections = _build_selections(mkt_in, home_team, away_team)
            db.add(market)

        return existing, True

    else:
        company_game = CompanyGame(
            game_id=game.id,
            company_name=cg_in.CompanyName,
            home_team=cg_in.HomeTeam,
            away_team=cg_in.AwayTeam,
            league=cg_in.League,
            score_home=live.ScoreHome if live else None,
            score_away=live.ScoreAway if live else None,
            corners_home=live.CornersHome if live else None,
            corners_away=live.CornersAway if live else None,
            date_live_data_updated=cg_in.DateLiveDataUpdated,
            date_pregame_data_updated=cg_in.DatePregameDataUpdated,
        )
        # Record bookmaker team name aliases
        if cg_in.HomeTeam:
            _upsert_team_alias(db, home_team, cg_in.CompanyName, cg_in.HomeTeam)
        if cg_in.AwayTeam:
            _upsert_team_alias(db, away_team, cg_in.CompanyName, cg_in.AwayTeam)

        seen_market_ids = set()
        for mkt_in in cg_in.PregameMarkets:
            if (mkt_in.Id, mkt_in.Umid) in seen_market_ids:
                logger.warning(f"Skipping duplicate market_id={mkt_in.Id} in payload")
                continue
            seen_market_ids.add((mkt_in.Id, mkt_in.Umid))
            _upsert_market_type(db, mkt_in.Umid, mkt_in.App_Umn)
            market = PregameMarket(
                market_id=mkt_in.Id,
                umid=mkt_in.Umid,
            )
            market.selections = _build_selections(mkt_in, home_team, away_team)
            company_game.markets.append(market)

        db.add(company_game)
        db.flush()
        return company_game, False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse, summary="Ingest a snapshot batch from System Two")
async def ingest_snapshot(request: Request, db: Session = Depends(get_db)):
    received_at = datetime.utcnow()
    body = await request.body()

    logger.info(f"[INGEST] Request received at {received_at.isoformat()}Z | body size={len(body)} bytes")

    if SAVE_ALL_PAYLOADS:
        _save_payload(body)

    try:
        data = json.loads(body)
        payload = [GameIn(**g) for g in data]
    except Exception as e:
        logger.error(f"[INGEST] Parse failed at {received_at.isoformat()}Z: {e}")
        _save_failed_payload(body)
        raise HTTPException(status_code=422, detail=str(e))

    logger.info(f"[INGEST] Parsed {len(payload)} game(s) from payload")

    inserted, updated, game_ids, failed = 0, 0, [], []

    for game_payload in payload:
        label = f"{game_payload.HomeTeam} vs {game_payload.AwayTeam} ({game_payload.League})"
        try:
            existing_game = _get_existing_game(db, game_payload)

            if existing_game:
                game_ids.append(existing_game.id)
                for cg_in in game_payload.ListCompanyGames:
                    _, was_updated = _upsert_company_game(
                        db, existing_game, cg_in,
                        game_payload.HomeTeam, game_payload.AwayTeam
                    )
                    if was_updated:
                        updated += 1
                        logger.info(f"  [UPDATE] {cg_in.CompanyName} | game id={existing_game.id} | {label}")
            else:
                game = Game(
                    date_time_starts_utc=game_payload.DateTimeStartsUTC,
                    home_team=game_payload.HomeTeam,
                    away_team=game_payload.AwayTeam,
                    league=game_payload.League,
                    country=game_payload.Country,
                    univ_home_id=game_payload.Univ_HomeId,
                    univ_away_id=game_payload.Univ_AwayId,
                    univ_league_id=game_payload.Univ_LeagueId,
                )
                db.add(game)
                db.flush()

                bookmakers = []
                for cg_in in game_payload.ListCompanyGames:
                    _upsert_company_game(db, game, cg_in, game_payload.HomeTeam, game_payload.AwayTeam)
                    bookmakers.append(cg_in.CompanyName)

                game_ids.append(game.id)
                inserted += 1
                logger.info(f"  [INSERT] game id={game.id} | {label} | bookmakers={bookmakers}")

        except Exception as e:
            logger.error(f"  [FAILED] {label} | error={e}")
            failed.append(label)
            db.rollback()

    db.commit()

    elapsed = (datetime.utcnow() - received_at).total_seconds()
    logger.info(
        f"[INGEST] Done in {elapsed:.2f}s | "
        f"total={len(payload)} | inserted={inserted} | updated={updated} | failed={len(failed)}"
    )
    if failed:
        logger.warning(f"[INGEST] Failed games: {failed}")

    return IngestResponse(
        inserted=inserted,
        updated=updated,
        game_ids=game_ids,
        message=f"Processed {len(payload)} game(s): {inserted} inserted, {updated} bookmaker(s) updated."
        + (f" {len(failed)} failed." if failed else ""),
    )


@app.get("/games", response_model=List[GameSummary], summary="List all games")
def list_games(
    league: Optional[str] = Query(None, description="Filter by league name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Game)
    if league:
        q = q.filter(Game.league.ilike(f"%{league}%"))
    return q.order_by(Game.date_time_starts_utc.desc()).offset(offset).limit(limit).all()


@app.get("/games/{game_id}", response_model=GameOut, summary="Get full game detail with markets")
def get_game(game_id: int, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@app.get("/health")
def health():
    return {"status": "ok"}