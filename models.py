from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class SofaGame(Base):
    __tablename__ = "sofa_games"

    sofa_event_id = Column(Integer, primary_key=True)
    home_name = Column(String(150))
    away_name = Column(String(150))
    league_name = Column(String(150))
    start_timestamp = Column(Integer)            # epoch UTC from Sofasport
    score_home = Column(Integer)
    score_away = Column(Integer)
    status = Column(String(100))
    fetched_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="sofa_game", uselist=False)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_time_starts_utc = Column(DateTime, nullable=False)
    home_team = Column(String(150), nullable=False)
    away_team = Column(String(150), nullable=False)
    league = Column(String(150), nullable=False)
    country = Column(String(100))
    univ_home_id = Column(Integer)
    univ_away_id = Column(Integer)
    univ_league_id = Column(Integer)
    sofa_event_id = Column(Integer, ForeignKey("sofa_games.sofa_event_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sofa_game = relationship("SofaGame", back_populates="game")
    company_games = relationship("CompanyGame", back_populates="game", cascade="all, delete-orphan")
    sofa_odds = relationship("SofaOdds", back_populates="game", cascade="all, delete-orphan")
    sofa_statistics = relationship("SofaStatistic", back_populates="game", cascade="all, delete-orphan")


class CompanyGame(Base):
    __tablename__ = "company_games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    company_name = Column(String(100), nullable=False)
    home_team = Column(String(150))
    away_team = Column(String(150))
    league = Column(String(150))
    score_home = Column(Integer)
    score_away = Column(Integer)
    corners_home = Column(Integer)
    corners_away = Column(Integer)
    date_live_data_updated = Column(DateTime)
    date_pregame_data_updated = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("game_id", "company_name", name="uq_company_game"),)

    game = relationship("Game", back_populates="company_games")
    markets = relationship("PregameMarket", back_populates="company_game", cascade="all, delete-orphan")


class PregameMarket(Base):
    __tablename__ = "pregame_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_game_id = Column(Integer, ForeignKey("company_games.id"), nullable=False)
    market_id = Column(String(100))
    umid = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    company_game = relationship("CompanyGame", back_populates="markets")
    selections = relationship("Selection", back_populates="market", cascade="all, delete-orphan")


class Selection(Base):
    __tablename__ = "selections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("pregame_markets.id"), nullable=False)
    selection_id = Column(String(100))

    canonical_outcome = Column(String(20))
    line_value = Column(Float)
    raw_outcome = Column(String(150))

    odd = Column(Float)

    # Flattened back (Bod) ladder — up to 3 positions
    back_bpf_pos1 = Column(Float)
    back_bsz_pos1 = Column(Float)
    back_bpf_pos2 = Column(Float)
    back_bsz_pos2 = Column(Float)
    back_bpf_pos3 = Column(Float)
    back_bsz_pos3 = Column(Float)

    # Flattened lay (Lod) ladder — up to 3 positions
    lay_bpf_pos1 = Column(Float)
    lay_bsz_pos1 = Column(Float)
    lay_bpf_pos2 = Column(Float)
    lay_bsz_pos2 = Column(Float)
    lay_bpf_pos3 = Column(Float)
    lay_bsz_pos3 = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)

    market = relationship("PregameMarket", back_populates="selections")


class SofaOdds(Base):
    __tablename__ = "sofa_odds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    sofa_event_id = Column(Integer, nullable=False)
    market_id = Column(Integer)                  # Sofascore marketId
    market_name = Column(String(100))            # e.g. "Full time", "Match goals"
    market_group = Column(String(100))           # e.g. "1X2", "Asian Handicap"
    market_period = Column(String(50))           # e.g. "Full-time", "1st half"
    choice_group = Column(String(20))            # line value for O/U e.g. "2.5" (null for 1X2)
    outcome = Column(String(150))                # e.g. "1", "X", "2", "Over", "Under"
    odd = Column(Float)                          # fractionalValue (decimal)
    initial_odd = Column(Float)                  # initialFractionalValue
    winning = Column(Integer)                    # 1/0/null
    change = Column(Integer)                     # -1 drift down, 0 no change, 1 drift up
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", "market_id", "choice_group", "outcome", name="uq_sofa_odds"),
    )

    game = relationship("Game", back_populates="sofa_odds")


class SofaStatistic(Base):
    __tablename__ = "sofa_statistics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    sofa_event_id = Column(Integer, nullable=False)
    period = Column(String(10))                      # "ALL", "1ST", "2ND"

    # ── Match overview ────────────────────────────────────────────────────────
    ball_possession_home = Column(Float)             # %
    ball_possession_away = Column(Float)
    expected_goals_home = Column(Float)
    expected_goals_away = Column(Float)
    total_shots_home = Column(Float)
    total_shots_away = Column(Float)
    goalkeeper_saves_home = Column(Float)
    goalkeeper_saves_away = Column(Float)
    corner_kicks_home = Column(Float)
    corner_kicks_away = Column(Float)
    fouls_home = Column(Float)
    fouls_away = Column(Float)
    passes_home = Column(Float)
    passes_away = Column(Float)
    tackles_home = Column(Float)
    tackles_away = Column(Float)
    free_kicks_home = Column(Float)
    free_kicks_away = Column(Float)
    yellow_cards_home = Column(Float)
    yellow_cards_away = Column(Float)
    red_cards_home = Column(Float)
    red_cards_away = Column(Float)

    # ── Shots ─────────────────────────────────────────────────────────────────
    shots_on_target_home = Column(Float)
    shots_on_target_away = Column(Float)
    shots_off_target_home = Column(Float)
    shots_off_target_away = Column(Float)
    blocked_shots_home = Column(Float)
    blocked_shots_away = Column(Float)
    shots_inside_box_home = Column(Float)
    shots_inside_box_away = Column(Float)
    shots_outside_box_home = Column(Float)
    shots_outside_box_away = Column(Float)
    hit_woodwork_home = Column(Float)
    hit_woodwork_away = Column(Float)

    # ── Attack ────────────────────────────────────────────────────────────────
    through_balls_home = Column(Float)
    through_balls_away = Column(Float)
    touches_in_opp_box_home = Column(Float)
    touches_in_opp_box_away = Column(Float)
    offsides_home = Column(Float)
    offsides_away = Column(Float)

    # ── Passes (ratio stats: value = accurate, total = attempted) ─────────────
    accurate_passes_home = Column(Float)
    accurate_passes_away = Column(Float)
    throw_ins_home = Column(Float)
    throw_ins_away = Column(Float)
    long_balls_home = Column(Float)              # accurate
    long_balls_home_total = Column(Float)        # attempted
    long_balls_away = Column(Float)
    long_balls_away_total = Column(Float)
    crosses_home = Column(Float)                 # accurate
    crosses_home_total = Column(Float)           # attempted
    crosses_away = Column(Float)
    crosses_away_total = Column(Float)
    final_third_home = Column(Float)             # accurate
    final_third_home_total = Column(Float)       # attempted
    final_third_away = Column(Float)
    final_third_away_total = Column(Float)

    # ── Duels ─────────────────────────────────────────────────────────────────
    duel_won_pct_home = Column(Float)            # %
    duel_won_pct_away = Column(Float)
    dispossessed_home = Column(Float)
    dispossessed_away = Column(Float)
    ground_duels_home = Column(Float)            # won
    ground_duels_home_total = Column(Float)      # total
    ground_duels_away = Column(Float)
    ground_duels_away_total = Column(Float)
    aerial_duels_home = Column(Float)
    aerial_duels_home_total = Column(Float)
    aerial_duels_away = Column(Float)
    aerial_duels_away_total = Column(Float)
    dribbles_home = Column(Float)                # successful
    dribbles_home_total = Column(Float)          # attempted
    dribbles_away = Column(Float)
    dribbles_away_total = Column(Float)

    # ── Defending ─────────────────────────────────────────────────────────────
    interceptions_home = Column(Float)
    interceptions_away = Column(Float)
    clearances_home = Column(Float)
    clearances_away = Column(Float)
    errors_lead_to_shot_home = Column(Float)
    errors_lead_to_shot_away = Column(Float)

    # ── Goalkeeping ───────────────────────────────────────────────────────────
    goal_kicks_home = Column(Float)
    goal_kicks_away = Column(Float)

    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", "period", name="uq_sofa_stat"),
    )

    game = relationship("Game", back_populates="sofa_statistics")


class TeamAlias(Base):
    __tablename__ = "team_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String(150), nullable=False)   # System Two name (games table)
    company_name = Column(String(100), nullable=False)     # bookmaker
    company_team_name = Column(String(150), nullable=False) # how that bookmaker names the team
    first_seen_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("canonical_name", "company_name", name="uq_team_alias"),
    )


class MarketType(Base):
    __tablename__ = "market_types"

    umid = Column(Integer, primary_key=True)
    canonical_name = Column(String(150))   # App_Umn; may be NULL if not yet seen
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)