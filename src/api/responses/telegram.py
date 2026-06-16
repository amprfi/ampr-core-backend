"""
Telegram channel handler for AI response generation.

This module handles the Telegram-specific response generation flow,
preserving the current zero-module and single-module behavior.
"""

import asyncio
import logging
import time
from typing import Optional

from ...agents.amprChat import get_amprChat_agent, TalkerContext
from ...agents.onboarding import get_onboarding_agent, OnboardingContext
from ...modules.registry import get_module_registry
from .context import ResponseContext
from .preprocessing import run_preprocessing
from .postprocessing import store_and_deliver_response, schedule_memory_management, schedule_profile_watcher

logger = logging.getLogger(__name__)


async def generate_telegram_response(context: ResponseContext) -> list[str]:
    """
    Generate an AI response for Telegram channel messages.

    This handler preserves the current behavior for Telegram-based chat,
    including the full AI pipeline with module detection and invocation,
    plus Telegram-specific delivery (paragraph chunking).

    Args:
        context: ResponseContext object containing all necessary information

    Returns:
        list[str]: The generated AI response messages

    Raises:
        Exception: If any step in the process fails
    """
    logger.info(f"Generating Telegram response for message in chat {context.chat_id}")

    try:
        # Run preprocessing
        preprocess_result = await run_preprocessing(context)

        # Handle bare &help fast path
        if preprocess_result.is_bare_help:
            help_text = preprocess_result.help_text

            # Store and deliver the help response
            await store_and_deliver_response(
                context,
                [help_text],  # type: ignore[arg-type]
                specialist_module=None
            )

            # Schedule background tasks
            # Note: original responses.py returned before memory management; we now
            # schedule it so the stored &help user message still transitions to PendingSummary.
            schedule_memory_management(context)

            logger.info(f"Stored AI response in database for chat {context.chat_id}")
            return [help_text]  # type: ignore[return-value]

        # Build context string for the agent
        context_str = _build_context_string(
            preprocess_result.summaries_str,
            preprocess_result.message_history_str,
            preprocess_result.message_content,
            preprocess_result.date_context_str,
            preprocess_result.module_name,
            preprocess_result.module_response,
            preprocess_result.unresolved_triggers,
        )

        # Get the agent response with enhanced context (retry on transient LLM errors)
        max_retries = 3
        talker_context = None  # Track for module attribution

        for attempt in range(max_retries):
            try:
                agent_start = time.monotonic()
                if preprocess_result.needs_onboarding:
                    logger.info(f"User {context.user_id} needs onboarding, using onboarding agent")
                    onboarding_agent = get_onboarding_agent()
                    onboarding_context = OnboardingContext(
                        convex_client=context.convex_client,
                        user_id=context.user_id,
                        telegram_id=context.telegram_id
                    )
                    result = await onboarding_agent.run(
                        context_str,
                        deps=onboarding_context,
                    )
                else:
                    amprChat_agent = get_amprChat_agent()
                    talker_context = TalkerContext(
                        convex_client=context.convex_client,
                        user_id=context.user_id,
                        date_context=preprocess_result.date_context_str,
                        invoked_modules=[preprocess_result.module_name] if preprocess_result.module_name else [],
                        module_already_invoked=preprocess_result.module_name is not None,
                        channel=context.channel,
                        telegram_id=context.telegram_id,
                        currency_context=preprocess_result.currency_context,
                    )
                    result = await amprChat_agent.run(
                        context_str,
                        deps=talker_context,
                    )
                agent_elapsed = round(time.monotonic() - agent_start, 2)  # type: ignore[possibly-unbound]
                logger.info(f"Agent run completed in {agent_elapsed}s (attempt {attempt + 1})")
                break  # Success, exit retry loop
            except Exception as agent_err:
                agent_elapsed = round(time.monotonic() - agent_start, 2)  # type: ignore[possibly-unbound]
                logger.warning(f"Agent run failed after {agent_elapsed}s (attempt {attempt + 1}): {agent_err}")
                err_str = str(agent_err).lower()
                is_transient = "503" in err_str or "overloaded" in err_str or "rate" in err_str
                if is_transient and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(f"Transient LLM error (attempt {attempt + 1}/{max_retries}), retrying in {wait}s: {agent_err}")
                    await asyncio.sleep(wait)
                else:
                    raise

        # Extract the output from the AgentRunResult
        agent_output: str = result.output  # type: ignore[possibly-unbound]
        # interim_messages is always a list (never None) due to the or [] in PreprocessingResult.__init__
        interim_msgs: list[str] = preprocess_result.interim_messages  # type: ignore[assignment]
        response_messages = interim_msgs + [agent_output]

        logger.info(f"Generated AI response: {response_messages}")

        # Determine specialist_module from invoked modules (for amprChat path)
        specialist_module = None
        if talker_context and talker_context.invoked_modules:
            specialist_module = talker_context.invoked_modules[0]  # Primary module
            logger.info(f"Response powered by module: {specialist_module}")

        # Store and deliver each message (includes Telegram-specific delivery)
        await store_and_deliver_response(
            context,
            response_messages,  # type: ignore[arg-type]
            specialist_module=specialist_module
        )

        # Schedule background tasks
        schedule_memory_management(context)

        # For post-onboarding users, watch for profile-relevant info
        if not preprocess_result.needs_onboarding:
            schedule_profile_watcher(context, context.message_content)

        return response_messages  # type: ignore[return-value]

    except Exception as e:
        logger.error(f"Error generating Telegram response: {str(e)}", exc_info=True)
        raise


def _build_context_string(
    summaries_str: str,
    message_history_str: str,
    message_content: str,
    date_context_str: Optional[str],
    module_name: Optional[str],
    module_response: Optional[str],
    unresolved_triggers: list[str],
) -> str:
    """
    Build the context string for the AI agent.

    Constructs the prompt context including summaries, message history,
    current message, date context, and module information.

    Args:
        summaries_str: Formatted summaries string
        message_history_str: JSON string of message history
        message_content: Current user message content
        date_context_str: Optional date context string
        module_name: Optional name of the invoked module
        module_response: Optional response from the invoked module
        unresolved_triggers: List of unresolved module triggers

    Returns:
        str: The complete context string for the agent
    """
    # Build date context section if available
    date_context_section = f"\n\n        {date_context_str}" if date_context_str else ""

    if module_response:
        # Build module-specific presentation instructions if available
        module_registry = get_module_registry()
        response_instructions = module_registry.get_response_instructions(module_name) if module_name else ""
        constraints = module_registry.get_constraints_for_module(module_name) if module_name else []
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
        {message_content}{date_context_section}

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
        {message_content}{date_context_section}
        {module_not_found_section}"""

    return context_str
