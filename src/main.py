from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os
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
from .api import diagnostics
from .api import admin
from .api import chat
from .middleware.auth import HankoAuthMiddleware
from .clients.convex_client import get_client
from .clients.async_convex_client import get_async_client
from .notifications.queue_processor import get_queue_processor
from .modules.defianalyst.price_poller import get_price_poller
from .modules.oracle.event_poller import get_event_poller
from .modules.oracle.probability_poller import get_probability_poller
from .modules.registry import get_module_registry
from .modules.remote_proxy import RemoteModuleProxy
from .modules.transport import get_http_transport
from .agents.interest_expiration import get_interest_expiration_job
from convex import ConvexClient

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

    # Build core_url for remote modules
    core_url = "http://ampr-core.railway.internal"
    railway_service_name = os.environ.get("RAILWAY_SERVICE_NAME")
    if railway_service_name:
        core_url = f"http://{railway_service_name}.railway.internal"

    # Register modules and their notification types (idempotent)
    # Use the registry's instance so _convex_client is set on the same object
    # that gets returned by get_module_registry().get_module()
    registry = get_module_registry()
    defianalyst = registry.get_module("defianalyst")
    if defianalyst and hasattr(defianalyst, "register"):
        await defianalyst.register(convex_client)

    oracle = registry.get_module("oracle")
    if oracle and hasattr(oracle, "register"):
        await oracle.register(convex_client)

    # Register remote modules (if any) and start retry tasks for unavailable ones
    remote_modules = registry.get_remote_modules()
    retry_tasks = []
    for name, proxy in remote_modules.items():
        try:
            await proxy.register(convex_client, core_url)
        except Exception as exc:
            logger.warning(
                f"Remote module '{name}' unavailable at startup: {exc}. "
                "Will retry periodically in the background."
            )
            retry_tasks.append(
                asyncio.create_task(
                    retry_remote_module_registration(proxy, convex_client, core_url)
                )
            )

    queue_processor = get_queue_processor(convex_client)
    price_poller = get_price_poller(convex_client)
    event_poller = get_event_poller(convex_client)
    probability_poller = get_probability_poller(convex_client)
    expiration_job = get_interest_expiration_job(convex_client)

    queue_task = asyncio.create_task(queue_processor.run())
    poller_task = asyncio.create_task(price_poller.run())
    event_poller_task = asyncio.create_task(event_poller.run())
    probability_poller_task = asyncio.create_task(probability_poller.run())
    expiration_task = asyncio.create_task(expiration_job.run())

    logger.info("Background services started")

    yield

    # Shutdown
    queue_processor.stop()
    price_poller.stop()
    event_poller.stop()
    probability_poller.stop()
    expiration_job.stop()

    queue_task.cancel()
    poller_task.cancel()
    event_poller_task.cancel()
    probability_poller_task.cancel()
    expiration_task.cancel()

    # Cancel any active remote module retry tasks
    for task in retry_tasks:
        task.cancel()

    await price_poller.close()
    await event_poller.close()
    await probability_poller.close()

    # Close the async Convex HTTP client connection pool
    async_client = get_async_client()
    await async_client.close()

    # Close the HTTP transport connection pool
    await get_http_transport().close()

    logger.info("Background services stopped")


fast_api = FastAPI(lifespan=lifespan)

# Add Hanko auth middleware first (runs before CORS)
fast_api.add_middleware(HankoAuthMiddleware)

# Set all CORS enabled origins.
fast_api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fast_api.include_router(admin.router, prefix="/api")

fast_api.include_router(chat.router, prefix="/api")

fast_api.include_router(users.router, prefix="/api")

fast_api.include_router(webhooks.router, prefix="/api")

fast_api.include_router(notifications.router, prefix="/api")

fast_api.include_router(countries.router, prefix="/api")

fast_api.include_router(watchlist.router, prefix="/api")

fast_api.include_router(assets.router, prefix="/api")

fast_api.include_router(lenses.router, prefix="/api")

fast_api.include_router(oracle.router, prefix="/api")

fast_api.include_router(diagnostics.router, prefix="/api")

@fast_api.get("/")
async def root():
    return {"message": "Hello from Ampr"}


@fast_api.get("/health")
async def health():
    """Health check endpoint - public, no auth required."""
    return {"status": "ok"}

async def retry_remote_module_registration(
    proxy: RemoteModuleProxy,
    convex_client: ConvexClient,
    core_url: str,
    interval_seconds: int = 30,
) -> None:
    """
    Retry registering a remote module until it becomes available.

    Runs in a background task during application lifespan. Logs warnings
    on each failure and info on success. Stops when the module registers
    successfully or when the task is cancelled during shutdown.
    """
    while True:
        try:
            await proxy.register(convex_client, core_url)
            logger.info(f"Remote module '{proxy.name}' became available after retry")
            return  # Success — stop retrying
        except Exception as exc:
            logger.warning(
                f"Retry failed for remote module '{proxy.name}': {exc}. "
                f"Will retry in {interval_seconds} seconds."
            )
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info(f"Stopping retry task for remote module '{proxy.name}'")
                return  # Task cancelled during shutdown

@fast_api.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"VALIDATION ERROR DETAILS: {exc.errors()}")
    print(f"VALIDATION ERROR BODY: {exc.body}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )