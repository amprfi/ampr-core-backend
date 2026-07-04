"""
Web channel handler for AI response generation.

This module handles the web-specific response generation flow,
including multi-module parallel response support (AMPRFI-104).
"""

import asyncio
import logging
import time

from ...agents.amprChat import get_amprChat_agent, TalkerContext
from ...agents.onboarding import get_onboarding_agent, OnboardingContext
from ...modules.registry import get_module_registry
from .context import ResponseContext
from .preprocessing import run_preprocessing
from .postprocessing import store_and_deliver_response, schedule_memory_management, schedule_profile_watcher
from .context_builder import build_context_string
from .synthesis_context import build_module_synthesis_context
from src.models.chat_message import GeneratedResponseMessage

logger = logging.getLogger(__name__)


async def generate_web_response(context: ResponseContext) -> list[GeneratedResponseMessage]:
    """
    Generate an AI response for web channel messages.

    This handler supports multi-module parallel response generation (AMPRFI-104):
    - For multiple modules: invoke modules concurrently, synthesize each independently
      with cross-module awareness, store each as separate message with attribution
    - For single module: same behavior as before
    - For zero modules: fall through to general amprChat

    Args:
        context: ResponseContext object containing all necessary information

    Returns:
        list[GeneratedResponseMessage]: The generated AI response messages with attribution

    Raises:
        Exception: If any step in the process fails
    """
    logger.info(f"Generating web response for message in chat {context.chat_id}")

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
            return [GeneratedResponseMessage(content=help_text)]

        # Multi-module support: handle different cases based on number of modules
        module_registry = get_module_registry()
        modules = preprocess_result.modules or []
        module_responses = preprocess_result.module_responses or {}

        # Generate attributed responses
        if len(modules) > 1:
            # Multi-module case: synthesize each module response independently with cross-module awareness
            logger.info(f"Multi-module response: {len(modules)} modules detected: {modules}")
            attributed_responses = await _synthesize_multi_module_response(
                context, preprocess_result, module_registry, modules, module_responses
            )
        elif len(modules) == 1:
            # Single-module case: preserve existing behavior but return attributed
            logger.info(f"Single-module response: module '{modules[0]}'")
            attributed_responses = await _synthesize_single_module_response(
                context, preprocess_result, module_registry
            )
        else:
            # Zero-module case: fall through to general amprChat
            logger.info("Zero-module response: falling through to general amprChat")
            attributed_responses = await _synthesize_general_response(
                context, preprocess_result, module_registry
            )

        logger.info(f"Generated AI response: {len(attributed_responses)} attributed messages")

        # Store each attributed response with proper specialist_module
        for attributed_msg in attributed_responses:
            await store_and_deliver_response(
                context,
                [attributed_msg.content],
                specialist_module=attributed_msg.specialist_module
            )

        # Schedule background tasks
        schedule_memory_management(context)

        # For post-onboarding users, watch for profile-relevant info
        if not preprocess_result.needs_onboarding:
            schedule_profile_watcher(context, context.message_content)

        # Return the attributed messages directly
        return attributed_responses

    except Exception as e:
        logger.error(f"Error generating web response: {str(e)}", exc_info=True)
        raise


async def _synthesize_multi_module_response(
    context: ResponseContext,
    preprocess_result,
    module_registry,
    modules: list[str],
    module_responses: dict[str, str]
) -> list[GeneratedResponseMessage]:
    """
    Synthesize responses for multiple modules concurrently.

    Each module's result is synthesized independently with awareness of other responding modules
    to reduce duplication. All synthesis calls run concurrently.

    Args:
        context: ResponseContext object
        preprocess_result: PreprocessingResult with all collected data
        module_registry: ModuleRegistry instance
        modules: List of module names that responded
        module_responses: Dict mapping module names to their responses

    Returns:
        list[GeneratedResponseMessage]: List of synthesized attributed responses
    """
    logger.info(f"Synthesizing responses for {len(modules)} modules: {modules}")

    # Create synthesis tasks for each module
    synthesis_tasks = []

    for module_name in modules:
        module_response = module_responses.get(module_name, "")

        # Build cross-module awareness context per-module
        other_modules = [m for m in modules if m != module_name]
        other_module_names = [module_registry.metadata.get(m, {}).get("trigger", f"&{m}") for m in other_modules]
        cross_module_context = f"Other responding modules: {', '.join(other_module_names)}" if other_modules else ""

        # Build module-specific context for synthesis
        synthesis_context = build_module_synthesis_context(
            preprocess_result, module_registry, module_name, module_response,
            cross_module_context
        )

        task = asyncio.create_task(
            _synthesize_module_response(
                context, preprocess_result, module_registry, module_name,
                synthesis_context
            )
        )
        synthesis_tasks.append(task)

    # Run all synthesis concurrently and preserve order
    # Use return_exceptions=True to tolerate per-module synthesis failures
    synthesis_results_raw = await asyncio.gather(*synthesis_tasks, return_exceptions=True)

    # Process results: if a synthesis failed, use the raw module response as fallback
    synthesis_results = []
    for module_name, result in zip(modules, synthesis_results_raw):
        if isinstance(result, Exception):
            logger.warning(f"Synthesis failed for module '{module_name}': {result}")
            # Use raw module response as fallback
            synthesis_results.append(module_responses.get(module_name, ""))
        else:
            synthesis_results.append(result)

    # Convert results to GeneratedResponseMessage objects with attribution
    attributed_results = []
    for module_name, result_content in zip(modules, synthesis_results):
        attributed_results.append(GeneratedResponseMessage(
            content=result_content,
            specialist_module=module_name
        ))

    # Combine with interim messages (only once at the beginning)
    # Interim messages don't have module attribution
    interim_msgs = preprocess_result.interim_messages or []
    interim_attributed = [GeneratedResponseMessage(content=msg, specialist_module=None) for msg in interim_msgs]
    response_messages = interim_attributed + attributed_results

    return response_messages


async def _synthesize_single_module_response(
    context: ResponseContext,
    preprocess_result,
    module_registry
) -> list[GeneratedResponseMessage]:
    """
    Synthesize response for single module case (preserves existing behavior).

    Args:
        context: ResponseContext object
        preprocess_result: PreprocessingResult with all collected data
        module_registry: ModuleRegistry instance

    Returns:
        list[GeneratedResponseMessage]: List of attributed response messages
    """
    # Build context string for the agent using shared builder
    context_str = build_context_string(
        preprocess_result.summaries_str,
        preprocess_result.message_history_str,
        preprocess_result.message_content,
        preprocess_result.date_context_str,
        preprocess_result.currency_context,
        preprocess_result.module_name,
        preprocess_result.module_response,
        preprocess_result.unresolved_triggers,
        registry=module_registry,
    )

    # Get the agent response with enhanced context (retry on transient LLM errors)
    result_content = await _get_agent_response(
        context, preprocess_result, context_str,
        invoked_modules=[preprocess_result.module_name] if preprocess_result.module_name else []
    )

    # Extract the output from the AgentRunResult
    agent_output: str = result_content
    interim_msgs: list[str] = preprocess_result.interim_messages or []
    response_messages = interim_msgs + [agent_output]

    # Convert to GeneratedResponseMessage objects
    # For single-module, all messages get the same attribution (the single module)
    module_name = preprocess_result.module_name
    attributed_messages = [
        GeneratedResponseMessage(content=msg, specialist_module=(module_name if i > 0 else None))
        for i, msg in enumerate(response_messages)
    ]
    return attributed_messages


async def _synthesize_general_response(
    context: ResponseContext,
    preprocess_result,
    module_registry
) -> list[GeneratedResponseMessage]:
    """
    Synthesize response for zero-module case (general amprChat).

    Args:
        context: ResponseContext object
        preprocess_result: PreprocessingResult with all collected data
        module_registry: ModuleRegistry instance

    Returns:
        list[GeneratedResponseMessage]: List of attributed response messages
    """
    # Build context string without module response
    context_str = build_context_string(
        preprocess_result.summaries_str,
        preprocess_result.message_history_str,
        preprocess_result.message_content,
        preprocess_result.date_context_str,
        preprocess_result.currency_context,
        None,  # No module name
        None,  # No module response
        preprocess_result.unresolved_triggers,
        registry=module_registry,
    )

    # Get the agent response with enhanced context
    result_content = await _get_agent_response(
        context, preprocess_result, context_str, invoked_modules=[]
    )

    # Extract the output from the AgentRunResult
    agent_output: str = result_content
    interim_msgs: list[str] = preprocess_result.interim_messages or []
    response_messages = interim_msgs + [agent_output]

    # Convert to GeneratedResponseMessage objects (no specialist_module for general chat)
    attributed_messages = [GeneratedResponseMessage(content=msg, specialist_module=None) for msg in response_messages]
    return attributed_messages


async def _get_agent_response(
    context: ResponseContext,
    preprocess_result,
    context_str: str,
    invoked_modules: list[str]
) -> str:
    """
    Get agent response with retry logic for transient LLM errors.

    Args:
        context: ResponseContext object
        preprocess_result: PreprocessingResult with all collected data
        context_str: The context string for the agent
        invoked_modules: List of invoked module names for TalkerContext

    Returns:
        str: The agent output
    """
    max_retries = 3

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
                    invoked_modules=invoked_modules,
                    channel=context.channel,
                    telegram_id=context.telegram_id,
                )
                result = await amprChat_agent.run(
                    context_str,
                    deps=talker_context,
                )
            agent_elapsed = round(time.monotonic() - agent_start, 2)
            logger.info(f"Agent run completed in {agent_elapsed}s (attempt {attempt + 1})")
            return result.output

        except Exception as agent_err:
            agent_elapsed = round(time.monotonic() - agent_start, 2)
            logger.warning(f"Agent run failed after {agent_elapsed}s (attempt {attempt + 1}): {agent_err}")
            err_str = str(agent_err).lower()
            is_transient = "503" in err_str or "overloaded" in err_str or "rate" in err_str
            if is_transient and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                logger.warning(f"Transient LLM error (attempt {attempt + 1}/{max_retries}), retrying in {wait}s: {agent_err}")
                await asyncio.sleep(wait)
            else:
                raise


# Use shared synthesis context builder (AMPRFI-114: avoid code duplication)
# The function is now in synthesis_context.py for use by both web.py and streaming.py


async def _synthesize_module_response(
    context: ResponseContext,
    preprocess_result,
    module_registry,
    module_name: str,
    synthesis_context: str
) -> str:
    """
    Synthesize a single module's response using the appropriate agent.

    Routes through _get_agent_response to respect onboarding status,
    ensuring multi-module web synthesis is consistent with single/zero-module paths.

    Args:
        context: ResponseContext object
        preprocess_result: PreprocessingResult with all collected data
        module_registry: ModuleRegistry instance
        module_name: The module name being synthesized
        synthesis_context: The context string for this module

    Returns:
        str: Synthesized response for this module
    """
    # Use the same agent selection logic as single/zero-module paths
    # to ensure onboarding consistency
    return await _get_agent_response(
        context, preprocess_result, synthesis_context,
        invoked_modules=[module_name]
    )
