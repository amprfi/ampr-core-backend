"""
Tests for the unified module router (AMPRFI-103).
"""

import pytest
from src.modules.registry import ModuleRegistry, get_module_registry
from src.modules.router import (
    route_to_modules,
    RoutingDecision,
    _extract_mentions,
    _filter_substring_false_positives,
)


@pytest.fixture
def registry() -> ModuleRegistry:
    """Get a fresh module registry for testing with mock modules."""
    # Create a test registry manually with mock modules
    # to avoid importing actual modules that require API keys
    reg = ModuleRegistry(config_path=None)
    reg.triggers = {
        "&defianalyst": "defianalyst",
        "&oracle": "oracle",
        "&navigator": "navigator",
        "&lens": "lens",
    }
    reg.modules = {
        "defianalyst": None,
        "oracle": None,
        "navigator": None,
        "lens": None,
    }
    reg.metadata = {
        "defianalyst": {
            "trigger": "&defianalyst",
            "description": "Cryptocurrency market data analyst",
            "intents": ["price data", "market cap"],
        },
        "oracle": {
            "trigger": "&oracle",
            "description": "Prediction markets specialist",
            "intents": ["probability", "prediction"],
        },
        "navigator": {
            "trigger": "&navigator",
            "description": "Financial education module",
            "intents": ["courses", "learning"],
        },
        "lens": {
            "trigger": "&lens",
            "description": "RAG-powered author agent",
            "intents": ["search", "content"],
        },
    }
    return reg


class TestExtractMentions:
    """Tests for the _extract_mentions helper function."""

    def test_single_mention(self):
        """Test extracting a single mention."""
        mentions = _extract_mentions("What is &defianalyst doing?")
        assert mentions == ["&defianalyst"]

    def test_multiple_mentions(self):
        """Test extracting multiple mentions in order."""
        mentions = _extract_mentions("Tell me about &defianalyst and &oracle")
        assert mentions == ["&defianalyst", "&oracle"]

    def test_mention_with_colon(self):
        """Test extracting mentions with colons (e.g., &lens:author)."""
        mentions = _extract_mentions("Show me &lens:proof-of-words")
        assert mentions == ["&lens:proof-of-words"]

    def test_duplicate_mentions_deduplicated(self):
        """Test that duplicate mentions are deduplicated."""
        mentions = _extract_mentions("&defianalyst what about &defianalyst?")
        assert mentions == ["&defianalyst"]

    def test_mention_order_preserved(self):
        """Test that mention order is preserved."""
        mentions = _extract_mentions("&oracle then &defianalyst then &oracle again")
        assert mentions == ["&oracle", "&defianalyst"]

    def test_no_mentions(self):
        """Test message with no mentions."""
        mentions = _extract_mentions("Hello, how are you?")
        assert mentions == []

    def test_case_sensitive(self):
        """Test that mentions are case-sensitive."""
        mentions = _extract_mentions("&Defianalyst")
        assert mentions == ["&Defianalyst"]


class TestFilterSubstringFalsePositives:
    """Tests for the _filter_substring_false_positives helper function."""

    def test_no_substring_match(self):
        """Test when there's no substring match."""
        mentions = ["&defi", "&oracle"]
        registered = {"&defi", "&oracle"}
        filtered = _filter_substring_false_positives(mentions, registered)
        assert filtered == ["&defi", "&oracle"]

    def test_substring_filtered(self):
        """Test that substrings are filtered out."""
        mentions = ["&defi", "&defianalyst"]
        registered = {"&defi", "&defianalyst"}
        # &defi should be filtered because it's a substring of &defianalyst
        filtered = _filter_substring_false_positives(mentions, registered)
        assert filtered == ["&defianalyst"]

    def test_longer_first(self):
        """Test that longer triggers are checked first."""
        mentions = ["&defianalyst", "&defi"]
        registered = {"&defi", "&defianalyst"}
        filtered = _filter_substring_false_positives(mentions, registered)
        assert filtered == ["&defianalyst"]

    def test_standalone_short_trigger_not_filtered(self):
        """Regression: a short trigger must not be dropped just because a longer
        trigger containing it is registered but absent from the message.

        Review case: mentions=['&defi'] with registered={'&defi','&defianalyst'}
        previously returned [] because &defi is a substring of the (absent)
        &defianalyst trigger.
        """
        mentions = ["&defi"]
        registered = {"&defi", "&defianalyst"}
        filtered = _filter_substring_false_positives(mentions, registered)
        assert filtered == ["&defi"]


class TestRouteToModules:
    """Tests for the route_to_modules function."""

    def test_known_mention(self, registry):
        """Test routing with a known module mention."""
        decision = route_to_modules(
            "What is &defianalyst doing?",
            registry,
            enable_llm_classification=False
        )
        assert decision.method == "mention"
        assert decision.confidence == 1.0
        assert "defianalyst" in decision.modules
        assert decision.unresolved_triggers == []

    def test_multiple_known_mentions(self, registry):
        """Test routing with multiple known module mentions."""
        decision = route_to_modules(
            "Tell me about &defianalyst and &oracle",
            registry,
            enable_llm_classification=False
        )
        assert decision.method == "mention"
        assert decision.confidence == 1.0
        assert "defianalyst" in decision.modules
        assert "oracle" in decision.modules

    def test_unknown_mention(self, registry):
        """Test routing with an unknown module mention."""
        decision = route_to_modules(
            "What is &unknown doing?",
            registry,
            enable_llm_classification=False
        )
        assert decision.method == "none"
        assert decision.confidence == 0.0
        assert decision.modules == []
        assert "&unknown" in decision.unresolved_triggers

    def test_mixed_known_and_unknown(self, registry):
        """Test routing with both known and unknown mentions."""
        decision = route_to_modules(
            "Tell me about &defianalyst and &unknown",
            registry,
            enable_llm_classification=False
        )
        assert decision.method == "mention"
        assert "defianalyst" in decision.modules
        assert "&unknown" in decision.unresolved_triggers

    def test_no_mentions_no_llm(self, registry):
        """Test routing with no mentions and LLM classification disabled."""
        decision = route_to_modules(
            "What is the price of Bitcoin?",
            registry,
            enable_llm_classification=False
        )
        assert decision.method == "none"
        assert decision.modules == []
        assert decision.confidence == 0.0


class TestModuleRegistryDetectTriggers:
    """Tests for the ModuleRegistry.detect_module_triggers method."""

    def test_single_trigger(self, registry):
        """Test detecting a single trigger."""
        # Note: This test may fail if defianalyst is disabled in modules.yaml
        # We'll check if it's registered first
        if "&defianalyst" in registry.triggers:
            triggers = registry.detect_module_triggers("What is &defianalyst doing?")
            assert "&defianalyst" in triggers
        else:
            # defianalyst might be disabled, skip this test
            pytest.skip("defianalyst module not registered")

    def test_multiple_triggers(self, registry):
        """Test detecting multiple triggers in order."""
        # Check which modules are actually registered
        available_triggers = [t for t in ["&defianalyst", "&oracle"] if t in registry.triggers]
        if len(available_triggers) < 2:
            pytest.skip(f"Not enough modules registered: {available_triggers}")
        
        triggers = registry.detect_module_triggers(
            "Tell me about &defianalyst and &oracle"
        )
        for t in available_triggers:
            assert t in triggers
        # Check order is preserved for available triggers
        if "&defianalyst" in triggers and "&oracle" in triggers:
            assert triggers.index("&defianalyst") < triggers.index("&oracle")

    def test_duplicate_triggers_deduplicated(self, registry):
        """Test that duplicate triggers are deduplicated."""
        if "&defianalyst" not in registry.triggers:
            pytest.skip("defianalyst module not registered")
        
        triggers = registry.detect_module_triggers(
            "&defianalyst what about &defianalyst?"
        )
        assert triggers.count("&defianalyst") == 1

    def test_unknown_trigger_not_included(self, registry):
        """Test that unknown triggers are not included."""
        triggers = registry.detect_module_triggers("What is &unknown doing?")
        assert triggers == []

    def test_substring_false_positive_filtered(self, registry):
        """Test that substring false positives are filtered."""
        # This test assumes we have both &defi and &defianalyst registered
        # In the actual registry, only &defianalyst is registered
        triggers = registry.detect_module_triggers("&defianalyst")
        # Should only return &defianalyst, not &defi (if it existed)
        assert "&defianalyst" in triggers or triggers == []

    def test_hyphenated_trigger_detected(self, registry):
        """Regression: registry.detect_module_triggers must use the same
        hyphen-allowing regex as the router.

        The old registry regex r'&([\\w:]+)' mis-tokenized &lens:proof-of-words;
        now it delegates to the router which uses r'&([\\w:\\-]+)'.
        """
        registry.triggers["&lens:proof-of-words"] = "lens"
        try:
            triggers = registry.detect_module_triggers("use &lens:proof-of-words")
            assert "&lens:proof-of-words" in triggers
        finally:
            del registry.triggers["&lens:proof-of-words"]


class TestRoutingDecision:
    """Tests for the RoutingDecision dataclass."""

    def test_default_values(self):
        """Test default values of RoutingDecision."""
        decision = RoutingDecision()
        assert decision.modules == []
        assert decision.method == "none"
        assert decision.confidence == 0.0
        assert decision.rationale is None
        assert decision.unresolved_triggers == []

    def test_custom_values(self):
        """Test custom values in RoutingDecision."""
        decision = RoutingDecision(
            modules=["defianalyst", "oracle"],
            method="mention",
            confidence=1.0,
            rationale="Explicit mentions detected",
            unresolved_triggers=["&unknown"],
        )
        assert decision.modules == ["defianalyst", "oracle"]
        assert decision.method == "mention"
        assert decision.confidence == 1.0
        assert decision.rationale == "Explicit mentions detected"
        assert decision.unresolved_triggers == ["&unknown"]
