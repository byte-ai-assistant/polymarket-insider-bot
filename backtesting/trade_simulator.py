"""
Trade Simulator - Position management, P&L calculation, stop-loss/take-profit logic.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import random
import logging

from .signal_detectors import Signal
from .market_state import MarketState

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """An open or closed trading position."""
    
    # Entry info
    signal: Signal
    entry_time: datetime
    entry_price: float
    size: float  # USDC amount
    shares: float  # Number of shares
    side: str  # 'YES' or 'NO'
    
    # Exit info (populated when closed)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # 'resolved', 'stop_loss', 'take_profit', 'time_decay'
    
    # P&L
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Metadata
    market_id: int = 0
    is_open: bool = True
    
    def __post_init__(self):
        self.market_id = self.signal.market_id


class TradeSimulator:
    """
    Simulates trading based on signals with realistic position management.
    
    Features:
    - Kelly Criterion position sizing
    - Stop-loss (15% default)
    - Take-profit (20-40% targets)
    - Time-based exits
    - Slippage simulation
    - Trading fees (2%)
    - Max concurrent positions
    - Max market exposure
    """
    
    def __init__(
        self,
        starting_capital: float = 5000,
        max_concurrent_positions: int = 5,
        max_position_size_pct: float = 10,  # Max 10% per trade
        max_market_exposure_pct: float = 30,  # Max 30% in one market
        stop_loss_pct: float = 15,  # 15% stop loss
        take_profit_pct: float = 25,  # 25% take profit
        max_hold_hours: float = 48,  # Max 48 hours per position
        trading_fee_pct: float = 2.0,  # 2% fees
        slippage_bps: tuple = (10, 30)  # 0.1% to 0.3% slippage
    ):
        """
        Initialize trade simulator.
        
        Args:
            starting_capital: Initial bankroll in USDC
            max_concurrent_positions: Maximum number of open positions
            max_position_size_pct: Maximum position size as % of bankroll
            max_market_exposure_pct: Maximum exposure to single market
            stop_loss_pct: Stop loss percentage
            take_profit_pct: Take profit percentage
            max_hold_hours: Maximum hours to hold a position
            trading_fee_pct: Trading fee percentage
            slippage_bps: Tuple of (min, max) slippage in basis points
        """
        self.initial_capital = starting_capital
        self.capital = starting_capital
        self.max_concurrent_positions = max_concurrent_positions
        self.max_position_size_pct = max_position_size_pct
        self.max_market_exposure_pct = max_market_exposure_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_hours = max_hold_hours
        self.trading_fee_pct = trading_fee_pct
        self.slippage_bps = slippage_bps
        
        self.positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.current_time: Optional[datetime] = None
        
        # Statistics
        self.signals_received = 0
        self.signals_executed = 0
        self.signals_rejected = 0
        
        logger.info(f"TradeSimulator initialized with ${starting_capital:,.2f} capital")
    
    def execute_signal(
        self,
        signal: Signal,
        market_state: MarketState
    ) -> Optional[Position]:
        """
        Execute a trading signal.
        
        Args:
            signal: Signal to execute
            market_state: Current market state
        
        Returns:
            Position object if executed, None if rejected
        """
        self.signals_received += 1
        self.current_time = signal.timestamp
        
        # Check if we can take the position
        if not self._can_take_position(signal):
            self.signals_rejected += 1
            return None
        
        # Calculate position size
        position_size = self._calculate_position_size(signal)
        
        if position_size < 10:  # Minimum $10 position
            self.signals_rejected += 1
            logger.debug(f"Position size too small: ${position_size:.2f}")
            return None
        
        # Get market info
        market = market_state.get_market(signal.market_id)
        if not market:
            self.signals_rejected += 1
            return None
        
        # Apply entry slippage
        entry_price = self._apply_slippage(signal.entry_price, side='entry')
        
        # Calculate shares
        shares = position_size / entry_price
        
        # Deduct from capital (including fees)
        total_cost = position_size * (1 + self.trading_fee_pct / 100)
        self.capital -= total_cost
        
        # Create position
        position = Position(
            signal=signal,
            entry_time=signal.timestamp,
            entry_price=entry_price,
            size=position_size,
            shares=shares,
            side=signal.recommended_side,
            market_id=signal.market_id,
            is_open=True
        )
        
        self.positions.append(position)
        self.signals_executed += 1
        
        logger.debug(
            f"✅ EXECUTED {signal.signal_type}: {signal.recommended_side} @ ${entry_price:.3f} "
            f"(${position_size:.2f}, {shares:.2f} shares) - "
            f"Capital: ${self.capital:.2f}"
        )
        
        return position
    
    def check_exits(self, market_state: MarketState, current_time: datetime):
        """
        Check all open positions for exit conditions.
        
        Args:
            market_state: Current market state
            current_time: Current backtest time
        """
        self.current_time = current_time
        
        for position in self.positions[:]:  # Iterate over copy
            if not position.is_open:
                continue
            
            market = market_state.get_market(position.market_id)
            if not market:
                continue
            
            # Exit condition 1: Market resolved
            if market.is_resolved:
                self._close_position(
                    position,
                    exit_price=market.resolution_price,
                    exit_time=current_time,
                    reason='resolved'
                )
                continue
            
            # Current price
            current_price = market.current_price
            
            # Calculate unrealized P&L %
            if position.side == 'YES':
                pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
            else:  # NO
                pnl_pct = ((position.entry_price - current_price) / position.entry_price) * 100
            
            # Exit condition 2: Stop loss
            if pnl_pct <= -self.stop_loss_pct:
                self._close_position(
                    position,
                    exit_price=current_price,
                    exit_time=current_time,
                    reason='stop_loss'
                )
                continue
            
            # Exit condition 3: Take profit
            if pnl_pct >= self.take_profit_pct:
                self._close_position(
                    position,
                    exit_price=current_price,
                    exit_time=current_time,
                    reason='take_profit'
                )
                continue
            
            # Exit condition 4: Time decay
            hours_held = (current_time - position.entry_time).total_seconds() / 3600
            if hours_held >= self.max_hold_hours:
                # Only exit if not profitable
                if pnl_pct < 5:  # Less than 5% profit
                    self._close_position(
                        position,
                        exit_price=current_price,
                        exit_time=current_time,
                        reason='time_decay'
                    )
                    continue
            
            # Exit condition 5: Market closing soon with minimal profit
            if market.hours_until_resolution is not None and market.hours_until_resolution < 6:
                if pnl_pct < 5:
                    self._close_position(
                        position,
                        exit_price=current_price,
                        exit_time=current_time,
                        reason='market_closing'
                    )
                    continue
    
    def _close_position(
        self,
        position: Position,
        exit_price: float,
        exit_time: datetime,
        reason: str
    ):
        """Close a position and calculate P&L."""
        
        # Apply exit slippage
        exit_price = self._apply_slippage(exit_price, side='exit')
        
        # Calculate P&L
        if position.side == 'YES':
            gross_pnl = position.shares * exit_price - position.size
        else:  # NO
            gross_pnl = position.size - position.shares * exit_price
        
        # Deduct exit fees
        exit_fees = position.size * (self.trading_fee_pct / 100)
        net_pnl = gross_pnl - exit_fees
        
        pnl_pct = (net_pnl / position.size) * 100
        
        # Update position
        position.is_open = False
        position.exit_time = exit_time
        position.exit_price = exit_price
        position.exit_reason = reason
        position.pnl = net_pnl
        position.pnl_pct = pnl_pct
        
        # Return capital plus P&L
        self.capital += position.size + net_pnl
        
        # Move to closed positions
        self.positions.remove(position)
        self.closed_positions.append(position)
        
        emoji = "✅" if net_pnl > 0 else "❌"
        logger.debug(
            f"{emoji} CLOSED {position.signal.signal_type} ({reason}): "
            f"{position.side} @ ${exit_price:.3f} | "
            f"P&L: ${net_pnl:+.2f} ({pnl_pct:+.1f}%) | "
            f"Capital: ${self.capital:.2f}"
        )
    
    def _can_take_position(self, signal: Signal) -> bool:
        """Check if we can take a new position."""
        
        # Check max concurrent positions
        if len(self.positions) >= self.max_concurrent_positions:
            logger.debug("Max concurrent positions reached")
            return False
        
        # Check if we have enough capital
        estimated_size = self.capital * (signal.recommended_size_pct / 100)
        if estimated_size > self.capital * 0.5:  # Don't risk more than 50% at once
            logger.debug("Insufficient capital for position")
            return False
        
        # Check market exposure
        market_exposure = sum(
            p.size for p in self.positions 
            if p.market_id == signal.market_id and p.is_open
        )
        max_market_exposure = self.initial_capital * (self.max_market_exposure_pct / 100)
        
        if market_exposure + estimated_size > max_market_exposure:
            logger.debug(f"Max market exposure reached for market {signal.market_id}")
            return False
        
        return True
    
    def _calculate_position_size(self, signal: Signal) -> float:
        """Calculate position size based on Kelly Criterion and risk limits."""
        
        # Kelly-based size
        kelly_size = self.initial_capital * signal.recommended_size_pct
        
        # Apply max position size limit
        max_size = self.initial_capital * (self.max_position_size_pct / 100)
        position_size = min(kelly_size, max_size)
        
        # Don't exceed available capital
        position_size = min(position_size, self.capital * 0.8)  # Keep 20% reserve
        
        return position_size
    
    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply realistic slippage to price."""
        min_slip, max_slip = self.slippage_bps
        slippage_bps = random.uniform(min_slip, max_slip)
        slippage = slippage_bps / 10000  # Convert basis points to decimal
        
        if side == 'entry':
            return price * (1 + slippage)  # Pay more to enter
        else:  # exit
            return price * (1 - slippage)  # Get less to exit
    
    def get_current_equity(self, market_state: MarketState) -> float:
        """Calculate current equity (capital + unrealized P&L)."""
        equity = self.capital
        
        for position in self.positions:
            if not position.is_open:
                continue
            
            market = market_state.get_market(position.market_id)
            if not market:
                continue
            
            # Calculate unrealized P&L
            current_price = market.current_price
            if position.side == 'YES':
                unrealized_pnl = position.shares * current_price - position.size
            else:
                unrealized_pnl = position.size - position.shares * current_price
            
            equity += unrealized_pnl
        
        return equity
    
    def get_stats(self) -> Dict:
        """Get trading statistics."""
        total_trades = len(self.closed_positions)
        
        if total_trades == 0:
            return {
                'total_trades': 0,
                'capital': self.capital,
                'total_pnl': 0,
                'roi_pct': 0,
                'signals_received': self.signals_received,
                'signals_executed': self.signals_executed,
                'signals_rejected': self.signals_rejected
            }
        
        wins = [p for p in self.closed_positions if p.pnl > 0]
        losses = [p for p in self.closed_positions if p.pnl <= 0]
        
        total_pnl = sum(p.pnl for p in self.closed_positions)
        roi_pct = (total_pnl / self.initial_capital) * 100
        
        return {
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / total_trades if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'roi_pct': roi_pct,
            'avg_win': sum(p.pnl for p in wins) / len(wins) if wins else 0,
            'avg_loss': sum(p.pnl for p in losses) / len(losses) if losses else 0,
            'largest_win': max((p.pnl for p in wins), default=0),
            'largest_loss': min((p.pnl for p in losses), default=0),
            'capital': self.capital,
            'signals_received': self.signals_received,
            'signals_executed': self.signals_executed,
            'signals_rejected': self.signals_rejected,
            'execution_rate': self.signals_executed / self.signals_received if self.signals_received > 0 else 0
        }
