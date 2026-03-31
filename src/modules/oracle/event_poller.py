"""
Oracle event poller service.

Periodically fetches prediction events from Polymarket based on configured
tag slugs and upserts them into the predictionEvents table.

Two-pass approach:
  1. Fetch active events from Polymarket by tags, filter out ephemeral
     ("5m") events, and upsert them.
  2. Lifecycle management: re-fetch expired active events from the API to
     get final data, then apply retention rules (mark historical or delete)
     based on tags and endDate.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from convex import ConvexClient

from .polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)

# Poll once per day
POLL_INTERVAL_SECONDS = 24 * 60 * 60

# Convex mutations have document limits; batch in groups
BATCH_SIZE = 50

# Max concurrent Polymarket API requests during lifecycle pass
LIFECYCLE_CONCURRENCY = 10

# Tags that indicate short-lived events
EPHEMERAL_TAGS = {"5m"}
SHORT_LIVED_TAGS = {"daily", "up-or-down"}

# Retention thresholds (days past endDate)
SHORT_LIVED_RETENTION_DAYS = 7
HISTORICAL_THRESHOLD_DAYS = 30

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_tags() -> list[str]:
    """Load tag slugs from the oracle config file."""
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    return config.get("tags", [])


def _has_any_tag(tags: list[str] | None, target: set[str]) -> bool:
    """Check if any of the event's tags match the target set (case-insensitive)."""
    if not tags:
        return False
    return bool({t.lower() for t in tags} & target)


def _days_since_end(end_date_str: str | None) -> float | None:
    """Return the number of days since the event's endDate, or None."""
    if not end_date_str:
        return None
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - end_dt
        return delta.total_seconds() / 86400
    except (ValueError, TypeError):
        return None


class EventPoller:
    """
    Polls Polymarket for prediction events matching configured tags
    and upserts them into the predictionEvents table.
    """

    def __init__(self, convex_client: ConvexClient):
        self.convex = convex_client
        self.polymarket = PolymarketClient()
        self._running = False

    async def poll_once(self) -> int:
        """
        Run a single poll cycle: fetch and upsert events, then run lifecycle.

        Returns:
            Number of events processed in pass 1.
        """
        tags = _load_tags()
        if not tags:
            logger.warning("No tags configured for oracle event poller")
            return 0

        logger.info(f"Polling Polymarket events for {len(tags)} tags")

        # --- Pass 1: fetch active events and upsert ---
        events = await self.polymarket.get_events_by_tags(tags, active=True)
        if not events:
            logger.info("No events returned from Polymarket")
            return 0

        # Build upsert records, filtering out ephemeral (5m) events
        records = []
        for event in events:
            event_id = event.get("id")
            slug = event.get("slug")
            title = event.get("title")

            if not event_id or not slug or not title:
                continue

            # Tags may come as objects or plain strings from Polymarket
            raw_tags = event.get("tags")
            tag_slugs = None
            if raw_tags and isinstance(raw_tags, list):
                tag_slugs = [
                    t["slug"] if isinstance(t, dict) and "slug" in t else t
                    for t in raw_tags
                    if isinstance(t, (str, dict))
                ]

            # Skip ephemeral events
            if _has_any_tag(tag_slugs, EPHEMERAL_TAGS):
                continue

            record = {
                "polymarketId": str(event_id),
                "slug": slug,
                "title": title,
                "active": not event.get("closed", False),
                "closed": event.get("closed", False),
            }
            if event.get("description"):
                record["description"] = event["description"]
            if tag_slugs:
                record["tags"] = tag_slugs
            if event.get("endDate"):
                record["endDate"] = event["endDate"]

            records.append(record)

        if not records:
            logger.warning("No valid events to upsert")
            return 0

        # Batch upsert
        total_created = 0
        total_updated = 0

        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            try:
                result = self.convex.mutation(
                    "predictionEvents:bulkUpsertEvents",
                    {"events": batch},
                )
                total_created += result.get("created", 0)
                total_updated += result.get("updated", 0)
            except Exception as e:
                logger.error(
                    f"Failed to upsert batch {i // BATCH_SIZE + 1}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Pass 1 complete: {total_created} created, "
            f"{total_updated} updated, {len(records)} total"
        )

        # --- Pass 2: lifecycle management ---
        await self._run_lifecycle()

        return len(records)

    async def _run_lifecycle(self):
        """
        Manage event lifecycle:
        1. Active events past endDate → re-fetch from API, upsert final data
        2. Inactive events past retention → mark historical or delete
        """
        # Step 1: find active events with expired endDate and close them
        await self._close_expired_events()

        # Step 2: apply retention rules to inactive events
        await self._apply_retention_rules()

    async def _close_expired_events(self):
        """
        For active events whose endDate has passed, re-fetch from Polymarket
        to get final resolved data and upsert (which will set active=False).
        """
        active_events = self.convex.query("predictionEvents:getActiveEvents")
        if not active_events:
            return

        expired = [
            e for e in active_events
            if _days_since_end(e.get("endDate")) is not None
            and _days_since_end(e.get("endDate")) > 0
        ]

        if not expired:
            logger.info("No expired active events to close")
            return

        logger.info(f"Closing {len(expired)} expired active events")

        semaphore = asyncio.Semaphore(LIFECYCLE_CONCURRENCY)
        to_upsert: list[dict] = []

        async def fetch_final(event: dict):
            slug = event.get("slug")
            if not slug:
                return
            async with semaphore:
                try:
                    live = await self.polymarket.get_event_by_slug(slug)

                    raw_tags = live.get("tags")
                    tag_slugs = None
                    if raw_tags and isinstance(raw_tags, list):
                        tag_slugs = [
                            t["slug"] if isinstance(t, dict) and "slug" in t else t
                            for t in raw_tags
                            if isinstance(t, (str, dict))
                        ]

                    upsert_record = {
                        "polymarketId": str(live.get("id", event["polymarketId"])),
                        "slug": slug,
                        "title": live.get("title", event.get("title", "")),
                        "active": not live.get("closed", False),
                        "closed": live.get("closed", False),
                    }
                    if live.get("description"):
                        upsert_record["description"] = live["description"]
                    if tag_slugs:
                        upsert_record["tags"] = tag_slugs
                    if live.get("endDate"):
                        upsert_record["endDate"] = live["endDate"]

                    to_upsert.append(upsert_record)
                except Exception as e:
                    logger.warning(f"Failed to fetch final data for '{slug}': {e}")

        await asyncio.gather(*[fetch_final(e) for e in expired])

        if not to_upsert:
            return

        for i in range(0, len(to_upsert), BATCH_SIZE):
            batch = to_upsert[i : i + BATCH_SIZE]
            try:
                self.convex.mutation(
                    "predictionEvents:bulkUpsertEvents",
                    {"events": batch},
                )
            except Exception as e:
                logger.error(f"Failed to upsert expired batch: {e}", exc_info=True)

        logger.info(f"Closed {len(to_upsert)} expired events with final data")

    async def _apply_retention_rules(self):
        """
        Apply retention rules to inactive, non-historical events:
        - Short-lived tags ("daily", "up-or-down") + endDate > 7 days → delete
        - All others + endDate > 30 days → mark historical
        """
        # Paginate through all inactive, non-historical events
        all_inactive: list[dict] = []
        cursor = None
        while True:
            result = self.convex.query(
                "predictionEvents:getInactiveEvents",
                {"paginationOpts": {"numItems": 500, "cursor": cursor}},
            )
            all_inactive.extend(result["page"])
            if result["isDone"]:
                break
            cursor = result["continueCursor"]

        if not all_inactive:
            logger.info("No inactive events for retention processing")
            return

        to_delete: list[str] = []
        to_historicise: list[str] = []

        for event in all_inactive:
            days = _days_since_end(event.get("endDate"))
            if days is None:
                continue

            tags = event.get("tags")
            event_id = event["_id"]

            if _has_any_tag(tags, SHORT_LIVED_TAGS) and days > SHORT_LIVED_RETENTION_DAYS:
                to_delete.append(event_id)
            elif days > HISTORICAL_THRESHOLD_DAYS:
                to_historicise.append(event_id)

        if to_delete:
            for i in range(0, len(to_delete), BATCH_SIZE):
                batch = to_delete[i : i + BATCH_SIZE]
                try:
                    self.convex.mutation(
                        "predictionEvents:deleteEvents",
                        {"ids": batch},
                    )
                except Exception as e:
                    logger.error(f"Failed to delete events batch: {e}", exc_info=True)
            logger.info(f"Deleted {len(to_delete)} short-lived events")

        if to_historicise:
            for i in range(0, len(to_historicise), BATCH_SIZE):
                batch = to_historicise[i : i + BATCH_SIZE]
                try:
                    self.convex.mutation(
                        "predictionEvents:markEventsHistorical",
                        {"ids": batch},
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to mark events historical: {e}", exc_info=True
                    )
            logger.info(f"Marked {len(to_historicise)} events as historical")

    async def run(self):
        """
        Run the poller continuously at the configured interval.
        Call stop() to terminate.

        Set DISABLE_EVENT_POLLER=true to skip polling entirely.
        """
        if os.getenv("DISABLE_EVENT_POLLER", "").lower() in ("true", "1", "yes"):
            logger.info("Oracle event poller disabled via DISABLE_EVENT_POLLER")
            return

        self._running = True
        logger.info(
            f"Starting oracle event poller (interval: {POLL_INTERVAL_SECONDS}s)"
        )

        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"Oracle event poller error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        logger.info("Oracle event poller stopped")

    def stop(self):
        """Stop the poller loop."""
        self._running = False

    async def close(self):
        """Clean up resources."""
        self.stop()
        await self.polymarket.close()


_poller_instance: Optional[EventPoller] = None


def get_event_poller(convex_client: ConvexClient) -> EventPoller:
    """Get or create the EventPoller singleton."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = EventPoller(convex_client)
    return _poller_instance
