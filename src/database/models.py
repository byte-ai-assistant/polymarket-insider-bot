"""SQLAlchemy ORM models for Polymarket bot"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Market(Base):
    """Polymarket event/market"""
    
    __tablename__ = "markets"
    
    id = Column(String(100), primary_key=True)
    condition_id = Column(String(100), unique=True, index=True)
    slug = Column(String(200), index=True)
    title = Column(Text)
    description = Column(Text)
    end_date = Column(DateTime)
    volume_24h = Column(Numeric(18, 6), default=0)
    volume_total = Column(Numeric(18, 6), default=0)
    liquidity = Column(Numeric(18, 6), default=0)
    open_interest = Column(Numeric(18, 6), default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    trades = relationship("Trade", back_populates="market")
    signals = relationship("Signal", back_populates="market")
    positions = relationship("Position", back_populates="market")


class Wallet(Base):
    """Wallet profile with trading history and metrics"""
    
    __tablename__ = "wallets"
    
    address = Column(String(42), primary_key=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    total_trades = Column(Integer, default=0)
    total_volume = Column(Numeric(18, 6), default=0)
    total_profit = Column(Numeric(18, 6), default=0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    win_rate = Column(Numeric(5, 4), default=0)  # 0.0000 to 1.0000
    avg_bet_size = Column(Numeric(18, 6), default=0)
    largest_bet = Column(Numeric(18, 6), default=0)
    flagged_insider = Column(Boolean, default=False)
    confidence_score = Column(Numeric(5, 4), default=0)  # 0.0000 to 1.0000
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    trades_as_maker = relationship(
        "Trade",
        back_populates="maker_wallet",
        foreign_keys="Trade.maker_address"
    )
    trades_as_taker = relationship(
        "Trade",
        back_populates="taker_wallet",
        foreign_keys="Trade.taker_address"
    )
    signals = relationship("Signal", back_populates="wallet")
    
    @property
    def account_age_days(self) -> int:
        """Calculate account age in days"""
        return (datetime.utcnow() - self.first_seen).days
    
    @property
    def is_fresh_account(self) -> bool:
        """Check if account is fresh (< 7 days old)"""
        return self.account_age_days < 7
    
    @property
    def is_proven_winner(self) -> bool:
        """Check if account is a proven winner (70%+ win rate, 20+ trades)"""
        return self.total_trades >= 20 and self.win_rate >= Decimal("0.70")


class Trade(Base):
    """Individual trade on Polymarket"""
    
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), ForeignKey("markets.id"), index=True)
    maker_address = Column(String(42), ForeignKey("wallets.address"), index=True)
    taker_address = Column(String(42), ForeignKey("wallets.address"), index=True)
    side = Column(String(10))  # 'BUY' or 'SELL'
    outcome = Column(String(10))  # 'YES' or 'NO'
    size = Column(Numeric(18, 6))  # Size in USDC
    price = Column(Numeric(8, 6))  # Price (0.000000 to 1.000000)
    timestamp = Column(DateTime, index=True)
    trade_id = Column(String(100), unique=True)  # External trade ID
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    market = relationship("Market", back_populates="trades")
    maker_wallet = relationship(
        "Wallet",
        back_populates="trades_as_maker",
        foreign_keys=[maker_address]
    )
    taker_wallet = relationship(
        "Wallet",
        back_populates="trades_as_taker",
        foreign_keys=[taker_address]
    )


class Signal(Base):
    """Detected insider trading signal"""
    
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_type = Column(String(50), index=True)  # 'fresh_account', 'proven_winner', etc.
    market_id = Column(String(100), ForeignKey("markets.id"), index=True)
    wallet_address = Column(String(42), ForeignKey("wallets.address"), index=True)
    confidence = Column(Numeric(5, 4))  # 0.0000 to 1.0000
    recommended_side = Column(String(10))  # 'YES' or 'NO'
    recommended_size = Column(Numeric(18, 6))  # Recommended position size in USDC
    entry_price = Column(Numeric(8, 6))  # Recommended entry price
    
    # Signal details (JSON-like text fields)
    signal_data = Column(Text)  # JSON string with signal-specific data
    reasoning = Column(Text)  # Human-readable explanation
    
    # Execution tracking
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    executed = Column(Boolean, default=False)
    execution_price = Column(Numeric(8, 6))
    execution_time = Column(DateTime)
    
    # Outcome tracking
    outcome = Column(String(20))  # 'won', 'lost', 'pending', 'stopped'
    profit_loss = Column(Numeric(18, 6))
    closed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    market = relationship("Market", back_populates="signals")
    wallet = relationship("Wallet", back_populates="signals")
    position = relationship("Position", back_populates="signal", uselist=False)


class Position(Base):
    """Active or closed trading position"""
    
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), unique=True, index=True)
    market_id = Column(String(100), ForeignKey("markets.id"), index=True)
    
    # Position details
    side = Column(String(10))  # 'YES' or 'NO'
    entry_price = Column(Numeric(8, 6))
    position_size = Column(Numeric(18, 6))  # Size in USDC
    shares = Column(Numeric(18, 6))  # Number of shares
    
    # Risk management
    stop_loss = Column(Numeric(8, 6))
    take_profit = Column(Numeric(8, 6))
    
    # Current value
    current_price = Column(Numeric(8, 6))
    current_value = Column(Numeric(18, 6))
    unrealized_pnl = Column(Numeric(18, 6))
    
    # Status tracking
    status = Column(String(20), index=True)  # 'open', 'closed', 'stopped'
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    
    # Final outcome
    exit_price = Column(Numeric(8, 6))
    realized_pnl = Column(Numeric(18, 6))
    close_reason = Column(String(50))  # 'take_profit', 'stop_loss', 'manual', 'resolution'
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    signal = relationship("Signal", back_populates="position")
    market = relationship("Market", back_populates="positions")
    
    @property
    def roi_percent(self) -> Optional[Decimal]:
        """Calculate ROI percentage"""
        if not self.realized_pnl or not self.position_size:
            return None
        return (self.realized_pnl / self.position_size) * 100
