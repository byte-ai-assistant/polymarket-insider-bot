"""Proven Winner Signal Detector - Signal #2

Detects accounts with consistent win rates making unusually large positions.
Pattern: Account with 70%+ win rate (min 20 trades) makes bet 3x larger than average
Confidence: 70-80%
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.wallet_analyzer import WalletAnalyzer
from src.config import settings
from src.database.models import Signal

logger = logging.getLogger(__name__)


class ProvenWinnerDetector:
    """Detect signals from proven winner accounts"""
    
    def __init__(self, db: AsyncSession):
        """Initialize detector
        
        Args:
            db: Database session
        """
        self.db = db
        self.wallet_analyzer = WalletAnalyzer(db)
    
    async def detect(
        self,
        wallet_address: str,
        market_id: str,
        trade_size: Decimal,
        trade_price: Decimal,
        side: str
    ) -> Optional[Signal]:
        """Detect if trade matches proven winner pattern
        
        Args:
            wallet_address: Wallet making the trade
            market_id: Market being traded
            trade_size: Size of trade in USDC
            trade_price: Price of trade
            side: 'BUY' or 'SELL'
            
        Returns:
            Signal object if detected, None otherwise
        """
        # Get wallet metrics
        wallet = await self.wallet_analyzer.get_or_create_wallet(wallet_address)
        metrics = await self.wallet_analyzer.get_wallet_metrics(wallet_address)
        
        # Check if wallet is a proven winner
        if not wallet.is_proven_winner:
            return None
        
        # Check if trade is unusually large (3x average)
        if wallet.avg_bet_size == 0:
            return None
        
        size_ratio = float(trade_size / wallet.avg_bet_size)
        if size_ratio < 3.0:
            return None
        
        # Calculate confidence score
        confidence = self._calculate_confidence(
            win_rate=wallet.win_rate,
            total_trades=wallet.total_trades,
            size_ratio=Decimal(str(size_ratio)),
            total_profit=wallet.total_profit
        )
        
        # Only trigger if confidence is high enough
        if confidence < settings.min_confidence:
            return None
        
        # Determine recommended side (follow the trade)
        recommended_side = "YES" if side == "BUY" else "NO"
        
        # Calculate recommended position size
        recommended_size = self._calculate_position_size(
            confidence=confidence,
            bankroll=settings.initial_bankroll
        )
        
        # Create signal
        signal = Signal(
            signal_type="proven_winner",
            market_id=market_id,
            wallet_address=wallet_address,
            confidence=confidence,
            recommended_side=recommended_side,
            recommended_size=recommended_size,
            entry_price=trade_price,
            signal_data=json.dumps({
                "win_rate": float(wallet.win_rate),
                "total_trades": wallet.total_trades,
                "total_profit": float(wallet.total_profit),
                "avg_bet_size": float(wallet.avg_bet_size),
                "trade_size": float(trade_size),
                "size_ratio": size_ratio,
            }),
            reasoning=self._generate_reasoning(
                wallet_address=wallet_address,
                win_rate=wallet.win_rate,
                total_trades=wallet.total_trades,
                total_profit=wallet.total_profit,
                avg_bet_size=wallet.avg_bet_size,
                trade_size=trade_size,
                size_ratio=size_ratio,
                confidence=confidence
            ),
            detected_at=datetime.utcnow()
        )
        
        # Flag wallet as high-confidence trader
        await self.wallet_analyzer.flag_wallet_as_insider(
            address=wallet_address,
            confidence=confidence,
            reason=f"Proven winner (WR: {wallet.win_rate*100:.1f}%) making large bet: ${trade_size} ({size_ratio:.1f}x avg)"
        )
        
        logger.info(
            f"💎 PROVEN WINNER SIGNAL DETECTED! "
            f"Wallet: {wallet_address[:8]}... | "
            f"Win Rate: {wallet.win_rate*100:.1f}% | "
            f"Size: ${trade_size} ({size_ratio:.1f}x avg) | "
            f"Confidence: {confidence*100:.1f}%"
        )
        
        return signal
    
    def _calculate_confidence(
        self,
        win_rate: Decimal,
        total_trades: int,
        size_ratio: Decimal,
        total_profit: Decimal
    ) -> Decimal:
        """Calculate confidence score for signal
        
        Args:
            win_rate: Win rate (0.0 to 1.0)
            total_trades: Total number of trades
            size_ratio: Ratio of current trade to average
            total_profit: Total profit in USDC
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = Decimal("0.60")  # Base confidence
        
        # Higher win rate = higher confidence
        if win_rate >= Decimal("0.80"):
            confidence += Decimal("0.15")
        elif win_rate >= Decimal("0.75"):
            confidence += Decimal("0.10")
        elif win_rate >= Decimal("0.70"):
            confidence += Decimal("0.05")
        
        # More trades = higher confidence (more data points)
        if total_trades >= 100:
            confidence += Decimal("0.10")
        elif total_trades >= 50:
            confidence += Decimal("0.05")
        
        # Larger size ratio = higher confidence
        if size_ratio >= Decimal("5.0"):
            confidence += Decimal("0.10")
        elif size_ratio >= Decimal("4.0"):
            confidence += Decimal("0.05")
        
        # Higher total profit = higher confidence (proven track record)
        if total_profit >= Decimal("100000"):
            confidence += Decimal("0.10")
        elif total_profit >= Decimal("50000"):
            confidence += Decimal("0.05")
        
        # Cap at 0.85
        return min(confidence, Decimal("0.85"))
    
    def _calculate_position_size(
        self,
        confidence: Decimal,
        bankroll: Decimal
    ) -> Decimal:
        """Calculate recommended position size using Kelly Criterion
        
        Args:
            confidence: Confidence score
            bankroll: Total bankroll
            
        Returns:
            Recommended position size in USDC
        """
        kelly_pct = (confidence - Decimal("0.5")) / Decimal("0.5")
        fractional_kelly = kelly_pct * settings.kelly_fraction
        
        position_size = bankroll * fractional_kelly
        
        # Apply maximum position size limit
        max_position = bankroll * (settings.max_position_size_pct / Decimal("100"))
        position_size = min(position_size, max_position)
        
        return position_size
    
    def _generate_reasoning(
        self,
        wallet_address: str,
        win_rate: Decimal,
        total_trades: int,
        total_profit: Decimal,
        avg_bet_size: Decimal,
        trade_size: Decimal,
        size_ratio: float,
        confidence: Decimal
    ) -> str:
        """Generate human-readable reasoning for signal
        
        Args:
            wallet_address: Wallet address
            win_rate: Win rate
            total_trades: Total trades
            total_profit: Total profit
            avg_bet_size: Average bet size
            trade_size: Current trade size
            size_ratio: Ratio of current to average
            confidence: Calculated confidence score
            
        Returns:
            Reasoning string
        """
        return (
            f"Proven winner signal detected for wallet {wallet_address[:8]}...\n\n"
            f"**Track Record:**\n"
            f"- Win rate: {win_rate*100:.1f}% (proven edge)\n"
            f"- Total trades: {total_trades} (sufficient sample size)\n"
            f"- Total profit: ${total_profit:,.2f}\n"
            f"- Average bet: ${avg_bet_size:,.2f}\n\n"
            f"**Current Position:**\n"
            f"- Trade size: ${trade_size:,.2f}\n"
            f"- Size ratio: {size_ratio:.1f}x average (unusually large)\n\n"
            f"**Why This Matters:**\n"
            f"Traders with consistent win rates have an edge - whether it's superior analysis, "
            f"information sources, or insider knowledge. When they make an unusually large bet, "
            f"it signals high conviction. This is a strong follow signal.\n\n"
            f"**Confidence:** {confidence*100:.1f}%\n"
            f"**Recommendation:** Follow this trade with appropriate position sizing."
        )
