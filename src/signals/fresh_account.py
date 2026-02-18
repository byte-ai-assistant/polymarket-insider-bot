"""Fresh Account Signal Detector - Signal #1 (Highest Priority)

Detects new wallets making large bets, often indicating insider trading.
Pattern: New wallet (< 7 days old) makes a single large bet ($10K+)
Confidence: 85-95%
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.wallet_analyzer import WalletAnalyzer
from src.config import settings
from src.database.models import Market, Signal, Wallet

logger = logging.getLogger(__name__)


class FreshAccountDetector:
    """Detect insider signals from fresh accounts"""
    
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
        """Detect if trade matches fresh account insider pattern
        
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
        
        # Check if wallet is fresh
        if not wallet.is_fresh_account:
            return None
        
        # Check if trade size is large enough
        if trade_size < settings.fresh_account_min_size_usd:
            return None
        
        # Check if account has very few trades
        if wallet.total_trades > 3:
            return None
        
        # Calculate confidence score
        confidence = self._calculate_confidence(
            account_age_days=wallet.account_age_days,
            trade_size=trade_size,
            total_trades=wallet.total_trades
        )
        
        # Only trigger if confidence is high enough
        if confidence < settings.min_confidence:
            return None
        
        # Determine recommended side (follow the trade)
        recommended_side = "YES" if side == "BUY" else "NO"
        
        # Calculate recommended position size using Kelly Criterion
        recommended_size = self._calculate_position_size(
            confidence=confidence,
            bankroll=settings.initial_bankroll
        )
        
        # Create signal
        signal = Signal(
            signal_type="fresh_account",
            market_id=market_id,
            wallet_address=wallet_address,
            confidence=confidence,
            recommended_side=recommended_side,
            recommended_size=recommended_size,
            entry_price=trade_price,
            signal_data=json.dumps({
                "account_age_days": wallet.account_age_days,
                "total_trades": wallet.total_trades,
                "trade_size": float(trade_size),
                "trade_price": float(trade_price),
            }),
            reasoning=self._generate_reasoning(
                wallet_address=wallet_address,
                account_age_days=wallet.account_age_days,
                total_trades=wallet.total_trades,
                trade_size=trade_size,
                confidence=confidence
            ),
            detected_at=datetime.utcnow()
        )
        
        # Flag wallet as potential insider
        await self.wallet_analyzer.flag_wallet_as_insider(
            address=wallet_address,
            confidence=confidence,
            reason=f"Fresh account large bet: ${trade_size} (age: {wallet.account_age_days} days)"
        )
        
        logger.info(
            f"🚨 FRESH ACCOUNT SIGNAL DETECTED! "
            f"Wallet: {wallet_address[:8]}... | "
            f"Size: ${trade_size} | "
            f"Age: {wallet.account_age_days} days | "
            f"Confidence: {confidence*100:.1f}%"
        )
        
        return signal
    
    def _calculate_confidence(
        self,
        account_age_days: int,
        trade_size: Decimal,
        total_trades: int
    ) -> Decimal:
        """Calculate confidence score for signal
        
        Args:
            account_age_days: Age of account in days
            trade_size: Size of trade in USDC
            total_trades: Total number of trades by this account
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = Decimal("0.65")  # Base confidence
        
        # Younger account = higher confidence
        if account_age_days <= 1:
            confidence += Decimal("0.15")
        elif account_age_days <= 3:
            confidence += Decimal("0.10")
        elif account_age_days <= 5:
            confidence += Decimal("0.05")
        
        # Larger trade = higher confidence
        if trade_size >= Decimal("50000"):
            confidence += Decimal("0.15")
        elif trade_size >= Decimal("25000"):
            confidence += Decimal("0.10")
        elif trade_size >= Decimal("15000"):
            confidence += Decimal("0.05")
        
        # Fewer trades = higher confidence (first trade is strongest signal)
        if total_trades == 0:
            confidence += Decimal("0.10")
        elif total_trades == 1:
            confidence += Decimal("0.05")
        
        # Cap at 0.95
        return min(confidence, Decimal("0.95"))
    
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
        # Kelly Criterion: f = (p - q) / b
        # where p = win probability, q = loss probability, b = odds
        # Simplified: f = 2p - 1 (for even odds)
        
        kelly_pct = (confidence - Decimal("0.5")) / Decimal("0.5")
        fractional_kelly = kelly_pct * settings.kelly_fraction
        
        # Calculate position size
        position_size = bankroll * fractional_kelly
        
        # Apply maximum position size limit
        max_position = bankroll * (settings.max_position_size_pct / Decimal("100"))
        position_size = min(position_size, max_position)
        
        return position_size
    
    def _generate_reasoning(
        self,
        wallet_address: str,
        account_age_days: int,
        total_trades: int,
        trade_size: Decimal,
        confidence: Decimal
    ) -> str:
        """Generate human-readable reasoning for signal
        
        Args:
            wallet_address: Wallet address
            account_age_days: Age of account in days
            total_trades: Total trades by this account
            trade_size: Size of this trade
            confidence: Calculated confidence score
            
        Returns:
            Reasoning string
        """
        return (
            f"Fresh account insider signal detected for wallet {wallet_address[:8]}...\n\n"
            f"**Pattern Match:** New wallet making large bet\n"
            f"- Account age: {account_age_days} days (< 7 days)\n"
            f"- Total trades: {total_trades} (very low activity)\n"
            f"- Trade size: ${trade_size:,.2f} (substantial position)\n\n"
            f"**Why This Matters:**\n"
            f"Insiders often create fresh wallets to avoid detection. They know the outcome "
            f"and want to capitalize without leaving a trail on their main accounts. "
            f"A brand new wallet making a large bet is a classic insider signal.\n\n"
            f"**Confidence:** {confidence*100:.1f}%\n"
            f"**Recommendation:** Follow this trade immediately."
        )
