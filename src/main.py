from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import users
from .api import webhooks
from .api import notifications
from .api import countries
from .api import watchlist
from .api import assets
from .api import lenses
from .api import oracle
from .clients.convex_client import get_client
from .notifications.queue_processor import get_queue_processor
from .modules.defianalyst.price_poller import get_price_poller
from .modules.oracle.event_poller import get_event_poller
from .modules.registry import get_module_registry
from .agents.interest_expiration import get_interest_expiration_job

# Configure logging for Railway/production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop background services with the application lifecycle."""
    convex_client = get_client()

    # Register modules and their notification types (idempotent)
    # Use the registry's instance so _convex_client is set on the same object
    # that gets returned by get_module_registry().get_module()
    registry = get_module_registry()
    defianalyst = registry.get_module("defianalyst")
    if defianalyst and hasattr(defianalyst, "register"):
        await defianalyst.register(convex_client)

    queue_processor = get_queue_processor(convex_client)
    price_poller = get_price_poller(convex_client)
    event_poller = get_event_poller(convex_client)
    expiration_job = get_interest_expiration_job(convex_client)

    queue_task = asyncio.create_task(queue_processor.run())
    poller_task = asyncio.create_task(price_poller.run())
    event_poller_task = asyncio.create_task(event_poller.run())
    expiration_task = asyncio.create_task(expiration_job.run())

    logger.info("Background services started")

    yield

    # Shutdown
    queue_processor.stop()
    price_poller.stop()
    event_poller.stop()
    expiration_job.stop()

    queue_task.cancel()
    poller_task.cancel()
    event_poller_task.cancel()
    expiration_task.cancel()

    await price_poller.close()
    await event_poller.close()

    logger.info("Background services stopped")


fast_api = FastAPI(lifespan=lifespan)

# Set all CORS enabled origins.
fast_api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fast_api.include_router(users.router, prefix="/api")

fast_api.include_router(webhooks.router, prefix="/api")

fast_api.include_router(notifications.router, prefix="/api")

fast_api.include_router(countries.router, prefix="/api")

fast_api.include_router(watchlist.router, prefix="/api")

fast_api.include_router(assets.router, prefix="/api")

fast_api.include_router(lenses.router, prefix="/api")

fast_api.include_router(oracle.router, prefix="/api")

@fast_api.get("/")
async def root():
    return {"message": "Hello from Ampr"}

@fast_api.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"VALIDATION ERROR DETAILS: {exc.errors()}")
    print(f"VALIDATION ERROR BODY: {exc.body}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )