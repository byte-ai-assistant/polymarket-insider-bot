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
    1. Fresh Account: New wallet (< 7 days) makes large bet ($1K+)
    2. Proven Winner: High win rate wallet (>65%) makes unusually large bet
    3. Volume Spike: 5x volume spike before news
    4. Wallet Clustering: Multiple new wallets betting same direction
    5. Perfect Timing: Wallet consistently enters before major moves
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

        # Cooldown tracking to prevent signal flooding
        # Key: (signal_type, market_id) or (signal_type, wallet_address)
        # Value: timestamp of last signal
        self._signal_cooldowns: Dict[tuple, datetime] = {}
        self._cooldown_hours = {
            'fresh_account': 24,       # One signal per wallet per market per 24h
            'proven_winner': 12,       # One signal per wallet per 12h
            'volume_spike': 4,         # One signal per market per 4h
            'wallet_clustering': 6,    # One signal per market per 6h
            'perfect_timing': 12,      # One signal per wallet per 12h
        }
    
    def _is_on_cooldown(self, signal_type: str, key: str, timestamp: datetime) -> bool:
        """Check if a signal is on cooldown to prevent flooding."""
        cooldown_key = (signal_type, key)
        if cooldown_key in self._signal_cooldowns:
            last_signal_time = self._signal_cooldowns[cooldown_key]
            cooldown_hours = self._cooldown_hours.get(signal_type, 6)
            if (timestamp - last_signal_time).total_seconds() < cooldown_hours * 3600:
                return True
        return False

    def _set_cooldown(self, signal_type: str, key: str, timestamp: datetime):
        """Record a signal emission for cooldown tracking."""
        self._signal_cooldowns[(signal_type, key)] = timestamp

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

        Pattern: New wallet (< 7 days) makes large bet ($1K+) on any active market.
        Removed the <48h to close constraint (too restrictive).
        Checks both maker and taker sides.
        Confidence: 75-95%
        """
        market = self.market_state.get_market(trade['market_id'])
        if not market:
            return None

        trade_size = trade['usd_amount']
        current_time = trade['timestamp']

        # Check both maker and taker
        for role in ['maker', 'taker']:
            wallet_addr = trade[role]
            direction_key = f'{role}_direction'
            direction = trade.get(direction_key)
            if not direction:
                continue

            wallet = self.wallet_tracker.get_wallet(wallet_addr)

            # Calculate account age relative to current time, not last_trade
            if wallet.first_trade is None:
                account_age_hours = 0.0
            else:
                account_age_hours = (current_time - wallet.first_trade).total_seconds() / 3600

            # Fresh account criteria (relaxed from $10K to $1K, removed <48h close requirement)
            if (
                account_age_hours < 168 and  # < 7 days
                trade_size >= 1000 and  # Lowered from $10K
                wallet.total_trades <= 5  # Relaxed from 3
            ):
                # Cooldown check
                cooldown_key = f"{wallet_addr}:{trade['market_id']}"
                if self._is_on_cooldown('fresh_account', cooldown_key, current_time):
                    continue

                # Calculate confidence
                confidence = 0.70

                if account_age_hours < 12:
                    confidence += 0.15
                elif account_age_hours < 24:
                    confidence += 0.10
                elif account_age_hours < 72:
                    confidence += 0.05

                if trade_size >= 25000:
                    confidence += 0.10
                elif trade_size >= 10000:
                    confidence += 0.07
                elif trade_size >= 5000:
                    confidence += 0.04

                if wallet.total_trades <= 1:
                    confidence += 0.05

                # Bonus if market closing soon
                hours_to_close = market.hours_until_resolution
                if hours_to_close is not None and hours_to_close < 72:
                    confidence += 0.05

                confidence = min(confidence, 0.95)

                if confidence < self.min_confidence:
                    continue

                kelly_pct = (confidence - 0.5) / 0.5
                recommended_size_pct = kelly_pct * 0.25
                recommended_size_pct = min(recommended_size_pct, 0.10)

                self._set_cooldown('fresh_account', cooldown_key, current_time)

                return Signal(
                    signal_type='fresh_account',
                    market_id=trade['market_id'],
                    wallet_address=wallet_addr,
                    timestamp=current_time,
                    confidence=confidence,
                    recommended_side=direction,
                    entry_price=trade['price'],
                    recommended_size_pct=recommended_size_pct,
                    reasoning=(
                        f"Fresh account ({account_age_hours:.1f}h old) with "
                        f"{wallet.total_trades} trades placed ${trade_size:,.0f} bet"
                    ),
                    metadata={
                        'account_age_hours': account_age_hours,
                        'trade_size': trade_size,
                        'total_trades': wallet.total_trades,
                        'role': role
                    }
                )

        return None
    
    def detect_proven_winner(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #2: Proven Winner Tracking

        Pattern: Account with 65%+ win rate and 10+ resolved trades makes
                 2x larger than average bet. Removed $50K profit requirement.
        Confidence: 65-85%
        """
        trade_size = trade['usd_amount']
        current_time = trade['timestamp']

        # Check both maker and taker
        for role in ['maker', 'taker']:
            wallet_addr = trade[role]
            direction_key = f'{role}_direction'
            direction = trade.get(direction_key)
            if not direction:
                continue

            wallet = self.wallet_tracker.get_wallet(wallet_addr)

            # Relaxed criteria: 65% win rate, 10+ trades, 2x avg bet, positive profit
            resolved_trades = wallet.wins + wallet.losses
            if (
                resolved_trades >= 10 and
                wallet.win_rate >= 0.65 and
                wallet.avg_bet_size > 0 and
                trade_size >= (2 * wallet.avg_bet_size) and
                wallet.total_profit > 0
            ):
                # Cooldown check
                cooldown_key = f"{wallet_addr}:{trade['market_id']}"
                if self._is_on_cooldown('proven_winner', cooldown_key, current_time):
                    continue

                # Calculate confidence
                confidence = 0.60

                if wallet.win_rate >= 0.80:
                    confidence += 0.15
                elif wallet.win_rate >= 0.75:
                    confidence += 0.10
                elif wallet.win_rate >= 0.70:
                    confidence += 0.05

                if resolved_trades >= 50:
                    confidence += 0.05
                elif resolved_trades >= 25:
                    confidence += 0.03

                # Size ratio bonus
                size_ratio = trade_size / wallet.avg_bet_size
                if size_ratio >= 5:
                    confidence += 0.07
                elif size_ratio >= 3:
                    confidence += 0.04

                # Profit bonus
                if wallet.total_profit >= 10000:
                    confidence += 0.05
                elif wallet.total_profit >= 1000:
                    confidence += 0.03

                confidence = min(confidence, 0.85)

                if confidence < self.min_confidence:
                    continue

                kelly_pct = (confidence - 0.5) / 0.5
                recommended_size_pct = kelly_pct * 0.25
                recommended_size_pct = min(recommended_size_pct, 0.10)

                self._set_cooldown('proven_winner', cooldown_key, current_time)

                return Signal(
                    signal_type='proven_winner',
                    market_id=trade['market_id'],
                    wallet_address=wallet_addr,
                    timestamp=current_time,
                    confidence=confidence,
                    recommended_side=direction,
                    entry_price=trade['price'],
                    recommended_size_pct=recommended_size_pct,
                    reasoning=(
                        f"Proven winner ({wallet.win_rate*100:.1f}% win rate, "
                        f"{resolved_trades} resolved trades, ${wallet.total_profit:,.0f} profit) "
                        f"bet ${trade_size:,.0f} ({size_ratio:.1f}x avg)"
                    ),
                    metadata={
                        'win_rate': wallet.win_rate,
                        'resolved_trades': resolved_trades,
                        'total_profit': wallet.total_profit,
                        'trade_size': trade_size,
                        'avg_bet_size': wallet.avg_bet_size,
                        'size_ratio': size_ratio
                    }
                )

        return None
    
    def detect_volume_spike(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #3: Volume Spike Before News

        Pattern: 5x+ hourly volume spike with <10% price change.
        Uses weighted trade flow direction instead of just last trade.
        Confidence: 60-80%
        """
        market = self.market_state.get_market(trade['market_id'])

        if not market:
            return None

        current_time = trade['timestamp']
        market_id = trade['market_id']

        # Cooldown check
        if self._is_on_cooldown('volume_spike', str(market_id), current_time):
            return None

        current_hour_volume = market.current_hour_volume
        avg_hourly_volume = market.avg_hourly_volume
        price_change = abs(market.price_change_1h)

        # Lowered from 10x to 5x, price tolerance from 5% to 10%, min volume from 5K to 2K
        if (
            avg_hourly_volume > 0 and
            current_hour_volume > (5 * avg_hourly_volume) and
            price_change < 0.10 and
            current_hour_volume > 2000
        ):
            spike_ratio = current_hour_volume / avg_hourly_volume

            confidence = 0.58

            if spike_ratio > 20:
                confidence += 0.15
            elif spike_ratio > 10:
                confidence += 0.10
            elif spike_ratio > 7:
                confidence += 0.05

            if price_change < 0.03:
                confidence += 0.07
            elif price_change < 0.05:
                confidence += 0.03

            confidence = min(confidence, 0.80)

            if confidence < self.min_confidence:
                return None

            # Determine direction from net trade flow (not just last trade)
            yes_volume = 0.0
            no_volume = 0.0
            for t in market.recent_trades:
                if t.get('maker_direction') == 'YES':
                    yes_volume += t['usd_amount']
                else:
                    no_volume += t['usd_amount']
            recommended_side = 'YES' if yes_volume >= no_volume else 'NO'

            kelly_pct = (confidence - 0.5) / 0.5
            recommended_size_pct = kelly_pct * 0.25
            recommended_size_pct = min(recommended_size_pct, 0.10)

            self._set_cooldown('volume_spike', str(market_id), current_time)

            return Signal(
                signal_type='volume_spike',
                market_id=market_id,
                wallet_address=None,
                timestamp=current_time,
                confidence=confidence,
                recommended_side=recommended_side,
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
                    'price_change': price_change,
                    'yes_volume': yes_volume,
                    'no_volume': no_volume
                }
            )

        return None
    
    def _check_cluster(
        self, wallets: set, volume: float, side: str,
        trade: Dict, market_id: int, current_time: datetime
    ) -> Optional[Signal]:
        """Helper to check a directional wallet cluster."""
        if len(wallets) < 3 or volume < 25000:
            return None

        new_wallet_count = sum(
            1 for w in wallets
            if (current_time - (self.wallet_tracker.get_wallet(w).first_trade or current_time)).total_seconds() < 48 * 3600
        )

        # Require majority of wallets to be new (>50%) for a real cluster
        fresh_ratio = new_wallet_count / len(wallets) if wallets else 0
        if new_wallet_count < 2 or fresh_ratio < 0.5:
            return None

        confidence = 0.55

        if len(wallets) >= 6:
            confidence += 0.10
        elif len(wallets) >= 5:
            confidence += 0.07
        elif len(wallets) >= 4:
            confidence += 0.04

        if volume > 100000:
            confidence += 0.10
        elif volume > 50000:
            confidence += 0.07
        elif volume > 35000:
            confidence += 0.04

        if fresh_ratio >= 0.8:
            confidence += 0.05

        confidence = min(confidence, 0.75)

        if confidence < self.min_confidence:
            return None

        kelly_pct = (confidence - 0.5) / 0.5
        recommended_size_pct = kelly_pct * 0.25
        recommended_size_pct = min(recommended_size_pct, 0.10)

        self._set_cooldown('wallet_clustering', str(market_id), current_time)

        return Signal(
            signal_type='wallet_clustering',
            market_id=market_id,
            wallet_address=None,
            timestamp=current_time,
            confidence=confidence,
            recommended_side=side,
            entry_price=trade['price'],
            recommended_size_pct=recommended_size_pct,
            reasoning=(
                f"Wallet cluster: {len(wallets)} wallets "
                f"({new_wallet_count} new, {fresh_ratio*100:.0f}% fresh) bet {side} with "
                f"${volume:,.0f} combined volume"
            ),
            metadata={
                'wallet_count': len(wallets),
                'new_wallet_count': new_wallet_count,
                'fresh_ratio': fresh_ratio,
                'combined_volume': volume
            }
        )

    def detect_wallet_clustering(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #4: Wallet Clustering

        Pattern: 3+ wallets (majority fresh) betting same direction, $25K+ volume.
        Now with per-market cooldown to prevent signal flooding.
        Confidence: 55-75%
        """
        market_id = trade['market_id']
        market = self.market_state.get_market(market_id)
        current_time = trade['timestamp']

        if not market or not market.recent_trades:
            return None

        # Cooldown check - this was the #1 issue, firing on every trade
        if self._is_on_cooldown('wallet_clustering', str(market_id), current_time):
            return None

        # Look at last 12 hours (narrowed from 24h for more targeted detection)
        cutoff_time = current_time - timedelta(hours=12)
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
            if t.get('maker_direction') == 'YES':
                yes_wallets.add(wallet)
                yes_volume += t['usd_amount']
            else:
                no_wallets.add(wallet)
                no_volume += t['usd_amount']

        # Check YES cluster
        sig = self._check_cluster(yes_wallets, yes_volume, 'YES', trade, market_id, current_time)
        if sig:
            return sig

        # Check NO cluster
        sig = self._check_cluster(no_wallets, no_volume, 'NO', trade, market_id, current_time)
        if sig:
            return sig

        return None
    
    def detect_perfect_timing(self, trade: Dict) -> Optional[Signal]:
        """
        Signal #5: Perfect Timing Pattern

        Dual approach:
        A) If resolution data exists: Wallet has 3+ recent wins out of last 5
        B) Fallback heuristic: Wallet consistently trades markets approaching
           resolution with high volume and conviction (large bets near close)

        Confidence: 65-85%
        """
        trade_size = trade['usd_amount']
        current_time = trade['timestamp']
        market = self.market_state.get_market(trade['market_id'])

        for role in ['maker', 'taker']:
            wallet_addr = trade[role]
            direction_key = f'{role}_direction'
            direction = trade.get(direction_key)
            if not direction:
                continue

            wallet = self.wallet_tracker.get_wallet(wallet_addr)

            if wallet.total_trades < 5:
                continue

            # Cooldown check
            cooldown_key = f"{wallet_addr}:{trade['market_id']}"
            if self._is_on_cooldown('perfect_timing', cooldown_key, current_time):
                continue

            # Approach A: Use resolution-based win rate if available
            resolved_trades = wallet.wins + wallet.losses
            recent_win_rate = wallet.get_recent_win_rate(n=5)
            has_resolution_data = resolved_trades >= 3

            # Approach B: Heuristic - high-volume wallet trading near market close
            is_near_close = (
                market is not None and
                market.hours_until_resolution is not None and
                6 <= market.hours_until_resolution <= 48
            )
            is_large_bet = (
                wallet.avg_bet_size > 0 and
                trade_size >= (1.5 * wallet.avg_bet_size)
            )
            is_high_volume = wallet.total_volume >= 5000

            # Check approach A (resolution-based)
            if has_resolution_data and recent_win_rate >= 0.60 and wallet.win_rate >= 0.60:
                confidence = 0.60

                if recent_win_rate >= 1.0:
                    confidence += 0.15
                elif recent_win_rate >= 0.80:
                    confidence += 0.10
                elif recent_win_rate >= 0.60:
                    confidence += 0.05

                if wallet.win_rate >= 0.80:
                    confidence += 0.05
                elif wallet.win_rate >= 0.70:
                    confidence += 0.03

                if resolved_trades >= 15:
                    confidence += 0.05

                if is_large_bet:
                    confidence += 0.05

                confidence = min(confidence, 0.85)

            # Check approach B (heuristic near-close timing)
            elif is_near_close and is_large_bet and is_high_volume:
                confidence = 0.60

                # Closer to resolution = higher confidence
                hours_left = market.hours_until_resolution
                if hours_left <= 12:
                    confidence += 0.10
                elif hours_left <= 24:
                    confidence += 0.05

                if trade_size >= 5000:
                    confidence += 0.05
                elif trade_size >= 2000:
                    confidence += 0.03

                if wallet.total_trades >= 15:
                    confidence += 0.03

                confidence = min(confidence, 0.80)
            else:
                continue

            if confidence < self.min_confidence:
                continue

            kelly_pct = (confidence - 0.5) / 0.5
            recommended_size_pct = kelly_pct * 0.25
            recommended_size_pct = min(recommended_size_pct, 0.10)

            self._set_cooldown('perfect_timing', cooldown_key, current_time)

            return Signal(
                signal_type='perfect_timing',
                market_id=trade['market_id'],
                wallet_address=wallet_addr,
                timestamp=current_time,
                confidence=confidence,
                recommended_side=direction,
                entry_price=trade['price'],
                recommended_size_pct=recommended_size_pct,
                reasoning=(
                    f"Perfect timing: {recent_win_rate*100:.0f}% recent win rate, "
                    f"{wallet.win_rate*100:.1f}% overall, "
                    f"{wallet.total_trades} trades, ${trade_size:,.0f} bet"
                    + (f", market closes in {market.hours_until_resolution:.0f}h" if is_near_close else "")
                ),
                metadata={
                    'recent_win_rate': recent_win_rate,
                    'overall_win_rate': wallet.win_rate,
                    'total_trades': wallet.total_trades,
                    'trade_size': trade_size,
                    'resolved_trades': resolved_trades,
                    'has_resolution_data': has_resolution_data,
                    'hours_until_resolution': market.hours_until_resolution if market else None
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
