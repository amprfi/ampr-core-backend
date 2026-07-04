"""
Tests for Mistral SDK agents (AMPRFI-120).

Mocked tests for structured-output agents to verify the response_format
and schema handling without requiring live API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from src.agents.mistral_helpers import (
    complete_json_schema,
    extract_text_from_content,
    parse_json_from_content,
    build_messages,
    get_mistral_client,
    MODEL_SMALL,
    to_strict_schema,
)
from src.agents.currency_inferrer import (
    CurrencyInferrerAgent,
    CurrencyInference,
    get_currency_inferrer_agent,
)
from src.agents.watchlist_inferrer import (
    WatchlistInferrerAgent,
    WatchlistIntent,
    get_watchlist_inferrer_agent,
)
from src.agents.date_preprocessor import (
    DatePreprocessorAgent,
    DateContext,
    get_date_preprocessor_agent,
)
from src.agents.extractor import (
    ExtractorAgent,
    ExtractedProfile,
    get_extractor_agent,
)
from src.agents.summarizer import (
    SummarizerAgent,
    get_summarizer_agent,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_mistral_client():
    """Create a mocked Mistral client for testing."""
    client = MagicMock()
    client.chat.complete_async = AsyncMock()
    return client


@pytest.fixture
def mock_response():
    """Create a mocked Mistral response with structured output."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = '{"test": "value"}'
    return response


@pytest.fixture
def mock_reasoning_response():
    """Create a mocked Mistral response with reasoning chunks."""
    response = MagicMock()
    response.choices = [MagicMock()]
    # When reasoning_effort="high", content is a list of chunks
    response.choices[0].message.content = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "Let me think..."}]},
        {"type": "text", "text": '{"test": "value"}'},
    ]
    return response


# =============================================================================
# Test mistral_helpers.py
# =============================================================================

class TestExtractTextFromContent:
    """Tests for extract_text_from_content helper."""

    def test_extract_text_from_string(self):
        """Test extracting text from a plain string."""
        assert extract_text_from_content("hello world") == "hello world"

    def test_extract_text_from_none(self):
        """Test extracting text from None."""
        assert extract_text_from_content(None) == ""

    def test_extract_text_from_reasoning_chunks(self):
        """Test extracting text from reasoning chunks (list format)."""
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Thinking..."}]},
            {"type": "text", "text": "Hello world"},
        ]
        assert extract_text_from_content(content) == "Hello world"

    def test_extract_text_discards_thinking_chunks(self):
        """Test that thinking chunks are discarded."""
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Secret thought"}]},
            {"type": "text", "text": "Public response"},
        ]
        assert extract_text_from_content(content) == "Public response"


class TestParseJsonFromContent:
    """Tests for parse_json_from_content helper."""

    def test_parse_json_from_string(self):
        """Test parsing JSON from a plain string."""
        result = parse_json_from_content('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_from_reasoning_chunks(self):
        """Test parsing JSON from reasoning chunks."""
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Thinking..."}]},
            {"type": "text", "text": '{"key": "value"}'},
        ]
        result = parse_json_from_content(content)
        assert result == {"key": "value"}

    def test_parse_json_empty_content_raises(self):
        """Test that empty content raises ValueError."""
        with pytest.raises(ValueError, match="No text content found"):
            parse_json_from_content("")

    def test_parse_json_invalid_json_raises(self):
        """Test that invalid JSON raises JSONDecodeError."""
        with pytest.raises(Exception):  # JSONDecodeError
            parse_json_from_content("not valid json")


class TestBuildMessages:
    """Tests for build_messages helper."""

    def test_build_messages_creates_system_and_user(self):
        """Test that build_messages creates SystemMessage and UserMessage."""
        from mistralai.client.models import SystemMessage, UserMessage

        messages = build_messages("system prompt", "user message")
        
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], UserMessage)
        assert messages[0].content == "system prompt"
        assert messages[1].content == "user message"


class TestCompleteJsonSchema:
    """Tests for complete_json_schema helper."""

    @pytest.mark.asyncio
    async def test_complete_json_schema_uses_response_format(self, mock_mistral_client, mock_response):
        """Test that complete_json_schema uses proper ResponseFormat with JSONSchema."""
        from mistralai.client.models import ResponseFormat, JSONSchema
        
        mock_mistral_client.chat.complete_async.return_value = mock_response
        
        schema = {"type": "object", "properties": {"test": {"type": "string"}}}
        
        result = await complete_json_schema(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            schema=schema,
            temperature=0.1,
            reasoning_effort="none",
        )
        
        # Verify the client was called
        mock_mistral_client.chat.complete_async.assert_called_once()
        
        # Get the call arguments
        call_args = mock_mistral_client.chat.complete_async.call_args
        
        # Verify response_format is a ResponseFormat object
        assert isinstance(call_args.kwargs.get("response_format"), ResponseFormat)
        
        # Verify it has json_schema
        response_format = call_args.kwargs.get("response_format")
        assert response_format.type == "json_schema"
        assert response_format.json_schema is not None
        # The schema passed should be the strict-transformed version
        transformed_schema = response_format.json_schema.schema_definition
        assert transformed_schema["type"] == "object"
        assert transformed_schema.get("additionalProperties") == False
        assert "required" in transformed_schema
        assert "test" in transformed_schema["required"]
        assert response_format.json_schema.strict is True

    @pytest.mark.asyncio
    async def test_complete_json_schema_requires_explicit_params(self, mock_mistral_client, mock_response):
        """Test that complete_json_schema requires explicit temperature and reasoning_effort."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        
        schema = {"type": "object"}
        
        # Should fail without temperature
        with pytest.raises(TypeError):
            await complete_json_schema(
                client=mock_mistral_client,
                model=MODEL_SMALL,
                messages=[],
                schema=schema,
                reasoning_effort="none",
            )
        
        # Should fail without reasoning_effort
        with pytest.raises(TypeError):
            await complete_json_schema(
                client=mock_mistral_client,
                model=MODEL_SMALL,
                messages=[],
                schema=schema,
                temperature=0.1,
            )

    @pytest.mark.asyncio
    async def test_complete_json_schema_strict_mode_and_reasoning_coexist(self, mock_mistral_client, mock_response):
        """
        Test that json_schema strict mode and reasoning_effort can coexist.
        
        This verifies the open item from the review: mistral-small-latest accepts
        response_format: json_schema strict=True + reasoning_effort simultaneously.
        The mocked test verifies the parameters are correctly passed to the API.
        
        NOTE: Full validation requires live API calls, but this ensures the
        parameters are correctly structured for the API.
        """
        from mistralai.client.models import ResponseFormat, JSONSchema
        
        mock_mistral_client.chat.complete_async.return_value = mock_response
        
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}
        
        await complete_json_schema(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            schema=schema,
            temperature=0.7,
            reasoning_effort="high",
        )
        
        # Verify the API was called with both strict mode and reasoning_effort
        call_args = mock_mistral_client.chat.complete_async.call_args
        
        # Check reasoning_effort is passed
        assert call_args.kwargs.get("reasoning_effort") == "high"
        
        # Check response_format has strict mode
        response_format = call_args.kwargs.get("response_format")
        assert isinstance(response_format, ResponseFormat)
        assert response_format.type == "json_schema"
        assert response_format.json_schema.strict is True
        
        # Verify schema was transformed to strict-mode compliant
        transformed_schema = response_format.json_schema.schema_definition
        assert transformed_schema.get("additionalProperties") == False
        assert "required" in transformed_schema

    @pytest.mark.asyncio
    async def test_complete_json_schema_parses_response(self, mock_mistral_client, mock_response):
        """Test that complete_json_schema correctly parses the response."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        
        schema = {"type": "object"}
        
        result = await complete_json_schema(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            schema=schema,
            temperature=0.1,
            reasoning_effort="none",
        )
        
        assert result == {"test": "value"}

    @pytest.mark.asyncio
    async def test_complete_json_schema_with_reasoning_chunks(self, mock_mistral_client, mock_reasoning_response):
        """Test that complete_json_schema handles reasoning chunks correctly."""
        mock_mistral_client.chat.complete_async.return_value = mock_reasoning_response
        
        schema = {"type": "object"}
        
        result = await complete_json_schema(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            schema=schema,
            temperature=0.1,
            reasoning_effort="high",
        )
        
        assert result == {"test": "value"}


class TestToStrictSchema:
    """Tests for to_strict_schema helper."""

    def test_adds_additional_properties_false_to_object(self):
        """Test that additionalProperties: false is added to object schemas."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        result = to_strict_schema(schema)
        
        assert result["additionalProperties"] == False
        assert result["type"] == "object"

    def test_adds_all_properties_to_required(self):
        """Test that all property names are added to required array."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string"}
            }
        }
        result = to_strict_schema(schema)
        
        assert "required" in result
        assert set(result["required"]) == {"name", "age", "email"}

    def test_preserves_existing_required(self):
        """Test that existing required fields are merged with all properties."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string"}
            },
            "required": ["name"]
        }
        result = to_strict_schema(schema)
        
        assert set(result["required"]) == {"name", "age", "email"}

    def test_handles_nested_objects(self):
        """Test that nested object schemas are also made strict."""
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"}
                    }
                }
            }
        }
        result = to_strict_schema(schema)
        
        assert result["additionalProperties"] == False
        assert result["properties"]["user"]["additionalProperties"] == False
        assert set(result["properties"]["user"]["required"]) == {"name", "age"}

    def test_handles_arrays_with_object_items(self):
        """Test that array items with object schemas are made strict."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "value": {"type": "integer"}
                        }
                    }
                }
            }
        }
        result = to_strict_schema(schema)
        
        items_schema = result["properties"]["items"]["items"]
        assert items_schema["additionalProperties"] == False
        assert set(items_schema["required"]) == {"id", "value"}

    def test_handles_empty_properties(self):
        """Test that objects with no properties are handled gracefully."""
        schema = {
            "type": "object",
            "properties": {}
        }
        result = to_strict_schema(schema)
        
        assert result["additionalProperties"] == False
        # Empty properties means no required fields
        assert result.get("required") is None

    def test_does_not_mutate_original(self):
        """Test that the original schema is not mutated."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}}
        }
        original_copy = schema.copy()
        
        result = to_strict_schema(schema)
        
        # Original should be unchanged
        assert "additionalProperties" not in schema
        assert "required" not in schema
        # Result should have the additions
        assert result["additionalProperties"] == False
        assert "required" in result


# =============================================================================
# Test currency_inferrer.py
# =============================================================================

class TestCurrencyInferrer:
    """Tests for CurrencyInferrerAgent."""

    @pytest.mark.asyncio
    async def test_currency_inferrer_uses_structured_output(self, mock_mistral_client, mock_response):
        """Test that CurrencyInferrerAgent uses structured JSON output."""
        with patch("src.agents.currency_inferrer.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.return_value = mock_response
            
            agent = CurrencyInferrerAgent()
            
            # Mock the schema
            agent.schema = {"type": "object", "properties": {"asset_currencies": {"type": "array"}}}
            
            result = await agent.run("Test message")
            
            # Verify the agent returned a CurrencyInference instance
            assert isinstance(result, CurrencyInference)

    @pytest.mark.asyncio
    async def test_currency_inferrer_fallback(self, mock_mistral_client):
        """Test that CurrencyInferrerAgent returns empty fallback on error."""
        with patch("src.agents.currency_inferrer.get_shared_client", return_value=mock_mistral_client):
            # Make the API call fail
            mock_mistral_client.chat.complete_async.side_effect = Exception("API error")
            
            agent = CurrencyInferrerAgent()
            result = await agent.run("Test message")
            
            # Should return empty CurrencyInference on error
            assert isinstance(result, CurrencyInference)
            assert result.asset_currencies is None


# =============================================================================
# Test watchlist_inferrer.py
# =============================================================================

class TestWatchlistInferrer:
    """Tests for WatchlistInferrerAgent."""

    @pytest.mark.asyncio
    async def test_watchlist_inferrer_uses_structured_output(self, mock_mistral_client, mock_response):
        """Test that WatchlistInferrerAgent uses structured JSON output."""
        with patch("src.agents.watchlist_inferrer.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.return_value = mock_response
            
            agent = WatchlistInferrerAgent()
            
            # Mock the schema to return a boolean
            mock_response.choices[0].message.content = '{"is_explicit_watch": true}'
            
            result = await agent.run("Test message")
            
            # Should return a boolean
            assert isinstance(result, bool)
            assert result is True

    @pytest.mark.asyncio
    async def test_watchlist_inferrer_fallback(self, mock_mistral_client):
        """Test that WatchlistInferrerAgent returns False on error."""
        with patch("src.agents.watchlist_inferrer.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.side_effect = Exception("API error")
            
            agent = WatchlistInferrerAgent()
            result = await agent.run("Test message")
            
            # Should return False on error
            assert result is False


# =============================================================================
# Test date_preprocessor.py
# =============================================================================

class TestDatePreprocessor:
    """Tests for DatePreprocessorAgent."""

    @pytest.mark.asyncio
    async def test_date_preprocessor_uses_structured_output(self, mock_mistral_client, mock_response):
        """Test that DatePreprocessorAgent uses structured JSON output."""
        with patch("src.agents.date_preprocessor.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.return_value = mock_response
            
            agent = DatePreprocessorAgent()
            
            # Mock the schema
            mock_response.choices[0].message.content = '{"date_references": []}'
            
            result = await agent.run("Test message")
            
            # Should return a DateContext instance directly
            assert isinstance(result, DateContext)


# =============================================================================
# Test extractor.py
# =============================================================================

class TestExtractor:
    """Tests for ExtractorAgent."""

    @pytest.fixture
    def mock_convex_client(self):
        """Create a mocked Convex client."""
        client = MagicMock()
        client.query = MagicMock(return_value={})
        return client

    @pytest.mark.asyncio
    async def test_extractor_schema_uses_response_format(self, mock_mistral_client, mock_response):
        """Test that ExtractorAgent's schema is properly passed to complete_json_schema."""
        with patch("src.agents.extractor.get_shared_client", return_value=mock_mistral_client):
            with patch("src.agents.extractor._get_current_profile_context", new_callable=AsyncMock) as mock_profile:
                mock_profile.return_value = "Current profile: test"
                mock_mistral_client.chat.complete_async.return_value = mock_response
                mock_response.choices[0].message.content = '{"inferred_investment_horizon": null}'
                
                agent = ExtractorAgent()
                
                # Verify the agent has a schema from the Pydantic model
                assert hasattr(agent, 'schema')
                assert 'properties' in agent.schema
                
                # Verify the schema includes expected fields
                assert 'inferred_investment_horizon' in agent.schema['properties']
                
                # Test the agent run method with proper parameters
                mock_client = MagicMock()
                result = await agent.run("Test message", convex_client=mock_client, user_id="test_user")
                
                # Should return ExtractedProfile directly
                assert isinstance(result, ExtractedProfile)


# =============================================================================
# Test summarizer.py
# =============================================================================

class TestSummarizer:
    """Tests for SummarizerAgent."""

    @pytest.mark.asyncio
    async def test_summarizer_uses_sdk(self, mock_mistral_client, mock_response):
        """Test that SummarizerAgent uses Mistral SDK."""
        with patch("src.agents.summarizer.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.return_value = mock_response
            mock_response.choices[0].message.content = "This is a summary"
            
            agent = SummarizerAgent()
            result = await agent.run("Test message to summarize")
            
            # Should return a string directly
            assert isinstance(result, str)
            assert result == "This is a summary"

    @pytest.mark.asyncio
    async def test_summarizer_fallback(self, mock_mistral_client):
        """Test that SummarizerAgent returns proper fallback on error."""
        with patch("src.agents.summarizer.get_shared_client", return_value=mock_mistral_client):
            mock_mistral_client.chat.complete_async.side_effect = Exception("API error")
            
            agent = SummarizerAgent()
            result = await agent.run("Test message" * 100)  # Long message
            
            # Should return empty string fallback, not truncated message
            assert isinstance(result, str)
            assert result == ""
