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
from models import Game, CompanyGame, PregameMarket, Selection
from schemas import GameIn, GameOut, GameSummary, IngestResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAVE_FAILED_PAYLOADS = os.getenv("SAVE_FAILED_PAYLOADS", "true").lower() == "true"
PAYLOADS_DIR = Path("payloads")


def _save_failed_payload(body: bytes):
    if not SAVE_FAILED_PAYLOADS:
        return
    PAYLOADS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = PAYLOADS_DIR / f"payload_{timestamp}_FAILED.json"
    filename.write_bytes(body)
    logger.info(f"Failed payload saved to {filename}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised")
    yield


app = FastAPI(
    title="Pregames Snapshot API",
    description="Ingests game snapshots from System Two and stores them.",
    version="1.0.0",
    lifespan=lifespan,
)


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


def _upsert_company_game(db: Session, game: Game, cg_in) -> tuple[CompanyGame, bool]:
    """
    Find existing company game for this bookmaker, or create a new one.
    Returns (company_game, was_updated).
    """
    live = cg_in.LiveData

    existing = db.query(CompanyGame).filter(
        CompanyGame.game_id == game.id,
        CompanyGame.company_name == cg_in.CompanyName,
    ).first()

    if existing:
        # Update live score data
        existing.score_home = live.ScoreHome if live else None
        existing.score_away = live.ScoreAway if live else None
        existing.corners_home = live.CornersHome if live else None
        existing.corners_away = live.CornersAway if live else None

        # Delete old markets and selections — they'll be re-inserted fresh
        for market in existing.markets:
            db.delete(market)
        db.flush()

        # Re-insert markets and selections
        for mkt_in in cg_in.PregameMarkets:
            market = PregameMarket(
                company_game_id=existing.id,
                market_id=mkt_in.Id,
                umid=mkt_in.Umid,
                market_name=mkt_in.Omn,
            )
            for sel_in in mkt_in.Slcs:
                market.selections.append(Selection(
                    selection_id=sel_in.Id,
                    user_short_name=sel_in.Usn,
                    original_short_name=sel_in.Osn,
                    odd=sel_in.Odd,
                    best_odd=sel_in.Bod,
                    last_odd=sel_in.Lod,
                ))
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
        )
        for mkt_in in cg_in.PregameMarkets:
            market = PregameMarket(
                market_id=mkt_in.Id,
                umid=mkt_in.Umid,
                market_name=mkt_in.Omn,
            )
            for sel_in in mkt_in.Slcs:
                market.selections.append(Selection(
                    selection_id=sel_in.Id,
                    user_short_name=sel_in.Usn,
                    original_short_name=sel_in.Osn,
                    odd=sel_in.Odd,
                    best_odd=sel_in.Bod,
                    last_odd=sel_in.Lod,
                ))
            company_game.markets.append(market)

        db.add(company_game)
        return company_game, False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse, summary="Ingest a snapshot batch from System Two")
async def ingest_snapshot(request: Request, db: Session = Depends(get_db)):
    body = await request.body()

    try:
        data = json.loads(body)
        payload = [GameIn(**g) for g in data]
    except Exception as e:
        _save_failed_payload(body)
        raise HTTPException(status_code=422, detail=str(e))

    inserted, updated, game_ids = 0, 0, []

    for game_payload in payload:
        existing_game = _get_existing_game(db, game_payload)

        if existing_game:
            # Game exists — upsert each bookmaker
            game_ids.append(existing_game.id)
            for cg_in in game_payload.ListCompanyGames:
                _, was_updated = _upsert_company_game(db, existing_game, cg_in)
                if was_updated:
                    updated += 1
                    logger.info(f"Updated {cg_in.CompanyName} for game id={existing_game.id}: {game_payload.HomeTeam} vs {game_payload.AwayTeam}")
        else:
            # New game — insert everything fresh
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

            for cg_in in game_payload.ListCompanyGames:
                _upsert_company_game(db, game, cg_in)

            game_ids.append(game.id)
            inserted += 1
            logger.info(f"Inserted game id={game.id}: {game_payload.HomeTeam} vs {game_payload.AwayTeam}")

    db.commit()

    return IngestResponse(
        inserted=inserted,
        updated=updated,
        game_ids=game_ids,
        message=f"Processed {len(payload)} game(s): {inserted} inserted, {updated} bookmaker(s) updated.",
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