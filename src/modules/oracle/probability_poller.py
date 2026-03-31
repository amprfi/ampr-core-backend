"""
Probability poller service.

Periodically fetches live market data from Polymarket for all watched
prediction events and triggers probability alert checks.
"""
import asyncio
import logging
from typing import Optional
from convex import ConvexClient

from .polymarket_client import PolymarketClient
from .alert_checker import ProbabilityAlertChecker

logger = logging.getLogger(__name__)

# Poll every hour
POLL_INTERVAL_SECONDS = 3600


class ProbabilityPoller:
    """
    Polls Polymarket for live market data on watched prediction events
    and triggers probability alert checks.

    Uses the watchlistEvents table to determine which events have watchers,
    then fetches live data from Polymarket via event slug.
    """

    def __init__(self, convex_client: ConvexClient):
        self.convex = convex_client
        self.polymarket = PolymarketClient()
        self._running = False
        self._alert_checker: Optional[ProbabilityAlertChecker] = None

    async def poll_once(self) -> int:
        """
        Run a single poll cycle: fetch watched events, get live data, check alerts.

        Returns:
            Number of events polled.
        """
        # Get all distinct watched event IDs from watchlistEvents
        watched_entries = self.convex.query(
            "watchlistEvents:getDistinctWatchedEventIds", {}
        )

        if not watched_entries:
            logger.debug("No watched prediction events")
            return 0

        event_ids = watched_entries
        logger.info(f"Polling probabilities for {len(event_ids)} watched events")

        events_data = []
        for event_id in event_ids:
            # Get the predictionEvent record for the slug
            prediction_event = self.convex.query(
                "predictionEvents:getEvent", {"id": event_id}
            )
            if not prediction_event:
                logger.warning(f"Prediction event {event_id} not found in DB")
                continue

            slug = prediction_event.get("slug")
            if not slug:
                logger.warning(f"Prediction event {event_id} has no slug")
                continue

            try:
                live_data = await self.polymarket.get_event_by_slug(slug)
            except Exception as e:
                logger.error(
                    f"Failed to fetch Polymarket data for {slug}: {e}",
                    exc_info=True,
                )
                continue

            # Build event data dict from live Polymarket response
            markets = []
            for market in live_data.get("markets", []):
                market_data: dict = {
                    "question": market.get("question"),
                    "groupItemTitle": market.get("groupItemTitle"),
                    "outcomePrices": market.get("outcomePrices", []),
                }
                # Polymarket may return price changes as strings
                raw_1d = market.get("oneDayPriceChange")
                raw_1w = market.get("oneWeekPriceChange")
                try:
                    market_data["oneDayPriceChange"] = float(raw_1d) if raw_1d is not None else None
                except (ValueError, TypeError):
                    market_data["oneDayPriceChange"] = None
                try:
                    market_data["oneWeekPriceChange"] = float(raw_1w) if raw_1w is not None else None
                except (ValueError, TypeError):
                    market_data["oneWeekPriceChange"] = None

                markets.append(market_data)

            events_data.append({
                "event_id": event_id,
                "title": live_data.get("title", prediction_event.get("title", "")),
                "slug": slug,
                "markets": markets,
            })

        if not events_data:
            logger.warning("No live event data fetched from Polymarket")
            return 0

        logger.info(f"Fetched live data for {len(events_data)} events")

        # Check alerts for all updated events
        await self._run_alert_check(events_data)

        return len(events_data)

    async def _run_alert_check(self, events_data: list[dict]) -> None:
        """Initialize alert checker if needed and check for alerts."""
        if self._alert_checker is None:
            self._alert_checker = self._init_alert_checker()

        if self._alert_checker is None:
            return

        try:
            alerts_sent = await self._alert_checker.check_alerts(events_data)
            if alerts_sent > 0:
                logger.info(f"Sent {alerts_sent} probability alerts")
        except Exception as e:
            logger.error(f"Alert checker error: {e}", exc_info=True)

    def _init_alert_checker(self) -> Optional[ProbabilityAlertChecker]:
        """Resolve the oracle module and notification type IDs."""
        try:
            module = self.convex.query(
                "notifications:getModuleByName", {"name": "oracle"}
            )
            if not module:
                logger.warning("oracle module not registered, alerts disabled")
                return None

            module_id = module["_id"]

            type_names = ["probability_change_24h", "probability_change_7d"]
            notification_type_ids: dict[str, str] = {}

            for name in type_names:
                notif_type = self.convex.query(
                    "notifications:getNotificationTypeByName",
                    {"module": module_id, "name": name},
                )
                if notif_type:
                    notification_type_ids[name] = notif_type["_id"]
                else:
                    logger.warning(f"Notification type '{name}' not registered")

            if not notification_type_ids:
                logger.warning("No notification types registered, alerts disabled")
                return None

            return ProbabilityAlertChecker(self.convex, module_id, notification_type_ids)
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
            f"Starting probability poller (interval: {POLL_INTERVAL_SECONDS}s)"
        )

        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"Probability poller error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        logger.info("Probability poller stopped")

    def stop(self):
        """Stop the poller loop."""
        self._running = False

    async def close(self):
        """Clean up resources."""
        self.stop()
        await self.polymarket.close()


_poller_instance: Optional[ProbabilityPoller] = None


def get_probability_poller(convex_client: ConvexClient) -> ProbabilityPoller:
    """Get or create the ProbabilityPoller singleton."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = ProbabilityPoller(convex_client)
    return _poller_instance
