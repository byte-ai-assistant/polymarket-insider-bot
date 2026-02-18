"""
Performance Analyzer - Calculate win rate, ROI, Sharpe ratio, max drawdown, per-signal metrics.
"""

from datetime import datetime, timedelta
from typing import Dict, List
import numpy as np
import logging

from .trade_simulator import Position, TradeSimulator

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """
    Analyzes backtesting performance with comprehensive metrics.
    
    Metrics calculated:
    - Win rate (overall and per signal type)
    - Total return and ROI
    - Monthly ROI (annualized)
    - Sharpe ratio
    - Maximum drawdown
    - Average trade metrics
    - Per-signal performance breakdown
    - Time-based analysis
    """
    
    def __init__(
        self,
        closed_positions: List[Position],
        starting_capital: float,
        start_date: datetime,
        end_date: datetime
    ):
        """
        Initialize performance analyzer.
        
        Args:
            closed_positions: List of closed positions
            starting_capital: Initial capital
            start_date: Backtest start date
            end_date: Backtest end date
        """
        self.positions = closed_positions
        self.starting_capital = starting_capital
        self.start_date = start_date
        self.end_date = end_date
        
        logger.info(
            f"PerformanceAnalyzer initialized with {len(closed_positions)} trades "
            f"from {start_date.date()} to {end_date.date()}"
        )
    
    def calculate_metrics(self) -> Dict:
        """Calculate all performance metrics."""
        
        if not self.positions:
            return self._empty_metrics()
        
        # Overall metrics
        total_trades = len(self.positions)
        wins = [p for p in self.positions if p.pnl > 0]
        losses = [p for p in self.positions if p.pnl <= 0]
        
        win_rate = len(wins) / total_trades
        
        # P&L metrics
        total_pnl = sum(p.pnl for p in self.positions)
        total_return_pct = (total_pnl / self.starting_capital) * 100
        
        # Time-based metrics
        days_traded = (self.end_date - self.start_date).days
        months_traded = days_traded / 30.44
        
        if months_traded > 0:
            monthly_roi = total_return_pct / months_traded
        else:
            monthly_roi = 0
        
        # Sharpe ratio
        sharpe = self._calculate_sharpe_ratio()
        
        # Max drawdown
        max_drawdown_pct = self._calculate_max_drawdown()
        
        # Trade metrics
        avg_win = np.mean([p.pnl for p in wins]) if wins else 0
        avg_loss = np.mean([p.pnl for p in losses]) if losses else 0
        largest_win = max((p.pnl for p in wins), default=0)
        largest_loss = min((p.pnl for p in losses), default=0)
        
        avg_win_pct = np.mean([p.pnl_pct for p in wins]) if wins else 0
        avg_loss_pct = np.mean([p.pnl_pct for p in losses]) if losses else 0
        
        # Profit factor
        gross_profit = sum(p.pnl for p in wins)
        gross_loss = abs(sum(p.pnl for p in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Average hold time
        hold_times = [
            (p.exit_time - p.entry_time).total_seconds() / 3600
            for p in self.positions if p.exit_time
        ]
        avg_hold_hours = np.mean(hold_times) if hold_times else 0
        
        # Signal type breakdown
        signal_performance = self._calculate_signal_performance()
        
        # Exit reason breakdown
        exit_reasons = self._calculate_exit_reasons()
        
        return {
            # Overall
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            
            # Returns
            'total_pnl': total_pnl,
            'total_return_pct': total_return_pct,
            'monthly_roi': monthly_roi,
            'final_capital': self.starting_capital + total_pnl,
            
            # Risk metrics
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_drawdown_pct,
            
            # Trade metrics
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_win_pct': avg_win_pct,
            'avg_loss_pct': avg_loss_pct,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'profit_factor': profit_factor,
            'avg_hold_hours': avg_hold_hours,
            
            # Breakdowns
            'signal_performance': signal_performance,
            'exit_reasons': exit_reasons,
            
            # Time period
            'days_traded': days_traded,
            'months_traded': months_traded,
            'start_date': self.start_date,
            'end_date': self.end_date
        }
    
    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio (annualized)."""
        if not self.positions:
            return 0
        
        # Calculate daily returns
        returns = [p.pnl / p.size for p in self.positions]
        
        if len(returns) < 2:
            return 0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0
        
        # Annualize assuming ~250 trading days
        sharpe = (mean_return / std_return) * np.sqrt(250)
        
        return sharpe
    
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage."""
        if not self.positions:
            return 0
        
        # Build equity curve
        equity = self.starting_capital
        equity_curve = [equity]
        
        for position in sorted(self.positions, key=lambda p: p.exit_time):
            equity += position.pnl
            equity_curve.append(equity)
        
        # Calculate running maximum
        running_max = np.maximum.accumulate(equity_curve)
        
        # Calculate drawdown
        drawdown = (np.array(equity_curve) - running_max) / running_max * 100
        
        max_drawdown = np.min(drawdown)
        
        return abs(max_drawdown)
    
    def _calculate_signal_performance(self) -> Dict:
        """Calculate performance breakdown by signal type."""
        signal_types = set(p.signal.signal_type for p in self.positions)
        
        performance = {}
        
        for signal_type in signal_types:
            type_positions = [p for p in self.positions if p.signal.signal_type == signal_type]
            
            if not type_positions:
                continue
            
            wins = [p for p in type_positions if p.pnl > 0]
            
            performance[signal_type] = {
                'count': len(type_positions),
                'win_rate': len(wins) / len(type_positions),
                'total_pnl': sum(p.pnl for p in type_positions),
                'avg_pnl': np.mean([p.pnl for p in type_positions]),
                'avg_pnl_pct': np.mean([p.pnl_pct for p in type_positions]),
                'avg_confidence': np.mean([p.signal.confidence for p in type_positions]),
                'largest_win': max((p.pnl for p in wins), default=0),
                'largest_loss': min((p.pnl for p in type_positions), default=0)
            }
        
        return performance
    
    def _calculate_exit_reasons(self) -> Dict:
        """Calculate breakdown of exit reasons."""
        exit_counts = {}
        
        for position in self.positions:
            reason = position.exit_reason or 'unknown'
            exit_counts[reason] = exit_counts.get(reason, 0) + 1
        
        return exit_counts
    
    def _empty_metrics(self) -> Dict:
        """Return empty metrics when no trades."""
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'total_return_pct': 0,
            'monthly_roi': 0,
            'final_capital': self.starting_capital,
            'sharpe_ratio': 0,
            'max_drawdown_pct': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'avg_win_pct': 0,
            'avg_loss_pct': 0,
            'largest_win': 0,
            'largest_loss': 0,
            'profit_factor': 0,
            'avg_hold_hours': 0,
            'signal_performance': {},
            'exit_reasons': {},
            'days_traded': (self.end_date - self.start_date).days,
            'months_traded': (self.end_date - self.start_date).days / 30.44,
            'start_date': self.start_date,
            'end_date': self.end_date
        }
    
    def generate_report(self, output_path: str):
        """
        Generate detailed performance report as markdown.
        
        Args:
            output_path: Path to save report
        """
        metrics = self.calculate_metrics()
        
        # Success criteria
        meets_win_rate = metrics['win_rate'] >= 0.58
        meets_roi = metrics['monthly_roi'] >= 120
        meets_drawdown = metrics['max_drawdown_pct'] <= 25
        meets_sharpe = metrics['sharpe_ratio'] >= 2.0
        
        # Count high-performing signals
        high_performing_signals = sum(
            1 for perf in metrics['signal_performance'].values()
            if perf['win_rate'] >= 0.65
        )
        meets_signal_criteria = high_performing_signals >= 2
        
        # Overall assessment
        criteria_met = sum([
            meets_win_rate,
            meets_roi,
            meets_drawdown,
            meets_sharpe,
            meets_signal_criteria
        ])
        
        if criteria_met >= 5:
            recommendation = "✅ **PROCEED** to live trading"
            assessment = "All success criteria met"
        elif criteria_met >= 3:
            recommendation = "⚠️ **OPTIMIZE** before live trading"
            assessment = "Some criteria met, needs improvement"
        else:
            recommendation = "❌ **PIVOT** strategy"
            assessment = "Strategy underperforms, major changes needed"
        
        # Generate report
        report = f"""# Polymarket Insider Bot - Backtest Results

**Period:** {metrics['start_date'].strftime('%Y-%m-%d')} to {metrics['end_date'].strftime('%Y-%m-%d')}  
**Duration:** {metrics['days_traded']} days ({metrics['months_traded']:.1f} months)  
**Starting Capital:** ${self.starting_capital:,.2f}  
**Final Capital:** ${metrics['final_capital']:,.2f}

---

## 🎯 Overall Performance

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Win Rate** | {metrics['win_rate']*100:.1f}% | ≥58% | {"✅" if meets_win_rate else "❌"} |
| **Monthly ROI** | {metrics['monthly_roi']:.1f}% | ≥120% | {"✅" if meets_roi else "❌"} |
| **Max Drawdown** | {metrics['max_drawdown_pct']:.1f}% | ≤25% | {"✅" if meets_drawdown else "❌"} |
| **Sharpe Ratio** | {metrics['sharpe_ratio']:.2f} | ≥2.0 | {"✅" if meets_sharpe else "❌"} |
| **High-Win Signals** | {high_performing_signals}/5 | ≥2 | {"✅" if meets_signal_criteria else "❌"} |

### Summary Statistics
- **Total Trades:** {metrics['total_trades']}
- **Winning Trades:** {metrics['wins']} ({metrics['wins']/metrics['total_trades']*100:.1f}%)
- **Losing Trades:** {metrics['losses']} ({metrics['losses']/metrics['total_trades']*100:.1f}%)
- **Total P&L:** ${metrics['total_pnl']:,.2f}
- **Total Return:** {metrics['total_return_pct']:+.1f}%
- **Profit Factor:** {metrics['profit_factor']:.2f}

### Trade Metrics
- **Average Win:** ${metrics['avg_win']:,.2f} ({metrics['avg_win_pct']:+.1f}%)
- **Average Loss:** ${metrics['avg_loss']:,.2f} ({metrics['avg_loss_pct']:+.1f}%)
- **Largest Win:** ${metrics['largest_win']:,.2f}
- **Largest Loss:** ${metrics['largest_loss']:,.2f}
- **Average Hold Time:** {metrics['avg_hold_hours']:.1f} hours

---

## 📊 Signal Performance Breakdown

"""
        
        # Add signal performance table
        for signal_type, perf in sorted(
            metrics['signal_performance'].items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True
        ):
            status = "✅" if perf['win_rate'] >= 0.65 else "⚠️" if perf['win_rate'] >= 0.55 else "❌"
            
            report += f"""### {signal_type.replace('_', ' ').title()} {status}

- **Trades:** {perf['count']}
- **Win Rate:** {perf['win_rate']*100:.1f}%
- **Avg Confidence:** {perf['avg_confidence']*100:.1f}%
- **Total P&L:** ${perf['total_pnl']:,.2f}
- **Avg P&L per Trade:** ${perf['avg_pnl']:,.2f} ({perf['avg_pnl_pct']:+.1f}%)
- **Largest Win:** ${perf['largest_win']:,.2f}
- **Largest Loss:** ${perf['largest_loss']:,.2f}

"""
        
        # Exit reasons
        report += """---

## 🚪 Exit Reasons

"""
        for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: x[1], reverse=True):
            pct = count / metrics['total_trades'] * 100
            report += f"- **{reason.replace('_', ' ').title()}:** {count} ({pct:.1f}%)\n"
        
        # Recommendation
        report += f"""
---

## 🎯 Recommendation

{recommendation}

**Assessment:** {assessment}

**Criteria Met:** {criteria_met}/5

"""
        
        if criteria_met >= 5:
            report += """
### Next Steps:
1. ✅ Deploy bot to paper trading for 7 days
2. ✅ Monitor performance matches backtest expectations
3. ✅ Start live trading with $500-1000 initial capital
4. ✅ Scale up gradually based on live performance
"""
        elif criteria_met >= 3:
            report += """
### Next Steps:
1. ⚠️ Identify underperforming signal types
2. ⚠️ Adjust confidence thresholds and position sizing
3. ⚠️ Re-run backtest with optimized parameters
4. ⚠️ Consider removing weakest signal types
"""
        else:
            report += """
### Next Steps:
1. ❌ Review signal detection logic for flaws
2. ❌ Consider alternative data sources or indicators
3. ❌ Test on different market categories
4. ❌ May need fundamental strategy pivot
"""
        
        report += f"""
---

## 📈 Capital Growth

- **Starting:** ${self.starting_capital:,.2f}
- **Ending:** ${metrics['final_capital']:,.2f}
- **Growth:** {metrics['total_return_pct']:+.1f}%
- **CAGR:** {(metrics['total_return_pct'] / metrics['months_traded'] * 12):.1f}%

---

*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        
        # Write report
        with open(output_path, 'w') as f:
            f.write(report)
        
        logger.info(f"Performance report saved to {output_path}")
        
        return metrics
