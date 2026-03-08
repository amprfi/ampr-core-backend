"""
Notification service for sending notifications through the chat system.

Central API for:
- Checking user preferences
- Timezone-aware delivery windows
- Routing to appropriate channel (Telegram, SMS)
- Queueing notifications for delayed delivery
"""
import logging
from dataclasses import dataclass
from typing import Optional
from convex import ConvexClient

from .timezone import get_timezone_utils
from ..clients.telegram_client import TelegramClient
from ..utils.formatting import strip_markdown

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    success: bool
    delivered: bool  # True if sent immediately, False if queued
    message_id: Optional[str] = None  # Convex message ID if delivered
    queue_id: Optional[str] = None    # Convex queue ID if queued
    error: Optional[str] = None


class NotificationService:
    """
    Central service for sending notifications.
    
    Handles preference checking, timezone windows, and channel routing.
    Notifications flow through the chat system as messages.
    """
    
    def __init__(self, convex_client: ConvexClient):
        self.convex = convex_client
        self.timezone_utils = get_timezone_utils()
    
    async def send(
        self,
        user_id: str,
        module_id: str,
        notification_type_id: str,
        content: str,
        asset_ref: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send a notification to a user.
        
        Flow:
        1. Check if user has this notification type enabled
        2. Check if within delivery window
        3. Either deliver immediately or queue for later
        
        Args:
            user_id: Convex user ID
            module_id: Convex module ID
            notification_type_id: Convex notification type ID
            content: Notification message content
            asset_ref: Optional Convex asset ID for overnight deduplication
            
        Returns:
            NotificationResult with delivery status
        """
        try:
            is_enabled = self.convex.query("notifications:isNotificationEnabled", {
                "user": user_id,
                "module": module_id,
                "notification_type": notification_type_id,
            })
            
            if not is_enabled:
                logger.info(f"Notification disabled for user {user_id}, type {notification_type_id}")
                return NotificationResult(
                    success=True,
                    delivered=False,
                    error="Notification disabled by user preference"
                )
            
            user = self.convex.query("users:getUser", {"userId": user_id})
            if not user:
                return NotificationResult(
                    success=False,
                    delivered=False,
                    error=f"User {user_id} not found"
                )
            
            profile = self.convex.query("profiles:getProfileByUser", {"userId": user_id})
            user_timezone = profile.get("timezone") if profile else None
            user_country = profile.get("country") if profile else None
            
            can_deliver_now, scheduled_for_ms = self.timezone_utils.get_delivery_window(
                user_timezone, user_country
            )
            
            if can_deliver_now:
                return await self._deliver_now(
                    user_id=user_id,
                    user=user,
                    module_id=module_id,
                    notification_type_id=notification_type_id,
                    content=content,
                )
            else:
                assert scheduled_for_ms is not None, "scheduled_for_ms must be set when can_deliver_now is False"
                return self._enqueue(
                    user_id=user_id,
                    module_id=module_id,
                    notification_type_id=notification_type_id,
                    content=content,
                    scheduled_for_ms=scheduled_for_ms,
                    asset_ref=asset_ref,
                )
                
        except Exception as e:
            logger.error(f"Error sending notification: {e}", exc_info=True)
            return NotificationResult(
                success=False,
                delivered=False,
                error=str(e)
            )
    
    async def _deliver_now(
        self,
        user_id: str,
        user: dict,
        module_id: str,
        notification_type_id: str,
        content: str,
    ) -> NotificationResult:
        """Deliver notification immediately via user's preferred channel."""
        channel = user.get("default_notification_channel", "telegram")
        
        message = self.convex.mutation("messages:createMessage", {
            "userId": user_id,
            "role": "assistant",
            "channel": channel,
            "content": content,
            "is_notification": True,
            "notification_module": module_id,
            "notification_type": notification_type_id,
        })
        
        message_id = message.get("_id") if message else None
        
        delivery_success = False
        if channel == "telegram":
            telegram_id = user.get("telegram_id")
            if telegram_id:
                delivery_success = await self._send_telegram(telegram_id, content)
            else:
                logger.warning(f"User {user_id} has telegram channel but no telegram_id")
        elif channel == "sms":
            phone = user.get("phone")
            if phone:
                delivery_success = await self._send_sms(phone, content)
            else:
                logger.warning(f"User {user_id} has sms channel but no phone")
        
        if not delivery_success:
            logger.error(f"Failed to deliver notification to user {user_id} via {channel}")
            return NotificationResult(
                success=False,
                delivered=False,
                message_id=message_id,
                error=f"Delivery via {channel} failed",
            )
        
        return NotificationResult(
            success=True,
            delivered=True,
            message_id=message_id,
        )
    
    def _enqueue(
        self,
        user_id: str,
        module_id: str,
        notification_type_id: str,
        content: str,
        scheduled_for_ms: int,
        asset_ref: Optional[str] = None,
    ) -> NotificationResult:
        """Queue notification for later delivery."""
        args: dict = {
            "user": user_id,
            "module": module_id,
            "notification_type": notification_type_id,
            "content": content,
            "scheduled_for": scheduled_for_ms,
        }
        if asset_ref is not None:
            args["asset_ref"] = asset_ref
        queue_id = self.convex.mutation("notifications:enqueueNotification", args)
        
        logger.info(f"Queued notification for user {user_id}, scheduled for {scheduled_for_ms}")
        
        return NotificationResult(
            success=True,
            delivered=False,
            queue_id=queue_id,
        )
    
    async def _send_telegram(self, telegram_id: str, content: str) -> bool:
        """Send message via Telegram."""
        try:
            client = TelegramClient()
            result = await client.send_message(
                chat_id=int(telegram_id),
                text=content,
            )
            await client.close()
            return result is not None
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    
    async def _send_sms(self, phone: str, content: str) -> bool:
        """Send message via SMS (placeholder for Vonage integration)."""
        content = strip_markdown(content)
        # TODO: Implement SMS sending via Vonage
        logger.warning("SMS sending not yet implemented")
        return False
    
    async def process_queued_notification(self, queue_item: dict) -> bool:
        """
        Process a single queued notification.
        
        Called by the queue processor for each pending item.
        
        Args:
            queue_item: Notification queue record from Convex
            
        Returns:
            True if successfully delivered
        """
        queue_id = queue_item["_id"]
        user_id = queue_item["user"]
        module_id = queue_item["module"]
        notification_type_id = queue_item["notification_type"]
        content = queue_item["content"]
        
        self.convex.mutation("notifications:updateNotificationStatus", {
            "id": queue_id,
            "status": "sending",
        })
        
        try:
            user = self.convex.query("users:getUser", {"userId": user_id})
            if not user:
                self.convex.mutation("notifications:updateNotificationStatus", {
                    "id": queue_id,
                    "status": "failed",
                    "last_error": "User not found",
                })
                return False
            
            result = await self._deliver_now(
                user_id=user_id,
                user=user,
                module_id=module_id,
                notification_type_id=notification_type_id,
                content=content,
            )
            
            if result.delivered:
                self.convex.mutation("notifications:updateNotificationStatus", {
                    "id": queue_id,
                    "status": "sent",
                })
                return True
            else:
                self.convex.mutation("notifications:updateNotificationStatus", {
                    "id": queue_id,
                    "status": "failed",
                    "last_error": result.error or "Delivery failed",
                })
                return False
                
        except Exception as e:
            logger.error(f"Error processing queued notification {queue_id}: {e}")
            self.convex.mutation("notifications:updateNotificationStatus", {
                "id": queue_id,
                "status": "failed",
                "last_error": str(e),
            })
            return False


_service_instance: Optional[NotificationService] = None


def get_notification_service(convex_client: ConvexClient) -> NotificationService:
    """Get or create the NotificationService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = NotificationService(convex_client)
    return _service_instance
