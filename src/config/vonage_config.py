"""
Vonage configuration module for the chat application.

This module provides functions to load Vonage credentials from environment variables
and create a configured Vonage client instance.
"""

import os
from typing import Optional
from vonage import Vonage, Auth

def get_vonage_client() -> Vonage:
    """
    Create and return a configured Vonage client instance.

    Returns:
        Vonage: Configured Vonage client

    Raises:
        ValueError: If required environment variables are missing
    """
    # Get environment variables
    application_id = os.getenv("VONAGE_APPLICATION_ID")
    private_key = os.getenv("VONAGE_PRIVATE_KEY")

    # Validate required environment variables
    if not application_id:
        raise ValueError("VONAGE_APPLICATION_ID environment variable is not set")
    if not private_key:
        raise ValueError("VONAGE_PRIVATE_KEY environment variable is not set")

    # Create and return a Vonage client
    return Vonage(Auth(application_id=application_id, private_key=private_key))

def get_vonage_sms_sender() -> str:
    """
    Get the default SMS sender number or name.

    Returns:
        str: The SMS sender number or name

    Raises:
        ValueError: If VONAGE_SMS_SENDER environment variable is not set
    """
    sms_sender = os.getenv("VONAGE_SMS_SENDER")
    if not sms_sender:
        raise ValueError("VONAGE_SMS_SENDER environment variable is not set")
    return sms_sender

def get_vonage_whatsapp_sender() -> str:
    """
    Get the default WhatsApp sender number.

    Returns:
        str: The WhatsApp sender number

    Raises:
        ValueError: If VONAGE_WHATSAPP_SENDER environment variable is not set
    """
    whatsapp_sender = os.getenv("VONAGE_WHATSAPP_SENDER")
    if not whatsapp_sender:
        raise ValueError("VONAGE_WHATSAPP_SENDER environment variable is not set")
    return whatsapp_sender