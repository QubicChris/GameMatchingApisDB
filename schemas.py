from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# --- Inbound (mirrors System Two JSON) ---

class SelectionIn(BaseModel):
    Id: str
    Usn: Optional[str] = None
    Osn: Optional[str] = None
    Odd: Optional[float] = None
    Bod: Optional[float] = None
    Lod: Optional[float] = None
    Ui_n: Optional[str] = None
    Ui_t: Optional[str] = None


class PregameMarketIn(BaseModel):
    Id: str
    Umid: Optional[int] = None
    Omn: Optional[str] = None
    Slcs: List[SelectionIn] = []
    Ui_n: Optional[str] = None


class LiveDataIn(BaseModel):
    ScoreHome: Optional[int] = None
    ScoreAway: Optional[int] = None
    CornersHome: Optional[int] = None
    CornersAway: Optional[int] = None


class CompanyGameIn(BaseModel):
    CompanyName: str
    DateTimeStartsUTC: Optional[datetime] = None
    HomeTeam: Optional[str] = None
    AwayTeam: Optional[str] = None
    League: Optional[str] = None
    DateLiveDataUpdated: Optional[datetime] = None
    DatePregameDataUpdated: Optional[datetime] = None
    LiveData: Optional[LiveDataIn] = None
    PregameMarkets: List[PregameMarketIn] = []


class GameIn(BaseModel):
    DateTimeStartsUTC: datetime
    HomeTeam: str
    AwayTeam: str
    League: str
    Country: Optional[str] = None
    Univ_HomeId: Optional[int] = None
    Univ_AwayId: Optional[int] = None
    Univ_LeagueId: Optional[int] = None
    ListCompanyGames: List[CompanyGameIn] = []


# --- Outbound ---

class SelectionOut(BaseModel):
    id: int
    selection_id: Optional[str]
    user_short_name: Optional[str]
    original_short_name: Optional[str]
    odd: Optional[float]
    best_odd: Optional[float]
    last_odd: Optional[float]

    class Config:
        from_attributes = True


class MarketOut(BaseModel):
    id: int
    market_id: Optional[str]
    umid: Optional[int]
    market_name: Optional[str]
    selections: List[SelectionOut] = []

    class Config:
        from_attributes = True


class CompanyGameOut(BaseModel):
    id: int
    company_name: str
    home_team: Optional[str]
    away_team: Optional[str]
    league: Optional[str]
    score_home: Optional[int]
    score_away: Optional[int]
    corners_home: Optional[int]
    corners_away: Optional[int]
    markets: List[MarketOut] = []

    class Config:
        from_attributes = True


class GameOut(BaseModel):
    id: int
    date_time_starts_utc: datetime
    home_team: str
    away_team: str
    league: str
    country: Optional[str]
    univ_home_id: Optional[int]
    univ_away_id: Optional[int]
    univ_league_id: Optional[int]
    created_at: datetime
    company_games: List[CompanyGameOut] = []

    class Config:
        from_attributes = True


class GameSummary(BaseModel):
    id: int
    date_time_starts_utc: datetime
    home_team: str
    away_team: str
    league: str
    country: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class IngestResponse(BaseModel):
    inserted: int
    skipped: int
    game_ids: List[int]
    message: str