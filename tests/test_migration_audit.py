"""
Source audit tests for the Mistral SDK migration (AMPRFI-115).

These tests verify that:
- No in-scope core path uses raw https://api.mistral.ai URLs
- No in-scope core path imports pydantic_ai
- Deferred holdout files are explicitly recorded and excluded from the in-scope audit
- The orphaned src/utils/types.py has been deleted
- pydantic-ai remains in pyproject.toml (intentionally retained)
- Migration documentation exists and states frontend work follows this gate
- REST flow (/api/chat/message) is covered by tests
"""

import os
import re
import pytest
from unittest.mock import MagicMock, AsyncMock
from convex import ConvexClient
from pathlib import Path


# =============================================================================
# In-scope directories and files for the core migration audit
# =============================================================================

# Top-level directories that are in-scope for the core migration.
# All Python files under these directories are scanned, with explicit
# holdout files subtracted.
IN_SCOPE_DIRS = [
    "src/agents",
    "src/api",
    "src/modules",
    "src/notifications",
    "src/utils",
]

# Deferred holdout files — these are EXPECTED to still use pydantic_ai
# or raw Mistral URLs. They are tracked by separate issues and are
# EXCLUDED from the in-scope audit.
DEFERRED_HOLDOUTS = {
    "src/agents/onboarding.py": "AMPRFI-110",
    "src/modules/defianalyst/agent.py": "AMPRFI-122",
    "src/modules/defianalyst/utils.py": "AMPRFI-127",
    "src/modules/lens/agent.py": "AMPRFI-121",
    "src/modules/oracle/agent.py": "AMPRFI-125",
}

# The orphaned types file that should have been deleted
ORPHANED_TYPES_FILE = "src/utils/types.py"


# =============================================================================
# Helper functions
# =============================================================================

def _read_file(path: str) -> str:
    """Read a file and return its contents, raising if not found."""
    full_path = Path(path)
    if not full_path.exists():
        raise FileNotFoundError(f"Expected file does not exist: {path}")
    return full_path.read_text()


def _list_python_files(directory: str) -> list[str]:
    """List all Python files in a directory recursively."""
    dir_path = Path(directory)
    if not dir_path.exists():
        return []
    return [str(f) for f in dir_path.rglob("*.py") if f.is_file()]


def _get_in_scope_files() -> list[str]:
    """Get all in-scope Python files, excluding deferred holdouts."""
    files = []
    for dir_path in IN_SCOPE_DIRS:
        files.extend(_list_python_files(dir_path))
    # Subtract deferred holdouts
    return [f for f in files if f not in DEFERRED_HOLDOUTS]


# =============================================================================
# Test: No raw Mistral URLs in in-scope code
# =============================================================================

class TestNoRawMistralUrls:
    """Tests to verify no raw https://api.mistral.ai URLs remain in in-scope code."""

    def test_no_raw_mistral_url_in_in_scope_files(self):
        """No in-scope file (excluding holdouts) should contain a raw Mistral API URL."""
        violations = []
        for file_path in _get_in_scope_files():
            content = _read_file(file_path)
            if "https://api.mistral.ai" in content:
                violations.append(file_path)

        assert not violations, (
            f"Raw Mistral API URL found in in-scope files: {violations}. "
            f"These should use the shared Mistral SDK client instead."
        )

    def test_no_mistral_api_url_constant_in_in_scope_files(self):
        """No in-scope file should define a MISTRAL_API_URL constant."""
        violations = []
        for file_path in _get_in_scope_files():
            content = _read_file(file_path)
            if re.search(r'MISTRAL_API_URL\s*=', content):
                violations.append(file_path)

        assert not violations, (
            f"MISTRAL_API_URL constant found in in-scope files: {violations}. "
            f"Use get_shared_client() instead."
        )

    def test_deferred_holdouts_excluded_from_raw_url_audit(self):
        """Deferred holdout files should be excluded from the raw URL audit."""
        in_scope_files = _get_in_scope_files()
        for holdout in DEFERRED_HOLDOUTS:
            assert holdout not in in_scope_files, (
                f"Deferred holdout {holdout} should be excluded from in-scope audit"
            )


# =============================================================================
# Test: No pydantic_ai imports in in-scope code
# =============================================================================

class TestNoPydanticAiImports:
    """Tests to verify no in-scope core path imports pydantic_ai."""

    def test_no_pydantic_ai_import_in_in_scope_files(self):
        """No in-scope file (excluding holdouts) should import pydantic_ai."""
        violations = []
        for file_path in _get_in_scope_files():
            content = _read_file(file_path)
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("from pydantic_ai") or stripped.startswith("import pydantic_ai"):
                    violations.append((file_path, stripped))

        assert not violations, (
            f"pydantic_ai import found in in-scope files: {violations}. "
            f"These should use the Mistral SDK instead."
        )

    def test_deferred_holdouts_excluded_from_pydantic_ai_audit(self):
        """Deferred holdout files should be excluded from the pydantic_ai audit."""
        in_scope_files = _get_in_scope_files()
        for holdout in DEFERRED_HOLDOUTS:
            assert holdout not in in_scope_files, (
                f"Deferred holdout {holdout} should be excluded from in-scope audit"
            )


# =============================================================================
# Test: Deferred holdouts are explicitly recorded
# =============================================================================

class TestDeferredHoldouts:
    """Tests to verify deferred holdout files are explicitly recorded."""

    def test_deferred_holdouts_are_recorded(self):
        """The DEFERRED_HOLDOUTS dict should contain all known holdout files."""
        expected_holdouts = {
            "src/agents/onboarding.py",
            "src/modules/defianalyst/agent.py",
            "src/modules/defianalyst/utils.py",
            "src/modules/lens/agent.py",
            "src/modules/oracle/agent.py",
        }
        assert set(DEFERRED_HOLDOUTS.keys()) == expected_holdouts

    def test_deferred_holdout_tracking_issues(self):
        """Each deferred holdout should have a tracking issue number."""
        for file_path, issue in DEFERRED_HOLDOUTS.items():
            assert issue.startswith("AMPRFI-"), (
                f"Deferred holdout {file_path} should have an AMPRFI- tracking issue"
            )

    def test_deferred_holdout_files_exist(self):
        """All deferred holdout files should exist on disk."""
        for file_path in DEFERRED_HOLDOUTS:
            assert Path(file_path).exists(), (
                f"Deferred holdout file {file_path} should exist on disk"
            )

    def test_deferred_holdouts_are_excluded_from_audit(self):
        """Deferred holdouts should be excluded from the in-scope file list."""
        in_scope_files = _get_in_scope_files()
        for holdout in DEFERRED_HOLDOUTS:
            assert holdout not in in_scope_files, (
                f"Deferred holdout {holdout} should be excluded from in-scope audit"
            )


# =============================================================================
# Test: Orphaned types file is deleted
# =============================================================================

class TestOrphanedTypesFile:
    """Tests to verify the orphaned src/utils/types.py has been deleted."""

    def test_types_file_does_not_exist(self):
        """src/utils/types.py should not exist (orphaned, deleted)."""
        assert not Path(ORPHANED_TYPES_FILE).exists(), (
            f"{ORPHANED_TYPES_FILE} should have been deleted — it was orphaned "
            f"and contained pydantic_ai imports that are no longer needed"
        )

    def test_no_imports_of_utils_types(self):
        """No file in src/ should import from utils.types."""
        violations = []
        for file_path in _list_python_files("src"):
            content = _read_file(file_path)
            for line in content.split("\n"):
                stripped = line.strip()
                if "utils.types" in stripped and stripped.startswith(("from", "import")):
                    # Allow aiogram.types and mistralai.client.types
                    if "aiogram.types" in stripped or "mistralai" in stripped:
                        continue
                    violations.append((file_path, stripped))

        assert not violations, (
            f"Files still import from utils.types: {violations}"
        )

    def test_no_common_message_or_common_chat_references(self):
        """No file in src/ should reference CommonMessage or CommonChat."""
        violations = []
        for file_path in _list_python_files("src"):
            content = _read_file(file_path)
            if "CommonMessage" in content or "CommonChat" in content:
                violations.append(file_path)

        assert not violations, (
            f"Files still reference CommonMessage/CommonChat: {violations}"
        )


# =============================================================================
# Test: pydantic-ai remains in pyproject.toml
# =============================================================================

class TestPydanticAiRetained:
    """Tests to verify pydantic-ai is intentionally retained in pyproject.toml."""

    def test_pydantic_ai_in_pyproject(self):
        """pydantic-ai should be listed in pyproject.toml dependencies."""
        content = _read_file("pyproject.toml")
        assert "pydantic-ai" in content, (
            "pydantic-ai should remain in pyproject.toml because deferred holdouts "
            "still depend on it"
        )

    def test_pydantic_ai_in_lockfile(self):
        """pydantic-ai should be in the lockfile (poetry.lock)."""
        content = _read_file("poetry.lock")
        assert "pydantic-ai" in content, (
            "pydantic-ai should remain in poetry.lock because deferred holdouts "
            "still depend on it"
        )


# =============================================================================
# Test: Migration documentation exists
# =============================================================================

class TestMigrationDocumentation:
    """Tests to verify migration documentation exists and is accurate."""

    def test_migration_doc_exists(self):
        """Migration documentation file should exist."""
        assert Path("docs/migration-mistral-sdk.md").exists(), (
            "Migration documentation should exist at docs/migration-mistral-sdk.md"
        )

    def test_migration_doc_mentions_frontend_follows_gate(self):
        """Migration doc should state frontend work follows this core migration gate."""
        content = _read_file("docs/migration-mistral-sdk.md")
        assert "frontend" in content.lower(), (
            "Migration doc should mention that frontend work follows this core migration gate"
        )

    def test_migration_doc_does_not_claim_all_backend_migrated(self):
        """Migration doc should NOT claim all backend Mistral usage has moved."""
        content = _read_file("docs/migration-mistral-sdk.md")
        assert "deferred" in content.lower() or "holdout" in content.lower(), (
            "Migration doc should mention deferred holdouts, not claim all "
            "backend Mistral usage has already moved"
        )

    def test_migration_doc_lists_deferred_holdouts(self):
        """Migration doc should list the deferred holdout files."""
        content = _read_file("docs/migration-mistral-sdk.md")
        assert "onboarding.py" in content
        assert "defianalyst/agent.py" in content
        assert "defianalyst/utils.py" in content
        assert "lens/agent.py" in content
        assert "oracle/agent.py" in content

    def test_migration_doc_mentions_shared_client(self):
        """Migration doc should mention get_shared_client() as the shared client."""
        content = _read_file("docs/migration-mistral-sdk.md")
        assert "get_shared_client" in content, (
            "Migration doc should mention get_shared_client() as the shared client"
        )

    def test_migration_doc_mentions_complete_text_helper(self):
        """Migration doc should mention the complete_text() shared helper."""
        content = _read_file("docs/migration-mistral-sdk.md")
        assert "complete_text" in content, (
            "Migration doc should mention complete_text() as a shared helper"
        )


# =============================================================================
# Test: REST flow coverage
# =============================================================================

class TestRestFlowCoverage:
    """Tests to verify the REST flow (/api/chat/message) is covered."""

    def test_rest_endpoint_exists(self):
        """The /api/chat/message endpoint should be registered."""
        from src.api.chat import router as chat_router
        routes = [route.path for route in chat_router.routes]
        assert "/chat/message" in routes, (
            "/chat/message endpoint should be registered for REST flow"
        )

    def test_rest_endpoint_accepts_post(self):
        """The /api/chat/message endpoint should accept POST."""
        from src.api.chat import router as chat_router
        message_route = None
        for route in chat_router.routes:
            if route.path == "/chat/message":
                message_route = route
                break
        assert message_route is not None
        assert "POST" in message_route.methods

    def test_rest_endpoint_has_send_message_request_model(self):
        """SendMessageRequest should have channel and content fields."""
        from src.api.chat import SendMessageRequest
        request = SendMessageRequest(channel="web", content="Test message")
        assert request.channel == "web"
        assert request.content == "Test message"

    def test_rest_endpoint_has_send_message_response_model(self):
        """SendMessageResponse should have messages and acknowledged fields."""
        from src.api.chat import SendMessageResponse
        response = SendMessageResponse(messages=None, acknowledged=True)
        assert response.acknowledged is True

    def test_rest_endpoint_routes_web_to_web_handler(self):
        """The REST endpoint should route web channel to the web response handler."""
        import inspect
        from src.api.responses import generate_ai_response
        source = inspect.getsource(generate_ai_response)
        # The web handler should be called for web channel
        assert "web" in source
        assert "_generate_web_response" in source

    def test_rest_endpoint_returns_chat_messages_with_attribution(self):
        """The REST endpoint should return ChatMessage objects with attribution."""
        from src.models.chat_message import ChatMessage, GeneratedResponseMessage
        # Verify the models exist and have the right fields
        msg = ChatMessage(content="Test", specialist_module="defianalyst")
        assert msg.content == "Test"
        assert msg.specialist_module == "defianalyst"

        gen_msg = GeneratedResponseMessage(content="Test", specialist_module="oracle")
        assert gen_msg.content == "Test"
        assert gen_msg.specialist_module == "oracle"

    def test_rest_endpoint_behavioral_web_routing(self, monkeypatch):
        """Behavioral test: /api/chat/message with web channel routes through generate_ai_response
        and returns attributed messages.

        This test invokes the actual endpoint via TestClient with mocked dependencies,
        verifying that:
        - The web channel handler is called (not the app/store-only path)
        - The response contains AI-generated messages with attribution
        - The agent's output is returned as a ChatMessage
        """
        from fastapi.testclient import TestClient
        from src.main import fast_api
        from src.models.chat_message import GeneratedResponseMessage
        from src.agents.amprChat import AgentRunResult

        mock_convex = MagicMock(spec=ConvexClient)
        mock_convex.query.return_value = {"_id": "test_user_123"}
        mock_convex.mutation.return_value = {"_id": "test_msg_id", "chat": "chat_1"}

        mock_async_convex = AsyncMock()
        mock_async_convex.mutation = AsyncMock(return_value={"_id": "test_msg_id", "chat": "chat_1"})

        async def fake_validate_hanko_session(session_token: str):
            return "hanko_user_123", "test@example.com"

        async def fake_run_preprocessing(context):
            context.chat_id = "chat_1"
            return MagicMock(
                is_bare_help=False,
                modules=[],
                module_responses={},
                interim_messages=[],
                unresolved_triggers=[],
                date_context_str=None,
                currency_context="display_currency: USD",
                message_content="What is the price of BTC?",
                summaries_str="",
                message_history_str="[]",
                needs_onboarding=False,
                user={},
                chat_data={}
            )

        mock_registry = MagicMock()
        mock_registry.metadata = {}
        mock_registry.list_modules.return_value = []

        # Mock the amprChat agent to return a known response
        mock_agent = MagicMock()
        mock_result = AgentRunResult(output="Bitcoin is trading at $100,000 USD.")
        mock_agent.run = AsyncMock(return_value=mock_result)

        monkeypatch.setattr('src.middleware.auth.validate_hanko_session', fake_validate_hanko_session)
        monkeypatch.setattr('src.clients.convex_client.get_client', lambda: mock_convex)
        monkeypatch.setattr('src.api.chat.get_client', lambda: mock_convex)
        monkeypatch.setattr('src.api.responses.context.get_async_client', lambda: mock_async_convex)
        monkeypatch.setattr('src.api.responses.web.run_preprocessing', fake_run_preprocessing)
        monkeypatch.setattr('src.api.responses.web.get_module_registry', lambda: mock_registry)
        monkeypatch.setattr('src.api.responses.web.get_amprChat_agent', lambda: mock_agent)
        # Mock store_and_deliver_response to avoid actual Convex writes
        monkeypatch.setattr('src.api.responses.web.store_and_deliver_response', AsyncMock())
        monkeypatch.setattr('src.api.responses.web.schedule_memory_management', lambda context: None)
        monkeypatch.setattr('src.api.responses.web.schedule_profile_watcher', lambda context, message: None)

        client = TestClient(fast_api)
        response = client.post(
            "/api/chat/message",
            headers={"Authorization": "Bearer test-token"},
            json={"channel": "web", "content": "What is the price of BTC?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["acknowledged"] is True
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Bitcoin is trading at $100,000 USD."
        assert data["messages"][0]["specialist_module"] is None

        # Verify the amprChat agent was actually called (web routing, not store-only)
        mock_agent.run.assert_awaited_once()

    def test_rest_endpoint_behavioral_app_channel_is_store_only(self, monkeypatch):
        """Behavioral test: /api/chat/message with app channel stores only (no agent call)."""
        from fastapi.testclient import TestClient
        from src.main import fast_api

        mock_convex = MagicMock(spec=ConvexClient)
        mock_convex.query.return_value = {"_id": "test_user_123"}
        mock_convex.mutation.return_value = {"_id": "test_msg_id", "chat": "chat_1"}

        async def fake_validate_hanko_session(session_token: str):
            return "hanko_user_123", "test@example.com"

        monkeypatch.setattr('src.middleware.auth.validate_hanko_session', fake_validate_hanko_session)
        monkeypatch.setattr('src.clients.convex_client.get_client', lambda: mock_convex)
        monkeypatch.setattr('src.api.chat.get_client', lambda: mock_convex)

        client = TestClient(fast_api)
        response = client.post(
            "/api/chat/message",
            headers={"Authorization": "Bearer test-token"},
            json={"channel": "app", "content": "Hello from mobile"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["acknowledged"] is True
        assert data["messages"] is None

        # Verify the message was stored (mutation called)
        mock_convex.mutation.assert_called()
        call_args = mock_convex.mutation.call_args
        assert call_args.args[0] == "messages:createMessage"
        assert call_args.args[1]["channel"] == "app"
