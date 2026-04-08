"""
Notification API endpoints for testing and management.

Provides endpoints for:
- Manually triggering test notifications
- Managing notification preferences
- Module callback endpoint for remote modules to send notifications
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client
from ..notifications.service import get_notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


class SendNotificationRequest(BaseModel):
    """Request body for sending a test notification."""
    user_id: str
    module_id: str
    notification_type_id: str
    content: str


class SendNotificationResponse(BaseModel):
    """Response for notification send request."""
    success: bool
    delivered: bool
    message_id: Optional[str] = None
    queue_id: Optional[str] = None
    error: Optional[str] = None


@router.post("/send", response_model=SendNotificationResponse)
async def send_notification(request: SendNotificationRequest):
    """
    Send a notification to a user (for testing).
    
    This endpoint allows manual triggering of notifications for testing
    the notification system end-to-end.
    
    Args:
        request: Notification details including user, module, type, and content
        
    Returns:
        SendNotificationResponse with delivery status
    """
    logger.info(f"Sending test notification to user {request.user_id}")
    
    try:
        convex_client = get_client()
        service = get_notification_service(convex_client)
        
        result = await service.send(
            user_id=request.user_id,
            module_id=request.module_id,
            notification_type_id=request.notification_type_id,
            content=request.content,
        )
        
        return SendNotificationResponse(
            success=result.success,
            delivered=result.delivered,
            message_id=result.message_id,
            queue_id=result.queue_id,
            error=result.error,
        )
        
    except Exception as e:
        logger.error(f"Error sending notification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


class RegisterModuleRequest(BaseModel):
    """Request body for registering a test module."""
    name: str
    description: Optional[str] = None


class RegisterNotificationTypeRequest(BaseModel):
    """Request body for registering a notification type."""
    module_id: str
    name: str
    description: str
    default_enabled: bool = True
    priority: str = "medium"


@router.post("/modules/register")
async def register_module(request: RegisterModuleRequest):
    """
    Register a module (for testing).
    
    Returns the module ID for use in subsequent calls.
    """
    try:
        convex_client = get_client()
        module_id = convex_client.mutation("notifications:registerModule", {
            "name": request.name,
            "description": request.description or f"Test module: {request.name}",
        })
        
        return {"module_id": module_id}
        
    except Exception as e:
        logger.error(f"Error registering module: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/types/register")
async def register_notification_type(request: RegisterNotificationTypeRequest):
    """
    Register a notification type for a module (for testing).
    
    Returns the notification type ID.
    """
    try:
        convex_client = get_client()
        type_id = convex_client.mutation("notifications:registerNotificationType", {
            "module": request.module_id,
            "name": request.name,
            "description": request.description,
            "default_enabled": request.default_enabled,
            "priority": request.priority,
        })
        
        return {"notification_type_id": type_id}
        
    except Exception as e:
        logger.error(f"Error registering notification type: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/modules")
async def list_modules():
    """List all registered modules."""
    try:
        convex_client = get_client()
        modules = convex_client.query("notifications:getAllModules", {})
        return {"modules": modules}
        
    except Exception as e:
        logger.error(f"Error listing modules: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/types/{module_id}")
async def list_notification_types(module_id: str):
    """List notification types for a module."""
    try:
        convex_client = get_client()
        types = convex_client.query("notifications:getNotificationTypesByModule", {
            "module": module_id,
        })
        return {"notification_types": types}
        
    except Exception as e:
        logger.error(f"Error listing notification types: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

class ModuleSendRequest(BaseModel):
    """Request body for module-send notification callback.

    Note: user_id must be the Convex document _id from the core users table
    (not an email, external ID, or other identifier). Remote modules receive
    this value in the /invoke payload and should pass it through unchanged.
    """
    user_id: str
    module_name: str
    notification_type_name: str
    content: str
    asset_ref: Optional[str] = None

class ModuleSendResponse(BaseModel):
    """Response for module-send notification callback."""
    success: bool
    delivered: bool
    message_id: Optional[str] = None
    queue_id: Optional[str] = None
    error: Optional[str] = None

@router.post("/module-send", response_model=ModuleSendResponse)
async def module_send_notification(request: ModuleSendRequest):
    """
    Module callback endpoint for remote modules to send notifications.

    Remote modules POST to this endpoint with a core user_id and human-readable
    module/type names. Core resolves the Convex IDs and routes through the
    existing notification pipeline (queue → preferences check → Telegram/WhatsApp).

    Args:
        request: Notification details including user_id, module_name,
                 notification_type_name, content, and optional asset_ref.

    Returns:
        ModuleSendResponse with delivery status.

    Raises:
        HTTPException 404: If the module is not found.
        HTTPException 400: If the notification type is not found.
        HTTPException 500: If notification send fails.
    """
    logger.info(f"Module callback: sending notification for user {request.user_id}")

    try:
        convex_client = get_client()

        # Resolve module ID by name
        module = convex_client.query("notifications:getModuleByName", {
            "name": request.module_name,
        })
        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Module '{request.module_name}' not found",
            )
        module_id = module["_id"]

        # Resolve notification type ID by module + name
        notification_type = convex_client.query("notifications:getNotificationTypeByName", {
            "module": module_id,
            "name": request.notification_type_name,
        })
        if not notification_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Notification type '{request.notification_type_name}' not found for module '{request.module_name}'",
            )
        notification_type_id = notification_type["_id"]

        # Route through existing notification service
        service = get_notification_service(convex_client)
        result = await service.send(
            user_id=request.user_id,
            module_id=module_id,
            notification_type_id=notification_type_id,
            content=request.content,
            asset_ref=request.asset_ref,
        )

        return ModuleSendResponse(
            success=result.success,
            delivered=result.delivered,
            message_id=result.message_id,
            queue_id=result.queue_id,
            error=result.error,
        )

    except HTTPException:
        # Re-raise our own HTTPExceptions (404, 400)
        raise

    except Exception as e:
        logger.error(f"Error sending module notification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
