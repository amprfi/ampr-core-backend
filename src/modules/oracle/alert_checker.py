"""
Probability alert checker.

Runs after each probability poll cycle to detect prediction events where
market probabilities have shifted past user-defined thresholds and triggers
notifications.

Handles two alert types:
- percentage_24h: fires when any market's 24h probability change exceeds threshold.
  Max once per day.
- percentage_7d: fires when any market's 7d probability change exceeds threshold.
  Max once per week.

Deduplication:
- Per-period: percentage_24h max once/24h, percentage_7d max once/7d.
  Tracked via last_triggered_at on the predictionAlerts row.
- 2x threshold override: when change >= 2x threshold, sends with priority="high".
  Allowed once per cooldown period via override_alerted_at on watchlistEvents.
"""
import logging
import time
from convex import ConvexClient

from ...notifications.service import get_notification_service

logger = logging.getLogger(__name__)

# Cooldown periods in milliseconds
COOLDOWN_24H_MS = 24 * 60 * 60 * 1000
COOLDOWN_7D_MS = 7 * 24 * 60 * 60 * 1000


class ProbabilityAlertChecker:
    """
    Checks updated prediction events against user thresholds and sends notifications.
    """

    def __init__(
        self,
        convex_client: ConvexClient,
        module_id: str,
        notification_type_ids: dict[str, str],
    ):
        """
        Args:
            convex_client: Convex client instance
            module_id: Convex ID of the oracle module
            notification_type_ids: Map of type name -> Convex ID
                e.g. {"probability_change_24h": "...", "probability_change_7d": "..."}
        """
        self.convex = convex_client
        self.module_id = module_id
        self.notification_type_ids = notification_type_ids
        self.notification_service = get_notification_service(convex_client)

    async def check_alerts(self, updated_events: list[dict]) -> int:
        """
        Check all updated events against user thresholds and send alerts.

        Args:
            updated_events: List of event data dicts, each containing:
                - event_id: Convex predictionEvents ID
                - title: Event title
                - slug: Event slug
                - markets: List of market dicts with oneDayPriceChange,
                  oneWeekPriceChange, outcomePrices, question, groupItemTitle

        Returns:
            Number of alerts sent.
        """
        if not updated_events:
            return 0

        alerts_sent = 0

        for event_data in updated_events:
            alerts_sent += await self._check_percentage_alerts(event_data)

        return alerts_sent

    async def _check_percentage_alerts(self, event_data: dict) -> int:
        """Check percentage-based alerts (24h and 7d) for all registered alerts on an event.

        For each alert row, finds the market with the maximum absolute change
        and fires if it exceeds the threshold.
        """
        event_id = event_data["event_id"]
        markets = event_data.get("markets", [])

        if not markets:
            return 0

        # Find max absolute changes across all markets in this event
        max_24h_change = None
        max_24h_market = None
        max_7d_change = None
        max_7d_market = None

        for market in markets:
            day_change = market.get("oneDayPriceChange")
            if day_change is not None:
                if max_24h_change is None or abs(day_change) > abs(max_24h_change):
                    max_24h_change = day_change
                    max_24h_market = market

            week_change = market.get("oneWeekPriceChange")
            if week_change is not None:
                if max_7d_change is None or abs(week_change) > abs(max_7d_change):
                    max_7d_change = week_change
                    max_7d_market = market

        if max_24h_change is None and max_7d_change is None:
            return 0

        # Query predictionAlerts — source of truth for registrations
        alert_rows = self.convex.query(
            "predictionAlerts:getPercentageAlertsByEvent",
            {"event": event_id},
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

            if alert_kind == "percentage_24h":
                pct_change = max_24h_change
                triggering_market = max_24h_market
                cooldown_ms = COOLDOWN_24H_MS
                timeframe_label = "24 hours"
            elif alert_kind == "percentage_7d":
                pct_change = max_7d_change
                triggering_market = max_7d_market
                cooldown_ms = COOLDOWN_7D_MS
                timeframe_label = "7 days"
            else:
                continue

            if pct_change is None or triggering_market is None:
                continue

            if abs(pct_change) < threshold:
                continue

            # Fetch the watchlistEvent for override_alerted_at tracking
            watcher = self.convex.query(
                "watchlistEvents:getWatchlistEvent",
                {"user": user_id, "event": event_id},
            )

            sent = await self._check_single_percentage_alert(
                user_id=user_id,
                event_data=event_data,
                alert_row=alert_row,
                watcher=watcher,
                alert_kind=alert_kind,
                pct_change=pct_change,
                triggering_market=triggering_market,
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
        event_data: dict,
        alert_row: dict,
        watcher: dict | None,
        alert_kind: str,
        pct_change: float,
        triggering_market: dict,
        threshold: float,
        cooldown_ms: int,
        timeframe_label: str,
        now: float,
    ) -> bool:
        """Check a single percentage alert for deduplication and send if eligible."""
        if alert_row.get("last_triggered_at") is not None:
            elapsed = now - alert_row["last_triggered_at"]
            if elapsed < cooldown_ms:
                # In cooldown — check for 2x override
                override_alerted_at = watcher.get("override_alerted_at") if watcher else None
                if abs(pct_change) >= threshold * 2 and override_alerted_at is None:
                    return await self._send_percentage_alert(
                        user_id=user_id,
                        event_data=event_data,
                        alert_kind=alert_kind,
                        alert_row=alert_row,
                        watcher=watcher,
                        pct_change=pct_change,
                        triggering_market=triggering_market,
                        threshold=threshold,
                        timeframe_label=timeframe_label,
                        now=now,
                        is_override=True,
                    )
                return False

        return await self._send_percentage_alert(
            user_id=user_id,
            event_data=event_data,
            alert_kind=alert_kind,
            alert_row=alert_row,
            watcher=watcher,
            pct_change=pct_change,
            triggering_market=triggering_market,
            threshold=threshold,
            timeframe_label=timeframe_label,
            now=now,
            is_override=False,
        )

    async def _send_percentage_alert(
        self,
        user_id: str,
        event_data: dict,
        alert_kind: str,
        alert_row: dict,
        watcher: dict | None,
        pct_change: float,
        triggering_market: dict,
        threshold: float,
        timeframe_label: str,
        now: float,
        is_override: bool,
    ) -> bool:
        """Format and send a percentage alert. Returns True if successful."""
        type_name = (
            "probability_change_24h" if alert_kind == "percentage_24h"
            else "probability_change_7d"
        )
        notification_type_id = self.notification_type_ids.get(type_name)
        if not notification_type_id:
            return False

        # 2x threshold → high priority override
        priority = "high" if abs(pct_change) >= threshold * 2 else None

        content = self._format_percentage_alert(
            event_data, triggering_market, pct_change, threshold, timeframe_label
        )

        result = await self.notification_service.send(
            user_id=user_id,
            module_id=self.module_id,
            notification_type_id=notification_type_id,
            content=content,
            priority=priority,
        )

        if result.success:
            # Stamp last_triggered_at on the alert row
            self.convex.mutation("predictionAlerts:stampTriggered", {
                "id": alert_row["_id"],
                "last_triggered_at": now,
            })

            # Stamp override on watchlistEvent (if it exists)
            if watcher:
                self.convex.mutation("watchlistEvents:stampAlerted", {
                    "id": watcher["_id"],
                    "last_alerted_at": now,
                    "is_override": is_override,
                })

            logger.info(
                f"{'Override alert' if is_override else 'Alert'} sent to user {user_id} "
                f"for {event_data.get('title', event_data['event_id'])}: "
                f"{alert_kind}={pct_change:.4f}"
                f"{' (priority=high)' if priority == 'high' else ''}"
            )
            return True

        return False

    def _format_percentage_alert(
        self,
        event_data: dict,
        triggering_market: dict,
        pct_change: float,
        threshold: float,
        timeframe_label: str,
    ) -> str:
        """Format a percentage probability alert message."""
        event_title = event_data.get("title", "Unknown Event")
        market_name = (
            triggering_market.get("groupItemTitle")
            or triggering_market.get("question")
            or "Unknown Market"
        )

        # Current probability from outcomePrices (first outcome = "Yes" probability)
        outcome_prices = triggering_market.get("outcomePrices", [])
        if outcome_prices:
            try:
                current_prob = float(outcome_prices[0])
                current_prob_str = f"{current_prob:.0%}"
            except (ValueError, IndexError):
                current_prob_str = "N/A"
        else:
            current_prob_str = "N/A"

        direction = "up" if pct_change >= 0 else "down"
        change_str = f"{direction} {abs(pct_change):.2%}"
        threshold_str = f"{threshold:.0%}"

        return (
            f"{event_title} — {market_name} probability shifted {change_str}, "
            f"now at {current_prob_str}. "
            f"This crossed your {threshold_str} alert threshold "
            f"over the past {timeframe_label}."
        )
