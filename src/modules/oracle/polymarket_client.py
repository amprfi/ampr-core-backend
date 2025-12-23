import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    Async client for Polymarket Gamma API.
    
    Provides read-only access to prediction markets data including
    events, markets, tags, and search functionality.
    """
    
    BASE_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, timeout: float = 30.0):
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"accept": "application/json"},
            timeout=timeout
        )
    
    async def get_events(
        self,
        limit: int = 50,
        offset: int = 0,
        order: str = "id",
        ascending: bool = False,
        closed: Optional[bool] = False,
        active: Optional[bool] = None,
        tag_id: Optional[int] = None,
        tag_slug: Optional[str] = None,
        liquidity_min: Optional[float] = None,
        volume_min: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of prediction events (each event can contain multiple markets).
        
        Args:
            limit: Number of results per page (default: 50)
            offset: Pagination offset
            order: Field to order by (default: "id")
            ascending: Sort direction
            closed: Filter by closed status (default: False for active only)
            active: Filter by active status
            tag_id: Filter by tag ID
            tag_slug: Filter by tag slug
            liquidity_min: Minimum liquidity threshold
            volume_min: Minimum volume threshold
            
        Returns:
            List of event dictionaries containing markets
            
        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params: Dict[str, Any] = {
                "limit": limit,
                "offset": offset,
                "order": order,
                "ascending": str(ascending).lower(),
            }
            
            if closed is not None:
                params["closed"] = str(closed).lower()
            if active is not None:
                params["active"] = str(active).lower()
            if tag_id is not None:
                params["tag_id"] = tag_id
            if tag_slug is not None:
                params["tag_slug"] = tag_slug
            if liquidity_min is not None:
                params["liquidity_min"] = liquidity_min
            if volume_min is not None:
                params["volume_min"] = volume_min
            
            logger.info(f"Fetching Polymarket events: limit={limit}, offset={offset}")
            
            response = await self.client.get("/events", params=params)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched {len(data)} events")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch events: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket events: {str(e)}")
            raise
    
    async def get_event_by_id(self, event_id: int) -> Dict[str, Any]:
        """
        Get a specific event by its ID.
        
        Args:
            event_id: The event ID
            
        Returns:
            Event dictionary with full details and markets
        """
        try:
            logger.info(f"Fetching Polymarket event: {event_id}")
            
            response = await self.client.get(f"/events/{event_id}")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched event: {data.get('title', event_id)}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch event {event_id}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket event: {str(e)}")
            raise
    
    async def get_event_by_slug(self, slug: str) -> Dict[str, Any]:
        """
        Get a specific event by its URL slug.
        
        Args:
            slug: The event slug (from Polymarket URL)
            
        Returns:
            Event dictionary with full details and markets
        """
        try:
            logger.info(f"Fetching Polymarket event by slug: {slug}")
            
            response = await self.client.get(f"/events/slug/{slug}")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched event: {data.get('title', slug)}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch event by slug {slug}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket event: {str(e)}")
            raise
    
    async def get_markets(
        self,
        limit: int = 50,
        offset: int = 0,
        order: str = "id",
        ascending: bool = False,
        closed: Optional[bool] = False,
        tag_id: Optional[int] = None,
        liquidity_num_min: Optional[float] = None,
        liquidity_num_max: Optional[float] = None,
        volume_num_min: Optional[float] = None,
        volume_num_max: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of individual prediction markets.
        
        Args:
            limit: Number of results per page (default: 50)
            offset: Pagination offset
            order: Field to order by (default: "id")
            ascending: Sort direction
            closed: Filter by closed status (default: False for active only)
            tag_id: Filter by tag ID
            liquidity_num_min: Minimum liquidity threshold
            liquidity_num_max: Maximum liquidity threshold
            volume_num_min: Minimum volume threshold
            volume_num_max: Maximum volume threshold
            
        Returns:
            List of market dictionaries
        """
        try:
            params: Dict[str, Any] = {
                "limit": limit,
                "offset": offset,
                "order": order,
                "ascending": str(ascending).lower(),
            }
            
            if closed is not None:
                params["closed"] = str(closed).lower()
            if tag_id is not None:
                params["tag_id"] = tag_id
            if liquidity_num_min is not None:
                params["liquidity_num_min"] = liquidity_num_min
            if liquidity_num_max is not None:
                params["liquidity_num_max"] = liquidity_num_max
            if volume_num_min is not None:
                params["volume_num_min"] = volume_num_min
            if volume_num_max is not None:
                params["volume_num_max"] = volume_num_max
            
            logger.info(f"Fetching Polymarket markets: limit={limit}, offset={offset}")
            
            response = await self.client.get("/markets", params=params)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched {len(data)} markets")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch markets: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {str(e)}")
            raise
    
    async def get_market_by_id(self, market_id: int) -> Dict[str, Any]:
        """
        Get a specific market by its ID.
        
        Args:
            market_id: The market ID
            
        Returns:
            Market dictionary with full details
        """
        try:
            logger.info(f"Fetching Polymarket market: {market_id}")
            
            response = await self.client.get(f"/markets/{market_id}")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched market: {data.get('question', market_id)}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch market {market_id}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket market: {str(e)}")
            raise
    
    async def get_market_by_slug(self, slug: str) -> Dict[str, Any]:
        """
        Get a specific market by its URL slug.
        
        Args:
            slug: The market slug (from Polymarket URL)
            
        Returns:
            Market dictionary with full details
        """
        try:
            logger.info(f"Fetching Polymarket market by slug: {slug}")
            
            response = await self.client.get(f"/markets/slug/{slug}")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched market: {data.get('question', slug)}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch market by slug {slug}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket market: {str(e)}")
            raise
    
    async def get_tags(self) -> List[Dict[str, Any]]:
        """
        Get all available tags for filtering markets/events.
        
        Returns:
            List of tag dictionaries with id, label, and slug
        """
        try:
            logger.info("Fetching Polymarket tags")
            
            response = await self.client.get("/tags")
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched {len(data)} tags")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch tags: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Polymarket tags: {str(e)}")
            raise
    
    async def search(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """
        Search for markets and events by keyword.
        
        Args:
            query: Search query string
            limit: Maximum results to return
            
        Returns:
            Dictionary containing matching events and markets
        """
        try:
            params = {"q": query, "limit": limit}
            
            logger.info(f"Searching Polymarket for: {query}")
            
            response = await self.client.get("/search", params=params)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Search returned results for: {query}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to search: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error searching Polymarket: {str(e)}")
            raise
    
    async def get_trending_events(
        self,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get trending/featured prediction events.
        
        Args:
            limit: Number of events to return
            
        Returns:
            List of trending event dictionaries
        """
        return await self.get_events(
            limit=limit,
            order="volume24hr",
            ascending=False,
            closed=False,
        )
    
    async def close(self):
        """Close the HTTP client connection."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
