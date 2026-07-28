"""
Tests for the notification synthesizer (AMPRFI-126).

Verifies that synthesize_notifications:
- Returns single-content notifications unchanged (fast path)
- Uses the shared Mistral SDK client with explicit model/temperature/reasoning settings
- Extracts text correctly from both plain-string and reasoning-chunk responses
- Falls back to newline-concatenation on SDK failure (including blank/empty responses)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.notifications.synthesizer import synthesize_notifications


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
    """Create a mocked Mistral response with plain string content."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = "Combined notification text"
    return response


@pytest.fixture
def mock_reasoning_response():
    """Create a mocked Mistral response with reasoning chunks (list format)."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "Let me combine these..."}]},
        {"type": "text", "text": "Combined notification text"},
    ]
    return response


# =============================================================================
# Fast Path Tests
# =============================================================================

class TestSynthesizeFastPath:
    """Tests for the single-content fast path."""

    @pytest.mark.asyncio
    async def test_single_content_returns_unchanged(self, mock_mistral_client):
        """A single notification should be returned as-is without any SDK call."""
        content = "BTC price crossed $100,000"

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications([content])

        assert result == content
        # The SDK client should never have been called
        mock_mistral_client.chat.complete_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_content_preserves_exact_text(self, mock_mistral_client):
        """The fast path must return the exact original string, not a copy."""
        content = "ETH: +5.2% in the last 24 hours — threshold alert at 10%"

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications([content])

        assert result is content

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, mock_mistral_client):
        """An empty list should return an empty string (no SDK call)."""
        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications([])

        assert result == ""
        mock_mistral_client.chat.complete_async.assert_not_called()


# =============================================================================
# Successful Synthesis Tests
# =============================================================================

class TestSynthesizeSuccess:
    """Tests for successful multi-content synthesis."""

    @pytest.mark.asyncio
    async def test_successful_synthesis_returns_combined_text(
        self, mock_mistral_client, mock_response
    ):
        """Multiple notifications should be synthesized into a single message."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        contents = [
            "BTC price crossed $100,000",
            "ETH is up 5.2% today",
        ]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "Combined notification text"
        mock_mistral_client.chat.complete_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_synthesis_uses_correct_model(self, mock_mistral_client, mock_response):
        """Synthesis must use mistral-small-latest (not a stale constant value)."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            await synthesize_notifications(["A", "B"])

        call_args = mock_mistral_client.chat.complete_async.call_args
        assert call_args.kwargs.get("model") == "mistral-small-latest"

    @pytest.mark.asyncio
    async def test_synthesis_uses_explicit_temperature(self, mock_mistral_client, mock_response):
        """Synthesis must pass an explicit temperature (not rely on SDK default)."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            await synthesize_notifications(["A", "B"])

        call_args = mock_mistral_client.chat.complete_async.call_args
        assert "temperature" in call_args.kwargs
        assert call_args.kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_synthesis_uses_explicit_reasoning_effort(
        self, mock_mistral_client, mock_response
    ):
        """Synthesis must pass an explicit reasoning_effort (not rely on SDK default)."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            await synthesize_notifications(["A", "B"])

        call_args = mock_mistral_client.chat.complete_async.call_args
        assert "reasoning_effort" in call_args.kwargs
        assert call_args.kwargs["reasoning_effort"] == "none"

    @pytest.mark.asyncio
    async def test_synthesis_passes_messages_with_system_prompt(
        self, mock_mistral_client, mock_response
    ):
        """Synthesis must build messages from the system prompt and user content."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        contents = ["BTC: $100k", "ETH: $5k"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            await synthesize_notifications(contents)

        call_args = mock_mistral_client.chat.complete_async.call_args
        messages = call_args.kwargs.get("messages")

        assert len(messages) == 2
        # First message is the system prompt
        assert messages[0].content is not None
        assert "Preserve all important information" in messages[0].content
        # Second message contains the numbered notifications
        assert messages[1].content is not None
        assert "BTC: $100k" in messages[1].content
        assert "ETH: $5k" in messages[1].content

    @pytest.mark.asyncio
    async def test_synthesis_preserves_key_facts_in_prompt(
        self, mock_mistral_client, mock_response
    ):
        """The synthesis prompt must include asset names, prices, percentages, and thresholds."""
        mock_mistral_client.chat.complete_async.return_value = mock_response

        contents = [
            "BTC crossed $100,000 (threshold: $95,000)",
            "ETH is up 5.2% (threshold: 5%)",
        ]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            await synthesize_notifications(contents)

        call_args = mock_mistral_client.chat.complete_async.call_args
        user_message = call_args.kwargs["messages"][1].content

        # All key data points must be present in the prompt
        assert "BTC" in user_message
        assert "$100,000" in user_message
        assert "$95,000" in user_message
        assert "ETH" in user_message
        assert "5.2%" in user_message
        assert "5%" in user_message


# =============================================================================
# Extracted Response Text Tests
# =============================================================================

class TestExtractedResponseText:
    """Tests for text extraction from Mistral responses."""

    @pytest.mark.asyncio
    async def test_plain_string_content_extracted(
        self, mock_mistral_client, mock_response
    ):
        """When the API returns a plain string, it should be used directly."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        mock_response.choices[0].message.content = "Synthesized: BTC and ETH alerts"

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(["A", "B"])

        assert result == "Synthesized: BTC and ETH alerts"

    @pytest.mark.asyncio
    async def test_reasoning_chunks_text_extracted(
        self, mock_mistral_client, mock_reasoning_response
    ):
        """When reasoning_effort returns chunks, only text chunks should be extracted."""
        mock_mistral_client.chat.complete_async.return_value = mock_reasoning_response

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(["A", "B"])

        # The thinking chunk should be discarded; only the text chunk remains
        assert result == "Combined notification text"


# =============================================================================
# Graceful Fallback Tests
# =============================================================================

class TestGracefulFallback:
    """Tests for fallback behavior when the SDK fails or returns blank content."""

    @pytest.mark.asyncio
    async def test_fallback_on_api_exception(self, mock_mistral_client):
        """On SDK exception, fall back to newline-concatenation."""
        mock_mistral_client.chat.complete_async.side_effect = Exception("API error")

        contents = ["BTC: $100k", "ETH: $5k"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "BTC: $100k\n\nETH: $5k"

    @pytest.mark.asyncio
    async def test_fallback_preserves_all_contents(self, mock_mistral_client):
        """Fallback must include every notification, separated by double newlines."""
        mock_mistral_client.chat.complete_async.side_effect = ConnectionError("timeout")

        contents = ["Alert 1", "Alert 2", "Alert 3"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "Alert 1\n\nAlert 2\n\nAlert 3"

    @pytest.mark.asyncio
    async def test_fallback_on_missing_api_key(self):
        """When MISTRAL_API_KEY is not set, get_shared_client raises and we fall back."""
        contents = ["BTC: $100k", "ETH: $5k"]

        # get_shared_client raises ValueError when MISTRAL_API_KEY is not set
        with patch(
            "src.notifications.synthesizer.get_shared_client",
            side_effect=ValueError("MISTRAL_API_KEY environment variable is required"),
        ):
            result = await synthesize_notifications(contents)

        assert result == "BTC: $100k\n\nETH: $5k"

    @pytest.mark.asyncio
    async def test_fallback_on_client_creation_failure(self, mock_mistral_client):
        """Fallback should trigger if the client itself fails to respond."""
        # Simulate a network-level error during the API call
        mock_mistral_client.chat.complete_async.side_effect = OSError("Network unreachable")

        contents = ["Price alert: BTC at $100,000", "Threshold: $95,000"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "Price alert: BTC at $100,000\n\nThreshold: $95,000"

    @pytest.mark.asyncio
    async def test_empty_response_falls_back_to_concatenation(
        self, mock_mistral_client, mock_response
    ):
        """An empty string response from the API must fall back to concatenation."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        mock_response.choices[0].message.content = ""

        contents = ["BTC: $100k", "ETH: $5k"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "BTC: $100k\n\nETH: $5k"

    @pytest.mark.asyncio
    async def test_none_response_falls_back_to_concatenation(
        self, mock_mistral_client, mock_response
    ):
        """A None response content must fall back to concatenation."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        mock_response.choices[0].message.content = None

        contents = ["BTC: $100k", "ETH: $5k"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "BTC: $100k\n\nETH: $5k"

    @pytest.mark.asyncio
    async def test_whitespace_only_response_falls_back_to_concatenation(
        self, mock_mistral_client, mock_response
    ):
        """A whitespace-only response must fall back to concatenation."""
        mock_mistral_client.chat.complete_async.return_value = mock_response
        mock_response.choices[0].message.content = "   \n\t  \n  "

        contents = ["BTC: $100k", "ETH: $5k"]

        with patch(
            "src.notifications.synthesizer.get_shared_client",
            return_value=mock_mistral_client,
        ):
            result = await synthesize_notifications(contents)

        assert result == "BTC: $100k\n\nETH: $5k"


# =============================================================================
# No pydantic_ai Dependency Tests
# =============================================================================

class TestNoPydanticAiDependency:
    """Verify the synthesizer no longer depends on pydantic_ai."""

    @pytest.mark.asyncio
    async def test_no_pydantic_ai_import(self):
        """The synthesizer module must not import pydantic_ai."""
        import src.notifications.synthesizer as synth_module

        source = open(synth_module.__file__).read()
        assert "pydantic_ai" not in source, (
            "synthesizer.py must not import or reference pydantic_ai"
        )

    @pytest.mark.asyncio
    async def test_no_agent_instantiation(self):
        """The synthesizer module must not instantiate a pydantic_ai Agent."""
        import src.notifications.synthesizer as synth_module

        source = open(synth_module.__file__).read()
        assert "Agent(" not in source, (
            "synthesizer.py must not instantiate pydantic_ai.Agent"
        )
