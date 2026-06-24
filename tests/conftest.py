"""
Pytest configuration for ampr-core-backend tests.

This file sets up environment to prevent module-level Agent initialization
from failing during test collection.
"""

import os

# Set a dummy API key to prevent UserError during module imports
# The actual value doesn't matter - we'll mock the agent calls in tests
os.environ['MISTRAL_API_KEY'] = 'test-api-key-for-testing-only'
