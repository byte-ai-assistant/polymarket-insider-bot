"""
Data Loader - Load and prepare historical Polymarket data from poly_data CSVs.
"""

import polars as pl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Loads historical Polymarket trade and market data from poly_data repository.
    
    Data sources:
    - markets.csv: Market metadata (questions, tokens, volumes, etc.)
    - processed/trades.csv: Structured trade data with prices and directions
    """
    
    def __init__(self, poly_data_path: str = "../poly_data"):
        """
        Initialize data loader.
        
        Args:
            poly_data_path: Path to poly_data repository directory
        """
        self.poly_data_path = Path(poly_data_path)
        
        if not self.poly_data_path.exists():
            raise ValueError(f"poly_data path does not exist: {poly_data_path}")
        
        self.markets_path = self.poly_data_path / "markets.csv"
        self.trades_path = self.poly_data_path / "processed" / "trades.csv"
        
        logger.info(f"DataLoader initialized with path: {self.poly_data_path}")
    
    def load_markets(self) -> pl.DataFrame:
        """
        Load market metadata.
        
        Returns:
            Polars DataFrame with market data
        """
        logger.info("Loading markets from markets.csv...")
        
        if not self.markets_path.exists():
            raise FileNotFoundError(f"Markets file not found: {self.markets_path}")
        
        markets = pl.read_csv(self.markets_path)
        
        # Convert timestamp columns
        if 'createdAt' in markets.columns:
            markets = markets.with_columns(
                pl.col("createdAt").str.to_datetime().alias("createdAt")
            )
        
        if 'closedTime' in markets.columns:
            markets = markets.with_columns(
                pl.col("closedTime").str.to_datetime().alias("closedTime")
            )
        
        logger.info(f"Loaded {len(markets)} markets")
        return markets
    
    def load_trades(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        market_ids: Optional[list] = None,
        streaming: bool = True
    ) -> pl.DataFrame:
        """
        Load trade data with optional filtering.
        
        Args:
            start_date: Filter trades after this date
            end_date: Filter trades before this date
            market_ids: Filter trades for specific market IDs
            streaming: Use streaming mode for large files (memory efficient)
        
        Returns:
            Polars DataFrame with trade data
        """
        logger.info("Loading trades from processed/trades.csv...")
        
        if not self.trades_path.exists():
            raise FileNotFoundError(f"Trades file not found: {self.trades_path}")
        
        # Load with lazy evaluation for filtering
        trades = pl.scan_csv(str(self.trades_path))
        
        # Convert timestamp
        trades = trades.with_columns(
            pl.col("timestamp").str.to_datetime().alias("timestamp")
        )
        
        # Apply filters
        if start_date:
            trades = trades.filter(pl.col("timestamp") >= start_date)
            logger.info(f"Filtering trades >= {start_date}")
        
        if end_date:
            trades = trades.filter(pl.col("timestamp") <= end_date)
            logger.info(f"Filtering trades <= {end_date}")
        
        if market_ids:
            trades = trades.filter(pl.col("market_id").is_in(market_ids))
            logger.info(f"Filtering for {len(market_ids)} markets")
        
        # Collect results
        if streaming:
            trades = trades.collect(streaming=True)
        else:
            trades = trades.collect()
        
        logger.info(f"Loaded {len(trades)} trades")
        return trades
    
    def load_backtest_data(
        self,
        start_date: datetime,
        end_date: datetime,
        min_market_volume: Optional[float] = None
    ) -> Tuple[pl.DataFrame, pl.DataFrame]:
        """
        Load markets and trades for backtesting period.
        
        Args:
            start_date: Start date for backtest
            end_date: End date for backtest
            min_market_volume: Minimum market volume (USD) to include
        
        Returns:
            Tuple of (markets, trades) DataFrames
        """
        logger.info(f"Loading backtest data: {start_date} to {end_date}")
        
        # Load markets
        markets = self.load_markets()
        
        # Filter markets by volume if specified
        if min_market_volume:
            markets = markets.filter(pl.col("volume") >= min_market_volume)
            logger.info(f"Filtered to {len(markets)} markets with volume >= ${min_market_volume:,.0f}")
        
        # Get market IDs for trade filtering
        market_ids = markets['id'].to_list()
        
        # Load trades for these markets in the date range
        trades = self.load_trades(
            start_date=start_date,
            end_date=end_date,
            market_ids=market_ids
        )
        
        return markets, trades
    
    def get_date_range(self) -> Tuple[datetime, datetime]:
        """
        Get the date range of available trade data.
        
        Returns:
            Tuple of (earliest_date, latest_date)
        """
        if not self.trades_path.exists():
            raise FileNotFoundError("Trades file not found")
        
        # Load just the timestamp column
        trades = pl.scan_csv(str(self.trades_path)).select("timestamp")
        trades = trades.with_columns(
            pl.col("timestamp").str.to_datetime().alias("timestamp")
        )
        trades = trades.collect()
        
        earliest = trades['timestamp'].min()
        latest = trades['timestamp'].max()
        
        logger.info(f"Data range: {earliest} to {latest}")
        return earliest, latest
    
    def get_high_volume_markets(
        self,
        min_volume: float = 50000,
        limit: int = 100
    ) -> pl.DataFrame:
        """
        Get markets with highest trading volume.
        
        Args:
            min_volume: Minimum volume threshold
            limit: Maximum number of markets to return
        
        Returns:
            DataFrame of high-volume markets sorted by volume descending
        """
        markets = self.load_markets()
        
        high_volume = markets.filter(pl.col("volume") >= min_volume)
        high_volume = high_volume.sort("volume", descending=True)
        high_volume = high_volume.head(limit)
        
        logger.info(f"Found {len(high_volume)} markets with volume >= ${min_volume:,.0f}")
        return high_volume
