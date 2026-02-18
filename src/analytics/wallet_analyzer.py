"""Wallet profiling and analysis"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Trade, Wallet

logger = logging.getLogger(__name__)


class WalletAnalyzer:
    """Analyze wallet trading patterns and calculate metrics"""
    
    def __init__(self, db: AsyncSession):
        """Initialize wallet analyzer
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def get_or_create_wallet(self, address: str) -> Wallet:
        """Get wallet from database or create if doesn't exist
        
        Args:
            address: Wallet address
            
        Returns:
            Wallet model instance
        """
        result = await self.db.execute(
            select(Wallet).where(Wallet.address == address)
        )
        wallet = result.scalar_one_or_none()
        
        if not wallet:
            wallet = Wallet(
                address=address,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow()
            )
            self.db.add(wallet)
            await self.db.flush()
            logger.info(f"Created new wallet profile: {address}")
        
        return wallet
    
    async def update_wallet_metrics(self, address: str):
        """Update wallet metrics based on trade history
        
        Args:
            address: Wallet address to update
        """
        wallet = await self.get_or_create_wallet(address)
        
        # Get all trades for this wallet (as maker or taker)
        result = await self.db.execute(
            select(Trade).where(
                (Trade.maker_address == address) | (Trade.taker_address == address)
            ).order_by(Trade.timestamp.asc())
        )
        trades = result.scalars().all()
        
        if not trades:
            return
        
        # Calculate metrics
        total_trades = len(trades)
        total_volume = sum(Decimal(str(t.size)) for t in trades)
        
        # Calculate average bet size
        avg_bet_size = total_volume / total_trades if total_trades > 0 else Decimal("0")
        
        # Find largest bet
        largest_bet = max((Decimal(str(t.size)) for t in trades), default=Decimal("0"))
        
        # Update wallet
        wallet.total_trades = total_trades
        wallet.total_volume = total_volume
        wallet.avg_bet_size = avg_bet_size
        wallet.largest_bet = largest_bet
        wallet.last_seen = datetime.utcnow()
        wallet.updated_at = datetime.utcnow()
        
        await self.db.flush()
        logger.debug(f"Updated metrics for wallet {address}: {total_trades} trades, ${total_volume} volume")
    
    async def get_wallet_metrics(self, address: str) -> Dict:
        """Get aggregated wallet metrics
        
        Args:
            address: Wallet address
            
        Returns:
            Dictionary with wallet metrics
        """
        wallet = await self.get_or_create_wallet(address)
        
        return {
            "address": wallet.address,
            "account_age_days": wallet.account_age_days,
            "total_trades": wallet.total_trades,
            "total_volume": float(wallet.total_volume),
            "total_profit": float(wallet.total_profit),
            "win_count": wallet.win_count,
            "loss_count": wallet.loss_count,
            "win_rate": float(wallet.win_rate),
            "avg_bet_size": float(wallet.avg_bet_size),
            "largest_bet": float(wallet.largest_bet),
            "is_fresh_account": wallet.is_fresh_account,
            "is_proven_winner": wallet.is_proven_winner,
            "flagged_insider": wallet.flagged_insider,
            "confidence_score": float(wallet.confidence_score),
        }
    
    async def get_recent_trades(
        self,
        address: str,
        days: int = 30,
        limit: Optional[int] = None
    ) -> List[Trade]:
        """Get recent trades for a wallet
        
        Args:
            address: Wallet address
            days: Number of days to look back
            limit: Maximum number of trades to return
            
        Returns:
            List of Trade objects
        """
        since = datetime.utcnow() - timedelta(days=days)
        
        query = select(Trade).where(
            and_(
                (Trade.maker_address == address) | (Trade.taker_address == address),
                Trade.timestamp >= since
            )
        ).order_by(Trade.timestamp.desc())
        
        if limit:
            query = query.limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def detect_unusual_activity(
        self,
        address: str,
        market_id: str,
        trade_size: Decimal
    ) -> Dict:
        """Detect if a trade represents unusual activity for this wallet
        
        Args:
            address: Wallet address
            market_id: Market ID
            trade_size: Size of the trade in USDC
            
        Returns:
            Dictionary with flags and scores
        """
        wallet = await self.get_or_create_wallet(address)
        metrics = await self.get_wallet_metrics(address)
        
        flags = {
            "is_unusually_large": False,
            "is_first_trade": False,
            "is_fresh_account_large_bet": False,
            "unusual_activity_score": 0.0
        }
        
        # Check if trade is unusually large
        if wallet.total_trades > 0 and wallet.avg_bet_size > 0:
            size_ratio = float(trade_size / wallet.avg_bet_size)
            if size_ratio >= 3.0:  # 3x average
                flags["is_unusually_large"] = True
                flags["unusual_activity_score"] += 0.3
        
        # Check if this is the first trade
        if wallet.total_trades == 0:
            flags["is_first_trade"] = True
            flags["unusual_activity_score"] += 0.2
        
        # Check if fresh account making large bet
        if wallet.is_fresh_account and trade_size >= Decimal("10000"):
            flags["is_fresh_account_large_bet"] = True
            flags["unusual_activity_score"] += 0.5
        
        return flags
    
    async def get_top_wallets_by_volume(
        self,
        limit: int = 50,
        min_trades: int = 10
    ) -> List[Wallet]:
        """Get wallets with highest trading volume
        
        Args:
            limit: Maximum number of wallets to return
            min_trades: Minimum number of trades required
            
        Returns:
            List of Wallet objects
        """
        result = await self.db.execute(
            select(Wallet)
            .where(Wallet.total_trades >= min_trades)
            .order_by(Wallet.total_volume.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_top_wallets_by_win_rate(
        self,
        limit: int = 50,
        min_trades: int = 20
    ) -> List[Wallet]:
        """Get wallets with highest win rates
        
        Args:
            limit: Maximum number of wallets to return
            min_trades: Minimum number of trades required
            
        Returns:
            List of Wallet objects
        """
        result = await self.db.execute(
            select(Wallet)
            .where(Wallet.total_trades >= min_trades)
            .order_by(Wallet.win_rate.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def flag_wallet_as_insider(
        self,
        address: str,
        confidence: Decimal,
        reason: str
    ):
        """Flag a wallet as potential insider trader
        
        Args:
            address: Wallet address
            confidence: Confidence score (0.0 to 1.0)
            reason: Reasoning for flagging
        """
        wallet = await self.get_or_create_wallet(address)
        wallet.flagged_insider = True
        wallet.confidence_score = confidence
        wallet.notes = reason
        wallet.updated_at = datetime.utcnow()
        
        await self.db.flush()
        logger.info(f"Flagged wallet {address} as insider (confidence: {confidence}): {reason}")
