"""
Shared synthesis context building for AI response generation.

This module contains shared functions for building context strings used in
both streaming and non-streaming response generation paths, ensuring
consistency between the two (AMPRFI-117 parity requirement).
"""



def build_module_synthesis_context(
    preprocess_result,
    module_registry,
    module_name: str,
    module_response: str,
    cross_module_context: str
) -> str:
    """
    Build a specialized context string for module-specific synthesis.

    This creates a context that includes:
    - The module's raw result
    - Module-specific formatting instructions and constraints
    - Concise awareness of other responding modules
    - All the standard context (summaries, history, etc.)

    This function is shared between streaming (streaming.py) and non-streaming
    (web.py) paths to ensure equivalent context construction.

    Args:
        preprocess_result: PreprocessingResult with all collected data
        module_registry: ModuleRegistry instance
        module_name: Current module name
        module_response: The raw response from this module
        cross_module_context: Context about other responding modules

    Returns:
        str: Context string for synthesis
    """
    # Handle module errors: if module_response starts with "ERROR:", don't surface raw error
    # This mirrors the behavior in context_builder.py's build_context_string
    if module_response and module_response.startswith("ERROR:"):
        date_context_section = f"\n    {preprocess_result.date_context_str}" if preprocess_result.date_context_str else ""
        currency_context_section = f"\n    {preprocess_result.currency_context}" if preprocess_result.currency_context else ""
        combined_context_section = date_context_section + currency_context_section
        return f"""[LONG TERM MEMORY / SUMMARIES]
The following are summaries of earlier conversation parts (chronological order):
{preprocess_result.summaries_str}

[RECENT CONVERSATION]
Previous conversation history (chronological order):
{preprocess_result.message_history_str}

[CURRENT MESSAGE]
User message:
{preprocess_result.message_content}{combined_context_section}

[MODULE UNAVAILABLE]
A specialist module was invoked for this request but failed and is currently unavailable.
{module_response}

Acknowledge to the user that the module could not complete the request right now, advise them to try again later, and ask how else you can help. Do not surface the raw error details above to the user.
"""

    # Get module-specific metadata
    metadata = module_registry.metadata.get(module_name, {})
    response_instructions = metadata.get("response_instructions", "")
    constraints = metadata.get("constraints", [])

    # Build the module-specific sections
    module_specific_sections = []

    if response_instructions:
        module_specific_sections.append(f"MODULE-SPECIFIC FORMATTING:\n{response_instructions}")

    if constraints:
        constraints_str = "\n        ".join(f"- {c}" for c in constraints)
        module_specific_sections.append(f"MODULE CONSTRAINTS:\n{constraints_str}")

    if cross_module_context:
        module_specific_sections.append(f"CROSS-MODULE AWARENESS:\n{cross_module_context}")
        # Add guidance to avoid duplication
        module_specific_sections.append(
            "To reduce duplication, focus on information unique to this module's data. "
            "Acknowledge that other modules are also responding but present this module's specific insights."
        )

    module_specific_str = "\n\n        ".join(module_specific_sections)
    if module_specific_str:
        module_specific_str = f"\n\n        {module_specific_str}"

    # Build the main context string
    date_context_section = f"\n    {preprocess_result.date_context_str}" if preprocess_result.date_context_str else ""
    currency_context_section = f"\n    {preprocess_result.currency_context}" if preprocess_result.currency_context else ""
    combined_context_section = date_context_section + currency_context_section

    context_str = f"""[LONG TERM MEMORY / SUMMARIES]
The following are summaries of earlier conversation parts (chronological order):
{preprocess_result.summaries_str}

[RECENT CONVERSATION]
Previous conversation history (chronological order):
{preprocess_result.message_history_str}

[CURRENT MESSAGE]
User message:
{preprocess_result.message_content}{combined_context_section}

[MODULE RESPONSE]
A specialized module has processed this request and returned the following response:
{module_response}

IMPORTANT: Present this data in a natural, conversational way that fits your tone.
Preserve all factual information (numbers, dates, names) exactly as provided,
but feel free to rephrase for readability. Do not add speculation or information
beyond what the module provided.{module_specific_str}
"""

    return context_str
