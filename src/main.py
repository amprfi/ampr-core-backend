from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import users
from .api import webhooks
from .api import notifications
from .api import countries

# Configure logging for Railway/production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

fast_api = FastAPI()

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