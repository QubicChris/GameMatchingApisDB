from pydantic import BaseModel
from typing import Any, Optional, List
from datetime import datetime


# --- Inbound (mirrors System Two JSON) ---

class SelectionIn(BaseModel):
    model_config = {"extra": "ignore"}
    Id: str
    Usn: Optional[str] = None
    Osn: Optional[str] = None
    Odd: Optional[float] = None
    Bod: Optional[Any] = None
    Lod: Optional[Any] = None


class PregameMarketIn(BaseModel):
    model_config = {"extra": "ignore"}
    Id: str
    Umid: Optional[int] = None
    Omn: Optional[str] = None
    App_Umn: Optional[str] = None
    Slcs: List[SelectionIn] = []


class LiveDataIn(BaseModel):
    model_config = {"extra": "ignore"}
    ScoreHome: Optional[int] = None
    ScoreAway: Optional[int] = None
    CornersHome: Optional[int] = None
    CornersAway: Optional[int] = None


class CompanyGameIn(BaseModel):
    model_config = {"extra": "ignore"}
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
    model_config = {"extra": "ignore"}
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
    canonical_outcome: Optional[str]
    line_value: Optional[float]
    raw_outcome: Optional[str]
    odd: Optional[float]
    back_bpf_pos1: Optional[float]
    back_bsz_pos1: Optional[float]
    back_bpf_pos2: Optional[float]
    back_bsz_pos2: Optional[float]
    back_bpf_pos3: Optional[float]
    back_bsz_pos3: Optional[float]
    lay_bpf_pos1: Optional[float]
    lay_bsz_pos1: Optional[float]
    lay_bpf_pos2: Optional[float]
    lay_bsz_pos2: Optional[float]
    lay_bpf_pos3: Optional[float]
    lay_bsz_pos3: Optional[float]

    class Config:
        from_attributes = True


class MarketOut(BaseModel):
    id: int
    market_id: Optional[str]
    umid: Optional[int]
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
    date_live_data_updated: Optional[datetime]
    date_pregame_data_updated: Optional[datetime]
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
    updated: int
    game_ids: List[int]
    message: str