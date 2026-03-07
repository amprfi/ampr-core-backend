"""
Price poller service.

Periodically fetches market data from CoinGecko for all watched assets
and updates their price fields in Convex.
"""
import asyncio
import logging
import time
from typing import Optional
from convex import ConvexClient

from .coingecko_client import CoinGeckoClient
from .alert_checker import PriceAlertChecker

logger = logging.getLogger(__name__)

# Poll every 15 minutes
POLL_INTERVAL_SECONDS = 15 * 60

# CoinGecko /coins/markets supports up to 250 IDs per request
COINGECKO_BATCH_SIZE = 250


class PricePoller:
    """
    Polls CoinGecko for market data on watched assets and updates Convex.

    Uses the priceFeedMappings table to determine which external IDs to fetch,
    filtered to only assets in at least one user's watchlist.
    """

    def __init__(self, convex_client: ConvexClient):
        self.convex = convex_client
        self.coingecko = CoinGeckoClient()
        self._running = False
        self._alert_checker: Optional[PriceAlertChecker] = None

    async def poll_once(self) -> int:
        """
        Run a single poll cycle: fetch watched mappings, get prices, update assets.

        Returns:
            Number of assets updated.
        """
        # Get all watched mappings for the defianalyst price feed
        mappings = self.convex.query(
            "priceFeedMappings:getWatchedPriceFeedMappings",
            {"price_feed": "defianalyst"},
        )

        if not mappings:
            logger.debug("No watched assets with price feed mappings")
            return 0

        # Build lookup: external_id -> asset convex ID
        external_to_asset = {m["external_id"]: m["asset"] for m in mappings}
        external_ids = list(external_to_asset.keys())

        logger.info(f"Polling prices for {len(external_ids)} watched assets")

        # Batch-fetch from CoinGecko (up to 250 per request)
        all_market_data = []
        for i in range(0, len(external_ids), COINGECKO_BATCH_SIZE):
            batch = external_ids[i : i + COINGECKO_BATCH_SIZE]
            try:
                data = await self.coingecko.get_coins_markets(
                    ids=batch,
                    price_change_percentage="24h,7d",
                )
                all_market_data.extend(data)
            except Exception as e:
                logger.error(f"CoinGecko batch fetch failed: {e}", exc_info=True)

        if not all_market_data:
            logger.warning("No market data returned from CoinGecko")
            return 0

        # Build price updates
        now = time.time() * 1000  # epoch ms for Convex
        updates = []
        for coin in all_market_data:
            asset_id = external_to_asset.get(coin.get("id"))
            if not asset_id or coin.get("current_price") is None:
                continue

            update = {
                "asset_id": asset_id,
                "current_price_usd": float(coin["current_price"]),
                "price_updated_at": now,
            }

            pct_24h = coin.get("price_change_percentage_24h_in_currency")
            if pct_24h is not None:
                update["price_change_pct_24h"] = float(pct_24h)

            pct_7d = coin.get("price_change_percentage_7d_in_currency")
            if pct_7d is not None:
                update["price_change_pct_7d"] = float(pct_7d)

            updates.append(update)

        if not updates:
            logger.warning("No valid price updates to write")
            return 0

        # Write to Convex
        updated_count = self.convex.mutation(
            "assets:updateAssetPrices",
            {"updates": updates},
        )
        logger.info(f"Updated prices for {updated_count} assets")

        # Check alerts for updated assets
        updated_asset_ids = [u["asset_id"] for u in updates]
        await self._run_alert_check(updated_asset_ids)

        return updated_count

    async def _run_alert_check(self, asset_ids: list[str]) -> None:
        """Initialize alert checker if needed and check for alerts."""
        if self._alert_checker is None:
            self._alert_checker = self._init_alert_checker()

        if self._alert_checker is None:
            return

        try:
            alerts_sent = await self._alert_checker.check_alerts(asset_ids)
            if alerts_sent > 0:
                logger.info(f"Sent {alerts_sent} price alerts")
        except Exception as e:
            logger.error(f"Alert checker error: {e}", exc_info=True)

    def _init_alert_checker(self) -> Optional[PriceAlertChecker]:
        """Resolve the defianalyst module and price_alert notification type IDs."""
        try:
            module = self.convex.query(
                "notifications:getModuleByName", {"name": "defianalyst"}
            )
            if not module:
                logger.warning("defianalyst module not registered, alerts disabled")
                return None

            module_id = module["_id"]
            notif_type = self.convex.query(
                "notifications:getNotificationTypeByName",
                {"module": module_id, "name": "price_alert"},
            )
            if not notif_type:
                logger.warning("price_alert notification type not registered, alerts disabled")
                return None

            return PriceAlertChecker(self.convex, module_id, notif_type["_id"])
        except Exception as e:
            logger.error(f"Failed to initialize alert checker: {e}", exc_info=True)
            return None

    async def run(self):
        """
        Run the poller continuously at the configured interval.
        Call stop() to terminate.
        """
        self._running = True
        logger.info(
            f"Starting price poller (interval: {POLL_INTERVAL_SECONDS}s)"
        )

        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"Price poller error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        logger.info("Price poller stopped")

    def stop(self):
        """Stop the poller loop."""
        self._running = False

    async def close(self):
        """Clean up resources."""
        self.stop()
        await self.coingecko.close()


_poller_instance: Optional[PricePoller] = None


def get_price_poller(convex_client: ConvexClient) -> PricePoller:
    """Get or create the PricePoller singleton."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = PricePoller(convex_client)
    return _poller_instance
