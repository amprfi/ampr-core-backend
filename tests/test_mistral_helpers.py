"""
Tests for shared Mistral SDK helpers (AMPRFI-115).

Covers:
- get_shared_client() singleton behavior (with state restoration)
- get_mistral_client() factory behavior (no singleton claim)
- complete_text() helper with explicit model, temperature, reasoning
- complete_text() error propagation (caller handles fallback)
- complete_text() handles reasoning chunks
- No in-scope SDK caller uses get_mistral_client() directly
- Currency converter behavioral coverage
"""

import pytest
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.mistral_helpers import (
    get_shared_client,
    get_mistral_client,
    complete_text,
    complete_json_schema,
    extract_text_from_content,
    build_messages,
    MODEL_SMALL,
    MODEL_MEDIUM,
)
from src.agents.currency_converter import convert_currency


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_mistral_client():
    """Create a mocked Mistral SDK client."""
    client = MagicMock()
    client.chat.complete_async = AsyncMock()
    return client


@pytest.fixture
def mock_text_response():
    """Create a mocked Mistral chat completion response with text content."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = "Hello, world!"
    return response


@pytest.fixture
def mock_reasoning_response():
    """Create a mocked Mistral response with reasoning chunks."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "Let me think..."}]},
        {"type": "text", "text": "Hello, world!"},
    ]
    return response


@pytest.fixture
def reset_shared_client():
    """Reset and restore the shared client singleton around each test."""
    import src.agents.mistral_helpers as mh
    original = mh._mistral_client
    mh._mistral_client = None
    yield
    mh._mistral_client = original


# =============================================================================
# Test get_shared_client() singleton behavior
# =============================================================================

class TestSharedClient:
    """Tests for get_shared_client() singleton behavior."""

    def test_shared_client_is_singleton(self, reset_shared_client):
        """get_shared_client() returns the same instance on repeated calls."""
        with patch("src.agents.mistral_helpers.get_mistral_client") as mock_factory:
            mock_client = MagicMock()
            mock_factory.return_value = mock_client

            client1 = get_shared_client()
            client2 = get_shared_client()

            assert client1 is client2
            assert client1 is mock_client
            # Factory should only be called once
            mock_factory.assert_called_once()

    def test_shared_client_persists_after_first_call(self, reset_shared_client):
        """After first call, subsequent calls return the cached instance."""
        with patch("src.agents.mistral_helpers.get_mistral_client") as mock_factory:
            mock_client = MagicMock()
            mock_factory.return_value = mock_client

            first = get_shared_client()
            second = get_shared_client()
            third = get_shared_client()

            assert first is second is third

    def test_shared_client_raises_without_api_key(self, reset_shared_client):
        """get_shared_client() raises ValueError when MISTRAL_API_KEY is not set."""
        with patch.dict("os.environ", {"MISTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
                get_shared_client()

    def test_shared_client_creates_new_when_reset(self, reset_shared_client):
        """After resetting _mistral_client, a new client is created."""
        with patch("src.agents.mistral_helpers.get_mistral_client") as mock_factory:
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()
            mock_factory.side_effect = [mock_client1, mock_client2]

            client1 = get_shared_client()
            import src.agents.mistral_helpers as mh
            mh._mistral_client = None
            client2 = get_shared_client()

            assert client1 is mock_client1
            assert client2 is mock_client2
            assert client1 is not client2


# =============================================================================
# Test get_mistral_client() factory behavior
# =============================================================================

class TestMistralClientFactory:
    """Tests for get_mistral_client() factory function."""

    def test_mistral_client_creates_new_instance_each_call(self):
        """get_mistral_client() creates a new instance on each call (not a singleton)."""
        with patch("src.agents.mistral_helpers.Mistral") as mock_mistral:
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()
            mock_mistral.side_effect = [mock_client1, mock_client2]

            with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
                client1 = get_mistral_client()
                client2 = get_mistral_client()

                assert client1 is mock_client1
                assert client2 is mock_client2
                assert client1 is not client2
                # Mistral should be called twice
                assert mock_mistral.call_count == 2

    def test_mistral_client_passes_api_key(self):
        """get_mistral_client() passes the API key to the Mistral constructor."""
        with patch("src.agents.mistral_helpers.Mistral") as mock_mistral:
            with patch.dict("os.environ", {"MISTRAL_API_KEY": "my-secret-key"}):
                get_mistral_client()

                call_kwargs = mock_mistral.call_args
                assert call_kwargs.kwargs["api_key"] == "my-secret-key"

    def test_mistral_client_passes_retry_config(self):
        """get_mistral_client() passes retry configuration to the Mistral constructor."""
        with patch("src.agents.mistral_helpers.Mistral") as mock_mistral:
            with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
                get_mistral_client()

                call_kwargs = mock_mistral.call_args
                assert "retry_config" in call_kwargs.kwargs
                assert call_kwargs.kwargs["retry_config"] is not None

    def test_mistral_client_raises_without_api_key(self):
        """get_mistral_client() raises ValueError when MISTRAL_API_KEY is not set."""
        with patch.dict("os.environ", {"MISTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
                get_mistral_client()


# =============================================================================
# Test complete_text() helper
# =============================================================================

class TestCompleteText:
    """Tests for complete_text() helper."""

    @pytest.mark.asyncio
    async def test_complete_text_returns_text(self, mock_mistral_client, mock_text_response):
        """complete_text() returns extracted text from the response."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        result = await complete_text(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            temperature=0.3,
            reasoning_effort="none",
        )

        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_complete_text_requires_explicit_model(self, mock_mistral_client, mock_text_response):
        """complete_text() requires explicit model parameter."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        with pytest.raises(TypeError):
            await complete_text(
                client=mock_mistral_client,
                messages=[],
                temperature=0.3,
                reasoning_effort="none",
            )

    @pytest.mark.asyncio
    async def test_complete_text_requires_explicit_temperature(self, mock_mistral_client, mock_text_response):
        """complete_text() requires explicit temperature parameter."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        with pytest.raises(TypeError):
            await complete_text(
                client=mock_mistral_client,
                model=MODEL_SMALL,
                messages=[],
                reasoning_effort="none",
            )

    @pytest.mark.asyncio
    async def test_complete_text_requires_explicit_reasoning_effort(self, mock_mistral_client, mock_text_response):
        """complete_text() requires explicit reasoning_effort parameter."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        with pytest.raises(TypeError):
            await complete_text(
                client=mock_mistral_client,
                model=MODEL_SMALL,
                messages=[],
                temperature=0.3,
            )

    @pytest.mark.asyncio
    async def test_complete_text_passes_params_to_sdk(self, mock_mistral_client, mock_text_response):
        """complete_text() passes model, temperature, and reasoning_effort to the SDK."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        await complete_text(
            client=mock_mistral_client,
            model=MODEL_MEDIUM,
            messages=[],
            temperature=0.7,
            reasoning_effort="high",
        )

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs["model"] == MODEL_MEDIUM
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_complete_text_handles_reasoning_chunks(self, mock_mistral_client, mock_reasoning_response):
        """complete_text() extracts text from reasoning chunks, discarding thinking."""
        mock_mistral_client.chat.complete_async.return_value = mock_reasoning_response

        result = await complete_text(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            temperature=0.3,
            reasoning_effort="high",
        )

        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_complete_text_propagates_errors(self, mock_mistral_client):
        """complete_text() propagates errors to the caller (caller handles fallback)."""
        mock_mistral_client.chat.complete_async.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            await complete_text(
                client=mock_mistral_client,
                model=MODEL_SMALL,
                messages=[],
                temperature=0.3,
                reasoning_effort="none",
            )

    @pytest.mark.asyncio
    async def test_complete_text_passes_max_tokens(self, mock_mistral_client, mock_text_response):
        """complete_text() passes max_tokens when provided."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        await complete_text(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            temperature=0.3,
            reasoning_effort="none",
            max_tokens=100,
        )

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_complete_text_passes_none_max_tokens(self, mock_mistral_client, mock_text_response):
        """complete_text() passes max_tokens=None when not provided (SDK handles null)."""
        mock_mistral_client.chat.complete_async.return_value = mock_text_response

        await complete_text(
            client=mock_mistral_client,
            model=MODEL_SMALL,
            messages=[],
            temperature=0.3,
            reasoning_effort="none",
        )

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs.get("max_tokens") is None


# =============================================================================
# Test: No in-scope SDK caller uses get_mistral_client() directly
# =============================================================================

# In-scope directories and deferred holdouts — mirrors test_migration_audit.py
_IN_SCOPE_DIRS = [
    "src/agents",
    "src/api",
    "src/modules",
    "src/notifications",
    "src/utils",
]

_IN_SCOPE_HOLDOUTS = {
    "src/agents/onboarding.py",
    "src/modules/defianalyst/agent.py",
    "src/modules/defianalyst/utils.py",
    "src/modules/lens/agent.py",
    "src/modules/oracle/agent.py",
}


def _list_in_scope_files():
    """List all in-scope Python files, excluding deferred holdouts."""
    import pathlib
    files = []
    for dir_path in _IN_SCOPE_DIRS:
        p = pathlib.Path(dir_path)
        if p.exists():
            files.extend(str(f) for f in p.rglob("*.py") if f.is_file())
    return [f for f in files if f not in _IN_SCOPE_HOLDOUTS and f != "src/agents/mistral_helpers.py"]


class TestNoDirectMistralClientUsage:
    """Tests to verify no in-scope SDK caller uses get_mistral_client() directly.

    Scans the same in-scope file set used by test_migration_audit.py so that
    new in-scope files are automatically covered by this gate.
    """

    def test_no_in_scope_file_uses_get_mistral_client_directly(self):
        """No in-scope file (excluding holdouts) should reference get_mistral_client()."""
        violations = []
        for file_path in _list_in_scope_files():
            content = pathlib.Path(file_path).read_text()
            if "get_mistral_client" in content:
                violations.append(file_path)

        assert not violations, (
            f"get_mistral_client() found in in-scope files: {violations}. "
            f"All in-scope SDK callers should use get_shared_client() instead."
        )

    def test_mistral_helpers_uses_get_mistral_client_only_in_shared_client(self):
        """mistral_helpers.py should only reference get_mistral_client() inside get_shared_client()."""
        import importlib
        import inspect
        mod = importlib.import_module("src.agents.mistral_helpers")
        source = inspect.getsource(mod)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "get_mistral_client" in line and "def get_mistral_client" not in line:
                in_shared = False
                for j in range(i, -1, -1):
                    if "def get_shared_client" in lines[j]:
                        in_shared = True
                        break
                    if lines[j].startswith("def ") and "get_shared_client" not in lines[j]:
                        break
                assert in_shared, (
                    f"get_mistral_client() is called at line {i+1} outside of "
                    f"get_shared_client() — it should only be used for shared-client construction"
                )

    def test_known_callers_use_shared_client(self):
        """Spot-check known in-scope callers use get_shared_client()."""
        import importlib
        import inspect
        known_callers = [
            "src.agents.amprchat_tools",
            "src.agents.summarizer",
            "src.agents.extractor",
            "src.agents.currency_inferrer",
            "src.agents.watchlist_inferrer",
            "src.agents.date_preprocessor",
            "src.agents.currency_converter",
            "src.api.admin",
            "src.notifications.synthesizer",
            "src.modules.router",
        ]
        for module_path in known_callers:
            mod = importlib.import_module(module_path)
            source = inspect.getsource(mod)
            assert "get_mistral_client" not in source, (
                f"{module_path} should use get_shared_client() instead of get_mistral_client()"
            )
            assert "get_shared_client" in source, (
                f"{module_path} should use get_shared_client()"
            )

# =============================================================================
# Test: complete_text is used by in-scope text completion agents
# =============================================================================

class TestCompleteTextUsage:
    """Tests to verify in-scope text completion agents use complete_text()."""

    def test_summarizer_uses_complete_text(self):
        """SummarizerAgent should use complete_text() helper."""
        import inspect
        from src.agents.summarizer import SummarizerAgent
        source = inspect.getsource(SummarizerAgent)
        assert "complete_text" in source, (
            "SummarizerAgent should use complete_text() helper for text completion"
        )

    def test_admin_clean_uses_complete_text(self):
        """admin.py clean_with_mistral should use complete_text() helper."""
        import inspect
        from src.api.admin import clean_with_mistral
        source = inspect.getsource(clean_with_mistral)
        assert "complete_text" in source, (
            "clean_with_mistral should use complete_text() helper for text completion"
        )

    def test_synthesizer_uses_complete_text(self):
        """synthesizer.py should use complete_text() helper."""
        import inspect
        from src.notifications.synthesizer import synthesize_notifications
        source = inspect.getsource(synthesize_notifications)
        assert "complete_text" in source, (
            "synthesize_notifications should use complete_text() helper for text completion"
        )

    def test_currency_converter_uses_complete_text(self):
        """currency_converter.py should use complete_text() helper."""
        import inspect
        from src.agents.currency_converter import convert_currency
        source = inspect.getsource(convert_currency)
        assert "complete_text" in source, (
            "convert_currency should use complete_text() helper for text completion"
        )


# =============================================================================
# Test: Currency converter behavioral coverage
# =============================================================================

class TestCurrencyConverter:
    """Behavioral tests for the currency converter using complete_text()."""

    @pytest.mark.asyncio
    async def test_convert_currency_returns_converted_text(self):
        """convert_currency should return the LLM-converted text via complete_text()."""
        with patch("src.agents.currency_converter.fetch_exchange_rate", new_callable=AsyncMock, return_value=0.85), \
             patch("src.agents.currency_converter.get_shared_client") as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = "Bitcoin is €85,000"
            mock_client.return_value.chat.complete_async = AsyncMock(return_value=mock_response)

            result = await convert_currency("Bitcoin is $100,000 USD", "EUR")

            assert result == "Bitcoin is €85,000"

    @pytest.mark.asyncio
    async def test_convert_currency_falls_back_on_rate_failure(self):
        """convert_currency should return original text when exchange rate fetch fails."""
        with patch("src.agents.currency_converter.fetch_exchange_rate", new_callable=AsyncMock, return_value=None):
            result = await convert_currency("Bitcoin is $100,000 USD", "EUR")
            assert result == "Bitcoin is $100,000 USD"

    @pytest.mark.asyncio
    async def test_convert_currency_falls_back_on_llm_failure(self):
        """convert_currency should return original text when the LLM call fails."""
        with patch("src.agents.currency_converter.fetch_exchange_rate", new_callable=AsyncMock, return_value=0.85), \
             patch("src.agents.currency_converter.get_shared_client") as mock_client:
            mock_client.return_value.chat.complete_async = AsyncMock(side_effect=Exception("API error"))

            result = await convert_currency("Bitcoin is $100,000 USD", "EUR")
            assert result == "Bitcoin is $100,000 USD"

    @pytest.mark.asyncio
    async def test_convert_currency_passes_explicit_params(self):
        """convert_currency should pass explicit model, temperature, and reasoning_effort to the SDK."""
        with patch("src.agents.currency_converter.fetch_exchange_rate", new_callable=AsyncMock, return_value=0.85), \
             patch("src.agents.currency_converter.get_shared_client") as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = "Converted"
            mock_client.return_value.chat.complete_async = AsyncMock(return_value=mock_response)

            await convert_currency("Test $100", "GBP")

            call_kwargs = mock_client.return_value.chat.complete_async.call_args.kwargs
            assert call_kwargs["model"] == "mistral-small-latest"
            assert call_kwargs["temperature"] == 0.7
            assert call_kwargs["reasoning_effort"] == "high"
