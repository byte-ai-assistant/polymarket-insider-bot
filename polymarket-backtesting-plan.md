# Polymarket Bot Backtesting Plan

## Executive Summary

Before deploying the Polymarket insider signal bot with real money, we'll validate all 5 signal detection algorithms using historical trade data. This will calculate actual win rates, ROI, and risk metrics to confirm the strategy works.

**Timeline:** 2-3 days to build and run backtests  
**Data Coverage:** 2+ years of complete Polymarket trade history  
**Goal:** Validate 60-65% win rate and 160-200% monthly ROI targets

---

## Data Sources

### 1. poly_data Repository (Primary Source)
**GitHub:** https://github.com/warproxxx/poly_data

**What it provides:**
- Complete historical trade data from Polymarket's Goldsky subgraph
- Wallet-level trades (maker, taker, amounts, prices, timestamps)
- Market metadata (questions, outcomes, tokens, volume)
- CSV format ready for analysis

**Quick Start:**
```bash
# Clone repo
git clone https://github.com/warproxxx/poly_data.git
cd poly_data

# Download data snapshot (saves 2+ days of scraping)
wget https://polydata-archive.s3.us-east-1.amazonaws.com/orderFilled_complete.csv.xz
unxz orderFilled_complete.csv.xz

# Install dependencies
pip install uv
uv sync

# Update to latest data
uv run python update_all.py
```

**Data Files:**
- `markets.csv` - Market metadata (10MB+)
- `goldsky/orderFilled.csv` - Raw trade events (500MB+)
- `processed/trades.csv` - Structured trades with prices (300MB+)

### 2. Polymarket CLOB API (Price History)
**Endpoint:** `GET https://clob.polymarket.com/prices-history`

**Use for:**
- Historical price charts for each market
- Validating price movements after insider trades
- Calculating profit/loss on positions

**Example:**
```bash
curl "https://clob.polymarket.com/prices-history?market=TOKEN_ID&interval=1d&fidelity=60"
```

### 3. Polymarket Subgraph (GraphQL)
**GitHub:** https://github.com/Polymarket/polymarket-subgraph

**Schema includes:**
- `OrderFilledEvent` - Individual trades with maker/taker
- `Orderbook` - Volume metrics per token
- `OrdersMatchedGlobal` - Global trading statistics

**Use for:** Real-time validation during live testing phase

---

## Backtesting Framework Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Historical Data Loader                                       │
│ - Load trades.csv (300MB)                                   │
│ - Load markets.csv                                          │
│ - Filter date range (last 12-24 months)                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Signal Detection Engine (Backtester)                        │
│ - Process trades chronologically                            │
│ - Run all 5 signal algorithms in parallel                   │
│ - Track wallet history, market state, volume                │
│ - Generate trade signals with confidence scores             │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Trade Simulator                                             │
│ - Execute "follow trades" based on signals                  │
│ - Track position entry/exit                                 │
│ - Calculate P&L using actual historical prices              │
│ - Apply fees, slippage, position sizing                     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Performance Analytics                                        │
│ - Win rate per signal type                                  │
│ - ROI, Sharpe ratio, max drawdown                           │
│ - Signal accuracy vs confidence score                       │
│ - Trade timing analysis                                     │
│ - Generate performance report                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. Wallet Tracker
Tracks every wallet's trading history in real-time as we replay trades:
- Account age (first trade timestamp)
- Total trades count
- Win rate (positions that resolved profitable)
- Average bet size
- Total profit/loss
- Trading patterns (timing, frequency, market selection)

#### 2. Market State Tracker
Maintains current state of each market:
- Current price (bid/ask)
- Total volume (cumulative)
- Recent volume (hourly/daily windows)
- Active positions (who's holding what)
- Time to resolution

#### 3. Signal Detectors (5 Algorithms)

**Signal #1: Fresh Account Detector**
```python
def detect_fresh_account_signal(trade, wallet_history, market_state):
    account_age_hours = (trade.timestamp - wallet_history[trade.maker].first_trade).total_hours()
    
    if (
        account_age_hours < 168 and  # < 7 days
        trade.usd_amount > 10000 and
        wallet_history[trade.maker].total_trades < 3 and
        market_state[trade.market_id].hours_until_resolution < 48
    ):
        return Signal(
            type='fresh_account',
            confidence=0.95,
            wallet=trade.maker,
            market=trade.market_id,
            side=trade.maker_direction,
            entry_price=trade.price,
            position_size=calculate_position_size(0.95)
        )
    return None
```

**Signal #2: Proven Winner Detector**
```python
def detect_proven_winner_signal(trade, wallet_history, market_state):
    wallet = wallet_history[trade.maker]
    
    if (
        wallet.win_rate > 0.70 and
        wallet.total_trades > 20 and
        trade.usd_amount > (3 * wallet.avg_bet_size) and
        wallet.total_profit > 50000
    ):
        return Signal(
            type='proven_winner',
            confidence=0.75,
            wallet=trade.maker,
            market=trade.market_id,
            side=trade.maker_direction,
            entry_price=trade.price,
            position_size=calculate_position_size(0.75)
        )
    return None
```

**Signal #3: Volume Spike Detector**
```python
def detect_volume_spike_signal(trade, market_state):
    market = market_state[trade.market_id]
    current_hour_volume = market.get_hourly_volume(trade.timestamp)
    avg_hourly_volume = market.get_avg_hourly_volume(lookback_hours=24)
    
    if (
        current_hour_volume > (10 * avg_hourly_volume) and
        abs(market.price_change_1h) < 0.05 and  # < 5% price change
        current_hour_volume > 5000  # Minimum absolute volume
    ):
        return Signal(
            type='volume_spike',
            confidence=0.65,
            market=trade.market_id,
            side=trade.maker_direction,  # Follow the flow
            entry_price=trade.price,
            position_size=calculate_position_size(0.65)
        )
    return None
```

**Signal #4: Wallet Clustering Detector**
```python
def detect_wallet_clustering_signal(trade, recent_trades, wallet_history):
    # Find similar trades in last 24 hours
    similar_trades = [
        t for t in recent_trades
        if (
            t.market_id == trade.market_id and
            t.maker_direction == trade.maker_direction and
            (trade.timestamp - t.timestamp).total_hours() < 24
        )
    ]
    
    # Check if wallets are "new" (suspicious)
    new_wallet_count = sum(
        1 for t in similar_trades 
        if wallet_history[t.maker].account_age_days < 30
    )
    
    combined_volume = sum(t.usd_amount for t in similar_trades)
    
    if (
        len(similar_trades) >= 3 and
        new_wallet_count >= 2 and
        combined_volume > 25000
    ):
        return Signal(
            type='wallet_clustering',
            confidence=0.65,
            market=trade.market_id,
            side=trade.maker_direction,
            entry_price=trade.price,
            position_size=calculate_position_size(0.65)
        )
    return None
```

**Signal #5: Perfect Timing Detector**
```python
def detect_perfect_timing_signal(trade, wallet_history, market_history):
    wallet = wallet_history[trade.maker]
    
    # Check last 5 trades for early entry pattern
    last_5_trades = wallet.get_last_n_trades(5)
    
    if len(last_5_trades) < 5:
        return None
    
    # Calculate average hours before significant price move
    early_entry_count = 0
    for past_trade in last_5_trades:
        hours_before_move = calculate_hours_before_10pct_move(
            past_trade, market_history[past_trade.market_id]
        )
        if 6 <= hours_before_move <= 24:
            early_entry_count += 1
    
    # Check win rate
    recent_wins = sum(1 for t in last_5_trades if t.outcome == 'win')
    
    if (
        early_entry_count >= 4 and  # 4/5 trades had perfect timing
        recent_wins >= 4 and  # 4/5 wins
        trade.usd_amount > wallet.avg_bet_size
    ):
        return Signal(
            type='perfect_timing',
            confidence=0.80,
            wallet=trade.maker,
            market=trade.market_id,
            side=trade.maker_direction,
            entry_price=trade.price,
            position_size=calculate_position_size(0.80)
        )
    return None
```

#### 4. Trade Simulator

```python
class TradeSimulator:
    def __init__(self, starting_capital=5000):
        self.capital = starting_capital
        self.positions = []  # Open positions
        self.trade_history = []  # Closed positions
        self.max_concurrent_positions = 5
        
    def execute_signal(self, signal, market_state):
        # Check if we have capacity
        if len(self.positions) >= self.max_concurrent_positions:
            return False
            
        # Calculate position size (Kelly Criterion with 0.25 fractional)
        position_size = self.capital * signal.position_size * 0.25
        position_size = min(position_size, self.capital * 0.10)  # Max 10% per trade
        
        # Apply entry slippage (0.1-0.3%)
        entry_price = signal.entry_price * (1 + random.uniform(0.001, 0.003))
        
        # Create position
        position = Position(
            signal=signal,
            entry_time=market_state.current_time,
            entry_price=entry_price,
            size=position_size,
            shares=position_size / entry_price
        )
        
        self.positions.append(position)
        self.capital -= position_size
        
        return True
    
    def check_exits(self, market_state):
        for position in self.positions[:]:
            market = market_state[position.market_id]
            
            # Exit condition 1: Market resolved
            if market.is_resolved:
                pnl = self.settle_position(position, market.resolution_price)
                self.positions.remove(position)
                self.trade_history.append(position)
                continue
            
            # Exit condition 2: Stop loss (15% loss)
            current_price = market.current_price
            pnl_pct = (current_price - position.entry_price) / position.entry_price
            if position.side == 'SELL':
                pnl_pct = -pnl_pct
                
            if pnl_pct < -0.15:
                pnl = self.exit_position(position, current_price)
                self.positions.remove(position)
                self.trade_history.append(position)
                continue
            
            # Exit condition 3: Time decay (if market close imminent, no movement)
            hours_until_close = (market.close_time - market_state.current_time).total_hours()
            if hours_until_close < 6 and pnl_pct < 0.05:
                pnl = self.exit_position(position, current_price)
                self.positions.remove(position)
                self.trade_history.append(position)
                continue
    
    def settle_position(self, position, resolution_price):
        # Calculate final P&L
        if position.side == 'BUY':
            pnl = position.shares * resolution_price - position.size
        else:  # SELL
            pnl = position.size - position.shares * resolution_price
        
        # Apply exit fee (2%)
        pnl -= position.size * 0.02
        
        self.capital += position.size + pnl
        position.pnl = pnl
        position.exit_price = resolution_price
        position.exit_time = position.market.resolution_time
        
        return pnl
    
    def exit_position(self, position, exit_price):
        # Similar to settle but with current price + slippage
        exit_price = exit_price * (1 - random.uniform(0.001, 0.003))
        
        if position.side == 'BUY':
            pnl = position.shares * exit_price - position.size
        else:
            pnl = position.size - position.shares * exit_price
        
        pnl -= position.size * 0.02
        
        self.capital += position.size + pnl
        position.pnl = pnl
        position.exit_price = exit_price
        position.exit_time = self.current_time
        
        return pnl
```

#### 5. Performance Analyzer

```python
class PerformanceAnalyzer:
    def __init__(self, trade_history, starting_capital):
        self.trades = trade_history
        self.starting_capital = starting_capital
    
    def calculate_metrics(self):
        # Win rate
        wins = [t for t in self.trades if t.pnl > 0]
        win_rate = len(wins) / len(self.trades)
        
        # Total return
        total_pnl = sum(t.pnl for t in self.trades)
        total_return_pct = (total_pnl / self.starting_capital) * 100
        
        # Monthly ROI (annualized)
        days_traded = (self.trades[-1].exit_time - self.trades[0].entry_time).days
        monthly_roi = (total_return_pct / days_traded) * 30
        
        # Sharpe ratio
        returns = [t.pnl / t.size for t in self.trades]
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
        
        # Max drawdown
        cumulative_returns = np.cumsum([t.pnl for t in self.trades])
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / self.starting_capital
        max_drawdown = np.min(drawdown) * 100
        
        # Average trade metrics
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        losses = [t for t in self.trades if t.pnl <= 0]
        avg_loss = np.mean([t.pnl for t in losses]) if losses else 0
        
        # Signal type breakdown
        signal_performance = {}
        for signal_type in ['fresh_account', 'proven_winner', 'volume_spike', 'wallet_clustering', 'perfect_timing']:
            type_trades = [t for t in self.trades if t.signal.type == signal_type]
            if type_trades:
                signal_performance[signal_type] = {
                    'count': len(type_trades),
                    'win_rate': len([t for t in type_trades if t.pnl > 0]) / len(type_trades),
                    'total_pnl': sum(t.pnl for t in type_trades),
                    'avg_pnl': np.mean([t.pnl for t in type_trades])
                }
        
        return {
            'total_trades': len(self.trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': total_return_pct,
            'monthly_roi': monthly_roi,
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_drawdown,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'signal_performance': signal_performance
        }
    
    def generate_report(self, output_path):
        metrics = self.calculate_metrics()
        
        report = f"""
# Polymarket Insider Bot - Backtest Results

## Overall Performance

- **Total Trades:** {metrics['total_trades']}
- **Win Rate:** {metrics['win_rate']:.1%}
- **Total P&L:** ${metrics['total_pnl']:,.2f}
- **Total Return:** {metrics['total_return_pct']:.1%}
- **Monthly ROI:** {metrics['monthly_roi']:.1%}
- **Sharpe Ratio:** {metrics['sharpe_ratio']:.2f}
- **Max Drawdown:** {metrics['max_drawdown_pct']:.1%}
- **Average Win:** ${metrics['avg_win']:,.2f}
- **Average Loss:** ${metrics['avg_loss']:,.2f}

## Signal Performance Breakdown

"""
        for signal_type, perf in metrics['signal_performance'].items():
            report += f"""
### {signal_type.replace('_', ' ').title()}
- Trades: {perf['count']}
- Win Rate: {perf['win_rate']:.1%}
- Total P&L: ${perf['total_pnl']:,.2f}
- Avg P&L per trade: ${perf['avg_pnl']:,.2f}

"""
        
        with open(output_path, 'w') as f:
            f.write(report)
        
        return metrics
```

---

## Implementation Steps

### Phase 1: Setup (2 hours)

1. **Clone and setup poly_data**
```bash
cd /Users/openclaw/.openclaw/workspace/
git clone https://github.com/warproxxx/poly_data.git
cd poly_data

# Download snapshot
wget https://polydata-archive.s3.us-east-1.amazonaws.com/orderFilled_complete.csv.xz
unxz orderFilled_complete.csv.xz
mv orderFilled_complete.csv goldsky/orderFilled.csv

# Install dependencies
pip install uv
uv sync
```

2. **Update to latest data**
```bash
uv run python update_all.py
```
This will:
- Fetch latest markets
- Update trades from Goldsky
- Process into structured format

### Phase 2: Build Backtester (6-8 hours)

1. **Create backtesting framework**
```bash
cd /Users/openclaw/.openclaw/workspace/polymarket-insider-bot/
mkdir backtesting
cd backtesting
```

2. **Implement core modules**
- `data_loader.py` - Load and prepare poly_data CSV files
- `wallet_tracker.py` - Track wallet history and metrics
- `market_state.py` - Maintain market state during replay
- `signal_detectors.py` - All 5 signal detection algorithms
- `trade_simulator.py` - Position management and P&L
- `performance_analyzer.py` - Metrics and reporting
- `backtest_runner.py` - Main orchestrator

3. **Write unit tests**
- Test each signal detector independently
- Validate trade simulator logic
- Verify performance calculations

### Phase 3: Run Backtests (4-6 hours)

1. **Initial run: Last 6 months**
```bash
python backtest_runner.py --start-date 2025-08-01 --end-date 2026-02-01 --capital 5000
```

2. **Extended run: Last 12 months**
```bash
python backtest_runner.py --start-date 2025-02-01 --end-date 2026-02-01 --capital 5000
```

3. **Full run: All available data (2+ years)**
```bash
python backtest_runner.py --start-date 2023-01-01 --end-date 2026-02-01 --capital 5000
```

### Phase 4: Analysis & Optimization (4-6 hours)

1. **Review signal performance**
- Which signals have highest win rate?
- Which signals generate most profit?
- Are confidence scores accurate?

2. **Optimize parameters**
- Adjust confidence thresholds
- Tune position sizing
- Refine stop-loss levels
- Test different timeframes

3. **Scenario testing**
- Bull vs bear markets
- High vs low volatility periods
- Different market categories (politics, crypto, sports)

4. **Generate final report**
```bash
python backtest_runner.py --final-run --report-path ../reports/backtest-final-report.md
```

---

## Expected Results

### Baseline Targets (Conservative)
- **Win Rate:** 60-65%
- **Monthly ROI:** 160-200% (on $5K = $8-10K/month profit)
- **Sharpe Ratio:** 2.5-3.5
- **Max Drawdown:** 15-20%
- **Average Trade Duration:** 2-7 days

### Signal Performance Predictions

**Signal #1: Fresh Account (85-95% confidence)**
- Expected win rate: 75-85%
- Highest accuracy, lower frequency
- Most profitable per trade

**Signal #2: Proven Winner (70-80% confidence)**
- Expected win rate: 65-75%
- Medium frequency
- Consistent returns

**Signal #3: Volume Spike (60-75% confidence)**
- Expected win rate: 55-65%
- High frequency
- Lower per-trade profit, higher volume

**Signal #4: Wallet Clustering (55-70% confidence)**
- Expected win rate: 50-60%
- Medium-low frequency
- Moderate risk

**Signal #5: Perfect Timing (70-85% confidence)**
- Expected win rate: 70-80%
- Low frequency (rare pattern)
- High per-trade profit

---

## Success Criteria

**✅ Proceed to live testing if:**
1. Overall win rate ≥ 58%
2. Monthly ROI ≥ 120%
3. Max drawdown ≤ 25%
4. Sharpe ratio ≥ 2.0
5. At least 2 signal types show ≥65% win rate

**⚠️ Needs optimization if:**
1. Win rate 50-57%
2. Monthly ROI 80-119%
3. Max drawdown 25-35%

**❌ Back to drawing board if:**
1. Win rate < 50%
2. Monthly ROI < 80%
3. Max drawdown > 35%
4. Sharpe ratio < 1.5

---

## Risk Considerations

### Data Quality Issues
- **Missing trades:** Some early trades might not be captured
- **Resolution data:** Need to validate market outcomes
- **Timestamp accuracy:** Ensure chronological ordering

**Mitigation:** Validate against multiple sources, spot-check random samples

### Overfitting Risk
- Backtests can overfit to historical patterns
- Real markets may behave differently

**Mitigation:** 
- Test on multiple time periods
- Use walk-forward validation
- Keep strategy simple
- Start with small capital

### Execution Differences
- Backtests assume instant fills
- Real trading has slippage, latency, partial fills

**Mitigation:**
- Add conservative slippage estimates (0.1-0.3%)
- Factor in execution delays (5-10 seconds)
- Test with realistic position sizes

---

## Next Steps After Backtesting

1. **If results meet criteria:**
   - Deploy bot to testnet/paper trading
   - Monitor for 1 week with no real funds
   - Start live trading with $500-1000 (10-20% of target capital)
   - Scale up gradually based on performance

2. **Document findings:**
   - Save detailed backtest report
   - Update implementation plan with learnings
   - Refine signal detection algorithms
   - Set live trading risk parameters

3. **Continuous monitoring:**
   - Compare live results to backtest predictions
   - Track signal accuracy in real-time
   - Adjust parameters based on market changes

---

## File Structure

```
polymarket-insider-bot/
├── backtesting/
│   ├── __init__.py
│   ├── data_loader.py           # Load poly_data CSVs
│   ├── wallet_tracker.py         # Track wallet metrics
│   ├── market_state.py           # Market state management
│   ├── signal_detectors.py       # 5 signal algorithms
│   ├── trade_simulator.py        # Position & P&L simulator
│   ├── performance_analyzer.py   # Metrics calculator
│   ├── backtest_runner.py        # Main orchestrator
│   └── tests/
│       ├── test_signals.py
│       ├── test_simulator.py
│       └── test_performance.py
├── reports/
│   ├── backtest-6m-report.md
│   ├── backtest-12m-report.md
│   └── backtest-final-report.md
└── data/
    └── poly_data/ (submodule or clone)
        ├── markets.csv
        ├── goldsky/orderFilled.csv
        └── processed/trades.csv
```

---

## Timeline

**Day 1 (8 hours):**
- Morning: Setup poly_data, download snapshot, update to latest
- Afternoon: Build data_loader, wallet_tracker, market_state

**Day 2 (8 hours):**
- Morning: Implement all 5 signal detectors
- Afternoon: Build trade_simulator, performance_analyzer

**Day 3 (8 hours):**
- Morning: Write backtest_runner, run initial tests
- Afternoon: Run full backtests, analyze results, generate report

**Total:** 24 hours of focused development + compute time for backtests

---

## Conclusion

Backtesting will validate whether the insider signal detection strategy actually works before risking real money. Using 2+ years of complete Polymarket trade data, we can simulate the bot's performance with high accuracy and identify which signals are most profitable.

If backtests confirm 60%+ win rates and 160-200% monthly ROI, we proceed to paper trading, then live deployment with small capital. If not, we iterate on the signals or pivot strategy.

**Let's build it. 🚀**
