"""
Async Convex client using httpx.

Calls Convex's HTTP API (POST /api/query, /api/mutation, /api/action)
without blocking the asyncio event loop — unlike the synchronous
ConvexClient from the `convex` package which uses Rust's rt.block_on().

Drop-in replacement: every call site changes from
    result = convex_client.query("fn:name", {args})
to
    result = await async_convex_client.query("fn:name", {args})
"""

import os
import logging
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")

logger = logging.getLogger(__name__)


class ConvexError(Exception):
    """Raised when a Convex function returns an application error."""

    def __init__(self, message: str, data: Any = None):
        super().__init__(message)
        self.data = data


class AsyncConvexClient:
    """
    Async Convex client that calls the Convex HTTP API via httpx.

    Uses a shared httpx.AsyncClient with connection pooling for
    efficient persistent connections.
    """

    def __init__(self, convex_url: str):
        self._base_url = convex_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._auth_token: Optional[str] = None
        self._admin_key: Optional[str] = None

    # -- Auth helpers (mirror the sync client API) -----------------------

    def set_auth(self, token: str) -> None:
        """Set a user-level bearer token for authenticated function calls."""
        self._auth_token = token
        self._admin_key = None

    def set_admin_auth(self, admin_key: str) -> None:
        """Set an admin deploy key for calling internal functions."""
        self._admin_key = admin_key
        self._auth_token = None

    def clear_auth(self) -> None:
        self._auth_token = None
        self._admin_key = None

    # -- Core API --------------------------------------------------------

    async def query(self, path: str, args: Optional[dict] = None) -> Any:
        """Run a Convex query function (non-blocking)."""
        return await self._call("/api/query", path, args)

    async def mutation(self, path: str, args: Optional[dict] = None) -> Any:
        """Run a Convex mutation function (non-blocking)."""
        return await self._call("/api/mutation", path, args)

    async def action(self, path: str, args: Optional[dict] = None) -> Any:
        """Run a Convex action function (non-blocking)."""
        return await self._call("/api/action", path, args)

    # -- Internals -------------------------------------------------------

    async def _call(self, endpoint: str, path: str, args: Optional[dict]) -> Any:
        body: dict[str, Any] = {
            "path": path,
            "args": args or {},
            "format": "json",
        }

        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        elif self._admin_key:
            headers["Authorization"] = f"Convex {self._admin_key}"

        response = await self._http.post(endpoint, json=body, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get("status") == "error":
            error_msg = data.get("errorMessage", "Unknown Convex error")
            error_data = data.get("errorData")
            logger.error(f"Convex error calling {path}: {error_msg}")
            raise ConvexError(error_msg, data=error_data)

        return data.get("value")

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()


# -- Singleton -----------------------------------------------------------

_async_client_instance: Optional[AsyncConvexClient] = None


def get_async_client() -> AsyncConvexClient:
    """
    Get or create the global AsyncConvexClient singleton.

    Safe to call from any coroutine — the underlying httpx.AsyncClient
    handles concurrent requests via connection pooling.
    """
    global _async_client_instance
    if _async_client_instance is None:
        convex_url = os.getenv("CONVEX_URL")
        if not convex_url:
            raise ValueError("CONVEX_URL environment variable is not set")
        _async_client_instance = AsyncConvexClient(convex_url)
    return _async_client_instance
