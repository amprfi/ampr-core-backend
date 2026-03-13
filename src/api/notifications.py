"""
Notification API endpoints for testing and management.

Provides endpoints for:
- Manually triggering test notifications
- Managing notification preferences
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
