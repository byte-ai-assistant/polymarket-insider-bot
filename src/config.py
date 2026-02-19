"""Configuration management for Polymarket Bot"""

from decimal import Decimal
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Polymarket API
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    clob_api_url: str = "https://clob.polymarket.com"
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    polymarket_chain_id: int = 137
    
    # Wallet
    private_key: str
    wallet_address: str
    
    # Database
    database_url: str
    redis_url: str
    
    # Trading Parameters
    initial_bankroll: Decimal = Decimal("5000.00")
    min_confidence: Decimal = Decimal("0.65")
    max_position_size_pct: Decimal = Decimal("10.0")
    kelly_fraction: Decimal = Decimal("0.25")
    stop_loss_pct: Decimal = Decimal("30.0")  # Widened from 15% (too tight for prediction markets)
    max_concurrent_positions: int = 8  # Increased from 5 for diversification
    max_daily_loss_pct: Decimal = Decimal("10.0")

    # Risk Management
    min_liquidity_usd: Decimal = Decimal("5000.00")
    min_market_volume_usd: Decimal = Decimal("50000.00")
    max_slippage_pct: Decimal = Decimal("2.0")

    # Signal Detection Thresholds
    fresh_account_max_age_days: int = 7
    fresh_account_min_size_usd: Decimal = Decimal("1000")  # Lowered from $10K
    proven_winner_min_trades: int = 10  # Lowered from 20
    proven_winner_min_win_rate: Decimal = Decimal("0.65")  # Lowered from 0.70
    volume_spike_threshold: Decimal = Decimal("5.0")  # Lowered from 10x
    wallet_cluster_min_wallets: int = 3
    
    # Notifications
    whatsapp_api_token: Optional[str] = None
    whatsapp_phone_number: Optional[str] = None
    notification_min_confidence: Decimal = Decimal("0.85")
    
    # Monitoring & Logging
    sentry_dsn: Optional[str] = None
    log_level: str = "INFO"
    prometheus_port: int = 9090
    
    # Environment
    environment: str = "development"
    debug: bool = False
    
    # Google Cloud
    gcp_project_id: Optional[str] = None
    gcp_region: str = "us-central1"
    gcs_bucket: Optional[str] = None
    
    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment.lower() == "development"


# Global settings instance
settings = Settings()
