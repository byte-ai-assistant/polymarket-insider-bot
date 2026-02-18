"""Main Signal Detection Engine - Coordinates all detector algorithms"""

import logging
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Signal
from src.signals.fresh_account import FreshAccountDetector
from src.signals.perfect_timing import PerfectTimingDetector
from src.signals.proven_winner import ProvenWinnerDetector
from src.signals.volume_spike import VolumeSpikeDetector
from src.signals.wallet_clustering import WalletClusteringDetector

logger = logging.getLogger(__name__)


class SignalDetector:
    """Main signal detection engine coordinating all algorithms"""
    
    def __init__(self, db: AsyncSession):
        """Initialize signal detector
        
        Args:
            db: Database session
        """
        self.db = db
        
        # Initialize all detectors
        self.fresh_account = FreshAccountDetector(db)
        self.proven_winner = ProvenWinnerDetector(db)
        self.volume_spike = VolumeSpikeDetector(db)
        self.wallet_clustering = WalletClusteringDetector(db)
        self.perfect_timing = PerfectTimingDetector(db)
    
    async def detect_all(
        self,
        wallet_address: str,
        market_id: str,
        trade_size: float,
        trade_price: float,
        side: str
    ) -> List[Signal]:
        """Run all signal detection algorithms
        
        Args:
            wallet_address: Wallet making trade
            market_id: Market ID
            trade_size: Trade size in USDC
            trade_price: Trade price
            side: 'BUY' or 'SELL'
            
        Returns:
            List of detected signals (may be empty)
        """
        from decimal import Decimal
        
        trade_size_decimal = Decimal(str(trade_size))
        trade_price_decimal = Decimal(str(trade_price))
        
        signals: List[Signal] = []
        
        # Run wallet-specific detectors
        detectors = [
            ("fresh_account", self.fresh_account),
            ("proven_winner", self.proven_winner),
            ("perfect_timing", self.perfect_timing),
        ]
        
        for detector_name, detector in detectors:
            try:
                signal = await detector.detect(
                    wallet_address=wallet_address,
                    market_id=market_id,
                    trade_size=trade_size_decimal,
                    trade_price=trade_price_decimal,
                    side=side
                )
                if signal:
                    signals.append(signal)
                    logger.info(f"Signal detected by {detector_name}: confidence={signal.confidence}")
            except Exception as e:
                logger.error(f"Error in {detector_name} detector: {e}", exc_info=True)
        
        return signals
    
    async def detect_market_signals(self, market_id: str) -> List[Signal]:
        """Run market-level signal detection
        
        Args:
            market_id: Market ID to analyze
            
        Returns:
            List of detected signals (may be empty)
        """
        signals: List[Signal] = []
        
        # Run market-level detectors
        detectors = [
            ("volume_spike", self.volume_spike),
            ("wallet_clustering", self.wallet_clustering),
        ]
        
        for detector_name, detector in detectors:
            try:
                signal = await detector.detect(market_id=market_id)
                if signal:
                    signals.append(signal)
                    logger.info(f"Signal detected by {detector_name}: confidence={signal.confidence}")
            except Exception as e:
                logger.error(f"Error in {detector_name} detector: {e}", exc_info=True)
        
        return signals
    
    async def save_signal(self, signal: Signal):
        """Save signal to database
        
        Args:
            signal: Signal object to save
        """
        self.db.add(signal)
        await self.db.flush()
        logger.info(f"Saved signal {signal.id}: type={signal.signal_type}, confidence={signal.confidence}")
    
    async def save_all_signals(self, signals: List[Signal]):
        """Save multiple signals to database
        
        Args:
            signals: List of signals to save
        """
        for signal in signals:
            await self.save_signal(signal)
        
        await self.db.commit()
        logger.info(f"Saved {len(signals)} signals to database")
