"""
Transport abstraction layer for module communication.

Defines the ModuleTransport protocol and provides HttpTransport as the default
HTTP implementation. Future transports (e.g., XMTP, message bus) can be swapped
in without any changes to module or registry code.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@runtime_checkable
class ModuleTransport(Protocol):
    """
    Protocol defining the communication interface between core and remote modules.

    Implementations can swap the underlying transport (HTTP today, XMTP or a
    message bus in the future) without changing module or registry code.
    """

    async def send_invoke(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Send an invocation request to a remote module.

        Args:
            url: Base service URL (e.g., "http://education.railway.internal")
            payload: Request body with keys: message, user_id, date_context

        Returns:
            Response dict from the module (must include "response" key)

        Raises:
            httpx.TimeoutException: If the request times out
            httpx.HTTPStatusError: If the module returns a non-2xx status
            httpx.ConnectError: If the module is unreachable
        """
        ...

    async def send_register(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Send a registration request to a remote module.

        Called by core during startup to exchange the core_url and receive
        the module's self-description (manifest).

        Args:
            url: Base service URL
            payload: Request body with keys: core_url, config

        Returns:
            Module manifest dict (name, trigger, description, intents,
            notification_types, response_instructions)

        Raises:
            httpx.TimeoutException: If the request times out
            httpx.HTTPStatusError: If the module returns a non-2xx status
            httpx.ConnectError: If the module is unreachable
        """
        ...

    async def close(self) -> None:
        """Close the transport and release any held resources."""
        ...


class HttpTransport:
    """
    HTTP implementation of ModuleTransport using httpx.AsyncClient.

    Uses a single shared AsyncClient for connection-pool reuse across all
    remote module invocations. Call close() during application shutdown.
    """

    def __init__(self, timeout: float = 30.0):
        """
        Args:
            timeout: Request timeout in seconds (default 30s).
                     Education-module RAG queries may need a longer value.
        """
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send_invoke(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST {url}/invoke and return the parsed JSON response."""
        response = await self._client.post(f"{url}/invoke", json=payload)
        response.raise_for_status()
        return response.json()

    async def send_register(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST {url}/register and return the parsed JSON response."""
        response = await self._client.post(f"{url}/register", json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying httpx client and its connection pool."""
        global _transport_instance
        await self._client.aclose()
        _transport_instance = None


_transport_instance: Optional[HttpTransport] = None


def get_http_transport() -> HttpTransport:
    """
    Return the singleton HttpTransport instance.

    All RemoteModuleProxy instances share this transport so they all
    benefit from the same httpx connection pool.

    Returns:
        The shared HttpTransport instance.
    """
    global _transport_instance
    if _transport_instance is None:
        _transport_instance = HttpTransport()
    return _transport_instance