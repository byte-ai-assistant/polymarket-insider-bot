# Polymarket Bot Backtesting

This module provides comprehensive backtesting capabilities for validating the Polymarket insider trading bot strategy using historical data.

## Components

1. **DataLoader** - Loads historical Polymarket trade and market data from poly_data CSVs
2. **WalletTracker** - Tracks wallet trading history and metrics during replay
3. **MarketState** - Maintains current market state as trades are replayed
4. **SignalDetectors** - Runs all 5 signal detection algorithms
5. **TradeSimulator** - Simulates trade execution with position management
6. **PerformanceAnalyzer** - Calculates comprehensive performance metrics
7. **BacktestRunner** - Main orchestrator that ties everything together

## Setup Historical Data

### Option 1: Download Snapshot (Recommended - Fastest)

```bash
cd /Users/openclaw/.openclaw/workspace/poly_data

# Download complete historical data (~500MB compressed)
wget https://polydata-archive.s3.us-east-1.amazonaws.com/orderFilled_complete.csv.xz

# Extract it
unxz orderFilled_complete.csv.xz

# Move to correct location
mkdir -p goldsky
mv orderFilled_complete.csv goldsky/orderFilled.csv

# Update to latest
source .venv/bin/activate
python update_all.py
```

### Option 2: Build From Scratch (Slow - 2+ days)

```bash
cd /Users/openclaw/.openclaw/workspace/poly_data
source .venv/bin/activate
python update_all.py  # This will take 2+ days to fetch all historical data
```

## Installation

```bash
# Install dependencies
pip3 install --user numpy polars

# Or use project virtual environment
cd /Users/openclaw/.openclaw/workspace/polymarket-insider-bot
python3 -m venv venv
source venv/bin/activate
pip install numpy polars python-dateutil
```

## Running Backtests

### Quick Start (6-month backtest)

```bash
cd /Users/openclaw/.openclaw/workspace/polymarket-insider-bot
python -m backtesting.backtest_runner \
    --start-date 2025-08-01 \
    --end-date 2026-02-01 \
    --capital 5000 \
    --report reports/backtest-6mo.md
```

### 12-Month Backtest

```bash
python -m backtesting.backtest_runner \
    --start-date 2025-02-01 \
    --end-date 2026-02-01 \
    --capital 5000 \
    --report reports/backtest-12mo.md
```

### Full History Backtest

```bash
python -m backtesting.backtest_runner \
    --start-date 2023-01-01 \
    --end-date 2026-02-01 \
    --capital 5000 \
    --report reports/backtest-full.md
```

### Custom Parameters

```bash
python -m backtesting.backtest_runner \
    --start-date 2025-06-01 \
    --end-date 2026-02-01 \
    --capital 10000 \
    --min-confidence 0.70 \
    --min-volume 50000 \
    --poly-data-path ../poly_data \
    --report reports/backtest-custom.md
```

## Output

Backtest generates:
- Console summary with key metrics
- Detailed markdown report with:
  - Overall performance metrics
  - Win rate, ROI, Sharpe ratio, max drawdown
  - Per-signal performance breakdown
  - Exit reason analysis
  - Go/no-go recommendation

## Success Criteria

The bot meets success criteria if:
- ✅ Win rate ≥ 58%
- ✅ Monthly ROI ≥ 120%
- ✅ Max drawdown ≤ 25%
- ✅ Sharpe ratio ≥ 2.0
- ✅ At least 2 signals show ≥65% win rate

If 5/5 criteria met: **PROCEED** to live trading  
If 3-4/5 criteria met: **OPTIMIZE** parameters  
If <3/5 criteria met: **PIVOT** strategy

## Example Output

```
================================================================================
BACKTEST SUMMARY
================================================================================

📊 Overall Performance:
  Total Trades:       247
  Win Rate:           64.8%
  Total P&L:          $8,234.50
  Total Return:       +164.7%
  Monthly ROI:        164.7%
  Sharpe Ratio:       2.87
  Max Drawdown:       18.3%

💰 Capital:
  Starting:           $5,000.00
  Ending:             $13,234.50
  Growth:             +164.7%

📈 Trade Metrics:
  Average Win:        $127.45 (+31.2%)
  Average Loss:       -$68.20 (-17.1%)
  Profit Factor:      2.34
  Avg Hold Time:      28.3 hours

🎯 Signal Performance:
  fresh_account        ✅ | Count:  42 | Win Rate:  81.0% | P&L:  +$3,456.78
  proven_winner        ✅ | Count:  68 | Win Rate:  72.1% | P&L:  +$2,891.34
  perfect_timing       ✅ | Count:  31 | Win Rate:  67.7% | P&L:  +$1,678.23
  volume_spike         ⚠️ | Count:  89 | Win Rate:  58.4% | P&L:    +$892.45
  wallet_clustering    ⚠️ | Count:  17 | Win Rate:  52.9% | P&L:    -$684.30

✅ Success Criteria:
  Win Rate ≥ 58%:     ✅ (64.8%)
  Monthly ROI ≥ 120%: ✅ (164.7%)
  Max DD ≤ 25%:       ✅ (18.3%)
  Sharpe ≥ 2.0:       ✅ (2.87)
  ≥2 Signals @ 65%:   ✅ (3/5)
================================================================================
```

## Interpreting Results

### High-Performing Signals
- **fresh_account**: New wallets with large bets (highest confidence)
- **proven_winner**: High win rate wallets making large bets
- **perfect_timing**: Wallets with consistent early entry patterns

### Medium-Performing Signals
- **volume_spike**: 10x volume increases before news
- **wallet_clustering**: Multiple new wallets coordinating

### Optimization Tips

If underperforming:
1. Increase minimum confidence threshold (--min-confidence 0.70)
2. Focus on top-performing signal types only
3. Adjust position sizing (modify TradeSimulator parameters)
4. Tighten stop-loss / adjust take-profit levels
5. Filter by market volume (--min-volume 50000)

## Architecture

```
Historical Data (poly_data CSVs)
          ↓
    Data Loader
          ↓
  [Replay trades chronologically]
          ↓
    ┌─────────────┐
    │ Wallet      │
    │ Tracker     │ → Track wallet metrics
    └─────────────┘
          ↓
    ┌─────────────┐
    │ Market      │
    │ State       │ → Track market state
    └─────────────┘
          ↓
    ┌─────────────┐
    │ Signal      │
    │ Detectors   │ → Run all 5 algorithms
    └─────────────┘
          ↓
    ┌─────────────┐
    │ Trade       │
    │ Simulator   │ → Execute & manage positions
    └─────────────┘
          ↓
    ┌─────────────┐
    │ Performance │
    │ Analyzer    │ → Calculate metrics & reports
    └─────────────┘
```

## Signal Detection Algorithms

### 1. Fresh Account (85-95% confidence)
- Account < 7 days old
- Large bet ($10K+)
- < 3 total trades
- Market closes within 48h

### 2. Proven Winner (70-80% confidence)
- Win rate > 70%
- 20+ historical trades
- Bet > 3x average size
- $50K+ total profit

### 3. Volume Spike (60-75% confidence)
- 10x+ hourly volume spike
- < 5% price change
- $5K+ minimum volume

### 4. Wallet Clustering (55-70% confidence)
- 3+ new wallets
- Same direction
- $25K+ combined volume
- Within 24 hours

### 5. Perfect Timing (70-85% confidence)
- High recent win streak
- Larger than average bet
- 70%+ overall win rate
- Consistent early entries

## Next Steps

1. ✅ Complete backtesting modules (DONE)
2. ⏳ Download historical data
3. ⏳ Run 6-month, 12-month, and full history backtests
4. ⏳ Analyze results and optimize parameters
5. ⏳ Generate final go/no-go recommendation
6. ⏳ If successful: Deploy to paper trading
7. ⏳ If successful: Start live trading with small capital

## Troubleshooting

### "poly_data path does not exist"
- Run from correct directory
- Set `--poly-data-path` to correct location

### "Markets file not found"
- Download and setup poly_data first (see Setup section)

### "No module named 'polars'"
- Install dependencies: `pip3 install --user numpy polars`

### Out of memory
- Reduce date range
- Increase `--min-volume` to filter markets
- Process in smaller chunks

## Performance Notes

- **Memory usage**: ~2-4GB for full history
- **Processing time**: ~10-30 minutes for 6 months
- **Disk space**: ~1GB for complete poly_data

---

**Status:** ✅ Framework complete, ready for data and testing
**Last Updated:** Feb 18, 2026
