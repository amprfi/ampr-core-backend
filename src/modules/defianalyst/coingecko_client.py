import httpx
import logging
import os
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class CoinGeckoClient:
    """
    Async client for CoinGecko API v3 (Demo/Public API).
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("COINGECKO_API_KEY")
        if not self.api_key:
            logger.warning("CoinGecko API key not found. Requests may be rate-limited.")
        
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=self._get_headers(),
            timeout=30.0
        )
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["x-cg-demo-api-key"] = self.api_key
        return headers
    
    async def get_coins_list(self, include_platform: bool = False) -> list[Dict[str, Any]]:
        """
        Get list of all supported coins with id, symbol, and name.
        
        Args:
            include_platform: Include platform contract addresses
            
        Returns:
            List of coin dictionaries with id, symbol, name, and optionally platforms
            
        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params = {"include_platform": str(include_platform).lower()}
            
            logger.info("Fetching CoinGecko coins list")
            
            response = await self.client.get("/coins/list", params=params)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched {len(data)} coins")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch coins list: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching CoinGecko coins list: {str(e)}")
            raise
    
    async def get_coin_history(
        self, 
        coin_id: str, 
        date: str,
        localization: bool = False
    ) -> Dict[str, Any]:
        """
        Get historical data (price, market cap, volume) for a coin on a specific date.
        
        Args:
            coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum")
            date: Date in dd-mm-yyyy format (e.g., "24-11-2025")
            localization: Include localized languages in response
            
        Returns:
            Dictionary containing coin data including market_data with current_price, market_cap, etc.
            
        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params = {
                "date": date,
                "localization": str(localization).lower()
            }
            
            logger.info(f"Fetching CoinGecko data for {coin_id} on {date}")
            
            response = await self.client.get(
                f"/coins/{coin_id}/history",
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched data for {coin_id}")
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch coin data: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {str(e)}")
            raise
    
    async def get_current_price(self, coin_id: str) -> Dict[str, Any]:
        """
        Get current price and market data for a coin (uses today's date).
        
        Args:
            coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum")
            
        Returns:
            Dictionary containing current market data
        """
        today = datetime.now().strftime("%d-%m-%Y")
        return await self.get_coin_history(coin_id, today)
    
    async def close(self):
        """Close the HTTP client connection."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
