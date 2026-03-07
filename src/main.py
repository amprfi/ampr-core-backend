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
from .clients.convex_client import get_client
from .notifications.queue_processor import get_queue_processor
from .modules.defianalyst.price_poller import get_price_poller
from .modules.defianalyst.agent import get_defianalyst_module

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
    defianalyst = get_defianalyst_module()
    await defianalyst.register(convex_client)

    queue_processor = get_queue_processor(convex_client)
    price_poller = get_price_poller(convex_client)

    queue_task = asyncio.create_task(queue_processor.run())
    poller_task = asyncio.create_task(price_poller.run())

    logger.info("Background services started")

    yield

    # Shutdown
    queue_processor.stop()
    price_poller.stop()

    queue_task.cancel()
    poller_task.cancel()

    await price_poller.close()

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