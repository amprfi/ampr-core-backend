"""
Phone number normalization utilities.

This module provides shared phone number handling for ingestion modules.
"""

import logging

logger = logging.getLogger(__name__)


def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number to consistent storage/lookup format.
    
    Removes all non-digit characters (tel:, +, -, spaces, etc.)
    Returns digits only with country code.

    Args:
        phone: The phone number to normalize

    Returns:
        str: Normalized phone number (digits only)
    """
    # Remove ALL non-digit characters
    normalized = ''.join(c for c in phone if c.isdigit())

    # Ensure we're returning a string
    if not isinstance(normalized, str):
        logger.error(f"normalize_phone_number returned non-string type: {type(normalized)}")
        raise ValueError(f"Expected string but got {type(normalized)}")

    return normalized
