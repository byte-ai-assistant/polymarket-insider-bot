"""WebSocket client for real-time Polymarket trade updates"""

import asyncio
import json
import logging
from typing import Callable, Dict, List, Optional

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class PolymarketWebSocket:
    """WebSocket client for real-time Polymarket market updates"""
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self):
        """Initialize WebSocket client"""
        self.ws: Optional[WebSocketClientProtocol] = None
        self.subscribed_markets: List[str] = []
        self.callbacks: Dict[str, List[Callable]] = {
            "trade": [],
            "book": [],
            "last_trade_price": [],
        }
        self.running = False
    
    async def connect(self):
        """Connect to WebSocket server"""
        try:
            self.ws = await websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=10,
            )
            self.running = True
            logger.info(f"Connected to WebSocket: {self.WS_URL}")
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from WebSocket server"""
        self.running = False
        if self.ws:
            await self.ws.close()
            self.ws = None
        logger.info("Disconnected from WebSocket")
    
    async def subscribe_market(self, market_id: str):
        """Subscribe to market updates
        
        Args:
            market_id: Market condition ID to subscribe to
        """
        if not self.ws:
            raise ConnectionError("WebSocket not connected")
        
        subscribe_msg = {
            "type": "subscribe",
            "channel": "market",
            "market": market_id
        }
        
        await self.ws.send(json.dumps(subscribe_msg))
        self.subscribed_markets.append(market_id)
        logger.info(f"Subscribed to market: {market_id}")
    
    async def unsubscribe_market(self, market_id: str):
        """Unsubscribe from market updates
        
        Args:
            market_id: Market condition ID to unsubscribe from
        """
        if not self.ws:
            return
        
        unsubscribe_msg = {
            "type": "unsubscribe",
            "channel": "market",
            "market": market_id
        }
        
        await self.ws.send(json.dumps(unsubscribe_msg))
        if market_id in self.subscribed_markets:
            self.subscribed_markets.remove(market_id)
        logger.info(f"Unsubscribed from market: {market_id}")
    
    def on_trade(self, callback: Callable):
        """Register callback for trade events
        
        Args:
            callback: Async function to call when trade occurs
        """
        self.callbacks["trade"].append(callback)
    
    def on_book_update(self, callback: Callable):
        """Register callback for orderbook updates
        
        Args:
            callback: Async function to call when orderbook updates
        """
        self.callbacks["book"].append(callback)
    
    def on_price_update(self, callback: Callable):
        """Register callback for price updates
        
        Args:
            callback: Async function to call when price updates
        """
        self.callbacks["last_trade_price"].append(callback)
    
    async def _handle_message(self, message: Dict):
        """Handle incoming WebSocket message
        
        Args:
            message: Parsed JSON message from WebSocket
        """
        msg_type = message.get("type")
        
        if msg_type not in self.callbacks:
            return
        
        # Call all registered callbacks for this message type
        for callback in self.callbacks[msg_type]:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"Error in callback for {msg_type}: {e}", exc_info=True)
    
    async def listen(self):
        """Listen for WebSocket messages (blocking)"""
        if not self.ws:
            raise ConnectionError("WebSocket not connected")
        
        logger.info("Listening for WebSocket messages...")
        
        try:
            async for message in self.ws:
                if not self.running:
                    break
                
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse WebSocket message: {message}")
                except Exception as e:
                    logger.error(f"Error handling WebSocket message: {e}", exc_info=True)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in WebSocket listen loop: {e}", exc_info=True)
        finally:
            self.running = False
    
    async def start(self, market_ids: List[str]):
        """Connect, subscribe to markets, and start listening
        
        Args:
            market_ids: List of market condition IDs to monitor
        """
        await self.connect()
        
        for market_id in market_ids:
            await self.subscribe_market(market_id)
        
        await self.listen()
    
    async def run_with_reconnect(
        self,
        market_ids: List[str],
        reconnect_delay: int = 5,
        max_retries: Optional[int] = None
    ):
        """Run WebSocket with automatic reconnection
        
        Args:
            market_ids: List of market condition IDs to monitor
            reconnect_delay: Seconds to wait before reconnecting
            max_retries: Maximum reconnection attempts (None = infinite)
        """
        retries = 0
        
        while True:
            try:
                await self.start(market_ids)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                retries += 1
                
                if max_retries and retries >= max_retries:
                    logger.error(f"Max retries ({max_retries}) reached, giving up")
                    break
                
                logger.info(f"Reconnecting in {reconnect_delay} seconds... (attempt {retries})")
                await asyncio.sleep(reconnect_delay)
            
            if not self.running:
                break


# Singleton instance
ws_client = PolymarketWebSocket()
