"""Wallet Clustering Signal Detector - Signal #4

Detects multiple wallets making coordinated trades (same person hiding large position).
Pattern: 3+ wallets created within 24h, all betting same side, combined volume >$25K
Confidence: 55-70%
"""

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.wallet_analyzer import WalletAnalyzer
from src.config import settings
from src.database.models import Signal, Trade, Wallet

logger = logging.getLogger(__name__)


class WalletClusteringDetector:
    """Detect coordinated trading across multiple wallets"""
    
    def __init__(self, db: AsyncSession):
        """Initialize detector
        
        Args:
            db: Database session
        """
        self.db = db
        self.wallet_analyzer = WalletAnalyzer(db)
    
    async def detect(
        self,
        market_id: str,
    ) -> Optional[Signal]:
        """Detect if market has wallet clustering pattern
        
        Args:
            market_id: Market to analyze
            
        Returns:
            Signal object if detected, None otherwise
        """
        # Get recent trades (past 24 hours)
        since = datetime.utcnow() - timedelta(hours=24)
        
        result = await self.db.execute(
            select(Trade)
            .where(
                and_(
                    Trade.market_id == market_id,
                    Trade.timestamp >= since
                )
            )
        )
        recent_trades = result.scalars().all()
        
        if not recent_trades:
            return None
        
        # Find clusters
        clusters = await self._find_clusters(recent_trades)
        
        if not clusters:
            return None
        
        # Analyze best cluster
        best_cluster = max(clusters, key=lambda c: c["confidence"])
        
        # Only trigger if confidence is high enough
        if best_cluster["confidence"] < settings.min_confidence:
            return None
        
        # Calculate recommended position size
        recommended_size = self._calculate_position_size(
            confidence=best_cluster["confidence"],
            bankroll=settings.initial_bankroll
        )
        
        # Create signal
        signal = Signal(
            signal_type="wallet_clustering",
            market_id=market_id,
            wallet_address=None,  # Multiple wallets
            confidence=best_cluster["confidence"],
            recommended_side=best_cluster["side"],
            recommended_size=recommended_size,
            entry_price=best_cluster["avg_price"],
            signal_data=json.dumps({
                "wallet_count": best_cluster["wallet_count"],
                "combined_volume": float(best_cluster["combined_volume"]),
                "avg_wallet_age_hours": best_cluster["avg_wallet_age_hours"],
                "side": best_cluster["side"],
                "wallets": best_cluster["wallets"][:5],  # Top 5 for privacy
            }),
            reasoning=self._generate_reasoning(
                wallet_count=best_cluster["wallet_count"],
                combined_volume=best_cluster["combined_volume"],
                avg_wallet_age_hours=best_cluster["avg_wallet_age_hours"],
                side=best_cluster["side"],
                confidence=best_cluster["confidence"]
            ),
            detected_at=datetime.utcnow()
        )
        
        logger.info(
            f"👥 WALLET CLUSTERING SIGNAL DETECTED! "
            f"Wallets: {best_cluster['wallet_count']} | "
            f"Volume: ${best_cluster['combined_volume']} | "
            f"Side: {best_cluster['side']} | "
            f"Confidence: {best_cluster['confidence']*100:.1f}%"
        )
        
        return signal
    
    async def _find_clusters(self, trades: List[Trade]) -> List[Dict]:
        """Find wallet clusters in trades
        
        Args:
            trades: List of recent trades
            
        Returns:
            List of cluster dictionaries
        """
        # Group trades by side (YES/NO)
        yes_wallets: Set[str] = set()
        no_wallets: Set[str] = set()
        yes_volume = Decimal("0")
        no_volume = Decimal("0")
        yes_prices: List[Decimal] = []
        no_prices: List[Decimal] = []
        
        for trade in trades:
            wallet = trade.maker_address
            if trade.outcome == "YES":
                yes_wallets.add(wallet)
                yes_volume += Decimal(str(trade.size))
                yes_prices.append(Decimal(str(trade.price)))
            else:
                no_wallets.add(wallet)
                no_volume += Decimal(str(trade.size))
                no_prices.append(Decimal(str(trade.price)))
        
        clusters = []
        
        # Analyze YES cluster
        if len(yes_wallets) >= settings.wallet_cluster_min_wallets:
            yes_cluster = await self._analyze_cluster(
                wallets=list(yes_wallets),
                side="YES",
                combined_volume=yes_volume,
                prices=yes_prices
            )
            if yes_cluster:
                clusters.append(yes_cluster)
        
        # Analyze NO cluster
        if len(no_wallets) >= settings.wallet_cluster_min_wallets:
            no_cluster = await self._analyze_cluster(
                wallets=list(no_wallets),
                side="NO",
                combined_volume=no_volume,
                prices=no_prices
            )
            if no_cluster:
                clusters.append(no_cluster)
        
        return clusters
    
    async def _analyze_cluster(
        self,
        wallets: List[str],
        side: str,
        combined_volume: Decimal,
        prices: List[Decimal]
    ) -> Optional[Dict]:
        """Analyze a cluster of wallets
        
        Args:
            wallets: List of wallet addresses
            side: Trading side (YES/NO)
            combined_volume: Total volume
            prices: List of trade prices
            
        Returns:
            Cluster analysis dictionary or None
        """
        # Check minimum volume
        if combined_volume < Decimal("25000"):
            return None
        
        # Get wallet ages
        wallet_ages_hours: List[int] = []
        fresh_wallet_count = 0
        
        for address in wallets:
            wallet = await self.wallet_analyzer.get_or_create_wallet(address)
            age_hours = (datetime.utcnow() - wallet.first_seen).total_seconds() / 3600
            wallet_ages_hours.append(int(age_hours))
            
            if age_hours < 24:  # Fresh wallet
                fresh_wallet_count += 1
        
        # Calculate average age
        avg_age_hours = sum(wallet_ages_hours) / len(wallet_ages_hours) if wallet_ages_hours else 0
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            wallet_count=len(wallets),
            fresh_wallet_count=fresh_wallet_count,
            combined_volume=combined_volume,
            avg_age_hours=avg_age_hours
        )
        
        # Calculate average price
        avg_price = sum(prices) / len(prices) if prices else Decimal("0")
        
        return {
            "wallet_count": len(wallets),
            "fresh_wallet_count": fresh_wallet_count,
            "combined_volume": combined_volume,
            "avg_wallet_age_hours": avg_age_hours,
            "side": side,
            "avg_price": avg_price,
            "confidence": confidence,
            "wallets": wallets
        }
    
    def _calculate_confidence(
        self,
        wallet_count: int,
        fresh_wallet_count: int,
        combined_volume: Decimal,
        avg_age_hours: float
    ) -> Decimal:
        """Calculate confidence score for cluster
        
        Args:
            wallet_count: Number of wallets in cluster
            fresh_wallet_count: Number of fresh wallets (< 24h)
            combined_volume: Total volume in cluster
            avg_age_hours: Average wallet age in hours
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = Decimal("0.45")  # Base confidence
        
        # More wallets = higher confidence
        if wallet_count >= 5:
            confidence += Decimal("0.15")
        elif wallet_count >= 4:
            confidence += Decimal("0.10")
        elif wallet_count >= 3:
            confidence += Decimal("0.05")
        
        # More fresh wallets = higher confidence
        fresh_ratio = fresh_wallet_count / wallet_count
        if fresh_ratio >= 0.8:
            confidence += Decimal("0.15")
        elif fresh_ratio >= 0.6:
            confidence += Decimal("0.10")
        elif fresh_ratio >= 0.4:
            confidence += Decimal("0.05")
        
        # Higher volume = higher confidence
        if combined_volume >= Decimal("100000"):
            confidence += Decimal("0.15")
        elif combined_volume >= Decimal("50000"):
            confidence += Decimal("0.10")
        elif combined_volume >= Decimal("30000"):
            confidence += Decimal("0.05")
        
        # Younger average age = higher confidence
        if avg_age_hours < 12:
            confidence += Decimal("0.10")
        elif avg_age_hours < 24:
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
        wallet_count: int,
        combined_volume: Decimal,
        avg_wallet_age_hours: float,
        side: str,
        confidence: Decimal
    ) -> str:
        """Generate human-readable reasoning
        
        Returns:
            Reasoning string
        """
        return (
            f"Wallet clustering signal detected\n\n"
            f"**Cluster Analysis:**\n"
            f"- Wallets in cluster: {wallet_count}\n"
            f"- Combined volume: ${combined_volume:,.2f}\n"
            f"- Average wallet age: {avg_wallet_age_hours:.1f} hours\n"
            f"- Trading side: {side}\n\n"
            f"**Why This Matters:**\n"
            f"Multiple newly created wallets trading the same side indicates a single actor "
            f"splitting a large position to avoid detection. This is a common tactic used by "
            f"insiders who want to hide their total exposure. When wallets are created around "
            f"the same time and all bet the same way, it's likely coordinated.\n\n"
            f"**Confidence:** {confidence*100:.1f}%\n"
            f"**Recommendation:** Follow the cluster's direction."
        )
