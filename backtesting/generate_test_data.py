"""
Generate synthetic test data for backtesting framework validation.

This creates a small dataset with realistic trading patterns to test the backtesting
framework without requiring the full historical data download.
"""

import polars as pl
from datetime import datetime, timedelta
import random
import numpy as np
from pathlib import Path

def generate_test_markets(n_markets=100):
    """Generate test market data."""
    markets = []
    
    for i in range(n_markets):
        created_at = datetime(2025, 1, 1) + timedelta(days=random.randint(0, 300))
        closed_time = created_at + timedelta(days=random.randint(1, 30))
        volume = random.uniform(10000, 1000000)
        
        markets.append({
            'id': i,
            'question': f'Test Market {i}',
            'answer1': 'YES',
            'answer2': 'NO',
            'neg_risk': False,
            'market_slug': f'test-market-{i}',
            'token1': f'TOKEN1-{i}',
            'token2': f'TOKEN2-{i}',
            'condition_id': f'COND-{i}',
            'volume': volume,
            'ticker': f'MARKET{i}',
            'createdAt': created_at,
            'closedTime': closed_time
        })
    
    return pl.DataFrame(markets)


def generate_test_trades(markets_df, n_trades=10000):
    """Generate test trade data with realistic patterns."""
    trades = []
    
    # Create some "insider" wallets with high win rates
    insider_wallets = {
        f'insider_{i}': {
            'win_rate': random.uniform(0.70, 0.90),
            'avg_bet': random.uniform(10000, 50000),
            'created': datetime(2025, 1, 1) + timedelta(days=random.randint(0, 30))
        }
        for i in range(10)
    }
    
    # Create some fresh account wallets
    fresh_wallets = {
        f'fresh_{i}': {
            'created': datetime(2025, 11, 1) + timedelta(hours=random.randint(0, 168)),
            'trades': 0
        }
        for i in range(20)
    }
    
    # Create regular wallets
    regular_wallets = [f'wallet_{i}' for i in range(100)]
    
    market_ids = markets_df['id'].to_list()
    
    for i in range(n_trades):
        market_id = random.choice(market_ids)
        market_row = markets_df.filter(pl.col('id') == market_id).row(0, named=True)
        
        # Timestamp between market creation and close
        trade_time = market_row['createdAt'] + timedelta(
            seconds=random.randint(
                0,
                int((market_row['closedTime'] - market_row['createdAt']).total_seconds())
            )
        )
        
        # Randomly select maker type
        wallet_type = random.choices(
            ['insider', 'fresh', 'regular'],
            weights=[0.02, 0.05, 0.93]  # 2% insider, 5% fresh, 93% regular
        )[0]
        
        if wallet_type == 'insider':
            maker = random.choice(list(insider_wallets.keys()))
            size = insider_wallets[maker]['avg_bet'] * random.uniform(0.5, 2.0)
        elif wallet_type == 'fresh':
            maker = random.choice(list(fresh_wallets.keys()))
            # Fresh accounts sometimes make large bets
            if random.random() < 0.2:  # 20% chance of large bet
                size = random.uniform(10000, 50000)
            else:
                size = random.uniform(100, 5000)
            fresh_wallets[maker]['trades'] += 1
        else:
            maker = random.choice(regular_wallets)
            size = random.uniform(100, 10000)
        
        taker = random.choice(regular_wallets)
        
        # Price between 0.1 and 0.9
        price = random.uniform(0.1, 0.9)
        
        # Determine directions
        maker_direction = random.choice(['YES', 'NO'])
        taker_direction = 'NO' if maker_direction == 'YES' else 'YES'
        
        trades.append({
            'timestamp': trade_time,
            'market_id': market_id,
            'maker': maker,
            'taker': taker,
            'maker_direction': maker_direction,
            'taker_direction': taker_direction,
            'price': price,
            'usd_amount': size
        })
    
    return pl.DataFrame(trades).sort('timestamp')


def create_test_dataset(output_dir='../poly_data_test'):
    """Create complete test dataset."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print("Generating test markets...")
    markets = generate_test_markets(100)
    markets.write_csv(output_path / 'markets.csv')
    print(f"Created {len(markets)} test markets")
    
    print("Generating test trades...")
    trades = generate_test_trades(markets, 10000)
    
    # Create goldsky directory
    goldsky_path = output_path / 'goldsky'
    goldsky_path.mkdir(exist_ok=True)
    
    # Save trades (poly_data expects trades in goldsky/orderFilled.csv format)
    # But for backtesting we can use processed format directly
    processed_path = output_path / 'processed'
    processed_path.mkdir(exist_ok=True)
    trades.write_csv(processed_path / 'trades.csv')
    
    print(f"Created {len(trades)} test trades")
    print(f"Test dataset saved to: {output_path.absolute()}")
    print("\nTo run backtest:")
    print(f"python -m backtesting.backtest_runner --poly-data-path {output_path.absolute()} --start-date 2025-01-01 --end-date 2025-12-31")
    
    return output_path


if __name__ == '__main__':
    create_test_dataset()
