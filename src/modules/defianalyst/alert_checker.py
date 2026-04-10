"""
Price alert checker.

Runs after each price poll cycle to detect assets that have crossed
user-defined thresholds and triggers notifications.

Handles three alert types:
- percentage_24h: fires when 24h price change exceeds threshold. Max once per day.
- percentage_7d: fires when 7d price change exceeds threshold. Max once per week.
- absolute_price: fires when price crosses target in specified direction.
  One-shot — the alert row is deleted from DB on trigger.

Deduplication:
- Per-period: percentage_24h max once/24h, percentage_7d max once/7d.
  Tracked via last_triggered_at on the priceAlerts row.
- 2x threshold override: when change >= 2x threshold, sends with priority="high".
  Allowed once per cooldown period via override_alerted_at on portfolioItems.
"""
import logging
import time
from convex import ConvexClient

from ...notifications.service import get_notification_service
from .utils import format_price

logger = logging.getLogger(__name__)

# Cooldown periods in milliseconds
COOLDOWN_24H_MS = 24 * 60 * 60 * 1000
COOLDOWN_7D_MS = 7 * 24 * 60 * 60 * 1000

# Grace period after alert creation during which non-high-priority notifications
# are suppressed. Prevents a spurious immediate fire when the asset's rolling
# price-change window already exceeded the threshold before the alert was set.
GRACE_PERIOD_MS = 4 * 60 * 60 * 1000


class PriceAlertChecker:
    """
    Checks updated assets against user thresholds and sends notifications.
    """

    def __init__(
        self,
        convex_client: ConvexClient,
        module_id: str,
        notification_type_ids: dict[str, str],
        notification_type_priorities: dict[str, str],
    ):
        """
        Args:
            convex_client: Convex client instance
            module_id: Convex ID of the defianalyst module
            notification_type_ids: Map of type name -> Convex ID
                e.g. {"price_change_24h": "...", "price_change_7d": "...", "price_threshold": "..."}
            notification_type_priorities: Map of type name -> priority string
                e.g. {"price_change_24h": "medium", "price_change_7d": "medium", "price_threshold": "high"}
        """
        self.convex = convex_client
        self.module_id = module_id
        self.notification_type_ids = notification_type_ids
        self.notification_type_priorities = notification_type_priorities
        self.notification_service = get_notification_service(convex_client)

    async def check_alerts(self, updated_asset_ids: list[str]) -> int:
        """
        Check all updated assets against user thresholds and send alerts.

        Returns:
            Number of alerts sent.
        """
        if not updated_asset_ids:
            return 0

        alerts_sent = 0

        for asset_id in updated_asset_ids:
            asset = self.convex.query("assets:getAsset", {"id": asset_id})
            if not asset:
                continue

            # Check percentage alerts
            alerts_sent += await self._check_percentage_alerts(asset_id, asset)

            # Check absolute price alerts
            alerts_sent += await self._check_absolute_price_alerts(asset_id, asset)

        return alerts_sent

    async def _check_percentage_alerts(self, asset_id: str, asset: dict) -> int:
        """Check percentage-based alerts (24h and 7d) for all registered alerts on an asset.

        Uses priceAlerts as the source of truth — only user+asset combos with
        registered alert rows will be checked.
        """
        pct_24h = asset.get("price_change_pct_24h")
        pct_7d = asset.get("price_change_pct_7d")

        if pct_24h is None and pct_7d is None:
            return 0

        # Query priceAlerts directly — this is the source of truth for registrations
        alert_rows = self.convex.query(
            "priceAlerts:getPercentageAlertsByAsset",
            {"asset": asset_id},
        )

        if not alert_rows:
            return 0

        now = time.time() * 1000
        alerts_sent = 0

        for alert_row in alert_rows:
            alert_kind = alert_row["alert_kind"]
            threshold = alert_row.get("threshold_pct")
            user_id = alert_row["user"]

            if threshold is None:
                continue

            # Pick the relevant price change for this alert kind
            if alert_kind == "percentage_24h":
                pct_change = pct_24h
                cooldown_ms = COOLDOWN_24H_MS
                timeframe_label = "1 day ago"
            elif alert_kind == "percentage_7d":
                pct_change = pct_7d
                cooldown_ms = COOLDOWN_7D_MS
                timeframe_label = "1 week ago"
            else:
                continue

            if pct_change is None or abs(pct_change) < threshold:
                continue

            # Fetch the portfolioItem for override_alerted_at tracking
            watcher = self.convex.query(
                "portfolioItems:getPortfolioItem",
                {"user": user_id, "asset": asset_id},
            )

            sent = await self._check_single_percentage_alert(
                user_id=user_id,
                asset_id=asset_id,
                asset=asset,
                alert_row=alert_row,
                watcher=watcher,
                alert_kind=alert_kind,
                pct_change=pct_change,
                threshold=threshold,
                cooldown_ms=cooldown_ms,
                timeframe_label=timeframe_label,
                now=now,
            )
            if sent:
                alerts_sent += 1

        return alerts_sent

    async def _check_single_percentage_alert(
        self,
        user_id: str,
        asset_id: str,
        asset: dict,
        alert_row: dict,
        watcher: dict | None,
        alert_kind: str,
        pct_change: float,
        threshold: float,
        cooldown_ms: int,
        timeframe_label: str,
        now: float,
    ) -> bool:
        """Check a single percentage alert for deduplication and send if eligible."""
        # Resolve effective priority for this alert:
        # 2x threshold → always "high"; otherwise use the notification type's default.
        type_name = "price_change_24h" if alert_kind == "percentage_24h" else "price_change_7d"
        default_priority = self.notification_type_priorities.get(type_name, "medium")
        priority = "high" if abs(pct_change) >= threshold * 2 else default_priority

        # Grace period suppression: within the first GRACE_PERIOD_MS after the alert
        # was created, only send high-priority notifications. This prevents a spurious
        # immediate notification caused by price movement that predates the alert.
        created_at = alert_row.get("_creationTime")
        if created_at is not None and (now - created_at < GRACE_PERIOD_MS):
            if priority != "high":
                return False

        if alert_row.get("last_triggered_at") is not None:
            elapsed = now - alert_row["last_triggered_at"]
            if elapsed < cooldown_ms:
                # In cooldown — allow a one-time high-priority override
                override_alerted_at = watcher.get("override_alerted_at") if watcher else None
                if priority == "high" and override_alerted_at is None:
                    return await self._send_percentage_alert(
                        user_id=user_id,
                        asset_id=asset_id,
                        asset=asset,
                        alert_kind=alert_kind,
                        alert_row=alert_row,
                        watcher=watcher,
                        pct_change=pct_change,
                        threshold=threshold,
                        timeframe_label=timeframe_label,
                        now=now,
                        priority=priority,
                        is_override=True,
                    )
                return False

        return await self._send_percentage_alert(
            user_id=user_id,
            asset_id=asset_id,
            asset=asset,
            alert_kind=alert_kind,
            alert_row=alert_row,
            watcher=watcher,
            pct_change=pct_change,
            threshold=threshold,
            timeframe_label=timeframe_label,
            now=now,
            priority=priority,
            is_override=False,
        )

    async def _send_percentage_alert(
        self,
        user_id: str,
        asset_id: str,
        asset: dict,
        alert_kind: str,
        alert_row: dict,
        watcher: dict | None,
        pct_change: float,
        threshold: float,
        timeframe_label: str,
        now: float,
        priority: str,
        is_override: bool,
    ) -> bool:
        """Format and send a percentage alert. Returns True if successful."""
        type_name = "price_change_24h" if alert_kind == "percentage_24h" else "price_change_7d"
        notification_type_id = self.notification_type_ids.get(type_name)
        if not notification_type_id:
            return False

        content = self._format_percentage_alert(
            asset, pct_change, threshold, timeframe_label
        )

        result = await self.notification_service.send(
            user_id=user_id,
            module_id=self.module_id,
            notification_type_id=notification_type_id,
            content=content,
            asset_ref=asset_id,
            priority=priority,
        )

        if result.success:
            # Stamp last_triggered_at on the alert row
            self.convex.mutation("priceAlerts:stampTriggered", {
                "id": alert_row["_id"],
                "last_triggered_at": now,
            })

            # Stamp override on portfolioItem (if it exists)
            if watcher:
                self.convex.mutation("portfolioItems:stampAlerted", {
                    "id": watcher["_id"],
                    "last_alerted_at": now,
                    "is_override": is_override,
                })

            logger.info(
                f"{'Override alert' if is_override else 'Alert'} sent to user {user_id} "
                f"for {asset.get('name', asset_id)}: {alert_kind}={pct_change:.2f}%"
                f"{' (priority=high)' if priority == 'high' else ''}"
            )
            return True

        return False

    async def _check_absolute_price_alerts(self, asset_id: str, asset: dict) -> int:
        """Check absolute price alerts for an asset."""
        current_price = asset.get("current_price_usd")
        if current_price is None:
            return 0

        alerts = self.convex.query(
            "priceAlerts:getAbsolutePriceAlerts",
            {"asset": asset_id},
        )

        if not alerts:
            return 0

        notification_type_id = self.notification_type_ids.get("price_threshold")
        if not notification_type_id:
            return 0

        alerts_sent = 0

        for alert in alerts:
            target_price = alert.get("target_price")
            direction = alert.get("direction")

            if target_price is None or direction is None:
                continue

            triggered = (
                (direction == "above" and current_price >= target_price) or
                (direction == "below" and current_price <= target_price)
            )

            if not triggered:
                continue

            content = self._format_absolute_alert(asset, current_price, target_price, direction)

            result = await self.notification_service.send(
                user_id=alert["user"],
                module_id=self.module_id,
                notification_type_id=notification_type_id,
                content=content,
                asset_ref=asset_id,
                priority="high",
            )

            if result.success:
                # One-shot: delete the alert row on trigger
                self.convex.mutation("priceAlerts:removeAlert", {"id": alert["_id"]})
                alerts_sent += 1
                logger.info(
                    f"Absolute price alert triggered for user {alert['user']}: "
                    f"{asset.get('name', asset_id)} crossed ${target_price} ({direction})"
                )

        return alerts_sent

    def _format_percentage_alert(
        self, asset: dict, pct_change: float, threshold: float, timeframe_label: str
    ) -> str:
        """Format a percentage price alert message."""
        name = asset.get("name", "Unknown")
        ticker = asset.get("ticker", "")
        price = asset.get("current_price_usd")

        label = f"{name} ({ticker})" if ticker else name
        price_str = format_price(price) if price else "N/A"

        direction = "up" if pct_change >= 0 else "down"
        threshold_str = f"{threshold:g}"

        return (
            f"{label} just crossed your {threshold_str}% alert threshold, "
            f"it's now trading at {price_str}, "
            f"{direction} {abs(pct_change):.2f}% from {timeframe_label}."
        )

    def _format_absolute_alert(
        self, asset: dict, current_price: float, target_price: float, direction: str
    ) -> str:
        """Format an absolute price alert message."""
        name = asset.get("name", "Unknown")
        ticker = asset.get("ticker", "")

        label = f"{name} ({ticker})" if ticker else name
        current_str = format_price(current_price)
        target_str = format_price(target_price)

        return (
            f"{label} has crossed your price target of {target_str}, "
            f"it's now trading at {current_str}."
        )
