"""
Remote module proxy for dispatching invocations over HTTP.

When the module registry encounters a modules.yaml entry that has a
service_url field, it instantiates a RemoteModuleProxy instead of
importing the module in-process. The proxy implements the same
ModuleInterface as local modules, making the dispatch location fully
transparent to callers (amprChat, the registry, etc.).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from convex import ConvexClient

from .transport import ModuleTransport

logger = logging.getLogger(__name__)


class RemoteModuleProxy:
    """
    Implements ModuleInterface for a remotely-deployed module service.

    Lifecycle:
      - Created by the registry from modules.yaml config (before startup).
        _available starts as False.
      - main.py calls register() during lifespan startup. On success,
        _available is set to True.
      - If register() fails, main.py retries it periodically in a background
        task until it succeeds.
      - invoke() returns a graceful error string (not an exception) while
        _available is False, so amprChat can surface it to the user cleanly.
    """

    def __init__(
        self,
        name: str,
        trigger: str,
        service_url: str,
        transport: ModuleTransport,
    ):
        self.name = name
        self.trigger = trigger
        self.service_url = service_url.rstrip("/")  # Normalise — no trailing slash
        self._transport = transport
        self._available: bool = False  # Becomes True after successful register()
        self._module_id: Optional[str] = None
        self._notification_types: dict[str, str] = {}  # type name -> Convex ID

    @property
    def module_id(self) -> Optional[str]:
        """Get the module's Convex ID (set after registration)."""
        return self._module_id

    # ------------------------------------------------------------------
    # ModuleInterface implementation
    # ------------------------------------------------------------------

    async def invoke(
        self,
        message: str,
        date_context: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Invoke the remote module with the given message.

        Returns a user-friendly error string if the module is unavailable
        or the HTTP call fails — never raises — so amprChat can pass the
        message through to the user gracefully.

        Args:
            message: The user message (may include the &mention trigger).
            date_context: Optional resolved date context from the preprocessor.
            user_id: Core Convex user_id, forwarded to the remote module so
                     it can query its own data on behalf of the user.

        Returns:
            Module response string, or a user-friendly error message.
        """
        if not self._available:
            logger.warning(
                f"Remote module '{self.name}' invoked while marked unavailable"
            )
            return (
                f"The {self.name} module is currently unavailable. "
                "Please try again in a moment."
            )

        payload = {
            "message": message,
            "user_id": user_id,
            "date_context": date_context,
        }

        try:
            result = await self._transport.send_invoke(self.service_url, payload)
            return result.get("response", "No response received from module.")

        except httpx.TimeoutException:
            logger.error(f"Remote module '{self.name}' timed out during invoke")
            return (
                f"The {self.name} module timed out while processing your request. "
                "Please try again."
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Remote module '{self.name}' returned HTTP {exc.response.status_code} "
                "during invoke"
            )
            return (
                f"The {self.name} module returned an error "
                f"({exc.response.status_code}). Please try again."
            )

        except Exception as exc:
            logger.error(
                f"Remote module '{self.name}' invoke failed: {exc}", exc_info=True
            )
            return (
                f"The {self.name} module is currently unavailable. "
                "Please try again later."
            )

    async def register_notifications(
        self, user_id: str, asset_id: str
    ) -> None:
        """
        No-op for remote modules.

        Remote modules manage their own watchlist/notification registration
        via their own background workers and Convex project. Core does not
        reach into their data layer.
        """
        pass

    async def deregister_notifications(
        self, user_id: str, asset_id: str
    ) -> None:
        """
        No-op for remote modules.

        Remote modules manage their own cleanup independently of core.
        """
        pass

    # ------------------------------------------------------------------
    # Registration (called by main.py lifespan, retried on failure)
    # ------------------------------------------------------------------

    async def register(self, convex_client: ConvexClient, core_url: str) -> str:
        """
        Register this module with core.

        Calls POST {service_url}/register to exchange core_url (so the module
        knows where to POST notification callbacks) and receive the module's
        manifest. Then registers the module and its notification types in
        Convex.

        Sets self._available = True on success. Raises on any failure so the
        caller (main.py) can implement retry logic.

        Args:
            convex_client: Core's Convex client for registering the module.
            core_url: Core's Railway internal base URL
                      (e.g., "http://ampr-core.railway.internal").

        Returns:
            The module's Convex module_id.

        Raises:
            RuntimeError: If the Convex registerModule mutation returns None.
            httpx.*: If the /register HTTP call fails.
        """
        manifest = await self._transport.send_register(
            self.service_url,
            {"core_url": core_url, "config": {}},
        )

        # Register (or upsert) the module in Convex
        module_id = convex_client.mutation("notifications:registerModule", {
            "name": self.name,
            "description": manifest.get("description", f"Module: {self.name}"),
        })

        if module_id is None:
            raise RuntimeError(
                f"Failed to register remote module '{self.name}': "
                "notifications:registerModule returned None"
            )

        self._module_id = module_id
        logger.info(f"Registered remote module '{self.name}' with Convex ID: {module_id}")

        # Register notification types returned by the module manifest
        for nt in manifest.get("notification_types", []):
            type_id = convex_client.mutation("notifications:registerNotificationType", {
                "module": module_id,
                "name": nt["name"],
                "description": nt["description"],
                "default_enabled": nt.get("default_enabled", True),
                "priority": nt.get("priority", "medium"),
            })
            self._notification_types[nt["name"]] = type_id
            logger.info(
                f"Registered notification type '{nt['name']}' "
                f"for remote module '{self.name}' (ID: {type_id})"
            )

        self._available = True
        logger.info(f"Remote module '{self.name}' is now available")
        return module_id