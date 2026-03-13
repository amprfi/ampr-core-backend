"""
Notification queue processor.

Processes pending notifications from the queue at drain time:
1. Fetch distinct (user, module) pairs with pending-and-due notifications
2. For each pair, fetch all pending items and batch them
3. Synthesize multiple notifications from the same module into one message via LLM
4. Check rate limits before delivery
5. Deliver the synthesized message, marking all constituent items as sent

Priority handling:
- The synthesized message inherits the highest priority from its batch
- Rate limits are checked per-priority tier and per-module
- All rate-limited notifications are dropped regardless of priority
"""
import asyncio
import logging
import time
from typing import Optional
from convex import ConvexClient

from .service import NotificationService
from .synthesizer import synthesize_notifications
from .rate_limits import DEFAULT_RATE_LIMITS, get_rate_limit_for_priority

logger = logging.getLogger(__name__)

PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}


class NotificationQueueProcessor:
    """
    Processes queued notifications with batching, synthesis, and rate limiting.
    """

    def __init__(
        self,
        convex_client: ConvexClient,
        poll_interval_seconds: int = 60,
    ):
        self.convex = convex_client
        self.service = NotificationService(convex_client)
        self.poll_interval = poll_interval_seconds
        self._running = False

    async def process_batch(self) -> int:
        """
        Process all pending-and-due notifications, grouped by (user, module).

        Returns:
            Number of notification groups processed
        """
        try:
            pairs = self.convex.query("notifications:getPendingUserModulePairs", {})

            if not pairs:
                return 0

            logger.info(f"Processing {len(pairs)} (user, module) notification groups")

            processed = 0
            for pair in pairs:
                success = await self._process_user_module_batch(
                    user_id=pair["user"],
                    module_id=pair["module"],
                )
                if success:
                    processed += 1

            logger.info(f"Successfully processed {processed}/{len(pairs)} groups")
            return len(pairs)

        except Exception as e:
            logger.error(f"Error processing notification batch: {e}", exc_info=True)
            return 0

    async def _process_user_module_batch(
        self, user_id: str, module_id: str
    ) -> bool:
        """
        Process all pending notifications for a single (user, module) pair.

        Steps:
        1. Fetch all pending-and-due items for this user+module
        2. Check rate limits
        3. Synthesize if multiple items
        4. Deliver the combined message
        5. Mark all items as sent (or dropped/failed)
        """
        items = self.convex.query("notifications:getPendingByUserModule", {
            "user": user_id,
            "module": module_id,
        })

        if not items:
            return False

        # Check if user still has notifications enabled for this module
        # Use the first item's notification_type for the preference check
        is_enabled = self.convex.query("notifications:isNotificationEnabled", {
            "user": user_id,
            "module": module_id,
            "notification_type": items[0]["notification_type"],
        })

        if not is_enabled:
            logger.info(
                f"Notifications disabled for user {user_id}, module {module_id} — "
                f"cancelling {len(items)} queued notifications"
            )
            for item in items:
                self.convex.mutation("notifications:updateNotificationStatus", {
                    "id": item["_id"],
                    "status": "cancelled",
                    "last_error": "Notification disabled by user preference",
                })
            return False

        # Determine the highest priority in this batch
        batch_priority = max(
            (item.get("priority", "medium") for item in items),
            key=lambda p: PRIORITY_RANK.get(p, 1),
        )

        # Check rate limits — all rate-limited notifications are dropped
        if not self._check_rate_limits(user_id, module_id, batch_priority):
            for item in items:
                self.convex.mutation("notifications:updateNotificationStatus", {
                    "id": item["_id"],
                    "status": "cancelled",
                    "last_error": "Rate limit exceeded — dropped",
                })
            return False

        # Mark all items as sending
        for item in items:
            self.convex.mutation("notifications:updateNotificationStatus", {
                "id": item["_id"],
                "status": "sending",
            })

        try:
            # Synthesize if multiple notifications
            contents = [item["content"] for item in items]
            if len(contents) > 1:
                synthesized_content = await synthesize_notifications(contents)
                logger.info(
                    f"Synthesized {len(contents)} notifications for "
                    f"user {user_id}, module {module_id}"
                )
            else:
                synthesized_content = contents[0]

            # Deliver
            user = self.convex.query("users:getUser", {"userId": user_id})
            if not user:
                self._mark_all_failed(items, "User not found")
                return False

            # Use the first item's notification_type for the message metadata
            notification_type_id = items[0]["notification_type"]

            result = await self.service._deliver_now(
                user_id=user_id,
                user=user,
                module_id=module_id,
                notification_type_id=notification_type_id,
                content=synthesized_content,
            )

            if result.delivered:
                for item in items:
                    self.convex.mutation("notifications:updateNotificationStatus", {
                        "id": item["_id"],
                        "status": "sent",
                    })
                return True
            else:
                self._mark_all_failed(items, result.error or "Delivery failed")
                return False

        except Exception as e:
            logger.error(
                f"Error processing batch for user {user_id}, module {module_id}: {e}",
                exc_info=True,
            )
            self._mark_all_failed(items, str(e))
            return False

    def _check_rate_limits(
        self, user_id: str, module_id: str, priority: str
    ) -> bool:
        """
        Check whether sending a notification would exceed rate limits.

        Checks both per-priority and per-module limits.
        """
        # Use the longest window (24h) for the lookback
        since = int((time.time() - 24 * 3600) * 1000)

        try:
            counts = self.convex.query("notifications:getRecentSentCounts", {
                "user": user_id,
                "since": since,
            })

            by_priority = counts.get("byPriority", {})
            by_module = counts.get("byModule", {})

            # Check per-priority limit
            limit = get_rate_limit_for_priority(priority)
            current_count = by_priority.get(priority, 0)
            if current_count >= limit.max_per_window:
                logger.info(
                    f"Rate limit hit for user {user_id}, priority {priority}: "
                    f"{current_count}/{limit.max_per_window}"
                )
                return False

            # Check per-module limit
            module_count = by_module.get(module_id, 0)
            if module_count >= DEFAULT_RATE_LIMITS.max_per_module_per_day:
                logger.info(
                    f"Module rate limit hit for user {user_id}, module {module_id}: "
                    f"{module_count}/{DEFAULT_RATE_LIMITS.max_per_module_per_day}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Rate limit check failed, allowing delivery: {e}")
            return True

    def _mark_all_failed(self, items: list[dict], error: str):
        """Mark all items in a batch as failed."""
        for item in items:
            self.convex.mutation("notifications:updateNotificationStatus", {
                "id": item["_id"],
                "status": "failed",
                "last_error": error,
            })

    async def run_once(self) -> int:
        """
        Run a single processing cycle.

        Returns:
            Total number of groups processed
        """
        return await self.process_batch()

    async def run(self):
        """
        Run the processor continuously.

        Polls for pending notifications at the configured interval.
        Call stop() to terminate.
        """
        self._running = True
        logger.info(f"Starting notification queue processor (poll interval: {self.poll_interval}s)")

        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Queue processor error: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

        logger.info("Notification queue processor stopped")

    def stop(self):
        """Stop the processor loop."""
        self._running = False


_processor_instance: Optional[NotificationQueueProcessor] = None


def get_queue_processor(convex_client: ConvexClient) -> NotificationQueueProcessor:
    """Get or create the NotificationQueueProcessor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = NotificationQueueProcessor(convex_client)
    return _processor_instance
