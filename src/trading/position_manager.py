"""Position management - tracks and updates open positions"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import Position, Signal

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages open trading positions"""
    
    def __init__(self, db: AsyncSession):
        """Initialize position manager
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def create_position(
        self,
        signal: Signal,
        entry_price: Decimal,
        position_size: Decimal,
        shares: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal
    ) -> Position:
        """Create a new position
        
        Args:
            signal: Source signal
            entry_price: Entry price
            position_size: Position size in USDC
            shares: Number of shares
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            
        Returns:
            Created Position object
        """
        position = Position(
            signal_id=signal.id,
            market_id=signal.market_id,
            side=signal.recommended_side,
            entry_price=entry_price,
            position_size=position_size,
            shares=shares,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=entry_price,
            current_value=position_size,
            unrealized_pnl=Decimal("0"),
            status="open",
            opened_at=datetime.utcnow()
        )
        
        self.db.add(position)
        await self.db.flush()
        
        logger.info(
            f"✅ Position opened: #{position.id} | "
            f"Market: {signal.market_id} | "
            f"Side: {position.side} | "
            f"Size: ${position_size} | "
            f"Entry: {entry_price}"
        )
        
        return position
    
    async def update_position_price(
        self,
        position_id: int,
        current_price: Decimal
    ):
        """Update position with current market price
        
        Args:
            position_id: Position ID
            current_price: Current market price
        """
        result = await self.db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position or position.status != "open":
            return
        
        # Calculate current value
        current_value = position.shares * current_price
        
        # Calculate unrealized P&L
        unrealized_pnl = current_value - position.position_size
        
        # Update position
        position.current_price = current_price
        position.current_value = current_value
        position.unrealized_pnl = unrealized_pnl
        position.updated_at = datetime.utcnow()
        
        await self.db.flush()
    
    async def close_position(
        self,
        position_id: int,
        exit_price: Decimal,
        reason: str
    ):
        """Close a position
        
        Args:
            position_id: Position ID
            exit_price: Exit price
            reason: Reason for closing
        """
        result = await self.db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position or position.status != "open":
            return
        
        # Calculate final value and P&L
        final_value = position.shares * exit_price
        realized_pnl = final_value - position.position_size
        
        # Update position
        position.status = "closed"
        position.exit_price = exit_price
        position.current_value = final_value
        position.realized_pnl = realized_pnl
        position.close_reason = reason
        position.closed_at = datetime.utcnow()
        position.updated_at = datetime.utcnow()
        
        await self.db.flush()
        
        # Update signal outcome
        if position.signal_id:
            await self._update_signal_outcome(
                signal_id=position.signal_id,
                outcome="won" if realized_pnl > 0 else "lost",
                profit_loss=realized_pnl
            )
        
        roi_pct = position.roi_percent or Decimal("0")
        logger.info(
            f"{'✅' if realized_pnl > 0 else '❌'} Position closed: #{position.id} | "
            f"P&L: ${realized_pnl:.2f} | "
            f"ROI: {roi_pct:.1f}% | "
            f"Reason: {reason}"
        )
    
    async def check_stop_loss(self, position_id: int) -> bool:
        """Check if position hit stop-loss
        
        Args:
            position_id: Position ID
            
        Returns:
            True if stop-loss triggered
        """
        result = await self.db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position or position.status != "open":
            return False
        
        # Check stop-loss based on side
        if position.side == "YES":
            # For YES, trigger if price falls below stop-loss
            if position.current_price <= position.stop_loss:
                await self.close_position(
                    position_id=position_id,
                    exit_price=position.current_price,
                    reason="stop_loss"
                )
                return True
        else:
            # For NO, trigger if price rises above stop-loss
            if position.current_price >= position.stop_loss:
                await self.close_position(
                    position_id=position_id,
                    exit_price=position.current_price,
                    reason="stop_loss"
                )
                return True
        
        return False
    
    async def check_take_profit(self, position_id: int) -> bool:
        """Check if position hit take-profit
        
        Args:
            position_id: Position ID
            
        Returns:
            True if take-profit triggered
        """
        result = await self.db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position or position.status != "open":
            return False
        
        # Check take-profit based on side
        if position.side == "YES":
            # For YES, trigger if price rises above take-profit
            if position.current_price >= position.take_profit:
                await self.close_position(
                    position_id=position_id,
                    exit_price=position.current_price,
                    reason="take_profit"
                )
                return True
        else:
            # For NO, trigger if price falls below take-profit
            if position.current_price <= position.take_profit:
                await self.close_position(
                    position_id=position_id,
                    exit_price=position.current_price,
                    reason="take_profit"
                )
                return True
        
        return False
    
    async def check_time_stop(self, position_id: int, max_hours: int = 48) -> bool:
        """Check if position should be closed due to time
        
        Args:
            position_id: Position ID
            max_hours: Maximum hours to hold position
            
        Returns:
            True if time stop triggered
        """
        result = await self.db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position or position.status != "open":
            return False
        
        # Check if position is too old
        age_hours = (datetime.utcnow() - position.opened_at).total_seconds() / 3600
        
        if age_hours >= max_hours:
            await self.close_position(
                position_id=position_id,
                exit_price=position.current_price,
                reason="time_stop"
            )
            return True
        
        return False
    
    async def get_open_positions(self) -> List[Position]:
        """Get all open positions
        
        Returns:
            List of open Position objects
        """
        result = await self.db.execute(
            select(Position).where(Position.status == "open")
        )
        return result.scalars().all()
    
    async def monitor_all_positions(self):
        """Monitor all open positions for stop-loss/take-profit
        
        This should be called periodically (e.g., every minute)
        """
        positions = await self.get_open_positions()
        
        for position in positions:
            # Check stop-loss
            await self.check_stop_loss(position.id)
            
            # Check take-profit
            await self.check_take_profit(position.id)
            
            # Check time stop (48 hours)
            await self.check_time_stop(position.id, max_hours=48)
    
    async def _update_signal_outcome(
        self,
        signal_id: int,
        outcome: str,
        profit_loss: Decimal
    ):
        """Update signal with outcome
        
        Args:
            signal_id: Signal ID
            outcome: 'won' or 'lost'
            profit_loss: Realized profit/loss
        """
        await self.db.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                outcome=outcome,
                profit_loss=profit_loss,
                closed_at=datetime.utcnow()
            )
        )
        await self.db.flush()
