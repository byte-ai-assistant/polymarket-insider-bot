"""
Backtesting module for Polymarket insider trading bot.

This module provides comprehensive backtesting capabilities to validate
trading strategies using historical Polymarket data.
"""

from .data_loader import DataLoader
from .wallet_tracker import WalletTracker, WalletMetrics
from .market_state import MarketState, MarketInfo
from .signal_detectors import SignalDetectors, Signal
from .trade_simulator import TradeSimulator, Position
from .performance_analyzer import PerformanceAnalyzer
from .backtest_runner import BacktestRunner

__all__ = [
    'DataLoader',
    'WalletTracker',
    'WalletMetrics',
    'MarketState',
    'MarketInfo',
    'SignalDetectors',
    'Signal',
    'TradeSimulator',
    'Position',
    'PerformanceAnalyzer',
    'BacktestRunner',
]
