"""
Signal Detectors - Integrate all 5 signal detection algorithms for backtesting.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from .wallet_tracker import WalletTracker, WalletMetrics
from .market_state import MarketState, MarketInfo

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """A detected trading signal."""
    
    signal_type: str  # fresh_account, proven_winner, volume_spike, wallet_clustering, perfect_timing
    market_id: int
    wallet_address: Optional[str]  # None for market-wide signals like volume_spike
    timestamp: datetime
    confidence: float  # 0.0 to 1.0
    recommended_side: str  # 'YES' or 'NO'
    entry_price: float
    recommended_size_pct: float  # Percentage of bankroll to bet
    reasoning: str
    metadata: Dict


class SignalDetectors:
    """
    Runs all 5 signal detection algorithms against historical trade data.
    
    Algorithms:
    1. Fresh Account: New wallet (< 7 days) makes large bet ($10K+)
    2. Proven Winner: High win rate wallet (>70%) makes unusually large bet  
    3. Volume Spike: 10x volume spike before news
    4. Wallet Clustering: Multiple new wallets betting same direction
    5. Perfect Timing: Wallet consistently enters 6-24h before major moves
    """
    
    def __init__(
        self,
        wallet_tracker: WalletTracker,
        market_state: MarketState,
        min_confidence: float = 0.65
    ):
        """
        Initialize signal detectors.
        
        Args:
            wallet_tracker: Wallet metrics tracker
            market_state: Market state tracker
            min_confidence: Minimum confidence threshold to generate signals
        """
        self.wallet_tracker = wallet_tracker
        self.market_state = market_state
        self.min_confidence = min_confidence
        self.signals_detected: List[Signal] = []
    
    def process_trade(self, trade: Dict) -> List[Signal]:
        """
        Process a trade and check all signal algorithms.
        
        Args:
            trade: Trade dict with keys: timestamp, market_id, maker, taker, 
                   maker_direction, taker_direction, price, usd_amount
        
        Returns:
            List of detected signals (can be empty)
        """
        signals = []
        
        # Run all detection algorithms
        sig = self.detect_fresh_account(trade)
        if sig:
            signals.append(sig)
        
        sig = self.detect_proven_winner(trade)
        if sig:
            signals.append(sig)
        
        sig = self.detect_volume_spike(trade)
        if sig:
            signals.append(sig)
        
        sig = self.detect_wallet_clustering(trade)
        if sig:
            signals.append(sig)
        
        sig = self.detect_perfect_timing(trade)
        if sig:
            signals.append(sig)
        
        # Store all detected signals
        self.signals_detected.extend(signals)
        
        return signals
    
    def detect_fresh_account(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #1: Fresh Account Detection
        
        Pattern: New wallet (< 7 days) makes large bet ($10K+) on market 
                 closing within 48 hours
        Confidence: 85-95%
        """
        maker = trade['maker']
        maker_wallet = self.wallet_tracker.get_wallet(maker)
        market = self.market_state.get_market(trade['market_id'])
        
        if not market:
            return None
        
        # Check criteria
        account_age_hours = maker_wallet.account_age_hours
        trade_size = trade['usd_amount']
        hours_to_close = market.hours_until_resolution
        
        # Fresh account criteria
        if (
            account_age_hours < 168 and  # < 7 days
            trade_size > 10000 and
            maker_wallet.total_trades < 3 and
            hours_to_close is not None and hours_to_close < 48
        ):
            # Calculate confidence (higher for fresher accounts and larger bets)
            confidence = 0.80
            
            if account_age_hours < 24:
                confidence += 0.10
            elif account_age_hours < 72:
                confidence += 0.05
            
            if trade_size > 50000:
                confidence += 0.10
            elif trade_size > 25000:
                confidence += 0.05
            
            confidence = min(confidence, 0.95)
            
            if confidence < self.min_confidence:
                return None
            
            # Kelly criterion position sizing
            kelly_pct = (confidence - 0.5) / 0.5  # win_prob edge over 50/50
            recommended_size_pct = kelly_pct * 0.25  # Fractional Kelly
            recommended_size_pct = min(recommended_size_pct, 0.10)  # Max 10%
            
            return Signal(
                signal_type='fresh_account',
                market_id=trade['market_id'],
                wallet_address=maker,
                timestamp=trade['timestamp'],
                confidence=confidence,
                recommended_side=trade['maker_direction'],
                entry_price=trade['price'],
                recommended_size_pct=recommended_size_pct,
                reasoning=(
                    f"Fresh account ({account_age_hours:.1f}h old) with "
                    f"{maker_wallet.total_trades} trades placed ${trade_size:,.0f} bet "
                    f"on market closing in {hours_to_close:.1f}h"
                ),
                metadata={
                    'account_age_hours': account_age_hours,
                    'trade_size': trade_size,
                    'total_trades': maker_wallet.total_trades,
                    'hours_to_close': hours_to_close
                }
            )
        
        return None
    
    def detect_proven_winner(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #2: Proven Winner Tracking
        
        Pattern: Account with 70%+ win rate makes 3x larger than average bet
        Confidence: 70-80%
        """
        maker = trade['maker']
        maker_wallet = self.wallet_tracker.get_wallet(maker)
        trade_size = trade['usd_amount']
        
        # Check criteria
        if (
            maker_wallet.win_rate > 0.70 and
            maker_wallet.total_trades > 20 and
            maker_wallet.avg_bet_size > 0 and
            trade_size > (3 * maker_wallet.avg_bet_size) and
            maker_wallet.total_profit > 50000
        ):
            # Calculate confidence
            confidence = 0.65
            
            if maker_wallet.win_rate > 0.80:
                confidence += 0.10
            elif maker_wallet.win_rate > 0.75:
                confidence += 0.05
            
            if maker_wallet.total_trades > 50:
                confidence += 0.05
            
            confidence = min(confidence, 0.80)
            
            if confidence < self.min_confidence:
                return None
            
            kelly_pct = (confidence - 0.5) / 0.5
            recommended_size_pct = kelly_pct * 0.25
            recommended_size_pct = min(recommended_size_pct, 0.10)
            
            return Signal(
                signal_type='proven_winner',
                market_id=trade['market_id'],
                wallet_address=maker,
                timestamp=trade['timestamp'],
                confidence=confidence,
                recommended_side=trade['maker_direction'],
                entry_price=trade['price'],
                recommended_size_pct=recommended_size_pct,
                reasoning=(
                    f"Proven winner ({maker_wallet.win_rate*100:.1f}% win rate, "
                    f"{maker_wallet.total_trades} trades, ${maker_wallet.total_profit:,.0f} profit) "
                    f"bet ${trade_size:,.0f} (3x avg)"
                ),
                metadata={
                    'win_rate': maker_wallet.win_rate,
                    'total_trades': maker_wallet.total_trades,
                    'total_profit': maker_wallet.total_profit,
                    'trade_size': trade_size,
                    'avg_bet_size': maker_wallet.avg_bet_size
                }
            )
        
        return None
    
    def detect_volume_spike(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #3: Volume Spike Before News
        
        Pattern: 10x hourly volume spike with minimal price change
        Confidence: 60-75%
        """
        market = self.market_state.get_market(trade['market_id'])
        
        if not market:
            return None
        
        current_hour_volume = market.current_hour_volume
        avg_hourly_volume = market.avg_hourly_volume
        price_change = abs(market.price_change_1h)
        
        # Check criteria
        if (
            avg_hourly_volume > 0 and
            current_hour_volume > (10 * avg_hourly_volume) and
            price_change < 0.05 and  # < 5% price change
            current_hour_volume > 5000  # Minimum absolute volume
        ):
            # Calculate confidence
            spike_ratio = current_hour_volume / avg_hourly_volume
            
            confidence = 0.55
            
            if spike_ratio > 20:
                confidence += 0.15
            elif spike_ratio > 15:
                confidence += 0.10
            elif spike_ratio > 10:
                confidence += 0.05
            
            if price_change < 0.02:  # Very stable price
                confidence += 0.05
            
            confidence = min(confidence, 0.75)
            
            if confidence < self.min_confidence:
                return None
            
            kelly_pct = (confidence - 0.5) / 0.5
            recommended_size_pct = kelly_pct * 0.25
            recommended_size_pct = min(recommended_size_pct, 0.10)
            
            # Determine direction based on recent trade flow
            return Signal(
                signal_type='volume_spike',
                market_id=trade['market_id'],
                wallet_address=None,
                timestamp=trade['timestamp'],
                confidence=confidence,
                recommended_side=trade['maker_direction'],  # Follow the flow
                entry_price=trade['price'],
                recommended_size_pct=recommended_size_pct,
                reasoning=(
                    f"Volume spike: ${current_hour_volume:,.0f} current hour "
                    f"vs ${avg_hourly_volume:,.0f} avg ({spike_ratio:.1f}x) "
                    f"with only {price_change*100:.1f}% price change"
                ),
                metadata={
                    'current_hour_volume': current_hour_volume,
                    'avg_hourly_volume': avg_hourly_volume,
                    'spike_ratio': spike_ratio,
                    'price_change': price_change
                }
            )
        
        return None
    
    def detect_wallet_clustering(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #4: Wallet Clustering
        
        Pattern: 3+ new wallets betting same direction, combined volume > $25K
        Confidence: 55-70%
        """
        market_id = trade['market_id']
        market = self.market_state.get_market(market_id)
        
        if not market or not market.recent_trades:
            return None
        
        # Look at last 24 hours of trades
        cutoff_time = trade['timestamp'] - timedelta(hours=24)
        recent_trades = [
            t for t in market.recent_trades 
            if t['timestamp'] >= cutoff_time
        ]
        
        if len(recent_trades) < 3:
            return None
        
        # Group by direction
        yes_wallets = set()
        no_wallets = set()
        yes_volume = 0.0
        no_volume = 0.0
        
        for t in recent_trades:
            wallet = t['maker']
            w = self.wallet_tracker.get_wallet(wallet)
            
            if t['maker_direction'] == 'YES':
                yes_wallets.add(wallet)
                yes_volume += t['usd_amount']
            else:
                no_wallets.add(wallet)
                no_volume += t['usd_amount']
        
        # Check YES cluster
        if len(yes_wallets) >= 3 and yes_volume > 25000:
            new_wallet_count = sum(
                1 for w in yes_wallets
                if self.wallet_tracker.get_wallet(w).account_age_hours < 24
            )
            
            if new_wallet_count >= 2:
                confidence = 0.55
                
                if len(yes_wallets) >= 5:
                    confidence += 0.10
                elif len(yes_wallets) >= 4:
                    confidence += 0.05
                
                if yes_volume > 50000:
                    confidence += 0.10
                elif yes_volume > 35000:
                    confidence += 0.05
                
                confidence = min(confidence, 0.70)
                
                if confidence >= self.min_confidence:
                    kelly_pct = (confidence - 0.5) / 0.5
                    recommended_size_pct = kelly_pct * 0.25
                    recommended_size_pct = min(recommended_size_pct, 0.10)
                    
                    return Signal(
                        signal_type='wallet_clustering',
                        market_id=market_id,
                        wallet_address=None,
                        timestamp=trade['timestamp'],
                        confidence=confidence,
                        recommended_side='YES',
                        entry_price=trade['price'],
                        recommended_size_pct=recommended_size_pct,
                        reasoning=(
                            f"Wallet cluster: {len(yes_wallets)} wallets "
                            f"({new_wallet_count} new) bet YES with "
                            f"${yes_volume:,.0f} combined volume"
                        ),
                        metadata={
                            'wallet_count': len(yes_wallets),
                            'new_wallet_count': new_wallet_count,
                            'combined_volume': yes_volume
                        }
                    )
        
        # Check NO cluster
        if len(no_wallets) >= 3 and no_volume > 25000:
            new_wallet_count = sum(
                1 for w in no_wallets
                if self.wallet_tracker.get_wallet(w).account_age_hours < 24
            )
            
            if new_wallet_count >= 2:
                confidence = 0.55
                
                if len(no_wallets) >= 5:
                    confidence += 0.10
                elif len(no_wallets) >= 4:
                    confidence += 0.05
                
                if no_volume > 50000:
                    confidence += 0.10
                elif no_volume > 35000:
                    confidence += 0.05
                
                confidence = min(confidence, 0.70)
                
                if confidence >= self.min_confidence:
                    kelly_pct = (confidence - 0.5) / 0.5
                    recommended_size_pct = kelly_pct * 0.25
                    recommended_size_pct = min(recommended_size_pct, 0.10)
                    
                    return Signal(
                        signal_type='wallet_clustering',
                        market_id=market_id,
                        wallet_address=None,
                        timestamp=trade['timestamp'],
                        confidence=confidence,
                        recommended_side='NO',
                        entry_price=trade['price'],
                        recommended_size_pct=recommended_size_pct,
                        reasoning=(
                            f"Wallet cluster: {len(no_wallets)} wallets "
                            f"({new_wallet_count} new) bet NO with "
                            f"${no_volume:,.0f} combined volume"
                        ),
                        metadata={
                            'wallet_count': len(no_wallets),
                            'new_wallet_count': new_wallet_count,
                            'combined_volume': no_volume
                        }
                    )
        
        return None
    
    def detect_perfect_timing(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #5: Perfect Timing Pattern
        
        Pattern: Wallet's last 5 trades won, average entry 6-24h before resolution
        Confidence: 70-85%
        
        Note: This requires historical outcome data. For now, we'll use a simplified
        version based on high win rate + consistent early entry pattern.
        """
        maker = trade['maker']
        maker_wallet = self.wallet_tracker.get_wallet(maker)
        trade_size = trade['usd_amount']
        
        # Need sufficient history
        if maker_wallet.total_trades < 5:
            return None
        
        # Check recent win rate
        recent_win_rate = maker_wallet.get_recent_win_rate(n=5)
        
        # Check if this is a larger bet (indicates confidence)
        is_large_bet = (
            maker_wallet.avg_bet_size > 0 and
            trade_size > (1.5 * maker_wallet.avg_bet_size)
        )
        
        # Check criteria
        if (
            recent_win_rate >= 0.80 and  # 4/5 or 5/5 wins
            maker_wallet.win_rate >= 0.70 and
            is_large_bet
        ):
            confidence = 0.65
            
            if recent_win_rate >= 0.90:  # 5/5 wins
                confidence += 0.15
            else:
                confidence += 0.10
            
            if maker_wallet.win_rate >= 0.80:
                confidence += 0.05
            
            if maker_wallet.total_trades > 20:
                confidence += 0.05
            
            confidence = min(confidence, 0.85)
            
            if confidence < self.min_confidence:
                return None
            
            kelly_pct = (confidence - 0.5) / 0.5
            recommended_size_pct = kelly_pct * 0.25
            recommended_size_pct = min(recommended_size_pct, 0.10)
            
            return Signal(
                signal_type='perfect_timing',
                market_id=trade['market_id'],
                wallet_address=maker,
                timestamp=trade['timestamp'],
                confidence=confidence,
                recommended_side=trade['maker_direction'],
                entry_price=trade['price'],
                recommended_size_pct=recommended_size_pct,
                reasoning=(
                    f"Perfect timing: {recent_win_rate*100:.0f}% recent win rate, "
                    f"{maker_wallet.win_rate*100:.1f}% overall, "
                    f"{maker_wallet.total_trades} trades, large bet ${trade_size:,.0f}"
                ),
                metadata={
                    'recent_win_rate': recent_win_rate,
                    'overall_win_rate': maker_wallet.win_rate,
                    'total_trades': maker_wallet.total_trades,
                    'trade_size': trade_size
                }
            )
        
        return None
    
    def get_stats(self) -> Dict:
        """Get signal detection statistics."""
        signal_counts = {}
        for sig in self.signals_detected:
            signal_counts[sig.signal_type] = signal_counts.get(sig.signal_type, 0) + 1
        
        return {
            'total_signals': len(self.signals_detected),
            'by_type': signal_counts,
            'avg_confidence': sum(s.confidence for s in self.signals_detected) / len(self.signals_detected) if self.signals_detected else 0
        }
