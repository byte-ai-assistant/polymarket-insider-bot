"""Trade execution engine - executes signals with risk management"""

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import Position, Signal
from src.trading.position_manager import PositionManager
from src.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Executes trading signals with full risk management"""
    
    def __init__(self, db: AsyncSession):
        """Initialize trade executor
        
        Args:
            db: Database session
        """
        self.db = db
        self.risk_manager = RiskManager(db)
        self.position_manager = PositionManager(db)
    
    async def execute_signal(
        self,
        signal: Signal,
        dry_run: bool = False
    ) -> Optional[Position]:
        """Execute a trading signal
        
        Args:
            signal: Signal to execute
            dry_run: If True, simulate without actual trade
            
        Returns:
            Created Position object or None if not executed
        """
        # Check if we can open this position
        risk_check = await self.risk_manager.can_open_position(signal)
        
        if not risk_check["can_open"]:
            logger.warning(
                f"❌ Signal #{signal.id} rejected: {risk_check['reason']}"
            )
            return None
        
        # Calculate position size
        position_size = self.risk_manager.calculate_position_size(
            confidence=signal.confidence
        )
        
        # Calculate stop-loss and take-profit
        stop_loss = self.risk_manager.calculate_stop_loss(
            entry_price=signal.entry_price,
            side=signal.recommended_side
        )
        
        take_profit = self.risk_manager.calculate_take_profit(
            entry_price=signal.entry_price,
            side=signal.recommended_side,
            confidence=signal.confidence
        )
        
        # Calculate number of shares
        shares = position_size / signal.entry_price
        
        logger.info(
            f"📊 Executing signal #{signal.id} | "
            f"Type: {signal.signal_type} | "
            f"Confidence: {signal.confidence*100:.1f}% | "
            f"Side: {signal.recommended_side} | "
            f"Size: ${position_size:.2f} | "
            f"Entry: {signal.entry_price:.4f} | "
            f"Stop: {stop_loss:.4f} | "
            f"Target: {take_profit:.4f}"
        )
        
        if dry_run:
            logger.info("🧪 DRY RUN - No actual trade placed")
            return None
        
        # In production, this would call CLOB API to place order
        # For now, we'll simulate a successful entry
        
        # Create position
        position = await self.position_manager.create_position(
            signal=signal,
            entry_price=signal.entry_price,
            position_size=position_size,
            shares=shares,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        # Mark signal as executed
        signal.executed = True
        signal.execution_price = signal.entry_price
        signal.execution_time = position.opened_at
        await self.db.flush()
        
        # Commit transaction
        await self.db.commit()
        
        logger.info(
            f"✅ Position #{position.id} opened successfully | "
            f"Shares: {shares:.2f} @ ${signal.entry_price:.4f}"
        )
        
        return position
    
    async def close_all_positions(self, reason: str = "emergency_stop"):
        """Close all open positions (emergency stop)
        
        Args:
            reason: Reason for closing all positions
        """
        positions = await self.position_manager.get_open_positions()
        
        if not positions:
            logger.info("No open positions to close")
            return
        
        logger.critical(
            f"🚨 CLOSING ALL POSITIONS ({len(positions)}) - Reason: {reason}"
        )
        
        for position in positions:
            await self.position_manager.close_position(
                position_id=position.id,
                exit_price=position.current_price,
                reason=reason
            )
        
        await self.db.commit()
        logger.info(f"All {len(positions)} positions closed")
    
    async def auto_trade_signal(self, signal: Signal) -> Optional[Position]:
        """Automatically execute a high-confidence signal
        
        Args:
            signal: Signal to potentially execute
            
        Returns:
            Position if executed, None otherwise
        """
        # Only auto-execute high-confidence signals
        if signal.confidence < settings.notification_min_confidence:
            logger.info(
                f"Signal #{signal.id} confidence too low for auto-execution "
                f"({signal.confidence*100:.1f}% < {settings.notification_min_confidence*100:.1f}%)"
            )
            return None
        
        # Execute with real money
        position = await self.execute_signal(signal, dry_run=False)
        
        if position:
            logger.info(
                f"🤖 AUTO-EXECUTED high-confidence signal #{signal.id} → Position #{position.id}"
            )
        
        return position
    
    async def get_portfolio_summary(self) -> dict:
        """Get current portfolio summary
        
        Returns:
            Dictionary with portfolio metrics
        """
        positions = await self.position_manager.get_open_positions()
        
        total_position_value = sum(
            Decimal(str(p.current_value)) for p in positions
        )
        total_unrealized_pnl = sum(
            Decimal(str(p.unrealized_pnl)) for p in positions
        )
        
        daily_loss_pct = await self.risk_manager._get_daily_loss_percent()
        
        return {
            "bankroll": float(self.risk_manager.bankroll),
            "open_positions": len(positions),
            "total_position_value": float(total_position_value),
            "total_unrealized_pnl": float(total_unrealized_pnl),
            "daily_loss_pct": float(daily_loss_pct),
            "positions": [
                {
                    "id": p.id,
                    "market_id": p.market_id,
                    "side": p.side,
                    "entry_price": float(p.entry_price),
                    "current_price": float(p.current_price),
                    "position_size": float(p.position_size),
                    "unrealized_pnl": float(p.unrealized_pnl),
                    "roi_pct": float(p.roi_percent or 0)
                }
                for p in positions
            ]
        }


# Note: In production, this would integrate with py-clob-client
# Example integration (commented out):
#
# from py_clob_client.client import ClobClient
# from py_clob_client.clob_types import OrderArgs
#
# async def place_polymarket_order(
#     market_id: str,
#     side: str,
#     size: float,
#     price: float
# ):
#     client = ClobClient(
#         host=settings.clob_api_url,
#         key=settings.private_key
#     )
#     
#     order = OrderArgs(
#         token_id=market_id,
#         price=price,
#         size=size,
#         side="BUY" if side == "YES" else "SELL"
#     )
#     
#     response = await client.create_order(order)
#     return response
