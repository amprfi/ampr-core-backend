"""
Shared context string builder for AI response generation.

This module provides a unified interface for building the context string
that is passed to AI agents. It consolidates the previously duplicated
_build_context_string helper from web.py and telegram.py.

The context string includes sections for:
- Long term memory / summaries
- Recent conversation history
- Current message
- Module responses (when a specialist module has been invoked)
- Module not found messages (when unknown triggers are detected)
- Module-specific formatting and constraints
"""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)


def build_context_string(
    summaries_str: str,
    message_history_str: str,
    message_content: str,
    date_context_str: Optional[str],
    currency_context: Optional[str],
    module_name: Optional[str],
    module_response: Optional[str],
    unresolved_triggers: list[str],
    registry: Optional["ModuleRegistry"] = None,
) -> str:
    """
    Build the context string for the AI agent.

    Constructs the prompt context including summaries, message history,
    current message, date context, currency context, and module information.

    Args:
        summaries_str: Formatted summaries string
        message_history_str: JSON string of message history
        message_content: Current user message content
        date_context_str: Optional date context string
        currency_context: Optional currency context string (e.g., "display_currency: USD")
        module_name: Optional name of the invoked module
        module_response: Optional response from the invoked module
        unresolved_triggers: List of unresolved module triggers
        registry: Optional ModuleRegistry for looking up module metadata
            (if not provided, module-specific sections will be minimal)
    
    Returns:
        str: The complete context string for the agent
    """
    # Build context sections if available
    date_context_section = f"\n\n        {date_context_str}" if date_context_str else ""
    currency_context_section = f"\n\n        {currency_context}" if currency_context else ""
    combined_context_section = date_context_section + currency_context_section

    # Module invocations that fail arrive as "ERROR: ..." strings (see
    # preprocessing.py). Instead of presenting the internal error text as module
    # data, instruct amprChat to acknowledge the module is unavailable.
    if module_response and module_response.startswith("ERROR:"):
        return f"""
        [LONG TERM MEMORY / SUMMARIES]
        The following are summaries of earlier conversation parts (chronological order):
        {summaries_str}

        [RECENT CONVERSATION]
        Previous conversation history (chronological order):
        {message_history_str}

        [CURRENT MESSAGE]
        User message:
        {message_content}{combined_context_section}

        [MODULE UNAVAILABLE]
        A specialist module was invoked for this request but failed and is currently unavailable.
        {module_response}

        Acknowledge to the user that the module could not complete the request right now, advise them to try again later, and ask how else you can help. Do not surface the raw error details above to the user.
        """

    if module_response:
        # Build module-specific presentation instructions if available
        response_instructions = ""
        constraints = []
        
        if registry and module_name:
            response_instructions = registry.get_response_instructions(module_name)
            constraints = registry.get_constraints_for_module(module_name)
        
        extra_sections = ""
        if response_instructions:
            extra_sections += f"\n\n        MODULE-SPECIFIC FORMATTING:\n        {response_instructions}"
        if constraints:
            constraints_str = "\n        ".join(f"- {c}" for c in constraints)
            extra_sections += f"\n\n        MODULE CONSTRAINTS:\n        {constraints_str}"
        
        presentation_guidance = f"IMPORTANT: Present this data in a natural, conversational way that fits your tone. Preserve all factual information (numbers, dates, names) exactly as provided, but feel free to rephrase for readability. Do not add speculation or information beyond what the module provided.{extra_sections}"

        context_str = f"""
        [LONG TERM MEMORY / SUMMARIES]
        The following are summaries of earlier conversation parts (chronological order):
        {summaries_str}

        [RECENT CONVERSATION]
        Previous conversation history (chronological order):
        {message_history_str}

        [CURRENT MESSAGE]
        User message:
        {message_content}{combined_context_section}

        [MODULE RESPONSE]
        A specialized module has processed this request and returned the following response:
        {module_response}

        {presentation_guidance}
        """
    else:
        # Build optional module-not-found section
        module_not_found_section = ""
        if unresolved_triggers:
            triggers_list = ", ".join(unresolved_triggers)
            module_not_found_section = f"""

        [MODULE NOT FOUND]
        The user attempted to invoke the following module(s) that could not be found: {triggers_list}
        """

        context_str = f"""
        [LONG TERM MEMORY / SUMMARIES]
        The following are summaries of earlier conversation parts (chronological order):
        {summaries_str}

        [RECENT CONVERSATION]
        Previous conversation history (chronological order):
        {message_history_str}

        [CURRENT MESSAGE]
        Current message to respond to:
        {message_content}{combined_context_section}{module_not_found_section}"""
    
    return context_str
