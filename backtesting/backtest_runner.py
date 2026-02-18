"""
Backtest Runner - Main orchestrator that ties everything together.
"""

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

from .data_loader import DataLoader
from .wallet_tracker import WalletTracker
from .market_state import MarketState
from .signal_detectors import SignalDetectors
from .trade_simulator import TradeSimulator
from .performance_analyzer import PerformanceAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestRunner:
    """
    Main backtesting orchestrator.
    
    Workflow:
    1. Load historical market and trade data
    2. Replay trades chronologically
    3. Update wallet and market state
    4. Run signal detection algorithms
    5. Simulate trade execution
    6. Track positions and calculate P&L
    7. Generate performance report
    """
    
    def __init__(
        self,
        poly_data_path: str = "../poly_data",
        starting_capital: float = 5000,
        min_confidence: float = 0.65,
        min_market_volume: float = 10000
    ):
        """
        Initialize backtest runner.
        
        Args:
            poly_data_path: Path to poly_data repository
            starting_capital: Initial capital in USDC
            min_confidence: Minimum signal confidence threshold
            min_market_volume: Minimum market volume to consider
        """
        self.poly_data_path = poly_data_path
        self.starting_capital = starting_capital
        self.min_confidence = min_confidence
        self.min_market_volume = min_market_volume
        
        # Initialize components
        logger.info("Initializing backtest components...")
        
        self.data_loader = DataLoader(poly_data_path)
        self.wallet_tracker = WalletTracker()
        self.market_state = MarketState()
        self.signal_detectors = SignalDetectors(
            wallet_tracker=self.wallet_tracker,
            market_state=self.market_state,
            min_confidence=min_confidence
        )
        self.trade_simulator = TradeSimulator(
            starting_capital=starting_capital
        )
        
        logger.info("Backtest components initialized")
    
    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        report_path: str = None
    ) -> dict:
        """
        Run backtest for specified date range.
        
        Args:
            start_date: Start date for backtest
            end_date: End date for backtest
            report_path: Path to save performance report
        
        Returns:
            Performance metrics dictionary
        """
        logger.info("=" * 80)
        logger.info(f"STARTING BACKTEST: {start_date.date()} to {end_date.date()}")
        logger.info("=" * 80)
        
        # Load data
        logger.info("Loading market and trade data...")
        markets_df, trades_df = self.data_loader.load_backtest_data(
            start_date=start_date,
            end_date=end_date,
            min_market_volume=self.min_market_volume
        )
        
        logger.info(f"Loaded {len(markets_df):,} markets and {len(trades_df):,} trades")
        
        # Register markets
        logger.info("Registering markets...")
        for row in markets_df.iter_rows(named=True):
            self.market_state.register_market(
                market_id=row['id'],
                question=row.get('question', ''),
                created_at=row.get('createdAt'),
                close_time=row.get('closedTime')
            )
        
        # Sort trades chronologically
        trades_df = trades_df.sort('timestamp')
        
        # Replay trades
        logger.info("Replaying trades chronologically...")
        
        total_trades = len(trades_df)
        signals_found = 0
        trades_executed = 0
        
        for idx, row in enumerate(trades_df.iter_rows(named=True)):
            # Convert row to dict
            trade = dict(row)
            
            # Update wallet tracker
            self.wallet_tracker.process_trade(trade)
            
            # Update market state
            self.market_state.update_from_trade(trade)
            
            # Run signal detection
            signals = self.signal_detectors.process_trade(trade)
            
            if signals:
                signals_found += len(signals)
                
                # Execute signals
                for signal in signals:
                    position = self.trade_simulator.execute_signal(
                        signal=signal,
                        market_state=self.market_state
                    )
                    if position:
                        trades_executed += 1
            
            # Check for position exits
            self.trade_simulator.check_exits(
                market_state=self.market_state,
                current_time=trade['timestamp']
            )
            
            # Progress logging
            if (idx + 1) % 10000 == 0:
                progress_pct = ((idx + 1) / total_trades) * 100
                equity = self.trade_simulator.get_current_equity(self.market_state)
                pnl = equity - self.starting_capital
                
                logger.info(
                    f"Progress: {idx+1:,}/{total_trades:,} ({progress_pct:.1f}%) | "
                    f"Signals: {signals_found} | Trades: {trades_executed} | "
                    f"Equity: ${equity:,.2f} (${pnl:+,.2f})"
                )
        
        # Close any remaining open positions at market prices
        logger.info("Closing remaining open positions...")
        final_time = end_date
        for position in self.trade_simulator.positions[:]:
            if position.is_open:
                market = self.market_state.get_market(position.market_id)
                if market:
                    self.trade_simulator._close_position(
                        position,
                        exit_price=market.current_price,
                        exit_time=final_time,
                        reason='backtest_end'
                    )
        
        # Calculate performance
        logger.info("Calculating performance metrics...")
        
        analyzer = PerformanceAnalyzer(
            closed_positions=self.trade_simulator.closed_positions,
            starting_capital=self.starting_capital,
            start_date=start_date,
            end_date=end_date
        )
        
        metrics = analyzer.calculate_metrics()
        
        # Print summary
        self._print_summary(metrics)
        
        # Generate report
        if report_path:
            logger.info(f"Generating performance report: {report_path}")
            analyzer.generate_report(report_path)
        
        logger.info("=" * 80)
        logger.info("BACKTEST COMPLETE")
        logger.info("=" * 80)
        
        return metrics
    
    def _print_summary(self, metrics: dict):
        """Print backtest summary to console."""
        
        print("\n" + "=" * 80)
        print("BACKTEST SUMMARY")
        print("=" * 80)
        
        print(f"\n📊 Overall Performance:")
        print(f"  Total Trades:       {metrics['total_trades']}")
        print(f"  Win Rate:           {metrics['win_rate']*100:.1f}%")
        print(f"  Total P&L:          ${metrics['total_pnl']:,.2f}")
        print(f"  Total Return:       {metrics['total_return_pct']:+.1f}%")
        print(f"  Monthly ROI:        {metrics['monthly_roi']:.1f}%")
        print(f"  Sharpe Ratio:       {metrics['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown:       {metrics['max_drawdown_pct']:.1f}%")
        
        print(f"\n💰 Capital:")
        print(f"  Starting:           ${self.starting_capital:,.2f}")
        print(f"  Ending:             ${metrics['final_capital']:,.2f}")
        print(f"  Growth:             {metrics['total_return_pct']:+.1f}%")
        
        print(f"\n📈 Trade Metrics:")
        print(f"  Average Win:        ${metrics['avg_win']:,.2f} ({metrics['avg_win_pct']:+.1f}%)")
        print(f"  Average Loss:       ${metrics['avg_loss']:,.2f} ({metrics['avg_loss_pct']:+.1f}%)")
        print(f"  Profit Factor:      {metrics['profit_factor']:.2f}")
        print(f"  Avg Hold Time:      {metrics['avg_hold_hours']:.1f} hours")
        
        print(f"\n🎯 Signal Performance:")
        for signal_type, perf in sorted(
            metrics['signal_performance'].items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True
        ):
            status = "✅" if perf['win_rate'] >= 0.65 else "⚠️" if perf['win_rate'] >= 0.55 else "❌"
            print(
                f"  {signal_type:20s} {status} | "
                f"Count: {perf['count']:3d} | "
                f"Win Rate: {perf['win_rate']*100:5.1f}% | "
                f"P&L: ${perf['total_pnl']:+9,.2f}"
            )
        
        # Success criteria
        print(f"\n✅ Success Criteria:")
        print(f"  Win Rate ≥ 58%:     {'✅' if metrics['win_rate'] >= 0.58 else '❌'} ({metrics['win_rate']*100:.1f}%)")
        print(f"  Monthly ROI ≥ 120%: {'✅' if metrics['monthly_roi'] >= 120 else '❌'} ({metrics['monthly_roi']:.1f}%)")
        print(f"  Max DD ≤ 25%:       {'✅' if metrics['max_drawdown_pct'] <= 25 else '❌'} ({metrics['max_drawdown_pct']:.1f}%)")
        print(f"  Sharpe ≥ 2.0:       {'✅' if metrics['sharpe_ratio'] >= 2.0 else '❌'} ({metrics['sharpe_ratio']:.2f})")
        
        high_win_signals = sum(
            1 for perf in metrics['signal_performance'].values()
            if perf['win_rate'] >= 0.65
        )
        print(f"  ≥2 Signals @ 65%:   {'✅' if high_win_signals >= 2 else '❌'} ({high_win_signals}/5)")
        
        print("=" * 80 + "\n")


def main():
    """Main entry point for backtest runner."""
    
    parser = argparse.ArgumentParser(description='Run Polymarket insider bot backtest')
    
    parser.add_argument(
        '--start-date',
        type=str,
        default='2025-08-01',
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default='2026-02-01',
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--capital',
        type=float,
        default=5000,
        help='Starting capital in USDC'
    )
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.65,
        help='Minimum signal confidence threshold'
    )
    parser.add_argument(
        '--min-volume',
        type=float,
        default=10000,
        help='Minimum market volume threshold'
    )
    parser.add_argument(
        '--poly-data-path',
        type=str,
        default='../poly_data',
        help='Path to poly_data repository'
    )
    parser.add_argument(
        '--report',
        type=str,
        help='Path to save performance report'
    )
    
    args = parser.parse_args()
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    
    # Auto-generate report path if not specified
    if not args.report:
        days = (end_date - start_date).days
        report_name = f"backtest-{days}d-{start_date.strftime('%Y%m%d')}-to-{end_date.strftime('%Y%m%d')}.md"
        args.report = str(Path(__file__).parent.parent / 'reports' / report_name)
        
        # Create reports directory
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    
    # Run backtest
    runner = BacktestRunner(
        poly_data_path=args.poly_data_path,
        starting_capital=args.capital,
        min_confidence=args.min_confidence,
        min_market_volume=args.min_volume
    )
    
    metrics = runner.run(
        start_date=start_date,
        end_date=end_date,
        report_path=args.report
    )
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
