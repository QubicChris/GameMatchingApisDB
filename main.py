import logging
from contextlib import asynccontextmanager
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
    logger.error(f"422 Validation error on {request.method} {request.url}")
    logger.error(f"Details: {exc.errors()}")
    # Also log the raw body so you can see exactly what came in
    try:
        body = await request.body()
        logger.error(f"Raw body (first 1000 chars): {body[:1000]}")
    except Exception:
        pass
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game_already_exists(db: Session, payload: GameIn) -> bool:
    return db.query(Game).filter(
        Game.home_team == payload.HomeTeam,
        Game.away_team == payload.AwayTeam,
        Game.date_time_starts_utc == payload.DateTimeStartsUTC,
        Game.league == payload.League,
    ).first() is not None


def _build_game(payload: GameIn) -> Game:
    game = Game(
        date_time_starts_utc=payload.DateTimeStartsUTC,
        home_team=payload.HomeTeam,
        away_team=payload.AwayTeam,
        league=payload.League,
        country=payload.Country,
        univ_home_id=payload.Univ_HomeId,
        univ_away_id=payload.Univ_AwayId,
        univ_league_id=payload.Univ_LeagueId,
    )
    for cg_in in payload.ListCompanyGames:
        live = cg_in.LiveData
        company_game = CompanyGame(
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
        game.company_games.append(company_game)
    return game


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse, summary="Ingest a snapshot batch from System Two")
def ingest_snapshot(
    payload: List[GameIn],
    db: Session = Depends(get_db),
):
    inserted, skipped, game_ids = 0, 0, []

    for game_payload in payload:
        if _game_already_exists(db, game_payload):
            logger.info(f"Skipping duplicate: {game_payload.HomeTeam} vs {game_payload.AwayTeam}")
            skipped += 1
            continue

        game = _build_game(game_payload)
        db.add(game)
        db.flush()
        game_ids.append(game.id)
        inserted += 1
        logger.info(f"Inserted game id={game.id}: {game_payload.HomeTeam} vs {game_payload.AwayTeam}")

    db.commit()

    return IngestResponse(
        inserted=inserted,
        skipped=skipped,
        game_ids=game_ids,
        message=f"Processed {len(payload)} game(s): {inserted} inserted, {skipped} skipped.",
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