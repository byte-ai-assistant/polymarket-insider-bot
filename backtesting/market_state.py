"""
Market State - Maintain current market state during backtest replay.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketInfo:
    """Current state of a single market."""
    
    market_id: int
    question: str
    created_at: datetime
    close_time: Optional[datetime]
    resolution_price: Optional[float] = None
    is_resolved: bool = False
    
    # Price tracking
    current_price: float = 0.5
    last_trade_time: Optional[datetime] = None
    price_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    # Volume tracking
    total_volume: float = 0.0
    hourly_volumes: deque = field(default_factory=lambda: deque(maxlen=24))  # Last 24 hours
    recent_trades: deque = field(default_factory=lambda: deque(maxlen=100))  # Last 100 trades
    
    # Active positions
    active_positions: Dict[str, Dict] = field(default_factory=dict)  # wallet -> position info
    
    @property
    def hours_until_resolution(self) -> Optional[float]:
        """Calculate hours until market closes."""
        if not self.close_time or not self.last_trade_time:
            return None
        td = self.close_time - self.last_trade_time
        return max(0, td.total_seconds() / 3600)
    
    @property
    def current_hour_volume(self) -> float:
        """Get volume in the current hour."""
        if not self.hourly_volumes:
            return 0.0
        return self.hourly_volumes[-1]['volume']
    
    @property
    def avg_hourly_volume(self, lookback_hours: int = 24) -> float:
        """Calculate average hourly volume."""
        if not self.hourly_volumes:
            return 0.0
        
        volumes = [h['volume'] for h in list(self.hourly_volumes)[-lookback_hours:]]
        return sum(volumes) / len(volumes) if volumes else 0.0
    
    @property
    def price_change_1h(self) -> float:
        """Calculate 1-hour price change."""
        if len(self.price_history) < 2:
            return 0.0
        
        # Find price 1 hour ago
        current_time = self.last_trade_time
        if not current_time:
            return 0.0
        
        one_hour_ago = current_time - timedelta(hours=1)
        
        # Find closest price to 1 hour ago
        historical_price = None
        for timestamp, price in reversed(self.price_history):
            if timestamp <= one_hour_ago:
                historical_price = price
                break
        
        if historical_price is None:
            return 0.0
        
        return (self.current_price - historical_price) / historical_price if historical_price > 0 else 0.0
    
    def update_from_trade(self, trade: Dict):
        """
        Update market state from a new trade.
        
        Args:
            trade: Trade dict with keys: timestamp, price, usd_amount, maker, taker, maker_direction
        """
        timestamp = trade['timestamp']
        price = trade['price']
        volume = trade['usd_amount']
        
        # Update price
        self.current_price = price
        self.last_trade_time = timestamp
        self.price_history.append((timestamp, price))
        
        # Limit price history size
        if len(self.price_history) > 1000:
            self.price_history = self.price_history[-1000:]
        
        # Update volume
        self.total_volume += volume
        self.recent_trades.append(trade)
        
        # Update hourly volume tracking
        self._update_hourly_volume(timestamp, volume)
    
    def _update_hourly_volume(self, timestamp: datetime, volume: float):
        """Update hourly volume buckets."""
        current_hour = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # Check if we need a new hour bucket
        if not self.hourly_volumes or self.hourly_volumes[-1]['hour'] != current_hour:
            self.hourly_volumes.append({
                'hour': current_hour,
                'volume': 0.0
            })
        
        # Add volume to current hour
        self.hourly_volumes[-1]['volume'] += volume
    
    def resolve_market(self, resolution_price: float):
        """
        Mark market as resolved.
        
        Args:
            resolution_price: Final settlement price (typically 0 or 1)
        """
        self.is_resolved = True
        self.resolution_price = resolution_price
        self.current_price = resolution_price
        logger.debug(f"Market {self.market_id} resolved at price {resolution_price}")


class MarketState:
    """
    Maintains current state of all markets during backtest replay.
    
    Tracks prices, volumes, and positions as trades are replayed chronologically.
    """
    
    def __init__(self):
        """Initialize market state tracker."""
        self.markets: Dict[int, MarketInfo] = {}
        self.current_time: Optional[datetime] = None
        self.total_markets_tracked = 0
        logger.info("MarketState initialized")
    
    def register_market(
        self,
        market_id: int,
        question: str,
        created_at: datetime,
        close_time: Optional[datetime] = None
    ):
        """
        Register a new market.
        
        Args:
            market_id: Market ID
            question: Market question
            created_at: Market creation timestamp
            close_time: Market close/resolution timestamp
        """
        if market_id not in self.markets:
            self.markets[market_id] = MarketInfo(
                market_id=market_id,
                question=question,
                created_at=created_at,
                close_time=close_time
            )
            self.total_markets_tracked += 1
            
            if self.total_markets_tracked % 1000 == 0:
                logger.info(f"Tracking {self.total_markets_tracked:,} markets")
    
    def get_market(self, market_id: int) -> Optional[MarketInfo]:
        """
        Get market info.
        
        Args:
            market_id: Market ID
        
        Returns:
            MarketInfo or None if not found
        """
        return self.markets.get(market_id)
    
    def update_from_trade(self, trade: Dict):
        """
        Update market state from a new trade.
        
        Args:
            trade: Trade dict with keys: timestamp, market_id, price, usd_amount, etc.
        """
        market_id = trade['market_id']
        
        if market_id not in self.markets:
            logger.warning(f"Trade for unknown market {market_id}, skipping update")
            return
        
        market = self.markets[market_id]
        market.update_from_trade(trade)
        
        # Update current time
        self.current_time = trade['timestamp']
    
    def resolve_market(self, market_id: int, resolution_price: float):
        """
        Mark a market as resolved.
        
        Args:
            market_id: Market ID
            resolution_price: Final settlement price
        """
        market = self.get_market(market_id)
        if market:
            market.resolve_market(resolution_price)
    
    def get_volume_spike_markets(
        self,
        spike_threshold: float = 10.0,
        min_volume: float = 5000
    ) -> List[MarketInfo]:
        """
        Find markets with volume spikes.
        
        Args:
            spike_threshold: Multiplier for volume spike detection (e.g., 10x normal)
            min_volume: Minimum absolute volume to consider
        
        Returns:
            List of markets with volume spikes
        """
        spikes = []
        
        for market in self.markets.values():
            if market.is_resolved:
                continue
            
            current_vol = market.current_hour_volume
            avg_vol = market.avg_hourly_volume
            
            if (
                current_vol > min_volume and
                avg_vol > 0 and
                current_vol > (spike_threshold * avg_vol)
            ):
                spikes.append(market)
        
        return sorted(spikes, key=lambda m: m.current_hour_volume, reverse=True)
    
    def get_active_markets(
        self,
        min_volume: float = 10000,
        max_hours_to_close: Optional[float] = None
    ) -> List[MarketInfo]:
        """
        Get currently active high-volume markets.
        
        Args:
            min_volume: Minimum total volume
            max_hours_to_close: Filter markets closing within N hours
        
        Returns:
            List of active markets
        """
        active = []
        
        for market in self.markets.values():
            if market.is_resolved:
                continue
            
            if market.total_volume < min_volume:
                continue
            
            if max_hours_to_close is not None:
                hours_left = market.hours_until_resolution
                if hours_left is None or hours_left > max_hours_to_close:
                    continue
            
            active.append(market)
        
        return sorted(active, key=lambda m: m.total_volume, reverse=True)
    
    def get_stats(self) -> Dict:
        """Get market state statistics."""
        return {
            'total_markets': len(self.markets),
            'resolved_markets': len([m for m in self.markets.values() if m.is_resolved]),
            'active_markets': len([m for m in self.markets.values() if not m.is_resolved]),
            'current_time': self.current_time
        }
