"""
Wallet Tracker - Track wallet trading history and metrics during backtest replay.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class WalletMetrics:
    """Trading metrics for a single wallet."""
    
    address: str
    first_trade: Optional[datetime] = None
    last_trade: Optional[datetime] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0.0
    total_volume: float = 0.0
    avg_bet_size: float = 0.0
    largest_bet: float = 0.0
    
    # Recent trade history (limited window for performance)
    trade_history: List[Dict] = field(default_factory=list)
    position_history: List[Dict] = field(default_factory=list)
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        if self.total_trades == 0:
            return 0.0
        return self.wins / (self.wins + self.losses) if (self.wins + self.losses) > 0 else 0.0
    
    @property
    def account_age_days(self) -> float:
        """Calculate account age in days."""
        if not self.first_trade or not self.last_trade:
            return 0.0
        return (self.last_trade - self.first_trade).total_seconds() / 86400
    
    @property
    def account_age_hours(self) -> float:
        """Calculate account age in hours."""
        if not self.first_trade or not self.last_trade:
            return 0.0
        return (self.last_trade - self.first_trade).total_seconds() / 3600
    
    def update_from_trade(self, trade: Dict):
        """
        Update wallet metrics from a new trade.
        
        Args:
            trade: Trade dictionary with keys: timestamp, market_id, side, price, usd_amount
        """
        timestamp = trade['timestamp']
        usd_amount = trade['usd_amount']
        
        # Update timestamps
        if self.first_trade is None:
            self.first_trade = timestamp
        self.last_trade = timestamp
        
        # Update trade counts and volume
        self.total_trades += 1
        self.total_volume += usd_amount
        
        # Update bet size metrics
        if usd_amount > self.largest_bet:
            self.largest_bet = usd_amount
        
        self.avg_bet_size = self.total_volume / self.total_trades
        
        # Store trade (keep last 100 for performance)
        self.trade_history.append(trade)
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]
    
    def update_from_resolution(self, market_id: int, outcome: str, profit: float):
        """
        Update metrics when a market resolves.
        
        Args:
            market_id: Market that resolved
            outcome: 'win' or 'loss'
            profit: Profit or loss amount
        """
        if outcome == 'win':
            self.wins += 1
        elif outcome == 'loss':
            self.losses += 1
        
        self.total_profit += profit
    
    def get_last_n_trades(self, n: int = 5) -> List[Dict]:
        """Get the last N trades."""
        return self.trade_history[-n:]
    
    def get_recent_win_rate(self, n: int = 5) -> float:
        """Calculate win rate for last N trades."""
        recent = self.get_last_n_trades(n)
        if not recent:
            return 0.0
        wins = sum(1 for t in recent if t.get('outcome') == 'win')
        return wins / len(recent)


class WalletTracker:
    """
    Tracks all wallet trading activity during backtest replay.
    
    Maintains a dictionary of wallet addresses to WalletMetrics, updating
    as trades are replayed chronologically.
    """
    
    def __init__(self):
        """Initialize wallet tracker."""
        self.wallets: Dict[str, WalletMetrics] = {}
        self.total_trades_processed = 0
        logger.info("WalletTracker initialized")
    
    def get_wallet(self, address: str) -> WalletMetrics:
        """
        Get or create wallet metrics for an address.
        
        Args:
            address: Wallet address
        
        Returns:
            WalletMetrics for this address
        """
        if address not in self.wallets:
            self.wallets[address] = WalletMetrics(address=address)
        return self.wallets[address]
    
    def process_trade(self, trade: Dict) -> Tuple[WalletMetrics, WalletMetrics]:
        """
        Process a trade and update both maker and taker metrics.
        
        Args:
            trade: Trade dict with keys: timestamp, maker, taker, market_id,
                   maker_direction, taker_direction, price, usd_amount
        
        Returns:
            Tuple of (maker_metrics, taker_metrics)
        """
        maker_wallet = self.get_wallet(trade['maker'])
        taker_wallet = self.get_wallet(trade['taker'])
        
        # Build trade records for each side
        maker_trade = {
            'timestamp': trade['timestamp'],
            'market_id': trade['market_id'],
            'side': trade['maker_direction'],
            'price': trade['price'],
            'usd_amount': trade['usd_amount'],
            'role': 'maker'
        }
        
        taker_trade = {
            'timestamp': trade['timestamp'],
            'market_id': trade['market_id'],
            'side': trade['taker_direction'],
            'price': trade['price'],
            'usd_amount': trade['usd_amount'],
            'role': 'taker'
        }
        
        # Update metrics
        maker_wallet.update_from_trade(maker_trade)
        taker_wallet.update_from_trade(taker_trade)
        
        self.total_trades_processed += 1
        
        if self.total_trades_processed % 10000 == 0:
            logger.info(f"Processed {self.total_trades_processed:,} trades, tracking {len(self.wallets):,} wallets")
        
        return maker_wallet, taker_wallet
    
    def process_market_resolution(
        self,
        market_id: int,
        winning_side: str,
        resolution_price: float
    ):
        """
        Process a market resolution and update wallet win/loss records.
        
        Args:
            market_id: Market that resolved
            winning_side: 'BUY' or 'SELL' (which side won)
            resolution_price: Final settlement price (0 or 1)
        """
        # Find all wallets with positions in this market
        for wallet in self.wallets.values():
            # Check trade history for this market
            market_trades = [t for t in wallet.trade_history if t['market_id'] == market_id]
            
            if not market_trades:
                continue
            
            # Calculate net position and profit
            for trade in market_trades:
                if trade['side'] == winning_side:
                    # This trade was on the winning side
                    profit = trade['usd_amount'] * (1 - trade['price'])  # Simplified
                    wallet.update_from_resolution(market_id, 'win', profit)
                else:
                    # This trade was on the losing side
                    loss = -trade['usd_amount'] * trade['price']  # Simplified
                    wallet.update_from_resolution(market_id, 'loss', loss)
                
                # Mark trade as resolved
                trade['outcome'] = 'win' if trade['side'] == winning_side else 'loss'
    
    def get_high_win_rate_wallets(
        self,
        min_trades: int = 20,
        min_win_rate: float = 0.70
    ) -> List[WalletMetrics]:
        """
        Get wallets with high win rates.
        
        Args:
            min_trades: Minimum number of trades
            min_win_rate: Minimum win rate (0.0 - 1.0)
        
        Returns:
            List of WalletMetrics sorted by win rate descending
        """
        candidates = [
            w for w in self.wallets.values()
            if w.total_trades >= min_trades and w.win_rate >= min_win_rate
        ]
        return sorted(candidates, key=lambda w: w.win_rate, reverse=True)
    
    def get_fresh_accounts(
        self,
        current_time: datetime,
        max_age_hours: float = 168,  # 7 days
        max_trades: int = 3
    ) -> List[WalletMetrics]:
        """
        Get recently created accounts with few trades.
        
        Args:
            current_time: Current backtest timestamp
            max_age_hours: Maximum account age in hours
            max_trades: Maximum number of trades
        
        Returns:
            List of fresh account WalletMetrics
        """
        fresh = []
        for wallet in self.wallets.values():
            if wallet.first_trade is None:
                continue
            
            age_hours = (current_time - wallet.first_trade).total_seconds() / 3600
            
            if age_hours <= max_age_hours and wallet.total_trades <= max_trades:
                fresh.append(wallet)
        
        return fresh
    
    def get_wallet_summary(self, address: str) -> Dict:
        """
        Get a summary of wallet metrics.
        
        Args:
            address: Wallet address
        
        Returns:
            Dictionary with wallet metrics
        """
        wallet = self.get_wallet(address)
        
        return {
            'address': wallet.address,
            'first_trade': wallet.first_trade,
            'last_trade': wallet.last_trade,
            'account_age_days': wallet.account_age_days,
            'total_trades': wallet.total_trades,
            'win_rate': wallet.win_rate,
            'total_profit': wallet.total_profit,
            'total_volume': wallet.total_volume,
            'avg_bet_size': wallet.avg_bet_size,
            'largest_bet': wallet.largest_bet
        }
    
    def get_stats(self) -> Dict:
        """Get tracker statistics."""
        return {
            'total_wallets': len(self.wallets),
            'total_trades_processed': self.total_trades_processed,
            'active_wallets': len([w for w in self.wallets.values() if w.total_trades > 0]),
            'high_volume_wallets': len([w for w in self.wallets.values() if w.total_volume > 10000])
        }
