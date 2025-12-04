import os
import logging
from convex import ConvexClient
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")  # Load Convex-specific env vars

logger = logging.getLogger(__name__)

class ConvexClientError(Exception):
    """Base exception for Convex client operations"""
    pass

def create_convex_client() -> ConvexClient:
    """
    Creates a Convex client for accessing the Convex backend.
    
    Returns:
        ConvexClient: Initialized Convex client
        
    Raises:
        ValueError: If CONVEX_URL is not set
    """
    convex_url = os.getenv("CONVEX_URL")
    if not convex_url:
        raise ValueError("CONVEX_URL environment variable is not set")
    
    client = ConvexClient(convex_url)
    
    return client

# Global client instance for reuse
_client_instance = None

def get_client() -> ConvexClient:
    """
    Get or create a global Convex client instance.
    
    Returns:
        ConvexClient: The global client instance
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = create_convex_client()
    return _client_instance
