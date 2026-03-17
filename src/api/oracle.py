import logging

from fastapi import APIRouter, status

from ..clients.convex_client import get_client
from ..modules.oracle.event_poller import get_event_poller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oracle", tags=["oracle"])


@router.post("/poll-events", status_code=status.HTTP_200_OK)
async def poll_events():
    """Manually trigger the oracle event poller."""
    convex_client = get_client()
    poller = get_event_poller(convex_client)
    count = await poller.poll_once()
    return {"message": "Event poll complete", "events_processed": count}
