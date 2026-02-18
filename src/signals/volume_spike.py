"""Volume Spike Signal Detector - Signal #3

Detects unusual volume surges before major price movements or news.
Pattern: Hourly volume > 10x average hourly volume, minimal price movement
Confidence: 60-75%
"""

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import Market, Signal, Trade

logger = logging.getLogger(__name__)


class VolumeSpikeDetector:
    """Detect volume spike insider signals"""
    
    def __init__(self, db: AsyncSession):
        """Initialize detector
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def detect(
        self,
        market_id: str,
    ) -> Optional[Signal]:
        """Detect if market has unusual volume spike
        
        Args:
            market_id: Market to analyze
            
        Returns:
            Signal object if detected, None otherwise
        """
        # Get current hour volume
        current_hour_volume = await self._get_hourly_volume(market_id, hours_ago=0)
        
        # Get average hourly volume (past 24 hours, excluding current hour)
        avg_hourly_volume = await self._get_average_hourly_volume(market_id, hours=24)
        
        if avg_hourly_volume == 0:
            return None
        
        # Calculate volume ratio
        volume_ratio = current_hour_volume / avg_hourly_volume
        
        # Check if volume spike is significant
        if volume_ratio < settings.volume_spike_threshold:
            return None
        
        # Get market info
        result = await self.db.execute(
            select(Market).where(Market.id == market_id)
        )
        market = result.scalar_one_or_none()
        
        if not market:
            return None
        
        # Get recent price movement (past hour)
        price_change_pct = await self._get_price_change_percent(market_id, hours=1)
        
        # Only trigger if price hasn't moved much yet (< 5%)
        # This indicates volume before news, not after
        if abs(price_change_pct) > Decimal("5.0"):
            return None
        
        # Calculate confidence score
        confidence = self._calculate_confidence(
            volume_ratio=volume_ratio,
            price_change_pct=price_change_pct,
            market_liquidity=market.liquidity
        )
        
        # Only trigger if confidence is high enough
        if confidence < settings.min_confidence:
            return None
        
        # Determine recommended side (follow dominant side of recent trades)
        recommended_side = await self._get_dominant_side(market_id, hours=1)
        
        # Get current price for entry
        recent_trades = await self._get_recent_trades(market_id, limit=10)
        if not recent_trades:
            return None
        
        entry_price = sum(Decimal(str(t.price)) for t in recent_trades) / len(recent_trades)
        
        # Calculate recommended position size
        recommended_size = self._calculate_position_size(
            confidence=confidence,
            bankroll=settings.initial_bankroll
        )
        
        # Create signal
        signal = Signal(
            signal_type="volume_spike",
            market_id=market_id,
            wallet_address=None,  # Not specific to one wallet
            confidence=confidence,
            recommended_side=recommended_side,
            recommended_size=recommended_size,
            entry_price=entry_price,
            signal_data=json.dumps({
                "current_hour_volume": float(current_hour_volume),
                "avg_hourly_volume": float(avg_hourly_volume),
                "volume_ratio": float(volume_ratio),
                "price_change_pct": float(price_change_pct),
                "market_liquidity": float(market.liquidity),
            }),
            reasoning=self._generate_reasoning(
                market_title=market.title,
                volume_ratio=volume_ratio,
                current_hour_volume=current_hour_volume,
                avg_hourly_volume=avg_hourly_volume,
                price_change_pct=price_change_pct,
                confidence=confidence
            ),
            detected_at=datetime.utcnow()
        )
        
        logger.info(
            f"📈 VOLUME SPIKE SIGNAL DETECTED! "
            f"Market: {market.title[:50]}... | "
            f"Volume: {volume_ratio:.1f}x avg | "
            f"Price change: {price_change_pct:.1f}% | "
            f"Confidence: {confidence*100:.1f}%"
        )
        
        return signal
    
    async def _get_hourly_volume(self, market_id: str, hours_ago: int = 0) -> Decimal:
        """Get volume for a specific hour
        
        Args:
            market_id: Market ID
            hours_ago: How many hours ago (0 = current hour)
            
        Returns:
            Volume in USDC
        """
        now = datetime.utcnow()
        hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours_ago)
        hour_end = hour_start + timedelta(hours=1)
        
        result = await self.db.execute(
            select(func.sum(Trade.size))
            .where(
                and_(
                    Trade.market_id == market_id,
                    Trade.timestamp >= hour_start,
                    Trade.timestamp < hour_end
                )
            )
        )
        volume = result.scalar() or 0
        return Decimal(str(volume))
    
    async def _get_average_hourly_volume(self, market_id: str, hours: int = 24) -> Decimal:
        """Get average hourly volume over a period
        
        Args:
            market_id: Market ID
            hours: Number of hours to average over
            
        Returns:
            Average hourly volume in USDC
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        result = await self.db.execute(
            select(func.sum(Trade.size))
            .where(
                and_(
                    Trade.market_id == market_id,
                    Trade.timestamp >= since
                )
            )
        )
        total_volume = result.scalar() or 0
        return Decimal(str(total_volume)) / hours if hours > 0 else Decimal("0")
    
    async def _get_price_change_percent(self, market_id: str, hours: int = 1) -> Decimal:
        """Get price change percentage over period
        
        Args:
            market_id: Market ID
            hours: Number of hours to measure
            
        Returns:
            Price change percentage
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Get earliest and latest prices in period
        result = await self.db.execute(
            select(Trade.price)
            .where(
                and_(
                    Trade.market_id == market_id,
                    Trade.timestamp >= since
                )
            )
            .order_by(Trade.timestamp.asc())
            .limit(1)
        )
        first_price = result.scalar()
        
        result = await self.db.execute(
            select(Trade.price)
            .where(Trade.market_id == market_id)
            .order_by(Trade.timestamp.desc())
            .limit(1)
        )
        last_price = result.scalar()
        
        if not first_price or not last_price or first_price == 0:
            return Decimal("0")
        
        change_pct = ((Decimal(str(last_price)) - Decimal(str(first_price))) / Decimal(str(first_price))) * 100
        return change_pct
    
    async def _get_dominant_side(self, market_id: str, hours: int = 1) -> str:
        """Get dominant side (YES/NO) of recent trades
        
        Args:
            market_id: Market ID
            hours: Number of hours to analyze
            
        Returns:
            'YES' or 'NO'
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        result = await self.db.execute(
            select(Trade.outcome, func.sum(Trade.size))
            .where(
                and_(
                    Trade.market_id == market_id,
                    Trade.timestamp >= since
                )
            )
            .group_by(Trade.outcome)
        )
        volumes = {row[0]: row[1] for row in result}
        
        yes_volume = Decimal(str(volumes.get("YES", 0)))
        no_volume = Decimal(str(volumes.get("NO", 0)))
        
        return "YES" if yes_volume > no_volume else "NO"
    
    async def _get_recent_trades(self, market_id: str, limit: int = 10) -> List[Trade]:
        """Get recent trades for market
        
        Args:
            market_id: Market ID
            limit: Maximum number of trades
            
        Returns:
            List of Trade objects
        """
        result = await self.db.execute(
            select(Trade)
            .where(Trade.market_id == market_id)
            .order_by(Trade.timestamp.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    def _calculate_confidence(
        self,
        volume_ratio: Decimal,
        price_change_pct: Decimal,
        market_liquidity: Decimal
    ) -> Decimal:
        """Calculate confidence score
        
        Args:
            volume_ratio: Current volume / average volume
            price_change_pct: Price change percentage
            market_liquidity: Market liquidity in USDC
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = Decimal("0.55")  # Base confidence
        
        # Higher volume ratio = higher confidence
        if volume_ratio >= 20:
            confidence += Decimal("0.15")
        elif volume_ratio >= 15:
            confidence += Decimal("0.10")
        elif volume_ratio >= 10:
            confidence += Decimal("0.05")
        
        # Lower price change = higher confidence (volume before news)
        if abs(price_change_pct) < Decimal("1.0"):
            confidence += Decimal("0.10")
        elif abs(price_change_pct) < Decimal("2.5"):
            confidence += Decimal("0.05")
        
        # Higher liquidity = higher confidence (can enter/exit easily)
        if market_liquidity >= Decimal("50000"):
            confidence += Decimal("0.05")
        
        # Cap at 0.75
        return min(confidence, Decimal("0.75"))
    
    def _calculate_position_size(
        self,
        confidence: Decimal,
        bankroll: Decimal
    ) -> Decimal:
        """Calculate recommended position size
        
        Args:
            confidence: Confidence score
            bankroll: Total bankroll
            
        Returns:
            Recommended position size in USDC
        """
        kelly_pct = (confidence - Decimal("0.5")) / Decimal("0.5")
        fractional_kelly = kelly_pct * settings.kelly_fraction
        
        position_size = bankroll * fractional_kelly
        
        max_position = bankroll * (settings.max_position_size_pct / Decimal("100"))
        position_size = min(position_size, max_position)
        
        return position_size
    
    def _generate_reasoning(
        self,
        market_title: str,
        volume_ratio: Decimal,
        current_hour_volume: Decimal,
        avg_hourly_volume: Decimal,
        price_change_pct: Decimal,
        confidence: Decimal
    ) -> str:
        """Generate human-readable reasoning
        
        Returns:
            Reasoning string
        """
        return (
            f"Volume spike signal detected for market: {market_title}\n\n"
            f"**Volume Analysis:**\n"
            f"- Current hour volume: ${current_hour_volume:,.2f}\n"
            f"- Average hourly volume: ${avg_hourly_volume:,.2f}\n"
            f"- Volume ratio: {volume_ratio:.1f}x average\n"
            f"- Price change: {price_change_pct:.2f}% (minimal)\n\n"
            f"**Why This Matters:**\n"
            f"Unusual volume spikes before significant price movement often indicate insider "
            f"trading. Informed traders accumulate positions before news breaks. The fact that "
            f"the price hasn't moved much yet suggests we're early.\n\n"
            f"**Confidence:** {confidence*100:.1f}%\n"
            f"**Recommendation:** Enter position and monitor for news."
        )
