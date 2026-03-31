import httpx
import logging
import os
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class CoinGeckoClient:
    """
    Async client for CoinGecko API v3.
    """

    BASE_URL = "https://pro-api.coingecko.com/api/v3"

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
            headers["x-cg-pro-api-key"] = self.api_key
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
        Get current live price and market data for a coin.

        Args:
            coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum")

        Returns:
            Dictionary containing current market data in /coins/{id} format

        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false"
            }

            logger.info(f"Fetching current price for {coin_id}")

            response = await self.client.get(
                f"/coins/{coin_id}",
                params=params
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched current price for {coin_id}")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch current price: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching current price: {str(e)}")
            raise

    async def get_coins_markets(
        self,
        vs_currency: str = "usd",
        ids: Optional[list[str]] = None,
        order: str = "market_cap_desc",
        per_page: int = 100,
        page: int = 1,
        price_change_percentage: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """
        Get list of coins with market data (price, mcap, volume, price changes).

        Args:
            vs_currency: Target currency (default: "usd")
            ids: Optional list of coin IDs to filter
            order: Sort order (market_cap_desc, volume_desc, etc.)
            per_page: Results per page (1-250)
            page: Page number
            price_change_percentage: Comma-separated timeframes (1h,24h,7d,14d,30d,200d,1y)

        Returns:
            List of coin dictionaries with market data

        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params = {
                "vs_currency": vs_currency,
                "order": order,
                "per_page": str(per_page),
                "page": str(page),
                "sparkline": "false"
            }

            if ids:
                params["ids"] = ",".join(ids)

            if price_change_percentage:
                params["price_change_percentage"] = price_change_percentage

            logger.info(f"Fetching coins markets data: page={page}, per_page={per_page}, order={order}")

            response = await self.client.get("/coins/markets", params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched {len(data)} coins from markets")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch coins markets: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching coins markets: {str(e)}")
            raise

    async def get_top_gainers_losers(
        self,
        vs_currency: str = "usd",
        duration: str = "7d",
        top_coins: str = "1000"
    ) -> Dict[str, Any]:
        """
        Get top 30 gainers and losers by time duration.

        Args:
            vs_currency: Target currency (default: "usd")
            duration: Time range (1h, 24h, 7d, 14d, 30d, 1y)
            top_coins: Market cap scope to search within (300, 500, 1000, all). Default: 500

        Returns:
            Dict with 'top_gainers' and 'top_losers' arrays (30 coins each)
        """
        try:
            params = {
                "vs_currency": vs_currency,
                "duration": duration,
                "top_coins": top_coins
            }

            logger.info(f"Fetching top gainers/losers for duration={duration}")

            response = await self.client.get(
                "/coins/top_gainers_losers",
                params=params
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched {len(data.get('top_gainers', []))} gainers and {len(data.get('top_losers', []))} losers")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch top gainers/losers: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching top gainers/losers: {str(e)}")
            raise

    async def get_coin_market_chart(
        self,
        coin_id: str,
        vs_currency: str = "usd",
        days: str = "365"
    ) -> Dict[str, Any]:
        """
        Get historical chart data (price, mcap, volume) over time.

        Args:
            coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum")
            vs_currency: Target currency (default: "usd")
            days: Data range (1, 7, 14, 30, 90, 180, 365, max)

        Returns:
            Dict with 'prices', 'market_caps', 'total_volumes' arrays.
            Each array contains [timestamp_ms, value] pairs.

        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            Exception: For other failures
        """
        try:
            params = {
                "vs_currency": vs_currency,
                "days": days
            }

            logger.info(f"Fetching market chart for {coin_id}: days={days}")

            response = await self.client.get(
                f"/coins/{coin_id}/market_chart",
                params=params
            )
            response.raise_for_status()

            data = response.json()
            prices_count = len(data.get("prices", []))
            logger.info(f"Successfully fetched market chart for {coin_id}: {prices_count} data points")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to fetch market chart: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching market chart: {str(e)}")
            raise

    async def close(self):
        """Close the HTTP client connection."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
