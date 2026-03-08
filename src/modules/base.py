from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Protocol
import logging

from convex import ConvexClient

logger = logging.getLogger(__name__)


@dataclass
class NotificationTypeConfig:
    """Configuration for a notification type to be registered."""
    name: str
    description: str
    default_enabled: bool = True


class ModuleInterface(Protocol):
    """
    Protocol defining the interface that all third-party modules must implement.
    
    Modules are specialized agents that can be invoked via @mention syntax in user messages.
    They operate independently from core Ampr agents and return responses that are passed
    through the main chat agent.
    """
    
    name: str
    trigger: str
    
    async def invoke(self, message: str, date_context: Optional[str] = None) -> str:
        """
        Process a user message and return a response.
        
        Args:
            message: The full user message (including the @mention trigger)
            date_context: Optional resolved date context from preprocessor
                (e.g., '[DATE CONTEXT]\n• "a few weeks ago" = 08-12-2025')
            
        Returns:
            The module's response as a string
            
        Raises:
            Exception: If the module fails to process the message
        """
        ...


class BaseModule(ABC):
    """
    Abstract base class for third-party modules.
    
    All modules should inherit from this class and implement the invoke method.
    Supports notification registration and sending.
    """
    
    def __init__(self, name: str, trigger: str):
        self.name = name
        self.trigger = trigger
        self._module_id: Optional[str] = None
        self._notification_types: dict[str, str] = {}  # name -> convex ID
        self._convex_client: Optional[ConvexClient] = None
    
    def get_notification_types(self) -> list[NotificationTypeConfig]:
        """
        Override to define notification types for this module.
        
        Returns:
            List of NotificationTypeConfig objects to register
        """
        return []
    
    async def register(self, convex_client: ConvexClient) -> str:
        """
        Register the module and its notification types with Convex.
        
        Args:
            convex_client: Convex client instance
            
        Returns:
            The module's Convex ID
        """
        self._convex_client = convex_client
        
        module_id = convex_client.mutation("notifications:registerModule", {
            "name": self.name,
            "description": f"Module: {self.name}",
        })
        
        if module_id is None:
            raise RuntimeError(f"Failed to register module '{self.name}': mutation returned None")
        
        self._module_id = module_id
        logger.info(f"Registered module '{self.name}' with ID: {module_id}")
        
        for type_config in self.get_notification_types():
            type_id = convex_client.mutation("notifications:registerNotificationType", {
                "module": module_id,
                "name": type_config.name,
                "description": type_config.description,
                "default_enabled": type_config.default_enabled,
            })
            self._notification_types[type_config.name] = type_id
            logger.info(f"Registered notification type '{type_config.name}' with ID: {type_id}")
        
        return module_id
    
    @property
    def module_id(self) -> Optional[str]:
        """Get the module's Convex ID (set after registration)."""
        return self._module_id
    
    def get_notification_type_id(self, name: str) -> Optional[str]:
        """
        Get the Convex ID for a registered notification type.
        
        Args:
            name: The notification type name
            
        Returns:
            The Convex ID or None if not registered
        """
        return self._notification_types.get(name)
    
    async def send_notification(
        self,
        user_id: str,
        notification_type_name: str,
        content: str,
        asset_ref: Optional[str] = None,
    ) -> bool:
        """
        Send a notification to a user.
        
        Args:
            user_id: Convex user ID
            notification_type_name: Name of the registered notification type
            content: Notification message content
            asset_ref: Optional Convex asset ID for overnight deduplication
            
        Returns:
            True if notification was sent or queued successfully
        """
        if not self._convex_client or not self._module_id:
            logger.error(f"Module '{self.name}' not registered, cannot send notification")
            return False
        
        type_id = self.get_notification_type_id(notification_type_name)
        if not type_id:
            logger.error(f"Notification type '{notification_type_name}' not registered for module '{self.name}'")
            return False
        
        from ..notifications.service import get_notification_service
        service = get_notification_service(self._convex_client)
        
        result = await service.send(
            user_id=user_id,
            module_id=self._module_id,
            notification_type_id=type_id,
            content=content,
            asset_ref=asset_ref,
        )
        
        return result.success
    
    @abstractmethod
    async def invoke(self, message: str, date_context: Optional[str] = None) -> str:
        """
        Process a user message and return a response.
        
        Args:
            message: The full user message (including the @mention trigger)
            date_context: Optional resolved date context from preprocessor
                (e.g., '[DATE CONTEXT]\n• "a few weeks ago" = 08-12-2025')
            
        Returns:
            The module's response as a string
            
        Raises:
            Exception: If the module fails to process the message
        """
        pass
