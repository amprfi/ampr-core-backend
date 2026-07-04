"""
Unified module router for Ampersand.

This module provides a single source of truth for selecting zero, one, or multiple
specialist modules using deterministic mentions first and LLM classification second.

The router replaces the previous split routing model:
1. Single `&mention` detection in response generation
2. `amprChat` deciding to call `call_specialist_module` as a tool

Routing priority:
1. Explicit &mention triggers (deterministic, no LLM call)
2. LLM classification for natural-language routing (when no mention is present)
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from src.agents.mistral_helpers import (
    get_shared_client,
    build_messages,
    complete_json_schema,
    MODEL_SMALL,
)

if TYPE_CHECKING:
    from .registry import ModuleRegistry

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """
    Result of module routing decision.

    Attributes:
        modules: List of module names to invoke (empty list means no specialist modules)
        method: The routing method used - "mention", "llm", or "none"
        confidence: Confidence score (0.0 to 1.0) - 1.0 for mention-based, <1.0 for LLM
        rationale: Optional explanation for the routing decision
        unresolved_triggers: List of &mentions that couldn't be resolved to registered modules
    """
    modules: list[str] = field(default_factory=list)
    method: str = "none"
    confidence: float = 0.0
    rationale: Optional[str] = None
    unresolved_triggers: list[str] = field(default_factory=list)


def _extract_mentions(message: str) -> list[str]:
    """
    Extract all &mention triggers from a message.

    Preserves order from the user message and deduplicates repeated mentions.
    Avoids obvious substring false positives by matching word boundaries.

    Args:
        message: The user message to scan

    Returns:
        List of unique &mention triggers in order of first appearance
    """
    # Find all &word patterns (word = alphanumeric + underscore + hyphen + colon)
    # This matches &defianalyst, &oracle, &lens:something, &proof-of-words, etc.
    mentions = re.findall(r'&([\w:\-]+)', message)

    # Deduplicate while preserving order
    seen = set()
    unique_mentions = []
    for mention in mentions:
        if mention not in seen:
            seen.add(mention)
            unique_mentions.append(mention)

    return [f"&{m}" for m in unique_mentions]


def _filter_substring_false_positives(mentions: list[str], registered_triggers: set[str]) -> list[str]:
    """
    Suppress a mention only when a longer registered trigger that contains it is
    ALSO present among the extracted mentions.

    The word-boundary regex already tokenizes correctly (so "&defianalyst" is
    never split into "&defi" + "analyst"), which means a standalone "&defi" is
    almost always an intentional reference. We therefore only drop a shorter
    mention when the user actually wrote the longer trigger in the same message,
    e.g. "compare &defi and &defianalyst".

    Args:
        mentions: List of extracted (registered) mentions
        registered_triggers: Set of all registered trigger strings

    Returns:
        Filtered list of mentions that aren't shadowed by a longer present trigger
    """
    mention_set = set(mentions)
    filtered = []
    for mention in mentions:
        # Suppress only if a longer registered trigger containing this mention
        # is ALSO present in the message.
        is_shadowed = any(
            len(trigger) > len(mention)
            and mention in trigger
            and trigger in mention_set
            for trigger in registered_triggers
        )
        if not is_shadowed:
            filtered.append(mention)

    return filtered


async def route_to_modules(
    message: str,
    registry: "ModuleRegistry",
    enable_llm_classification: bool = True,
) -> RoutingDecision:
    """
    Route a user message to the appropriate specialist modules.

    This is the single source of truth for module routing. It uses:
    1. Deterministic mention detection first (if &mention triggers are present)
    2. LLM classification second (for natural-language routing when no mention)

    Args:
        message: The user message to route
        registry: The ModuleRegistry containing all available modules
        enable_llm_classification: Whether to use LLM classification for messages
            without explicit mentions (default: True). Set to False for testing
            or when LLM is unavailable.

    Returns:
        RoutingDecision with the selected modules and routing metadata
    """
    # Step 1: Extract all mentions from the message
    all_mentions = _extract_mentions(message)

    if not all_mentions:
        # No mentions found - try LLM classification
        if enable_llm_classification:
            return await _classify_with_llm(message, registry)
        else:
            logger.info("No module triggers detected and LLM classification disabled, routing to general chat")
            return RoutingDecision(
                modules=[],
                method="none",
                confidence=0.0,
                rationale="No module triggers detected and LLM classification disabled"
            )

    # Step 2: Separate known and unknown triggers
    registered_triggers = set(registry.triggers.keys())
    known_mentions = []
    unknown_mentions = []

    for mention in all_mentions:
        if mention in registered_triggers:
            known_mentions.append(mention)
        else:
            unknown_mentions.append(mention)

    # Step 3: Filter out substring false positives from known mentions
    known_mentions = _filter_substring_false_positives(known_mentions, registered_triggers)

    # Step 4: Resolve mention names to module names
    # (triggers map to module names in the registry)
    resolved_modules = []
    for mention in known_mentions:
        module_name = registry.triggers.get(mention)
        if module_name:
            resolved_modules.append(module_name)

    # Log the routing decision
    if resolved_modules:
        logger.info(
            f"Mention-based routing: message contains {all_mentions}, "
            f"resolved to modules {resolved_modules}"
        )

    if unknown_mentions:
        logger.warning(
            f"Unknown module triggers detected: {unknown_mentions}. "
            f"These will be surfaced to the user."
        )

    # Step 5: Return the decision
    if resolved_modules:
        return RoutingDecision(
            modules=resolved_modules,
            method="mention",
            confidence=1.0,
            rationale=f"Explicit mention(s) detected: {', '.join(all_mentions)}",
            unresolved_triggers=unknown_mentions,
        )
    else:
        # Only unknown mentions - no known modules to invoke
        if enable_llm_classification:
            # Still try LLM classification as a fallback
            llm_decision = await _classify_with_llm(message, registry)
            # Combine unresolved triggers with LLM result
            return RoutingDecision(
                modules=llm_decision.modules,
                method=llm_decision.method,
                confidence=llm_decision.confidence,
                rationale=llm_decision.rationale,
                unresolved_triggers=unknown_mentions + llm_decision.unresolved_triggers,
            )
        else:
            return RoutingDecision(
                modules=[],
                method="none",
                confidence=0.0,
                rationale=f"Only unknown triggers detected: {', '.join(unknown_mentions)}",
                unresolved_triggers=unknown_mentions,
            )


class ClassificationResult(BaseModel):
    """Structured output of the LLM module classifier."""
    modules: list[str]
    confidence: float
    rationale: str


# Global state for the classifier (system prompt depends on registry state)
_classifier_system_prompt: Optional[str] = None
_classifier_registry_hash: Optional[str] = None


def _build_classifier_system_prompt(registry: "ModuleRegistry") -> str:
    """
    Build the system prompt for the LLM classifier from the registry.

    This creates a prompt that describes all available modules to the LLM
    so it can classify messages appropriately.
    """
    # Build the module description block from the registry's enabled modules.
    module_descriptions = []
    for mod in registry.list_modules():
        name = mod.get("name", "")
        description = mod.get("description", "")
        intents = mod.get("intents", [])
        module_descriptions.append(f"{name}: {description}")
        if intents:
            module_descriptions.append(f"  Intents: {', '.join(intents[:3])}")
    modules_context = "\n".join(module_descriptions)

    system_prompt = f"""You are a message classifier for Ampersand's specialist modules.

Available modules:
{modules_context}

Your task:
- Analyze the user's message and determine which specialist module(s) would be most appropriate
- Return an empty list if the message is a general question or doesn't match any module's capabilities
- Only return module names that are in the available modules list above
- Provide a confidence score (0.0 to 1.0) where 1.0 is certain and 0.0 is a guess
- Provide a brief rationale for your classification

Guidelines:
- Be conservative: if unsure, return an empty list (general chat)
- Only classify to one module at a time unless the message clearly spans multiple domains
- If the message is a general financial question or greeting, return an empty list
- If the message asks about alerts, watchlist, or profile, return an empty list (these are handled by built-in tools)
"""
    return system_prompt


def _get_registry_hash(registry: "ModuleRegistry") -> str:
    """
    Compute a hash of the registry's module names for cache invalidation.
    
    This is more robust than using id(registry) which can be reused after GC.
    We hash the sorted module names to detect when modules have been added/removed.
    """
    module_names = sorted(registry.modules.keys())
    return hashlib.md5(",".join(module_names).encode()).hexdigest()


def _get_classifier_system_prompt(registry: "ModuleRegistry") -> str:
    """
    Get the classifier system prompt, rebuilding if registry has changed.

    We track a hash of module names to detect when modules have been added/removed.
    This is more robust than using id(registry) which can be reused after GC.
    """
    global _classifier_system_prompt, _classifier_registry_hash

    current_hash = _get_registry_hash(registry)
    if _classifier_system_prompt is None or _classifier_registry_hash != current_hash:
        _classifier_system_prompt = _build_classifier_system_prompt(registry)
        _classifier_registry_hash = current_hash

    return _classifier_system_prompt


async def _classify_with_llm(
    message: str,
    registry: "ModuleRegistry",
) -> RoutingDecision:
    """
    Classify a message using LLM to determine which specialist module(s) to invoke.

    This is used when no explicit &mention triggers are present in the message.
    Uses Mistral SDK with structured JSON output for classification.

    Args:
        message: The user message to classify
        registry: The ModuleRegistry containing all available modules

    Returns:
        RoutingDecision with LLM-classified modules
    """
    enabled_modules = registry.list_modules()

    if not enabled_modules:
        logger.info("No enabled modules available for LLM classification")
        return RoutingDecision(
            modules=[],
            method="llm",
            confidence=0.0,
            rationale="No enabled modules available"
        )

    try:
        logger.info(f"Running LLM classification for message: {message[:100]}...")

        # Build the system prompt from the registry
        system_prompt = _get_classifier_system_prompt(registry)

        # Use structured output with json_schema strict mode
        schema = ClassificationResult.model_json_schema()

        client = get_shared_client()

        # Build messages for the classifier
        user_content = f"Classify this message and determine the most appropriate specialist module(s):\n\n{message}"
        messages = build_messages(system_prompt, user_content)

        # Execute with structured output
        result_dict = await complete_json_schema(
            client=client,
            model=MODEL_SMALL,  # Use small model for classification
            messages=messages,
            schema=schema,
            temperature=0.0,
            reasoning_effort="none",
        )

        classification = ClassificationResult(**result_dict)

        # Validate the returned module names against registered modules
        registered_module_names = set(registry.modules.keys())
        valid_modules = [
            m for m in classification.modules
            if m in registered_module_names
        ]

        invalid_modules = [
            m for m in classification.modules
            if m not in registered_module_names
        ]

        if invalid_modules:
            logger.warning(
                f"LLM classification returned invalid module names: {invalid_modules}. "
                f"Valid modules: {list(registered_module_names)}"
            )

        # Log the classification result
        logger.info(
            f"LLM classification: modules={valid_modules}, "
            f"confidence={classification.confidence}, "
            f"rationale={classification.rationale}"
        )

        return RoutingDecision(
            modules=valid_modules,
            method="llm",
            confidence=classification.confidence,
            rationale=classification.rationale,
        )

    except Exception as e:
        logger.error(f"LLM classification failed: {str(e)}", exc_info=True)
        # On failure, default to zero modules (general chat)
        return RoutingDecision(
            modules=[],
            method="llm",
            confidence=0.0,
            rationale=f"LLM classification failed: {str(e)}",
        )


def detect_module_triggers(
    message: str,
    registry: "ModuleRegistry",
) -> list[str]:
    """
    Detect all module triggers in a message.

    Extracts mentions, keeps only registered triggers, and applies the same
    substring filtering used by route_to_modules. This is the single source of
    truth used by ModuleRegistry.detect_module_triggers(). Preserves order and
    deduplicates (deduplication happens inside _extract_mentions).

    Args:
        message: The user message to scan
        registry: The ModuleRegistry containing all available modules

    Returns:
        List of registered trigger strings found in the message (in order, deduplicated)
    """
    all_mentions = _extract_mentions(message)
    registered_triggers = set(registry.triggers.keys())

    # Keep only registered triggers, then apply the shared substring filter.
    known_mentions = [m for m in all_mentions if m in registered_triggers]
    return _filter_substring_false_positives(known_mentions, registered_triggers)
