"""
Vonage client module for sending SMS and WhatsApp messages.

This module provides a simple client for sending messages using the Vonage API.
"""
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from vonage import Vonage
from vonage_messages import Sms, WhatsappText
from src.config.vonage_config import get_vonage_client, get_vonage_sms_sender, get_vonage_whatsapp_sender

# Load environment variables from .env file
load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

class VonageClient:
    """
    A client for sending messages via Vonage's API.

    This client provides methods for sending SMS and WhatsApp messages.
    """

    def __init__(self):
        """
        Initialize the Vonage client.
        """
        self.client = get_vonage_client()
        self.sms_sender = get_vonage_sms_sender()
        self.whatsapp_sender = get_vonage_whatsapp_sender()

    def send_sms(self, to: str, text: str) -> Optional[dict]:
        """
        Send an SMS message.

        Args:
            to: The recipient's phone number
            text: The message text

        Returns:
            Dictionary containing the response data or None if failed
        """
        try:
            message = Sms(
                from_=self.sms_sender,
                to=to,
                text=text
            )

            response = self.client.messages.send(message)
            logger.info(f"SMS sent successfully to {to}")
            return response.model_dump(exclude_unset=True)

        except Exception as e:
            logger.error(f"Failed to send SMS to {to}: {str(e)}")
            return None

    # def send_whatsapp(self, to: str, text: str) -> Optional[dict]:
    #     """
    #     Send a WhatsApp message.
    #
    #     Args:
    #         to: The recipient's WhatsApp number
    #         text: The message text
    #
    #     Returns:
    #         Dictionary containing the response data or None if failed
    #     """
    #     try:
    #         message = WhatsappText(
    #             from_=self.whatsapp_sender,
    #             to=to,
    #             text=text
    #         )
    #
    #         response = self.client.messages.send(message)
    #         logger.info(f"WhatsApp message sent successfully to {to}")
    #         return response.model_dump(exclude_unset=True)
    #
    #     except Exception as e:
    #         logger.error(f"Failed to send WhatsApp message to {to}: {str(e)}")
    #         return None

def test_vonage_client():
    """
    Test function to demonstrate usage of the Vonage client.
    """
    client = VonageClient()

    # Test sending SMS
    sms_response = client.send_sms(
        to="18472840023",
        text="Hello from Vonage SMS!"
    )
    print("SMS Response:", sms_response)

    # Test sending WhatsApp message
    # whatsapp_response = client.send_whatsapp(
    #    to="18472840023",
    #    text="Hello from Vonage WhatsApp!"
    #)
    # print("WhatsApp Response:", whatsapp_response)

if __name__ == "__main__":
    test_vonage_client()