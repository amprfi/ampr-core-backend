"""
Price alert checker.

Runs after each price poll cycle to detect assets that have crossed
user-defined thresholds and triggers notifications.

Deduplication rules:
- After alerting, a 24-hour cooldown prevents repeat alerts for the same user+asset.
- If the price change reaches 2x the threshold, the cooldown is bypassed.
"""
import logging
import time
from convex import ConvexClient

from ...notifications.service import get_notification_service

logger = logging.getLogger(__name__)

# Cooldown period before re-alerting the same user+asset (24 hours in ms)
ALERT_COOLDOWN_MS = 24 * 60 * 60 * 1000


class PriceAlertChecker:
    """
    Checks updated assets against user thresholds and sends notifications.
    """

    def __init__(self, convex_client: ConvexClient, module_id: str, notification_type_id: str):
        self.convex = convex_client
        self.module_id = module_id
        self.notification_type_id = notification_type_id
        self.notification_service = get_notification_service(convex_client)

    async def check_alerts(self, updated_asset_ids: list[str]) -> int:
        """
        Check all updated assets against user thresholds and send alerts.

        Args:
            updated_asset_ids: List of Convex asset IDs that were just updated.

        Returns:
            Number of alerts sent.
        """
        if not updated_asset_ids:
            return 0

        alerts_sent = 0
        now = time.time() * 1000

        for asset_id in updated_asset_ids:
            asset = self.convex.query("assets:getAsset", {"id": asset_id})
            if not asset:
                continue

            pct_24h = asset.get("price_change_pct_24h")
            pct_7d = asset.get("price_change_pct_7d")

            # Skip if no price change data
            if pct_24h is None and pct_7d is None:
                continue

            # Get all users watching this asset
            watchers = self.convex.query(
                "portfolioItems:getWatchersByAsset",
                {"asset": asset_id},
            )

            if not watchers:
                continue

            for watcher in watchers:
                user_id = watcher["user"]
                last_alerted_at = watcher.get("last_alerted_at")

                # Resolve effective threshold for this user+asset
                threshold = self.convex.query(
                    "alertThresholds:getEffectiveThreshold",
                    {"user": user_id, "asset": asset_id},
                )

                # Determine the max absolute change across timeframes
                max_change = max(
                    abs(pct_24h) if pct_24h is not None else 0,
                    abs(pct_7d) if pct_7d is not None else 0,
                )

                if max_change < threshold:
                    continue

                # Deduplication: check cooldown
                in_cooldown = (
                    last_alerted_at is not None
                    and (now - last_alerted_at) < ALERT_COOLDOWN_MS
                )

                if in_cooldown:
                    # Bypass cooldown only if change is 2x the threshold
                    if max_change < threshold * 2:
                        continue

                # Build and send alert
                content = self._format_alert(asset, pct_24h, pct_7d, threshold)
                result = await self.notification_service.send(
                    user_id=user_id,
                    module_id=self.module_id,
                    notification_type_id=self.notification_type_id,
                    content=content,
                )

                if result.success:
                    # Stamp last_alerted_at
                    self.convex.mutation(
                        "portfolioItems:stampAlerted",
                        {"id": watcher["_id"], "last_alerted_at": now},
                    )
                    alerts_sent += 1
                    logger.info(
                        f"Alert sent to user {user_id} for {asset.get('name', asset_id)}: "
                        f"24h={pct_24h}%, 7d={pct_7d}%"
                    )

        return alerts_sent

    def _format_alert(
        self, asset: dict, pct_24h: float | None, pct_7d: float | None, threshold: float
    ) -> str:
        """Format a price alert message."""
        name = asset.get("name", "Unknown")
        ticker = asset.get("ticker", "")
        price = asset.get("current_price_usd")

        label = f"{name} ({ticker})" if ticker else name
        price_str = f"${price:,.2f}" if price and price >= 0.01 else f"${price:.6f}" if price else "N/A"

        # Determine which timeframe triggered and pick the most significant
        triggered_24h = pct_24h is not None and abs(pct_24h) >= threshold
        triggered_7d = pct_7d is not None and abs(pct_7d) >= threshold

        if triggered_24h and triggered_7d:
            # Use whichever has the larger absolute change
            if abs(pct_24h) >= abs(pct_7d):
                pct = pct_24h
                timeframe = "1 day ago"
            else:
                pct = pct_7d
                timeframe = "1 week ago"
        elif triggered_24h:
            pct = pct_24h
            timeframe = "1 day ago"
        else:
            pct = pct_7d
            timeframe = "1 week ago"

        direction = "up" if pct >= 0 else "down"
        threshold_str = f"{threshold:g}"

        return (
            f"{label} just crossed your {threshold_str}% alert threshold, "
            f"it's now trading at {price_str}, "
            f"{direction} {abs(pct):.2f}% from {timeframe}."
        )
