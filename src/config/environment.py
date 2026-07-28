"""
Environment configuration for the AMPRFI backend.

Provides functions to determine the current deployment environment
and gate development-only endpoints accordingly.

Precedence rules:
    Any Railway deployment is disabled by default (including
    ``RAILWAY_ENVIRONMENT_NAME=development``).  Only ``ENVIRONMENT``
    values of ``local``, ``dev``, or ``development`` enable automatic
    local/dev mode.  Any other non-empty ``ENVIRONMENT`` value
    (staging, qa, preview, etc.) requires explicit opt-in via
    ``ENABLE_REST_TESTING_ENDPOINT=true``.
"""

import os
import logging

logger = logging.getLogger(__name__)


def is_local_or_development() -> bool:
    """
    Determine whether the application is running in a local or development environment.

    Detection logic (evaluated in order):

    1. ``RAILWAY_ENVIRONMENT_NAME`` is set → False (any Railway deployment,
       including development, is disabled by default)
    2. ``ENVIRONMENT`` env var is ``local``, ``dev``, or ``development`` → True
    3. ``ENVIRONMENT`` is any other non-empty value → False (staging, qa,
       preview, etc. require explicit opt-in)
    4. ``DEBUG`` env var is ``true`` (case-insensitive) → True (local dev)
    5. Nothing set → True (local dev default)

    Returns:
        bool: True if running in local/development, False otherwise
    """
    env = os.getenv("ENVIRONMENT", "").lower()

    # Any Railway deployment is disabled by default (including development).
    # This check comes BEFORE the local/dev check so that a hosted Railway
    # deployment cannot be enabled by setting ENVIRONMENT=development.
    if os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return False

    # Only explicit dev markers enable automatic local/dev mode
    if env in ("local", "dev", "development"):
        return True

    # Any other non-empty ENVIRONMENT value requires explicit opt-in
    if env:
        return False

    # No ENVIRONMENT set and no Railway: local dev default
    debug = os.getenv("DEBUG", "").lower()
    if debug == "true":
        return True

    # No production markers, no explicit dev markers, no Railway:
    # likely running locally
    return True


def is_rest_testing_endpoint_enabled() -> bool:
    """
    Determine whether the REST testing endpoint (/api/webhooks/rest-message)
    should be enabled.

    The endpoint is enabled when:
    - The application is running in a local/development environment, OR
    - An explicit opt-in setting (ENABLE_REST_TESTING_ENDPOINT=true) is provided

    This ensures the endpoint is never accidentally exposed in production
    without an explicit administrator decision.

    Returns:
        bool: True if the REST testing endpoint should be enabled
    """
    if is_local_or_development():
        return True

    opt_in = os.getenv("ENABLE_REST_TESTING_ENDPOINT", "").lower()
    if opt_in == "true":
        logger.warning(
            "REST testing endpoint enabled in production via "
            "ENABLE_REST_TESTING_ENDPOINT. This is intended for temporary "
            "validation only."
        )
        return True

    return False
