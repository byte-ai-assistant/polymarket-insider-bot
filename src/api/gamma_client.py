"""Gamma API client for Polymarket market data"""

import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class GammaClient:
    """Client for Polymarket Gamma API (public market data)"""
    
    def __init__(self, base_url: Optional[str] = None):
        """Initialize Gamma API client
        
        Args:
            base_url: Base URL for Gamma API (defaults to config)
        """
        self.base_url = base_url or settings.gamma_api_url
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={"User-Agent": "Polymarket-Bot/0.1.0"}
        )
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    async def get_events(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """Get list of events/markets
        
        Args:
            active: Filter for active events
            closed: Filter for closed events
            limit: Maximum number of results
            offset: Pagination offset
            
        Returns:
            List of event dictionaries
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset
        }
        
        try:
            response = await self.client.get("/events", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch events: {e}")
            return []
    
    async def get_event(self, event_id: str) -> Optional[Dict]:
        """Get single event by ID
        
        Args:
            event_id: Event ID
            
        Returns:
            Event dictionary or None if not found
        """
        try:
            response = await self.client.get(f"/events/{event_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch event {event_id}: {e}")
            return None
    
    async def search_markets(self, query: str) -> List[Dict]:
        """Search markets by keyword
        
        Args:
            query: Search query string
            
        Returns:
            List of matching markets
        """
        try:
            response = await self.client.get(
                "/public-search",
                params={"q": query}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to search markets for '{query}': {e}")
            return []
    
    async def get_market(self, slug: str) -> Optional[Dict]:
        """Get market details by slug
        
        Args:
            slug: Market slug
            
        Returns:
            Market dictionary or None if not found
        """
        try:
            response = await self.client.get(
                "/markets",
                params={"slug": slug}
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch market '{slug}': {e}")
            return None
    
    async def get_high_volume_markets(
        self,
        min_volume_24h: float = 50000.0,
        limit: int = 50
    ) -> List[Dict]:
        """Get markets with high 24h volume
        
        Args:
            min_volume_24h: Minimum 24h volume in USD
            limit: Maximum number of results
            
        Returns:
            List of high-volume markets
        """
        events = await self.get_events(active=True, limit=limit * 2)
        
        # Filter by volume and sort
        high_volume = [
            event for event in events
            if event.get("volume24hr", 0) >= min_volume_24h
        ]
        high_volume.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)
        
        return high_volume[:limit]
    
    async def get_market_stats(self, market_id: str) -> Dict:
        """Get aggregated market statistics
        
        Args:
            market_id: Market/event ID
            
        Returns:
            Dictionary with volume, liquidity, and other stats
        """
        event = await self.get_event(market_id)
        if not event:
            return {}
        
        return {
            "market_id": market_id,
            "title": event.get("title", ""),
            "volume_24h": event.get("volume24hr", 0),
            "volume_total": event.get("volume", 0),
            "liquidity": event.get("liquidity", 0),
            "open_interest": event.get("openInterest", 0),
            "markets_count": len(event.get("markets", [])),
            "active": event.get("active", False),
            "end_date": event.get("endDate")
        }


# Singleton instance
gamma_client = GammaClient()
