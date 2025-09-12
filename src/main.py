from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import users

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

@fast_api.get("/")
async def root():
    return {"message": "Hello from Ampr"}