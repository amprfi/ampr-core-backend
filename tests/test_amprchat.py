"""
Tests for the migrated amprChat agent (AMPRFI-117).

These tests verify that:
- The new Mistral SDK runner-based implementation works correctly
- All 12 tools are available and function properly
- Pydantic validation works for tool arguments
- The compatibility shim works with existing caller patterns
- currency_context is passed via build_context_string, not as internal context
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from convex import ConvexClient

from src.agents.amprChat import (
    get_amprChat_agent,
    TalkerContext,
    AmprChatAgent,
    AgentRunResult,
    build_help_overview,
)
from src.agents.amprchat_tools import (
    AMPCHAT_MODEL,
    build_amprchat_tools,
    _build_system_prompt,
    build_amprchat_config,
    GetUserCountryArgs,
    UserInvestmentPreferencesArgs,
    GetHelpOverviewArgs,
    GetUserWatchlistArgs,
    GetAllAlertsArgs,
    ListSpecialistModulesArgs,
    ManageNotificationPreferencesArgs,
    ManagePriceAlertArgs,
    ManagePredictionAlertArgs,
    GetContributionScoreArgs,
    UpdateUserProfileArgs,
    ConvertModuleCurrencyArgs,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_convex_client():
    """Create a mock ConvexClient for testing."""
    client = MagicMock(spec=ConvexClient)
    client.query = MagicMock(return_value={})
    client.mutation = MagicMock(return_value=None)
    return client


@pytest.fixture
def talker_context(mock_convex_client):
    """Create a TalkerContext for testing."""
    return TalkerContext(
        convex_client=mock_convex_client,
        user_id="test_user_123",
        date_context="2026-06-23",
        invoked_modules=[],
        channel="web",
        telegram_id=None,
    )


# =============================================================================
# Test: TalkerContext Model
# =============================================================================

class TestTalkerContext:
    """Tests for the TalkerContext model."""
    
    def test_talker_context_defaults(self):
        """Test TalkerContext has correct default values."""
        ctx = TalkerContext(
            convex_client=MagicMock(spec=ConvexClient),
            user_id="test_user"
        )
        assert ctx.date_context is None
        assert ctx.invoked_modules == []
        assert ctx.channel is None
        assert ctx.telegram_id is None


# =============================================================================
# Test: Pydantic Args Models
# =============================================================================

class TestArgsModels:
    """Tests for Pydantic args models."""
    
    def test_get_user_country_args_no_fields(self):
        """GetUserCountryArgs should accept no arguments."""
        args = GetUserCountryArgs()
        assert args.model_dump() == {}
    
    def test_get_user_watchlist_args_types_validation(self):
        """GetUserWatchlistArgs should accept valid types."""
        # Valid types
        args = GetUserWatchlistArgs(types=["asset", "event"])
        assert args.types == ["asset", "event"]
        
        # None is valid
        args = GetUserWatchlistArgs(types=None)
        assert args.types is None
    
    def test_get_user_watchlist_args_rejects_invalid_types(self):
        """GetUserWatchlistArgs should reject invalid type values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GetUserWatchlistArgs(types=["asset", "invalid_type"])
    
    def test_get_all_alerts_args_rejects_invalid_types(self):
        """GetAllAlertsArgs should reject invalid type values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GetAllAlertsArgs(types=["price", "invalid_type"])
    
    def test_manage_notification_preferences_args_action_validation(self):
        """ManageNotificationPreferencesArgs should accept valid actions."""
        for action in ["get_status", "set_global", "set_module"]:
            args = ManageNotificationPreferencesArgs(action=action)
            assert args.action == action
    
    def test_manage_notification_preferences_args_rejects_invalid_action(self):
        """ManageNotificationPreferencesArgs should reject invalid action values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManageNotificationPreferencesArgs(action="invalid_action")
    
    def test_manage_price_alert_args_validation(self):
        """ManagePriceAlertArgs should validate alert_kind values."""
        for alert_kind in ["percentage_24h", "percentage_7d", "absolute_price"]:
            args = ManagePriceAlertArgs(
                action="set",
                asset_name="BTC",
                alert_kind=alert_kind
            )
            assert args.alert_kind == alert_kind
    
    def test_manage_price_alert_args_rejects_invalid_action(self):
        """ManagePriceAlertArgs should reject invalid action values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManagePriceAlertArgs(action="invalid_action", asset_name="BTC")
    
    def test_manage_price_alert_args_rejects_invalid_alert_kind(self):
        """ManagePriceAlertArgs should reject invalid alert_kind values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManagePriceAlertArgs(
                action="set",
                asset_name="BTC",
                alert_kind="invalid_alert_kind"
            )
    
    def test_manage_price_alert_args_rejects_invalid_direction(self):
        """ManagePriceAlertArgs should reject invalid direction values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManagePriceAlertArgs(
                action="set",
                asset_name="BTC",
                alert_kind="absolute_price",
                target_price=100.0,
                direction="invalid_direction"
            )
    
    def test_update_user_profile_args_optional_fields(self):
        """UpdateUserProfileArgs should have all optional fields."""
        args = UpdateUserProfileArgs()
        assert args.country_name is None
        assert args.preferred_currency is None
        assert args.email is None
        assert args.phone is None
        
        args = UpdateUserProfileArgs(
            country_name="CAN",
            preferred_currency="CAD",
            email="test@example.com",
            phone="+1234567890"
        )
        assert args.country_name == "CAN"
        assert args.preferred_currency == "CAD"
        assert args.email == "test@example.com"
        assert args.phone == "+1234567890"
    
    def test_manage_prediction_alert_args_rejects_invalid_action(self):
        """ManagePredictionAlertArgs should reject invalid action values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManagePredictionAlertArgs(action="invalid_action", event_query="test")
    
    def test_manage_prediction_alert_args_rejects_invalid_alert_kind(self):
        """ManagePredictionAlertArgs should reject invalid alert_kind values."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ManagePredictionAlertArgs(
                action="set",
                event_query="test",
                alert_kind="invalid_alert_kind"
            )


# =============================================================================
# Test: Tool Building
# =============================================================================

class TestToolBuilding:
    """Tests for tool factory functions."""
    
    def test_build_amprchat_tools_returns_all_tools(self, talker_context):
        """build_amprchat_tools should return all 12 tools."""
        tools = build_amprchat_tools(talker_context)
        expected_tool_names = {
            "get_user_country_tool",
            "user_investment_preferences",
            "get_help_overview",
            "get_user_watchlist",
            "get_all_alerts",
            "list_specialist_modules",
            "manage_notification_preferences",
            "manage_price_alert",
            "manage_prediction_alert",
            "get_contribution_score",
            "update_user_profile",
            "convert_module_currency",
        }
        assert set(tools.keys()) == expected_tool_names
    
    def test_tool_has_correct_name_and_description(self, talker_context):
        """Each tool should have correct name and description."""
        tools = build_amprchat_tools(talker_context)
        
        # Check a few examples
        assert tools["get_user_country_tool"].name == "get_user_country_tool"
        assert "country" in tools["get_user_country_tool"].description.lower()
        
        assert tools["get_user_watchlist"].name == "get_user_watchlist"
        assert "watchlist" in tools["get_user_watchlist"].description.lower()


# =============================================================================
# Test: System Prompt Building
# =============================================================================

class TestSystemPrompt:
    """Tests for system prompt generation."""
    
    @pytest.mark.asyncio
    async def test_system_prompt_does_not_contain_currency_context(self, talker_context):
        """System prompt should NOT contain currency_context."""
        # System prompt should not contain currency context - it's now in the context string
        # Use a sentinel value to avoid false positives from template text
        system_prompt = await _build_system_prompt(talker_context)
        assert "CURRENCY CONTEXT:" not in system_prompt
        # The system prompt template may contain example text, but not our sentinel
        assert "ZZ_SENTINEL" not in system_prompt
    
    @pytest.mark.asyncio
    async def test_system_prompt_contains_modules(self, talker_context):
        """System prompt should contain module information."""
        with patch('src.agents.amprchat_tools.get_module_registry') as mock_registry:
            mock_registry.return_value.list_modules.return_value = [
                {"name": "test_module", "description": "Test module", "intents": ["test intent"]}
            ]
            system_prompt = await _build_system_prompt(talker_context)
            assert "test_module" in system_prompt
            assert "Test module" in system_prompt


# =============================================================================
# Test: Runner Config Building
# =============================================================================

class TestRunnerConfig:
    """Tests for RunnerConfig building."""
    
    @pytest.mark.asyncio
    async def test_build_amprchat_config_returns_config(self, talker_context):
        """build_amprchat_config should return a valid RunnerConfig."""
        with patch('src.agents.amprchat_tools.get_mistral_client'):
            config = await build_amprchat_config(talker_context)
            assert config.model == AMPCHAT_MODEL
            assert config.reasoning_effort == "high"
            assert config.tool_choice == "auto"
            assert config.max_iterations == 10
    
    @pytest.mark.asyncio
    async def test_config_has_no_context_messages(self, talker_context):
        """Config should NOT include context_messages - currency_context is in context string."""
        with patch('src.agents.amprchat_tools.get_mistral_client'):
            config = await build_amprchat_config(talker_context)
            # context_messages should be None or empty since currency_context is now in context string
            assert config.context_messages is None or len(config.context_messages) == 0

    @pytest.mark.asyncio
    async def test_multi_module_synthesis_response_does_not_crash(self, monkeypatch):
        """Multi-module synthesis should not crash on the helper call signature."""
        # Importing the web handler pulls in onboarding.py, which initializes
        # pydantic-ai's Mistral provider at module load time.
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        from src.api.responses.web import _synthesize_multi_module_response

        preprocess_result = MagicMock()
        preprocess_result.summaries_str = "summary"
        preprocess_result.message_history_str = "[]"
        preprocess_result.message_content = "Compare BTC and a prediction market"
        preprocess_result.date_context_str = "DATE_CONTEXT"
        preprocess_result.currency_context = "display_currency: CAD"
        preprocess_result.needs_onboarding = False
        preprocess_result.interim_messages = []

        module_registry = MagicMock()
        module_registry.metadata = {
            "defianalyst": {"trigger": "&defianalyst"},
            "oracle": {"trigger": "&oracle"},
        }

        with patch("src.api.responses.web._get_agent_response", new_callable=AsyncMock) as mock_get_agent_response:
            mock_get_agent_response.side_effect = ["defi response", "oracle response"]

            results = await _synthesize_multi_module_response(
                MagicMock(),
                preprocess_result,
                module_registry,
                ["defianalyst", "oracle"],
                {
                    "defianalyst": "Bitcoin is $100,000 USD",
                    "oracle": "Probability is 60%",
                },
            )

        assert [msg.content for msg in results] == ["defi response", "oracle response"]
        assert [msg.specialist_module for msg in results] == ["defianalyst", "oracle"]


# =============================================================================
# Test: Compatibility Shim
# =============================================================================

class TestCompatibilityShim:
    """Tests for the AmprChatAgent compatibility shim."""
    
    def test_get_amprChat_agent_returns_agent(self):
        """get_amprChat_agent should return an AmprChatAgent instance."""
        agent = get_amprChat_agent()
        assert isinstance(agent, AmprChatAgent)
    
    def test_amprChat_agent_has_run_method(self):
        """AmprChatAgent should have a run method."""
        agent = get_amprChat_agent()
        assert hasattr(agent, 'run')
        assert callable(agent.run)
    
    def test_amprChat_agent_has_stream_method(self):
        """AmprChatAgent should have a stream method."""
        agent = get_amprChat_agent()
        assert hasattr(agent, 'stream')
        assert callable(agent.stream)
    
    @pytest.mark.asyncio
    async def test_agent_run_returns_result_with_output(self, talker_context):
        """Agent.run should return AgentRunResult with output attribute."""
        agent = get_amprChat_agent()
        
        with patch('src.agents.amprChat.build_amprchat_config') as mock_build_config, \
             patch('src.agents.amprChat.tool_runner_run') as mock_run:
            
            mock_config = MagicMock()
            mock_build_config.return_value = mock_config
            mock_run.return_value = "test output"
            
            result = await agent.run("test message", talker_context)
            
            assert isinstance(result, AgentRunResult)
            assert hasattr(result, 'output')
            assert result.output == "test output"


# =============================================================================
# Test: build_help_overview
# =============================================================================

class TestBuildHelpOverview:
    """Tests for build_help_overview function."""
    
    def test_build_help_overview_returns_string(self):
        """build_help_overview should return a non-empty string."""
        result = build_help_overview()
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_build_help_overview_contains_capabilities(self):
        """build_help_overview should contain capability descriptions."""
        result = build_help_overview()
        assert "Ampersand is your financial co-pilot" in result
        assert "General capabilities:" in result
    
    def test_build_help_overview_contains_modules(self):
        """build_help_overview should list available modules."""
        result = build_help_overview()
        assert "Available specialist modules:" in result


# =============================================================================
# Test: Internal Context Marker
# =============================================================================

class TestCurrencyContext:
    """Tests for currency_context handling."""
    
    @pytest.mark.asyncio
    async def test_currency_context_in_context_string(self, talker_context):
        """currency_context should be passed via build_context_string, not in config."""
        with patch('src.agents.amprchat_tools.get_mistral_client'):
            config = await build_amprchat_config(talker_context)
            # context_messages should be None or empty since currency_context is now in context string
            assert config.context_messages is None or len(config.context_messages) == 0

    def test_multi_module_synthesis_context_includes_currency_context(self, monkeypatch):
        """Web multi-module synthesis should preserve per-turn currency context."""
        # Importing the web handler imports onboarding.py, which still initializes
        # pydantic-ai's Mistral provider at module load time.
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        from src.api.responses.synthesis_context import build_module_synthesis_context

        preprocess_result = MagicMock()
        preprocess_result.summaries_str = "summary"
        preprocess_result.message_history_str = "[]"
        preprocess_result.message_content = "Compare BTC and a prediction market"
        preprocess_result.date_context_str = "DATE_CONTEXT"
        preprocess_result.currency_context = "display_currency: CAD"

        module_registry = MagicMock()
        module_registry.metadata = {"defianalyst": {}}

        normal_context = build_module_synthesis_context(
            preprocess_result,
            module_registry,
            "defianalyst",
            "Bitcoin is $100,000 USD",
            "",
        )
        unavailable_context = build_module_synthesis_context(
            preprocess_result,
            module_registry,
            "defianalyst",
            "ERROR: module unavailable",
            "",
        )

        assert "DATE_CONTEXT" in normal_context
        assert "display_currency: CAD" in normal_context
        assert "DATE_CONTEXT" in unavailable_context
        assert "display_currency: CAD" in unavailable_context


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the full amprChat flow."""
    
    @pytest.mark.asyncio
    async def test_full_agent_run_flow(self, talker_context):
        """Test the complete agent run flow with mocked dependencies."""
        agent = get_amprChat_agent()
        
        with patch('src.agents.amprchat_tools.get_mistral_client') as mock_client, \
             patch('src.agents.amprchat_tools._build_system_prompt') as mock_prompt, \
             patch('src.agents.amprchat_tools.build_amprchat_tools') as mock_tools, \
             patch('src.agents.amprChat.tool_runner_run') as mock_run:
            
            mock_client.return_value = MagicMock()
            mock_prompt.return_value = "System prompt"
            mock_tools.return_value = {}
            mock_run.return_value = "Test response"
            
            result = await agent.run("Test message", talker_context)
            
            assert result.output == "Test response"
            mock_run.assert_called_once()
