"""
Polymarket Insider Bot - Backtesting Framework

This module provides a complete backtesting framework for validating
insider signal detection algorithms using historical Polymarket trade data.
"""

from .data_loader import DataLoader
from .wallet_tracker import WalletTracker
from .market_state import MarketState
from .signal_detectors import SignalDetector
from .trade_simulator import TradeSimulator, Position
from .performance_analyzer import PerformanceAnalyzer
from .backtest_runner import BacktestRunner

__all__ = [
    'DataLoader',
    'WalletTracker',
    'MarketState',
    'SignalDetector',
    'TradeSimulator',
    'Position',
    'PerformanceAnalyzer',
    'BacktestRunner',
]
