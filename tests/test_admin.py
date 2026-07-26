"""
Tests for admin.py Mistral SDK migration (AMPRFI-123).

Covers:
- test_mistral_latency: response shape, per-model, no-tools, and dummy-tools results
- clean_with_mistral: cleaned-markdown success and fail-closed abort behavior
- _run_ingestion: Convex ingestion is not called after cleaner failure
- No raw https://api.mistral.ai URL remains in admin.py
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.admin import (
    test_mistral_latency as run_mistral_latency,
    clean_with_mistral,
    MODELS,
    DUMMY_TOOLS,
    CLEANER_SYSTEM_PROMPT,
    _run_ingestion,
    IngestDocumentRequest,
)


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
def mock_latency_response():
    """Create a mocked Mistral chat completion response for latency testing."""
    response = MagicMock()
    response.model = "mistral-small-latest"
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = "hello"
    return response


@pytest.fixture
def mock_clean_response():
    """Create a mocked Mistral chat completion response for cleaning."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = "# Cleaned Article\n\nThis is clean markdown."
    return response


# =============================================================================
# test_mistral_latency
# =============================================================================

class TestMistralLatency:
    """Tests for the test_mistral_latency endpoint."""

    @pytest.mark.asyncio
    async def test_latency_uses_shared_client(self, mock_mistral_client, mock_latency_response):
        """Test that test_mistral_latency uses the shared SDK client."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        # Verify the shared client was used (not raw httpx)
        mock_mistral_client.chat.complete_async.assert_called()

    @pytest.mark.asyncio
    async def test_latency_response_shape(self, mock_mistral_client, mock_latency_response):
        """Test that the latency response has the expected shape."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        assert "results" in result
        assert isinstance(result["results"], list)

        for entry in result["results"]:
            assert "model_requested" in entry
            assert "model_resolved" in entry
            assert "mode" in entry
            assert "status" in entry
            assert "latency_seconds" in entry
            assert "reply" in entry

    @pytest.mark.asyncio
    async def test_latency_per_model(self, mock_mistral_client, mock_latency_response):
        """Test that latency results cover all configured models."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        models_tested = {entry["model_requested"] for entry in result["results"]}
        assert models_tested == set(MODELS)

    @pytest.mark.asyncio
    async def test_latency_no_tools_mode(self, mock_mistral_client, mock_latency_response):
        """Test that latency results include no_tools mode."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        no_tools_results = [e for e in result["results"] if e["mode"] == "no_tools"]
        assert len(no_tools_results) == len(MODELS)

    @pytest.mark.asyncio
    async def test_latency_with_tools_mode(self, mock_mistral_client, mock_latency_response):
        """Test that latency results include with_tools mode with dummy tools."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        with_tools_results = [e for e in result["results"] if e["mode"] == "with_tools"]
        assert len(with_tools_results) == len(MODELS)

    @pytest.mark.asyncio
    async def test_latency_no_tools_omits_tools(self, mock_mistral_client, mock_latency_response):
        """Test that no_tools mode omits the tools argument entirely (not tools=None)."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await run_mistral_latency(None)

        # Check that no_tools calls do NOT include the tools kwarg at all
        # (passing tools=None would serialize as "tools": null, which we want to avoid)
        calls = mock_mistral_client.chat.complete_async.call_args_list
        no_tools_calls = [c for c in calls if "tools" not in c.kwargs]
        assert len(no_tools_calls) > 0

    @pytest.mark.asyncio
    async def test_latency_with_tools_passes_dummy_tools(self, mock_mistral_client, mock_latency_response):
        """Test that with_tools mode passes DUMMY_TOOLS to the SDK."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await run_mistral_latency(None)

        # Check that at least one call was made with tools=DUMMY_TOOLS
        calls = mock_mistral_client.chat.complete_async.call_args_list
        with_tools_calls = [c for c in calls if c.kwargs.get("tools") == DUMMY_TOOLS]
        assert len(with_tools_calls) > 0

    @pytest.mark.asyncio
    async def test_latency_success_status(self, mock_mistral_client, mock_latency_response):
        """Test that successful calls return numeric status 200."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        for entry in result["results"]:
            assert entry["status"] == 200

    @pytest.mark.asyncio
    async def test_latency_reply_content(self, mock_mistral_client, mock_latency_response):
        """Test that the reply field contains the extracted content."""
        mock_latency_response.choices[0].message.content = "hello"
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        for entry in result["results"]:
            assert entry["reply"] == "hello"

    @pytest.mark.asyncio
    async def test_latency_resolved_model(self, mock_mistral_client, mock_latency_response):
        """Test that model_resolved comes from the SDK response."""
        mock_latency_response.model = "mistral-small-2603"
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        for entry in result["results"]:
            assert entry["model_resolved"] == "mistral-small-2603"

    @pytest.mark.asyncio
    async def test_latency_error_handling(self, mock_mistral_client):
        """Test that API errors produce error entries without crashing."""
        mock_mistral_client.chat.complete_async.side_effect = Exception("API error")

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        assert len(result["results"]) == len(MODELS) * 2  # 2 models × 2 modes

        for entry in result["results"]:
            assert entry["status"] == "error"
            assert "error" in entry
            assert "latency_seconds" in entry

    @pytest.mark.asyncio
    async def test_latency_missing_api_key(self):
        """Test that missing MISTRAL_API_KEY returns an error response."""
        with patch("src.api.admin.get_shared_client", side_effect=ValueError("MISTRAL_API_KEY not set")):
            result = await run_mistral_latency(None)

        assert result["results"] == []
        assert "error" in result

    @pytest.mark.asyncio
    async def test_latency_total_result_count(self, mock_mistral_client, mock_latency_response):
        """Test that the total number of results is models × 2 modes."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        assert len(result["results"]) == len(MODELS) * 2

    @pytest.mark.asyncio
    async def test_latency_latency_is_float(self, mock_mistral_client, mock_latency_response):
        """Test that latency_seconds is a numeric value."""
        mock_mistral_client.chat.complete_async.return_value = mock_latency_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await run_mistral_latency(None)

        for entry in result["results"]:
            assert isinstance(entry["latency_seconds"], (int, float))
            assert entry["latency_seconds"] >= 0


# =============================================================================
# clean_with_mistral
# =============================================================================

class TestCleanWithMistral:
    """Tests for the clean_with_mistral function."""

    @pytest.mark.asyncio
    async def test_clean_uses_shared_client(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral uses the shared SDK client."""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await clean_with_mistral("Raw text to clean")

        mock_mistral_client.chat.complete_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_clean_returns_cleaned_markdown(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral returns the cleaned markdown from the response."""
        mock_clean_response.choices[0].message.content = "# Cleaned Article\n\nThis is clean markdown."
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await clean_with_mistral("Raw text to clean")

        assert result == "# Cleaned Article\n\nThis is clean markdown."

    @pytest.mark.asyncio
    async def test_clean_uses_correct_model(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral uses the small model."""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await clean_with_mistral("Raw text to clean")

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs["model"] == "mistral-small-latest"

    @pytest.mark.asyncio
    async def test_clean_uses_system_prompt(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral passes the system prompt."""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await clean_with_mistral("Raw text to clean")

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0].content == CLEANER_SYSTEM_PROMPT
        assert messages[1].content == "Raw text to clean"

    @pytest.mark.asyncio
    async def test_clean_raises_on_api_error(self, mock_mistral_client):
        """Test that clean_with_mistral raises on API failure (fail-closed)."""
        mock_mistral_client.chat.complete_async.side_effect = Exception("API error")

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            with pytest.raises(Exception, match="API error"):
                await clean_with_mistral("Raw text to clean")

    @pytest.mark.asyncio
    async def test_clean_raises_on_missing_api_key(self):
        """Test that clean_with_mistral raises when API key is missing (fail-closed)."""
        with patch("src.api.admin.get_shared_client", side_effect=ValueError("MISTRAL_API_KEY not set")):
            with pytest.raises(ValueError, match="MISTRAL_API_KEY not set"):
                await clean_with_mistral("Raw text to clean")

    @pytest.mark.asyncio
    async def test_clean_raises_on_none_content(self, mock_mistral_client):
        """Test that clean_with_mistral raises when SDK returns None content."""
        mock_clean_response_none = MagicMock()
        mock_clean_response_none.choices = [MagicMock()]
        mock_clean_response_none.choices[0].message = MagicMock()
        mock_clean_response_none.choices[0].message.content = None
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response_none

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            with pytest.raises(RuntimeError, match="empty or whitespace-only"):
                await clean_with_mistral("Raw text to clean")

    @pytest.mark.asyncio
    async def test_clean_raises_on_empty_string_content(self, mock_mistral_client):
        """Test that clean_with_mistral raises when SDK returns empty string content."""
        mock_clean_response_empty = MagicMock()
        mock_clean_response_empty.choices = [MagicMock()]
        mock_clean_response_empty.choices[0].message = MagicMock()
        mock_clean_response_empty.choices[0].message.content = ""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response_empty

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            with pytest.raises(RuntimeError, match="empty or whitespace-only"):
                await clean_with_mistral("Raw text to clean")

    @pytest.mark.asyncio
    async def test_clean_raises_on_whitespace_only_content(self, mock_mistral_client):
        """Test that clean_with_mistral raises when SDK returns whitespace-only content."""
        mock_clean_response_ws = MagicMock()
        mock_clean_response_ws.choices = [MagicMock()]
        mock_clean_response_ws.choices[0].message = MagicMock()
        mock_clean_response_ws.choices[0].message.content = "   \n\t  \n  "
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response_ws

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            with pytest.raises(RuntimeError, match="empty or whitespace-only"):
                await clean_with_mistral("Raw text to clean")

    @pytest.mark.asyncio
    async def test_clean_representative_output(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral preserves representative cleaned-markdown output."""
        cleaned_content = (
            "# Investment Trends 2024\n\n"
            "## Market Overview\n\n"
            "The market showed significant volatility in Q1.\n\n"
            "### Key Takeaways\n\n"
            "- Tech stocks outperformed\n"
            "- Energy sector lagged\n"
        )
        mock_clean_response.choices[0].message.content = cleaned_content
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await clean_with_mistral("Raw HTML content with lots of noise...")

        assert result == cleaned_content
        assert "# Investment Trends 2024" in result
        assert "## Market Overview" in result
        assert "### Key Takeaways" in result

    @pytest.mark.asyncio
    async def test_clean_handles_reasoning_chunks(self, mock_mistral_client):
        """Test that clean_with_mistral handles reasoning chunk responses."""
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        # When reasoning_effort="high", content is a list of chunks
        response.choices[0].message.content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Let me think..."}]},
            {"type": "text", "text": "# Cleaned Content\n\nClean text here."},
        ]

        mock_mistral_client.chat.complete_async.return_value = response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            result = await clean_with_mistral("Raw text to clean")

        assert result == "# Cleaned Content\n\nClean text here."

    @pytest.mark.asyncio
    async def test_clean_temperature_setting(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral uses a reasonable temperature."""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await clean_with_mistral("Raw text to clean")

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_clean_reasoning_effort_none(self, mock_mistral_client, mock_clean_response):
        """Test that clean_with_mistral uses reasoning_effort='none'."""
        mock_mistral_client.chat.complete_async.return_value = mock_clean_response

        with patch("src.api.admin.get_shared_client", return_value=mock_mistral_client):
            await clean_with_mistral("Raw text to clean")

        call_kwargs = mock_mistral_client.chat.complete_async.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "none"


# =============================================================================
# Ingestion fail-closed behavior
# =============================================================================

class TestIngestionFailure:
    """Tests for fail-closed ingestion behavior in _run_ingestion."""

    @pytest.mark.asyncio
    async def test_ingestion_aborts_on_cleaner_failure(self):
        """Test that Convex ingestion (lenses:ingestFromText) is NOT called
        when clean_with_mistral raises an exception."""
        mock_convex_client = MagicMock()
        request = IngestDocumentRequest(
            url="https://example.com/article",
            lens_id="lens123",
            title="Test Article",
            summary="Test summary",
            source_type="blog",
        )

        with patch("src.api.admin.fetch_and_extract", new_callable=AsyncMock, return_value="Raw text"), \
             patch("src.api.admin.clean_with_mistral", new_callable=AsyncMock, side_effect=RuntimeError("Cleaning failed")), \
             patch("src.api.admin.get_client", return_value=mock_convex_client):
            await _run_ingestion(request)

        # Convex ingestion must NOT have been called
        mock_convex_client.action.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingestion_aborts_on_missing_api_key(self):
        """Test that Convex ingestion is NOT called when the API key is missing."""
        mock_convex_client = MagicMock()
        request = IngestDocumentRequest(
            url="https://example.com/article",
            lens_id="lens123",
            title="Test Article",
            summary="Test summary",
            source_type="blog",
        )

        with patch("src.api.admin.fetch_and_extract", new_callable=AsyncMock, return_value="Raw text"), \
             patch("src.api.admin.clean_with_mistral", new_callable=AsyncMock, side_effect=ValueError("MISTRAL_API_KEY not set")), \
             patch("src.api.admin.get_client", return_value=mock_convex_client):
            await _run_ingestion(request)

        mock_convex_client.action.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingestion_aborts_on_empty_cleaner_output(self):
        """Test that Convex ingestion is NOT called when cleaner returns empty content."""
        mock_convex_client = MagicMock()
        request = IngestDocumentRequest(
            url="https://example.com/article",
            lens_id="lens123",
            title="Test Article",
            summary="Test summary",
            source_type="blog",
        )

        with patch("src.api.admin.fetch_and_extract", new_callable=AsyncMock, return_value="Raw text"), \
             patch("src.api.admin.clean_with_mistral", new_callable=AsyncMock, side_effect=RuntimeError("empty or whitespace-only")), \
             patch("src.api.admin.get_client", return_value=mock_convex_client):
            await _run_ingestion(request)

        mock_convex_client.action.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingestion_proceeds_on_cleaner_success(self):
        """Test that Convex ingestion IS called when cleaning succeeds."""
        mock_convex_client = MagicMock()
        mock_convex_client.action.return_value = {"success": True}
        request = IngestDocumentRequest(
            url="https://example.com/article",
            lens_id="lens123",
            title="Test Article",
            summary="Test summary",
            source_type="blog",
        )

        with patch("src.api.admin.fetch_and_extract", new_callable=AsyncMock, return_value="Raw text"), \
             patch("src.api.admin.clean_with_mistral", new_callable=AsyncMock, return_value="# Cleaned Article"), \
             patch("src.api.admin.get_client", return_value=mock_convex_client):
            await _run_ingestion(request)

        mock_convex_client.action.assert_called_once()
        call_args = mock_convex_client.action.call_args
        assert call_args.args[0] == "lenses:ingestFromText"
        assert call_args.args[1]["markdownText"] == "# Cleaned Article"


# =============================================================================
# No raw Mistral URLs
# =============================================================================

class TestNoRawMistralUrls:
    """Tests to verify no raw Mistral HTTP calls remain in admin.py."""

    def test_no_raw_mistral_url_in_admin_py(self):
        """Test that no raw https://api.mistral.ai URL remains in admin.py."""
        import src.api.admin as admin_module
        import inspect

        source = inspect.getsource(admin_module)
        assert "https://api.mistral.ai" not in source, (
            "Raw Mistral API URL found in admin.py - should use shared SDK client instead"
        )

    def test_no_mistral_api_url_constant(self):
        """Test that MISTRAL_API_URL constant is not defined in admin.py."""
        import src.api.admin as admin_module

        assert not hasattr(admin_module, "MISTRAL_API_URL"), (
            "MISTRAL_API_URL constant should be removed - use shared SDK client"
        )

    def test_no_mistral_api_key_constant(self):
        """Test that MISTRAL_API_KEY constant is not defined in admin.py."""
        import src.api.admin as admin_module

        assert not hasattr(admin_module, "MISTRAL_API_KEY"), (
            "MISTRAL_API_KEY constant should be removed - use shared SDK client"
        )

    def test_httpx_still_imported(self):
        """Test that httpx is still imported for external article fetching."""
        import src.api.admin as admin_module

        assert hasattr(admin_module, "httpx"), (
            "httpx should still be imported for external article fetching"
        )
