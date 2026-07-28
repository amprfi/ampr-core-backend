"""
Tests for the REST testing ingestion endpoint (AMPRFI-118).

These tests verify that:
- The endpoint exercises the migrated generate_ai_response path for the rest channel
- The endpoint is disabled outside local/development environments unless opted in
- Returned responses are JSON-serializable with a stable shape
- Generation failures are surfaced as HTTP errors (not null responses)
- Missing users return 404
- User lookup and chat routing remain intact when enabled
- Production markers (RAILWAY_ENVIRONMENT_NAME, ENVIRONMENT=production) take
  precedence over DEBUG or local defaults
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from convex import ConvexClient

from src.api.testing_ingestion import handle_rest_message, RestMessagePayload
from src.config.environment import is_local_or_development, is_rest_testing_endpoint_enabled
from src.models.chat_message import GeneratedResponseMessage


# ============================================================================
# Environment Detection Tests
# ============================================================================

class TestEnvironmentDetection:
    """Tests for environment detection and endpoint gating.

    Production markers take precedence over DEBUG or local defaults;
    only ENABLE_REST_TESTING_ENDPOINT=true may enable the endpoint in a
    non-development deployment.
    """

    def test_dev_environment_debug_true(self, monkeypatch):
        """DEBUG=true should indicate development."""
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert is_local_or_development() is True

    def test_dev_environment_env_var(self, monkeypatch):
        """ENVIRONMENT=development should indicate development."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_local_or_development() is True

    def test_dev_environment_env_var_local(self, monkeypatch):
        """ENVIRONMENT=local should indicate development."""
        monkeypatch.setenv("ENVIRONMENT", "local")
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_local_or_development() is True

    def test_dev_environment_no_railway_env(self, monkeypatch):
        """Absence of RAILWAY_ENVIRONMENT_NAME should indicate local dev."""
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_local_or_development() is True

    def test_production_environment(self, monkeypatch):
        """ENVIRONMENT=production should indicate production."""
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_local_or_development() is False

    def test_production_railway_env_name(self, monkeypatch):
        """RAILWAY_ENVIRONMENT_NAME set should indicate production."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        assert is_local_or_development() is False

    def test_production_env_without_railway(self, monkeypatch):
        """ENVIRONMENT=production without Railway variables should be production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        assert is_local_or_development() is False

    def test_production_takes_precedence_over_debug(self, monkeypatch):
        """ENVIRONMENT=production should take precedence over DEBUG=true."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_local_or_development() is False

    def test_production_railway_takes_precedence_over_debug(self, monkeypatch):
        """RAILWAY_ENVIRONMENT_NAME should take precedence over DEBUG=true."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert is_local_or_development() is False

    def test_endpoint_enabled_in_dev(self, monkeypatch):
        """Endpoint should be enabled in development."""
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        assert is_rest_testing_endpoint_enabled() is True

    def test_endpoint_disabled_in_production(self, monkeypatch):
        """Endpoint should be disabled in production without opt-in."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_rest_testing_endpoint_enabled() is False

    def test_endpoint_disabled_in_production_railway(self, monkeypatch):
        """Endpoint should be disabled when RAILWAY_ENVIRONMENT_NAME is set."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_rest_testing_endpoint_enabled() is False

    def test_endpoint_enabled_with_opt_in(self, monkeypatch):
        """Endpoint should be enabled in production with explicit opt-in."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")
        assert is_rest_testing_endpoint_enabled() is True

    def test_endpoint_disabled_with_opt_in_false(self, monkeypatch):
        """Endpoint should be disabled when opt-in is explicitly false."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "false")
        assert is_rest_testing_endpoint_enabled() is False

    def test_opt_in_is_only_production_override(self, monkeypatch):
        """Only ENABLE_REST_TESTING_ENDPOINT=true may enable in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_rest_testing_endpoint_enabled() is False

        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")
        assert is_rest_testing_endpoint_enabled() is True

    def test_railway_development_disabled_without_opt_in(self, monkeypatch):
        """RAILWAY_ENVIRONMENT_NAME=development must be disabled by default."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "development")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_local_or_development() is False
        assert is_rest_testing_endpoint_enabled() is False

    def test_railway_development_enabled_with_opt_in(self, monkeypatch):
        """RAILWAY_ENVIRONMENT_NAME=development with opt-in should be enabled."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "development")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")
        assert is_rest_testing_endpoint_enabled() is True

    @pytest.mark.parametrize("env_value", ["local", "dev", "development"])
    def test_railway_overrides_local_dev_env(self, monkeypatch, env_value):
        """Any populated RAILWAY_ENVIRONMENT_NAME must take precedence over
        ENVIRONMENT=local|dev|development without explicit opt-in."""
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        monkeypatch.setenv("ENVIRONMENT", env_value)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_local_or_development() is False
        assert is_rest_testing_endpoint_enabled() is False

        # With opt-in, the endpoint should be enabled
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")
        assert is_rest_testing_endpoint_enabled() is True

    def test_staging_environment_disabled(self, monkeypatch):
        """ENVIRONMENT=staging should require explicit opt-in."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_local_or_development() is False
        assert is_rest_testing_endpoint_enabled() is False

    def test_staging_environment_enabled_with_opt_in(self, monkeypatch):
        """ENVIRONMENT=staging with opt-in should be enabled."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")
        assert is_rest_testing_endpoint_enabled() is True

    def test_qa_environment_disabled(self, monkeypatch):
        """ENVIRONMENT=qa should require explicit opt-in."""
        monkeypatch.setenv("ENVIRONMENT", "qa")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_local_or_development() is False

    def test_unknown_environment_disabled(self, monkeypatch):
        """Unknown ENVIRONMENT values should require explicit opt-in."""
        monkeypatch.setenv("ENVIRONMENT", "preview")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)
        assert is_local_or_development() is False


# ============================================================================
# Endpoint Tests (direct function calls)
# ============================================================================

class TestRestMessageEndpoint:
    """Tests for the /api/webhooks/rest-message endpoint via direct calls."""

    @pytest.fixture
    def mock_convex_client(self):
        """Create a mock ConvexClient for testing."""
        client = MagicMock(spec=ConvexClient)
        client.query = MagicMock(return_value={"_id": "test_user_123", "phone": "15551234567"})
        client.mutation = MagicMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def mock_async_convex_client(self):
        """Create a mock async ConvexClient for testing."""
        client = AsyncMock()
        client.mutation = AsyncMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def dev_env(self, monkeypatch):
        """Set up dev environment."""
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

    @pytest.fixture
    def patched_deps(self, monkeypatch, mock_convex_client, mock_async_convex_client, dev_env):
        """Patch endpoint dependencies and return mocks."""
        monkeypatch.setattr('src.api.testing_ingestion.get_client', lambda: mock_convex_client)
        monkeypatch.setattr('src.api.responses.context.get_async_client', lambda: mock_async_convex_client)
        return mock_convex_client, mock_async_convex_client

    # ------------------------------------------------------------------
    # Successful response tests
    # ------------------------------------------------------------------

    async def test_successful_attributed_response(self, patched_deps, monkeypatch):
        """Test successful response with module attribution."""
        mock_convex_client, _ = patched_deps
        mock_response = [
            GeneratedResponseMessage(content="Bitcoin is $100,000", specialist_module="defianalyst"),
            GeneratedResponseMessage(content="Based on market analysis...", specialist_module=None),
        ]
        mock_generate = AsyncMock(return_value=mock_response)
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        payload = RestMessagePayload(
            text="What is BTC price?",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        assert result["status"] == "success"
        assert result["message"] == "Inbound message processed"
        assert len(result["ai_response"]) == 2
        assert result["ai_response"][0] == {
            "content": "Bitcoin is $100,000",
            "specialist_module": "defianalyst",
        }
        assert result["ai_response"][1] == {
            "content": "Based on market analysis...",
            "specialist_module": None,
        }

    async def test_response_is_json_serializable(self, patched_deps, monkeypatch):
        """Test that the response is JSON-serializable."""
        mock_convex_client, _ = patched_deps
        mock_response = [
            GeneratedResponseMessage(content="Hello world", specialist_module="defianalyst"),
        ]
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=mock_response)
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        # Should not raise
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized["ai_response"][0]["content"] == "Hello world"
        assert deserialized["ai_response"][0]["specialist_module"] == "defianalyst"

    async def test_response_shape_stable(self, patched_deps, monkeypatch):
        """Test that the response shape is stable with content and specialist_module keys."""
        mock_convex_client, _ = patched_deps
        mock_response = [
            GeneratedResponseMessage(content="With module", specialist_module="defianalyst"),
            GeneratedResponseMessage(content="Without module", specialist_module=None),
        ]
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=mock_response)
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        # Assert exact key sets
        assert set(result.keys()) == {"status", "message", "ai_response"}
        for msg in result["ai_response"]:
            assert set(msg.keys()) == {"content", "specialist_module"}
            assert isinstance(msg["content"], str)
            assert msg["specialist_module"] is None or isinstance(msg["specialist_module"], str)

    async def test_response_context_uses_rest_channel(self, patched_deps, monkeypatch):
        """Test that ResponseContext is created with channel='rest' and chat_id=None."""
        mock_convex_client, _ = patched_deps
        captured_context = []

        async def mock_generate(response_context):
            captured_context.append(response_context)
            return []

        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        payload = RestMessagePayload(
            text="test message",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        await handle_rest_message(payload)

        assert len(captured_context) == 1
        assert captured_context[0].channel == "rest"
        assert captured_context[0].chat_id is None
        assert captured_context[0].user_id == "test_user_123"
        assert captured_context[0].message_content == "test message"
        assert captured_context[0].convex_client is mock_convex_client

    # ------------------------------------------------------------------
    # User lookup tests
    # ------------------------------------------------------------------

    async def test_user_lookup_uses_normalized_phone(self, patched_deps, monkeypatch):
        """Test that user lookup uses the normalized phone number."""
        mock_convex_client, _ = patched_deps
        mock_convex_client.query = MagicMock(return_value={"_id": "test_user_123"})
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=[])
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+1 (555) 123-4567",
            to_number="+15550000000"
        )
        await handle_rest_message(payload)

        # Verify query was called with normalized phone number (digits only)
        mock_convex_client.query.assert_called_once_with(
            "users:getUserByPhone", {"phone": "15551234567"}
        )

    async def test_missing_user_returns_404(self, patched_deps, monkeypatch):
        """Test that missing users return 404."""
        mock_convex_client, _ = patched_deps
        mock_convex_client.query = MagicMock(return_value=None)
        mock_generate = AsyncMock(return_value=[])
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )

        with pytest.raises(HTTPException) as exc_info:
            await handle_rest_message(payload)

        assert exc_info.value.status_code == 404
        assert "No user found" in exc_info.value.detail
        mock_generate.assert_not_awaited()

    async def test_user_query_exception_returns_404(self, patched_deps, monkeypatch):
        """Test that query exceptions return 404."""
        mock_convex_client, _ = patched_deps
        mock_convex_client.query = MagicMock(side_effect=ConnectionError("DB unavailable"))
        mock_generate = AsyncMock(return_value=[])
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )

        with pytest.raises(HTTPException) as exc_info:
            await handle_rest_message(payload)

        assert exc_info.value.status_code == 404
        assert "No user found" in exc_info.value.detail
        mock_generate.assert_not_awaited()

    # ------------------------------------------------------------------
    # Generation failure tests
    # ------------------------------------------------------------------

    async def test_generation_failure_returns_502(self, patched_deps, monkeypatch):
        """Test that generation failures return 502, not null ai_response."""
        mock_convex_client, _ = patched_deps
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(side_effect=RuntimeError("Mistral API error"))
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )

        with pytest.raises(HTTPException) as exc_info:
            await handle_rest_message(payload)

        assert exc_info.value.status_code == 502
        # Internal error text must not be exposed
        assert "Mistral API error" not in exc_info.value.detail
        assert exc_info.value.detail == "AI response generation failed"

    # ------------------------------------------------------------------
    # Environment gate tests
    # ------------------------------------------------------------------

    async def test_disabled_in_production_returns_404(
        self, monkeypatch, mock_convex_client, mock_async_convex_client
    ):
        """Test that the endpoint is disabled in production."""
        # Set production environment
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

        # Patch dependencies (should not be called)
        monkeypatch.setattr('src.api.testing_ingestion.get_client', lambda: mock_convex_client)
        monkeypatch.setattr(
            'src.api.responses.context.get_async_client',
            lambda: mock_async_convex_client
        )
        mock_generate = AsyncMock(return_value=[])
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )

        with pytest.raises(HTTPException) as exc_info:
            await handle_rest_message(payload)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Endpoint not available"

        # Verify dependencies were never called
        mock_convex_client.query.assert_not_called()
        mock_generate.assert_not_awaited()

    async def test_enabled_with_opt_in_in_production(
        self, monkeypatch, mock_convex_client, mock_async_convex_client
    ):
        """Test that the endpoint is enabled in production with opt-in."""
        # Set production environment with opt-in
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("ENABLE_REST_TESTING_ENDPOINT", "true")

        # Patch dependencies
        monkeypatch.setattr('src.api.testing_ingestion.get_client', lambda: mock_convex_client)
        monkeypatch.setattr(
            'src.api.responses.context.get_async_client',
            lambda: mock_async_convex_client
        )
        mock_response = [GeneratedResponseMessage(content="Hello", specialist_module=None)]
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=mock_response)
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        assert result["status"] == "success"
        assert result["ai_response"][0]["content"] == "Hello"

    # ------------------------------------------------------------------
    # Edge case tests
    # ------------------------------------------------------------------

    async def test_empty_response_messages(self, patched_deps, monkeypatch):
        """Test that empty response messages return an empty list."""
        mock_convex_client, _ = patched_deps
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=[])
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        assert result["ai_response"] == []

    async def test_string_response_fallback(self, patched_deps, monkeypatch):
        """Test that string responses are converted to dicts with specialist_module=None."""
        mock_convex_client, _ = patched_deps
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=["Hello", "World"])
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        assert result["ai_response"] == [
            {"content": "Hello", "specialist_module": None},
            {"content": "World", "specialist_module": None},
        ]

    async def test_mixed_response_types(self, patched_deps, monkeypatch):
        """Test that mixed GeneratedResponseMessage and string responses are handled."""
        mock_convex_client, _ = patched_deps
        mock_response = [
            GeneratedResponseMessage(content="Attributed", specialist_module="defianalyst"),
            "Plain string",
            GeneratedResponseMessage(content="No attribution", specialist_module=None),
        ]
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=mock_response)
        )

        payload = RestMessagePayload(
            text="test",
            from_number="+15551234567",
            to_number="+15550000000"
        )
        result = await handle_rest_message(payload)

        assert result["ai_response"] == [
            {"content": "Attributed", "specialist_module": "defianalyst"},
            {"content": "Plain string", "specialist_module": None},
            {"content": "No attribution", "specialist_module": None},
        ]


# ============================================================================
# HTTP-level Tests (TestClient)
# ============================================================================

class TestRestMessageEndpointHTTP:
    """HTTP-level tests using TestClient(fast_api).

    These tests verify route registration, middleware behavior, HTTP
    serialization, and actual 404/502 responses.
    """

    @pytest.fixture
    def mock_convex_client(self):
        """Create a mock ConvexClient for testing."""
        client = MagicMock(spec=ConvexClient)
        client.query = MagicMock(return_value={"_id": "test_user_123", "phone": "15551234567"})
        client.mutation = MagicMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def mock_async_convex_client(self):
        """Create a mock async ConvexClient for testing."""
        client = AsyncMock()
        client.mutation = AsyncMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def dev_env(self, monkeypatch):
        """Set up dev environment."""
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

    @pytest.fixture
    def patched_http_deps(self, monkeypatch, mock_convex_client, mock_async_convex_client, dev_env):
        """Patch dependencies for HTTP-level tests."""
        monkeypatch.setattr('src.clients.convex_client.get_client', lambda: mock_convex_client)
        monkeypatch.setattr('src.api.testing_ingestion.get_client', lambda: mock_convex_client)
        monkeypatch.setattr(
            'src.api.responses.context.get_async_client',
            lambda: mock_async_convex_client
        )
        return mock_convex_client, mock_async_convex_client

    def test_http_successful_response(self, patched_http_deps, monkeypatch):
        """Test successful response via HTTP."""
        mock_convex_client, _ = patched_http_deps
        mock_response = [
            GeneratedResponseMessage(content="Bitcoin is $100,000", specialist_module="defianalyst"),
        ]
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=mock_response)
        )

        from src.main import fast_api
        client = TestClient(fast_api)
        response = client.post(
            "/api/webhooks/rest-message",
            json={"text": "What is BTC price?", "from_number": "+15551234567", "to_number": "+15550000000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Inbound message processed"
        assert data["ai_response"][0]["content"] == "Bitcoin is $100,000"
        assert data["ai_response"][0]["specialist_module"] == "defianalyst"

    def test_http_production_404(self, monkeypatch, mock_convex_client, mock_async_convex_client):
        """Test that production returns 404 via HTTP."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

        mock_generate = AsyncMock(return_value=[])
        mock_get_client = MagicMock(return_value=mock_convex_client)
        monkeypatch.setattr('src.api.testing_ingestion.get_client', mock_get_client)
        monkeypatch.setattr(
            'src.api.responses.context.get_async_client',
            lambda: mock_async_convex_client
        )
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        from src.main import fast_api
        client = TestClient(fast_api)
        response = client.post(
            "/api/webhooks/rest-message",
            json={"text": "test", "from_number": "+15551234567", "to_number": "+15550000000"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Endpoint not available"
        mock_get_client.assert_not_called()
        mock_generate.assert_not_awaited()

    def test_http_staging_404(self, monkeypatch, mock_convex_client, mock_async_convex_client):
        """Test that staging environment returns 404 via HTTP."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

        mock_generate = AsyncMock(return_value=[])
        mock_get_client = MagicMock(return_value=mock_convex_client)
        monkeypatch.setattr('src.api.testing_ingestion.get_client', mock_get_client)
        monkeypatch.setattr(
            'src.api.responses.context.get_async_client',
            lambda: mock_async_convex_client
        )
        monkeypatch.setattr('src.api.testing_ingestion.generate_ai_response', mock_generate)

        from src.main import fast_api
        client = TestClient(fast_api)
        response = client.post(
            "/api/webhooks/rest-message",
            json={"text": "test", "from_number": "+15551234567", "to_number": "+15550000000"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Endpoint not available"
        mock_get_client.assert_not_called()
        mock_generate.assert_not_awaited()

    def test_http_missing_user_404(self, patched_http_deps, monkeypatch):
        """Test that missing users return 404 via HTTP."""
        mock_convex_client, _ = patched_http_deps
        mock_convex_client.query = MagicMock(return_value=None)
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(return_value=[])
        )

        from src.main import fast_api
        client = TestClient(fast_api)
        response = client.post(
            "/api/webhooks/rest-message",
            json={"text": "test", "from_number": "+15551234567", "to_number": "+15550000000"},
        )

        assert response.status_code == 404
        assert "No user found" in response.json()["detail"]

    def test_http_generation_failure_502(self, patched_http_deps, monkeypatch):
        """Test that generation failures return 502 via HTTP."""
        mock_convex_client, _ = patched_http_deps
        monkeypatch.setattr(
            'src.api.testing_ingestion.generate_ai_response',
            AsyncMock(side_effect=RuntimeError("Mistral API error"))
        )

        from src.main import fast_api
        client = TestClient(fast_api)
        response = client.post(
            "/api/webhooks/rest-message",
            json={"text": "test", "from_number": "+15551234567", "to_number": "+15550000000"},
        )

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "Mistral API error" not in detail
        assert detail == "AI response generation failed"


# ============================================================================
# REST Dispatch Tests
# ============================================================================

class TestRestDispatch:
    """Tests verifying that generate_ai_response routes channel='rest' to
    the web response handler (migrated REST dispatch)."""

    @pytest.fixture
    def mock_convex_client(self):
        client = MagicMock(spec=ConvexClient)
        client.query = MagicMock(return_value={"_id": "test_user_123"})
        client.mutation = MagicMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def mock_async_convex_client(self):
        client = AsyncMock()
        client.mutation = AsyncMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})
        return client

    @pytest.fixture
    def dev_env(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ENABLE_REST_TESTING_ENDPOINT", raising=False)

    async def test_rest_channel_routes_to_web_handler(self, monkeypatch, mock_convex_client,
                                                       mock_async_convex_client, dev_env):
        """Test that generate_ai_response routes channel='rest' to _generate_web_response."""
        from src.api.responses import generate_ai_response
        from src.api.responses.context import ResponseContext

        monkeypatch.setattr('src.api.responses.context.get_async_client', lambda: mock_async_convex_client)

        # Track which handler was called
        web_called = False
        telegram_called = False

        async def mock_web_handler(context):
            nonlocal web_called
            web_called = True
            return [GeneratedResponseMessage(content="Web response", specialist_module=None)]

        async def mock_telegram_handler(context):
            nonlocal telegram_called
            telegram_called = True
            return ["Telegram response"]

        monkeypatch.setattr('src.api.responses._generate_web_response', mock_web_handler)
        monkeypatch.setattr('src.api.responses._generate_telegram_response', mock_telegram_handler)

        context = ResponseContext(
            message_content="test",
            chat_id=None,
            channel="rest",
            user_id="test_user_123",
            convex_client=mock_convex_client,
        )

        result = await generate_ai_response(context)

        assert web_called is True
        assert telegram_called is False
        assert len(result) == 1
        assert result[0].content == "Web response"

    async def test_rest_channel_with_mocked_preprocessing(self, monkeypatch, mock_convex_client,
                                                            mock_async_convex_client, dev_env):
        """Test that the full REST flow calls generate_ai_response with correct context.

        Verifies that chat_id is None (for monthly chat resolution) and the
        expected Convex client is passed through.
        """
        from src.api.responses import generate_ai_response
        from src.api.responses.context import ResponseContext

        monkeypatch.setattr('src.api.responses.context.get_async_client', lambda: mock_async_convex_client)

        captured_contexts = []

        async def mock_web_handler(context):
            captured_contexts.append(context)
            return [GeneratedResponseMessage(content="Response", specialist_module="defianalyst")]

        monkeypatch.setattr('src.api.responses._generate_web_response', mock_web_handler)

        context = ResponseContext(
            message_content="What is BTC price?",
            chat_id=None,
            channel="rest",
            user_id="test_user_123",
            convex_client=mock_convex_client,
        )

        result = await generate_ai_response(context)

        assert len(captured_contexts) == 1
        captured = captured_contexts[0]
        assert captured.channel == "rest"
        assert captured.chat_id is None
        assert captured.user_id == "test_user_123"
        assert captured.convex_client is mock_convex_client
        assert captured.message_content == "What is BTC price?"
        assert result[0].specialist_module == "defianalyst"

    async def test_preprocessing_receives_rest_channel(self, monkeypatch, mock_convex_client,
                                                        mock_async_convex_client, dev_env):
        """Test that run_preprocessing stores the user message with channel='rest'
        and assigns the returned chat ID to context.chat_id.

        Uses the bare &help fast path: preprocessing stores the message via
        messages:createMessage, then returns immediately without LLM calls.
        """
        from src.api.responses.preprocessing import run_preprocessing
        from src.api.responses.context import ResponseContext

        monkeypatch.setattr('src.api.responses.context.get_async_client', lambda: mock_async_convex_client)

        # Capture the mutation call and return a chat ID
        mutation_calls = []

        async def capture_mutation(fn_name, *args, **kwargs):
            mutation_calls.append((fn_name, args, kwargs))
            return {"_id": "test_msg_id", "chat": "test_chat_id"}

        mock_async_convex_client.mutation = capture_mutation

        context = ResponseContext(
            message_content="&help",
            chat_id=None,
            channel="rest",
            user_id="test_user_123",
            convex_client=mock_convex_client,
        )

        result = await run_preprocessing(context)

        # Verify that messages:createMessage was called with channel="rest"
        create_message_calls = [
            call for call in mutation_calls
            if call[0] == "messages:createMessage"
        ]
        assert len(create_message_calls) == 1
        _, args, kwargs = create_message_calls[0]
        # The payload is passed as the second positional argument
        payload = args[0] if len(args) > 0 else kwargs
        assert payload["channel"] == "rest"
        assert payload["userId"] == "test_user_123"
        assert payload["content"] == "&help"
        assert payload["role"] == "user"

        # Verify the returned chat ID was assigned to context.chat_id
        assert context.chat_id == "test_chat_id"

        # Verify the bare &help fast path was taken
        assert result.is_bare_help is True
        assert result.help_text is not None
        assert result.chat_id == "test_chat_id"
