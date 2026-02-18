"""Main application entry point for Polymarket Insider Trading Bot"""

import asyncio
import logging
import signal as signal_module
import sys
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.analytics.wallet_analyzer import WalletAnalyzer
from src.api.gamma_client import gamma_client
from src.api.websocket_client import ws_client
from src.config import settings
from src.database.connection import close_db, get_db, init_db
from src.signals.detector import SignalDetector
from src.trading.executor import TradeExecutor
from src.trading.position_manager import PositionManager
from src.trading.risk_manager import RiskManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("polymarket_bot.log")
    ]
)

logger = logging.getLogger(__name__)

# Global state
bot_running = False
monitoring_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting Polymarket Insider Trading Bot...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Bankroll: ${settings.initial_bankroll}")
    logger.info(f"Min Confidence: {settings.min_confidence*100:.1f}%")
    
    # Initialize database
    await init_db()
    logger.info("✅ Database initialized")
    
    # Start monitoring
    global monitoring_task, bot_running
    bot_running = True
    monitoring_task = asyncio.create_task(run_bot())
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down bot...")
    bot_running = False
    if monitoring_task:
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
    
    await gamma_client.close()
    await ws_client.disconnect()
    await close_db()
    logger.info("👋 Bot shut down successfully")


# Create FastAPI app
app = FastAPI(
    title="Polymarket Insider Bot",
    description="Automated insider trading signal detection and execution",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "running", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Detailed health check"""
    async with get_db() as db:
        executor = TradeExecutor(db)
        portfolio = await executor.get_portfolio_summary()
    
    return {
        "status": "healthy",
        "bot_running": bot_running,
        "environment": settings.environment,
        "portfolio": portfolio
    }


@app.get("/portfolio")
async def get_portfolio():
    """Get current portfolio status"""
    async with get_db() as db:
        executor = TradeExecutor(db)
        portfolio = await executor.get_portfolio_summary()
    
    return portfolio


@app.post("/emergency-stop")
async def emergency_stop():
    """Emergency stop - liquidate all positions"""
    async with get_db() as db:
        executor = TradeExecutor(db)
        await executor.close_all_positions(reason="manual_emergency_stop")
    
    return {"status": "all_positions_closed"}


async def on_trade_event(trade_data: dict):
    """Handle incoming trade event from WebSocket
    
    Args:
        trade_data: Trade data from WebSocket
    """
    try:
        market_id = trade_data.get("market")
        maker = trade_data.get("maker")
        size = float(trade_data.get("size", 0))
        price = float(trade_data.get("price", 0))
        side = trade_data.get("side", "BUY")
        
        logger.debug(
            f"📥 Trade event: Market={market_id}, "
            f"Maker={maker[:8] if maker else 'N/A'}..., "
            f"Size=${size:.2f}, Price={price:.4f}"
        )
        
        # Run signal detection
        async with get_db() as db:
            detector = SignalDetector(db)
            executor = TradeExecutor(db)
            wallet_analyzer = WalletAnalyzer(db)
            
            # Update wallet metrics
            if maker:
                await wallet_analyzer.update_wallet_metrics(maker)
            
            # Detect wallet-specific signals
            if maker:
                signals = await detector.detect_all(
                    wallet_address=maker,
                    market_id=market_id,
                    trade_size=size,
                    trade_price=price,
                    side=side
                )
                
                # Save and potentially execute signals
                for signal in signals:
                    await detector.save_signal(signal)
                    
                    # Auto-execute high-confidence signals
                    position = await executor.auto_trade_signal(signal)
                    if position:
                        logger.info(
                            f"🤖 Auto-executed signal #{signal.id} → "
                            f"Position #{position.id}"
                        )
            
            await db.commit()
            
    except Exception as e:
        logger.error(f"Error handling trade event: {e}", exc_info=True)


async def monitor_positions():
    """Monitor open positions for stop-loss/take-profit"""
    while bot_running:
        try:
            async with get_db() as db:
                position_manager = PositionManager(db)
                await position_manager.monitor_all_positions()
                await db.commit()
        except Exception as e:
            logger.error(f"Error monitoring positions: {e}", exc_info=True)
        
        # Check every minute
        await asyncio.sleep(60)


async def check_market_signals():
    """Periodically check for market-level signals (volume spikes, clustering)"""
    while bot_running:
        try:
            # Get high-volume markets
            markets = await gamma_client.get_high_volume_markets(
                min_volume_24h=50000,
                limit=20
            )
            
            async with get_db() as db:
                detector = SignalDetector(db)
                executor = TradeExecutor(db)
                
                for market in markets:
                    market_id = market.get("id")
                    
                    # Detect market signals
                    signals = await detector.detect_market_signals(market_id)
                    
                    # Save and execute
                    for signal in signals:
                        await detector.save_signal(signal)
                        position = await executor.auto_trade_signal(signal)
                        if position:
                            logger.info(
                                f"🤖 Auto-executed market signal #{signal.id} → "
                                f"Position #{position.id}"
                            )
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"Error checking market signals: {e}", exc_info=True)
        
        # Check every 30 seconds
        await asyncio.sleep(30)


async def check_emergency_stop():
    """Periodically check if emergency stop should trigger"""
    while bot_running:
        try:
            async with get_db() as db:
                risk_manager = RiskManager(db)
                executor = TradeExecutor(db)
                
                if await risk_manager.check_emergency_stop():
                    logger.critical("🚨 EMERGENCY STOP ACTIVATED!")
                    await executor.close_all_positions(reason="emergency_stop")
                    await db.commit()
                    
                    # Pause trading for 1 hour
                    logger.warning("⏸️ Trading paused for 1 hour")
                    await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Error in emergency stop check: {e}", exc_info=True)
        
        # Check every 5 minutes
        await asyncio.sleep(300)


async def run_bot():
    """Main bot loop"""
    logger.info("🤖 Bot started - monitoring markets...")
    
    # Start monitoring tasks
    tasks = [
        asyncio.create_task(monitor_positions()),
        asyncio.create_task(check_market_signals()),
        asyncio.create_task(check_emergency_stop()),
    ]
    
    # Register trade event callback
    ws_client.on_trade(on_trade_event)
    
    # Get top markets to monitor
    markets = await gamma_client.get_high_volume_markets(
        min_volume_24h=50000,
        limit=50
    )
    
    market_ids = [m["id"] for m in markets if m.get("id")]
    logger.info(f"📊 Monitoring {len(market_ids)} high-volume markets")
    
    # Start WebSocket with auto-reconnect
    try:
        await ws_client.run_with_reconnect(
            market_ids=market_ids,
            reconnect_delay=5
        )
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    
    # Cancel tasks on shutdown
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)


def handle_shutdown(sig, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {sig}, shutting down...")
    global bot_running
    bot_running = False
    sys.exit(0)


# Register signal handlers
signal_module.signal(signal_module.SIGINT, handle_shutdown)
signal_module.signal(signal_module.SIGTERM, handle_shutdown)


if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 80)
    logger.info("  POLYMARKET INSIDER TRADING BOT")
    logger.info("  Version: 0.1.0")
    logger.info("  Built by: Byte AI Assistant")
    logger.info("=" * 80)
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
