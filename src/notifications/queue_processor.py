"""
Notification queue processor.

Processes pending notifications from the queue and delivers them
when their scheduled delivery time has passed.
"""
import asyncio
import logging
from typing import Optional
from convex import ConvexClient

from .service import NotificationService

logger = logging.getLogger(__name__)


class NotificationQueueProcessor:
    """
    Processes queued notifications.
    
    Fetches pending notifications that are due for delivery and
    processes them through the NotificationService.
    """
    
    def __init__(
        self,
        convex_client: ConvexClient,
        batch_size: int = 50,
        poll_interval_seconds: int = 60,
    ):
        self.convex = convex_client
        self.service = NotificationService(convex_client)
        self.batch_size = batch_size
        self.poll_interval = poll_interval_seconds
        self._running = False
    
    async def process_batch(self) -> int:
        """
        Process a batch of pending notifications.
        
        Returns:
            Number of notifications processed
        """
        try:
            pending = self.convex.query("notifications:getPendingNotifications", {
                "limit": self.batch_size,
            })
            
            if not pending:
                return 0
            
            logger.info(f"Processing {len(pending)} pending notifications")
            
            processed = 0
            for item in pending:
                success = await self.service.process_queued_notification(item)
                if success:
                    processed += 1
            
            logger.info(f"Successfully delivered {processed}/{len(pending)} notifications")
            return len(pending)
            
        except Exception as e:
            logger.error(f"Error processing notification batch: {e}", exc_info=True)
            return 0
    
    async def run_once(self) -> int:
        """
        Run a single processing cycle.
        
        Processes all due notifications in batches until none remain.
        
        Returns:
            Total number of notifications processed
        """
        total_processed = 0
        
        while True:
            batch_count = await self.process_batch()
            total_processed += batch_count
            
            if batch_count < self.batch_size:
                break
        
        return total_processed
    
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
