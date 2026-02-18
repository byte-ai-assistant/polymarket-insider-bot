"""Risk management module for position sizing and capital protection"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import Position, Signal

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages risk, position sizing, and capital protection"""
    
    def __init__(self, db: AsyncSession):
        """Initialize risk manager
        
        Args:
            db: Database session
        """
        self.db = db
        self.bankroll = settings.initial_bankroll
    
    async def can_open_position(self, signal: Signal) -> Dict:
        """Check if we can safely open a new position
        
        Args:
            signal: Signal to evaluate
            
        Returns:
            Dictionary with decision and reason
        """
        # Check concurrent positions
        open_positions = await self._get_open_positions_count()
        if open_positions >= settings.max_concurrent_positions:
            return {
                "can_open": False,
                "reason": f"Max concurrent positions reached ({open_positions}/{settings.max_concurrent_positions})"
            }
        
        # Check daily loss limit
        daily_loss_pct = await self._get_daily_loss_percent()
        if daily_loss_pct >= settings.max_daily_loss_pct:
            return {
                "can_open": False,
                "reason": f"Daily loss limit exceeded ({daily_loss_pct:.1f}%)"
            }
        
        # Check if below minimum confidence
        if signal.confidence < settings.min_confidence:
            return {
                "can_open": False,
                "reason": f"Signal confidence too low ({signal.confidence*100:.1f}% < {settings.min_confidence*100:.1f}%)"
            }
        
        # Check exposure to same market
        market_exposure = await self._get_market_exposure(signal.market_id)
        max_market_exposure = self.bankroll * Decimal("0.30")  # 30% max per market
        
        if market_exposure + signal.recommended_size > max_market_exposure:
            return {
                "can_open": False,
                "reason": f"Market exposure limit reached (${market_exposure} + ${signal.recommended_size} > ${max_market_exposure})"
            }
        
        return {
            "can_open": True,
            "reason": "All risk checks passed"
        }
    
    def calculate_position_size(
        self,
        confidence: Decimal,
        override_size: Optional[Decimal] = None
    ) -> Decimal:
        """Calculate position size using Kelly Criterion
        
        Args:
            confidence: Confidence score (0.0 to 1.0)
            override_size: Optional override (for testing)
            
        Returns:
            Position size in USDC
        """
        if override_size:
            return override_size
        
        # Kelly Criterion: f = (p - q) / b
        # Simplified: f = 2p - 1 for even odds
        kelly_pct = (confidence - Decimal("0.5")) / Decimal("0.5")
        
        # Use fractional Kelly for safety
        fractional_kelly = kelly_pct * settings.kelly_fraction
        
        # Calculate size
        position_size = self.bankroll * fractional_kelly
        
        # Apply maximum position size limit
        max_position = self.bankroll * (settings.max_position_size_pct / Decimal("100"))
        position_size = min(position_size, max_position)
        
        # Minimum position size (at least $50)
        position_size = max(position_size, Decimal("50"))
        
        return position_size
    
    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        side: str
    ) -> Decimal:
        """Calculate stop-loss price
        
        Args:
            entry_price: Entry price
            side: 'YES' or 'NO'
            
        Returns:
            Stop-loss price
        """
        stop_loss_ratio = settings.stop_loss_pct / Decimal("100")
        
        if side == "YES":
            # For YES positions, stop-loss is below entry
            stop_loss = entry_price * (Decimal("1") - stop_loss_ratio)
        else:
            # For NO positions, stop-loss is above entry
            stop_loss = entry_price * (Decimal("1") + stop_loss_ratio)
        
        # Keep within valid range (0.0 to 1.0)
        stop_loss = max(Decimal("0.01"), min(Decimal("0.99"), stop_loss))
        
        return stop_loss
    
    def calculate_take_profit(
        self,
        entry_price: Decimal,
        side: str,
        confidence: Decimal
    ) -> Decimal:
        """Calculate take-profit price
        
        Args:
            entry_price: Entry price
            side: 'YES' or 'NO'
            confidence: Signal confidence
            
        Returns:
            Take-profit price
        """
        # Higher confidence = higher target
        if confidence >= Decimal("0.80"):
            target_pct = Decimal("40")  # 40% gain
        elif confidence >= Decimal("0.70"):
            target_pct = Decimal("30")  # 30% gain
        else:
            target_pct = Decimal("20")  # 20% gain
        
        target_ratio = target_pct / Decimal("100")
        
        if side == "YES":
            # For YES positions, take-profit is above entry
            take_profit = entry_price * (Decimal("1") + target_ratio)
        else:
            # For NO positions, take-profit is below entry
            take_profit = entry_price * (Decimal("1") - target_ratio)
        
        # Keep within valid range (0.0 to 1.0)
        take_profit = max(Decimal("0.01"), min(Decimal("0.99"), take_profit))
        
        return take_profit
    
    async def update_bankroll(self, new_bankroll: Decimal):
        """Update current bankroll
        
        Args:
            new_bankroll: New bankroll amount
        """
        old_bankroll = self.bankroll
        self.bankroll = new_bankroll
        logger.info(f"Bankroll updated: ${old_bankroll} → ${new_bankroll}")
    
    async def _get_open_positions_count(self) -> int:
        """Get count of currently open positions
        
        Returns:
            Number of open positions
        """
        result = await self.db.execute(
            select(func.count(Position.id))
            .where(Position.status == "open")
        )
        return result.scalar() or 0
    
    async def _get_daily_loss_percent(self) -> Decimal:
        """Get daily loss percentage
        
        Returns:
            Loss percentage (positive number if losing)
        """
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        result = await self.db.execute(
            select(func.sum(Position.realized_pnl))
            .where(
                and_(
                    Position.closed_at >= today,
                    Position.status == "closed"
                )
            )
        )
        daily_pnl = result.scalar() or Decimal("0")
        
        # Calculate percentage
        if self.bankroll == 0:
            return Decimal("0")
        
        loss_pct = (abs(daily_pnl) / self.bankroll) * 100 if daily_pnl < 0 else Decimal("0")
        return loss_pct
    
    async def _get_market_exposure(self, market_id: str) -> Decimal:
        """Get current exposure to a market
        
        Args:
            market_id: Market ID
            
        Returns:
            Total position size in market (USDC)
        """
        result = await self.db.execute(
            select(func.sum(Position.position_size))
            .where(
                and_(
                    Position.market_id == market_id,
                    Position.status == "open"
                )
            )
        )
        exposure = result.scalar() or Decimal("0")
        return Decimal(str(exposure))
    
    async def check_emergency_stop(self) -> bool:
        """Check if emergency stop should trigger
        
        Returns:
            True if should liquidate all positions
        """
        # Check daily loss
        daily_loss_pct = await self._get_daily_loss_percent()
        if daily_loss_pct >= settings.max_daily_loss_pct:
            logger.critical(
                f"🚨 EMERGENCY STOP TRIGGERED! Daily loss: {daily_loss_pct:.1f}% "
                f"(limit: {settings.max_daily_loss_pct}%)"
            )
            return True
        
        return False
