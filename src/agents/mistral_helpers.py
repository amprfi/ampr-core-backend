"""
Shared helpers for Mistral SDK usage across agents.

This module provides centralized utilities for:
- Mistral SDK client creation with retry configuration
- Response parsing (reasoning chunks, text extraction)
- Structured output handling with json_schema
- Error handling and graceful fallbacks
"""

import json
import logging
import os
from typing import Any, Optional, Union
import copy

from mistralai.client import Mistral
from mistralai.client.models import JSONSchema, ResponseFormat, SystemMessage, UserMessage
from mistralai.client.utils.retries import BackoffStrategy, RetryConfig

logger = logging.getLogger(__name__)

# Model identifiers (canonical names per Mistral SDK 2.x)
MODEL_SMALL = "mistral-small-latest"  # = mistral-small-2603
MODEL_MEDIUM = "mistral-medium-3-5"  # dash form, not dot

# Shared retry configuration for the Mistral client
# BackoffStrategy parameters are in seconds, not milliseconds
_RETRY_CONFIG = RetryConfig(
    strategy="exponential",
    backoff=BackoffStrategy(
        initial_interval=1,  # 1 second
        max_interval=30,     # 30 seconds
        exponent=2.0,        # exponential backoff
        max_elapsed_time=300,  # 5 minutes total
    ),
    retry_connection_errors=True,
)


def get_mistral_client() -> Mistral:
    """
    Get a configured Mistral SDK client with retry configuration.

    Returns a singleton client instance with:
    - API key from MISTRAL_API_KEY environment variable
    - Retry configuration for handling transient failures

    Note: The Mistral SDK handles retries internally via its own configuration.
    We configure it once at client creation time.
    """
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY environment variable is required")

    # Create client with retry configuration
    # The Mistral SDK handles retries internally via RetryConfig
    client = Mistral(api_key=api_key, retry_config=_RETRY_CONFIG)
    return client


def extract_text_from_content(content: Any) -> str:
    """
    Extract text from Mistral response content.

    When reasoning_effort="high", Mistral returns content as a list of chunks
    (ThinkChunk and TextChunk). This helper extracts only the text portions.

    When reasoning_effort="none", content is a plain string.

    Args:
        content: The message content from Mistral response (str or list)

    Returns:
        The extracted text as a single string
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        # Content is a list of chunks: extract text from TextChunk items
        text_parts = []
        for chunk in content:
            if isinstance(chunk, dict):
                # Check for TextChunk (type: "text")
                if chunk.get("type") == "text":
                    text_parts.append(chunk.get("text", ""))
                # Discard ThinkChunk (type: "thinking") - never surface to users
            elif hasattr(chunk, "type"):
                # Handle Pydantic model chunks
                if chunk.type == "text":  # type: ignore
                    text_parts.append(chunk.text)  # type: ignore
        return "".join(text_parts)

    # Fallback: try to convert to string
    return str(content)


def parse_json_from_content(content: Any) -> dict[str, Any]:
    """
    Parse JSON from Mistral response content.

    Handles both string content (reasoning_effort="none") and list content
    (reasoning_effort="high"). Extracts text, then parses as JSON.

    Args:
        content: The message content from Mistral response

    Returns:
        Parsed JSON as a dictionary

    Raises:
        json.JSONDecodeError: If content is not valid JSON
        ValueError: If content cannot be extracted as text
    """
    text_content = extract_text_from_content(content)
    if not text_content:
        raise ValueError("No text content found to parse as JSON")
    return json.loads(text_content)


def build_messages(system_prompt: str, user_content: str) -> list[Union[SystemMessage, UserMessage]]:
    """
    Build Mistral chat messages from system prompt and user content.

    Args:
        system_prompt: The system prompt string
        user_content: The user message string

    Returns:
        List of message objects (SystemMessage, UserMessage) for the Mistral API
    """
    return [
        SystemMessage(content=system_prompt),
        UserMessage(content=user_content),
    ]


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Transform a Pydantic-generated JSON schema to be strict-mode compliant.

    Mistral's strict mode requires:
    - additionalProperties: false on all object schemas
    - All properties listed in required arrays

    Pydantic's model_json_schema() does not include these by default,
    which causes unreliable/garbled JSON output in strict mode.

    This recursively transforms the schema to add these requirements.

    Args:
        schema: The JSON schema to transform (typically from model.model_json_schema())

    Returns:
        A new schema dict with strict-mode compliance additions
    """
    # Create a deep copy to avoid mutating the original
    schema_copy = copy.deepcopy(schema)

    _make_strict_recursive(schema_copy)
    return schema_copy


def _make_strict_recursive(schema: dict[str, Any]) -> None:
    """
    Recursively add strict-mode requirements to a schema dict.

    Modifies the schema in-place.
    """
    # Handle object schemas
    if schema.get("type") == "object":
        properties = schema.get("properties", {})

        # Add additionalProperties: false
        schema["additionalProperties"] = False

        # Add all property names to required (if properties exist)
        if properties and "required" not in schema:
            schema["required"] = list(properties.keys())
        elif properties and "required" in schema:
            # Merge existing required with all properties
            existing_required = set(schema["required"])
            all_properties = set(properties.keys())
            schema["required"] = list(existing_required | all_properties)

    # Handle arrays - process items schema
    if schema.get("type") == "array" and "items" in schema:
        items = schema["items"]
        if isinstance(items, dict):
            _make_strict_recursive(items)
        elif isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    _make_strict_recursive(item)

    # Handle allOf - process each schema in the array
    if "allOf" in schema and isinstance(schema["allOf"], list):
        for subschema in schema["allOf"]:
            if isinstance(subschema, dict):
                _make_strict_recursive(subschema)

    # Handle anyOf/oneOf - process each schema in the array
    for key in ["anyOf", "oneOf"]:
        if key in schema and isinstance(schema[key], list):
            for subschema in schema[key]:
                if isinstance(subschema, dict):
                    _make_strict_recursive(subschema)

    # Handle nested properties in objects
    if schema.get("type") == "object" and "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            if isinstance(prop_schema, dict):
                _make_strict_recursive(prop_schema)

    # Handle definitions (for $ref resolution)
    if "$defs" in schema and isinstance(schema["$defs"], dict):
        for def_name, def_schema in schema["$defs"].items():
            if isinstance(def_schema, dict):
                _make_strict_recursive(def_schema)





async def complete_json_schema(
    client: Mistral,
    model: str,
    messages: list[Union[SystemMessage, UserMessage]],
    schema: dict[str, Any],
    temperature: float,
    reasoning_effort: str,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """
    Execute a Mistral completion with strict JSON schema response format.

    This is the helper for structured-output agents. It:
    - Transforms the schema to be strict-mode compliant (adds additionalProperties: false, populates required)
    - Uses response_format: json_schema with strict: true
    - Executes the completion via the SDK client (which handles retries via RetryConfig)
    - Extracts and parses the JSON response

    Args:
        client: Mistral SDK client instance
        model: Model identifier
        messages: List of message objects (SystemMessage, UserMessage)
        schema: JSON schema for the output (from Pydantic model.model_json_schema())
        temperature: Sampling temperature (required, for explicit per-agent control)
        reasoning_effort: "high" or "none" (required, for explicit per-agent control)
        max_tokens: Optional maximum tokens

    Returns:
        Parsed JSON response as a dictionary

    Raises:
        Exception: On completion or parsing failures (caller should handle gracefully)
    """
    # Transform schema to be strict-mode compliant
    strict_schema = to_strict_schema(schema)

    # Use proper ResponseFormat with JSONSchema for structured output
    # The name parameter is required by the SDK; we use a generic name
    response_format = ResponseFormat(
        type="json_schema",
        json_schema=JSONSchema(
            name="structured_output",
            schema=strict_schema,
            strict=True,
        ),
    )

    try:
        response = await client.chat.complete_async(
            model=model,
            messages=messages,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            response_format=response_format,
            max_tokens=max_tokens,
        )

        # Extract content and parse as JSON
        content = response.choices[0].message.content
        return parse_json_from_content(content)
    except Exception as e:
        logger.error(f"Mistral completion failed: {e}", exc_info=True)
        raise


# Convenience: pre-configured client for reuse
_mistral_client: Optional[Mistral] = None


def get_shared_client() -> Mistral:
    """
    Get or create a shared Mistral client instance.

    This provides a singleton client for reuse across agents,
    avoiding repeated client instantiation.

    Returns:
        Configured Mistral client instance
    """
    global _mistral_client
    if _mistral_client is None:
        _mistral_client = get_mistral_client()
    return _mistral_client
