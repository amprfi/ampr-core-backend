"""
Interest expiration background job.

Scans for inferred watches that haven't been mentioned in 30+ days
and cleans them up:
1. Calls each associated module's deregistration endpoint to remove alerts
2. Deletes the portfolioItem

Only inferred watches expire — stated watches and owned assets are never touched.
No user notification is sent on expiration.
"""
import asyncio
import logging
from typing import Optional
from convex import ConvexClient

logger = logging.getLogger(__name__)

# Run expiration check every 6 hours
EXPIRATION_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


class InterestExpirationJob:
    """
    Background job that expires stale inferred watches.
    """

    def __init__(self, convex_client: ConvexClient):
        self.convex = convex_client
        self._running = False

    async def run_once(self) -> int:
        """
        Run a single expiration cycle.

        Returns:
            Number of expired interests removed.
        """
        try:
            expired_items = self.convex.query(
                "portfolioItems:getExpiredInferredWatches", {}
            )

            if not expired_items:
                logger.debug("No expired inferred watches found")
                return 0

            logger.info(f"Found {len(expired_items)} expired inferred watches")

            removed = 0
            for item in expired_items:
                try:
                    await self._expire_item(item)
                    removed += 1
                except Exception as e:
                    logger.error(
                        f"Error expiring interest {item['_id']}: {e}",
                        exc_info=True,
                    )

            logger.info(f"Expired {removed}/{len(expired_items)} inferred watches")
            return removed

        except Exception as e:
            logger.error(f"Error running expiration check: {e}", exc_info=True)
            return 0

    async def _expire_item(self, item: dict) -> None:
        """
        Expire a single inferred watch:
        1. Deregister notifications from each associated module
        2. Delete the portfolioItem
        """
        user_id = item["user"]
        asset_id = item["asset"]
        notification_modules = item.get("notification_modules") or []

        # Deregister from each associated module
        for module_id in notification_modules:
            try:
                module_record = self.convex.query(
                    "notifications:getModule", {"id": module_id}
                )
                if not module_record:
                    continue

                module_name = module_record.get("name")
                await self._deregister_from_module(module_name, user_id, asset_id)
            except Exception as e:
                logger.error(
                    f"Error deregistering module {module_id} for "
                    f"user {user_id}, asset {asset_id}: {e}",
                )

        # Remove the portfolioItem
        self.convex.mutation("portfolioItems:removeFromWatchlist", {
            "user": user_id,
            "asset": asset_id,
        })
        logger.info(f"Expired inferred watch: user={user_id}, asset={asset_id}")

    async def _deregister_from_module(
        self, module_name: str, user_id: str, asset_id: str
    ) -> None:
        """
        Call a module's deregistration endpoint to clean up alerts for a user+asset.
        Uses the module registry to find the module instance.
        """
        from ..modules.registry import get_module_registry

        registry = get_module_registry()
        module = registry.get_module(module_name)

        if module is None:
            logger.warning(f"Module '{module_name}' not found in registry, skipping deregistration")
            return

        if hasattr(module, "deregister_notifications"):
            await module.deregister_notifications(user_id, asset_id)
            logger.info(
                f"Deregistered notifications from '{module_name}' "
                f"for user={user_id}, asset={asset_id}"
            )
        else:
            logger.debug(
                f"Module '{module_name}' has no deregister_notifications method, skipping"
            )

    async def run(self):
        """
        Run the expiration job continuously.
        Call stop() to terminate.
        """
        self._running = True
        logger.info(
            f"Starting interest expiration job "
            f"(interval: {EXPIRATION_CHECK_INTERVAL_SECONDS}s)"
        )

        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Interest expiration error: {e}", exc_info=True)

            await asyncio.sleep(EXPIRATION_CHECK_INTERVAL_SECONDS)

        logger.info("Interest expiration job stopped")

    def stop(self):
        """Stop the expiration job loop."""
        self._running = False


_expiration_instance: Optional[InterestExpirationJob] = None


def get_interest_expiration_job(convex_client: ConvexClient) -> InterestExpirationJob:
    """Get or create the InterestExpirationJob instance."""
    global _expiration_instance
    if _expiration_instance is None:
        _expiration_instance = InterestExpirationJob(convex_client)
    return _expiration_instance
