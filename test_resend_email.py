#!/usr/bin/env python3
"""
Simple script to test sending an email via Resend.
"""

import os
import httpx
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Resend API key from environment
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

def test_send_email():
    """Test sending an email via Resend API."""
    if not RESEND_API_KEY:
        print("Error: RESEND_API_KEY environment variable not set")
        return

    url = "https://api.resend.com/emails"

    payload = {
        "from": "noreply@ampr.fi",
        "to": ["chrisjgeorgen@gmail.com"],
        "subject": "Test Email from Resend",
        "html": "<p>This is a test email sent via Resend API.</p>"
    }

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = httpx.post(url, json=payload, headers=headers)
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")

        if response.status_code == 200:
            print("Email sent successfully!")
        else:
            print("Failed to send email")
    except Exception as e:
        print(f"Error sending email: {str(e)}")

if __name__ == "__main__":
    test_send_email()