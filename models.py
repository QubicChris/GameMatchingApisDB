from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


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
    created_at = Column(DateTime, default=datetime.utcnow)

    company_games = relationship("CompanyGame", back_populates="game", cascade="all, delete-orphan")


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
    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="company_games")
    markets = relationship("PregameMarket", back_populates="company_game", cascade="all, delete-orphan")


class PregameMarket(Base):
    __tablename__ = "pregame_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_game_id = Column(Integer, ForeignKey("company_games.id"), nullable=False)
    market_id = Column(String(100))
    umid = Column(Integer)
    market_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    company_game = relationship("CompanyGame", back_populates="markets")
    selections = relationship("Selection", back_populates="market", cascade="all, delete-orphan")


class Selection(Base):
    __tablename__ = "selections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("pregame_markets.id"), nullable=False)
    selection_id = Column(String(100))
    user_short_name = Column(String(50))
    original_short_name = Column(String(100))
    odd = Column(Float)
    best_odd = Column(Float)
    last_odd = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    market = relationship("PregameMarket", back_populates="selections")