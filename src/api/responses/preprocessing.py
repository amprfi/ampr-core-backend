"""
Shared preprocessing for AI response generation.

This module contains the shared preprocessing logic that was previously
interleaved in the monolithic generate_ai_response function. It handles:
- Date-reference detection and date preprocessor task
- User message storage and chat auto-resolution
- Bare `&help` deterministic fast path
- `&help <question>` prefix stripping
- User/chat DB fetch
- Watchlist inference fire-and-forget
- Currency inference
- Profile ensure step
- Summary and recent-message context preparation
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from convex import ConvexClient

if TYPE_CHECKING:
    from src.modules.router import RoutingDecision
    from src.modules.registry import ModuleRegistry

from ...agents.date_preprocessor import get_date_preprocessor_agent, DatePreprocessorContext, has_date_references, DateContext
from ...agents.amprChat import build_help_overview
from ...agents.watchlist_inferrer import infer_watchlist
from ...agents.currency_inferrer import infer_display_currency
from ...modules.registry import get_module_registry
from .context import ResponseContext

logger = logging.getLogger(__name__)


class PreprocessingResult:
    """
    Result of the preprocessing phase.

    Contains all the data collected during preprocessing that will be used
    by the channel handlers to generate responses.
    
    For backward compatibility with the existing single-module flow,
    module_name and module_response refer to the primary (first) module
    when multiple modules are invoked. The router_decision field contains
    the full RoutingDecision for multi-module support.
    
    For multi-module support (AMPRFI-104):
    - modules: List of all module names that were invoked
    - module_responses: Dict mapping module names to their responses
    """
    def __init__(
        self,
        chat_id: Optional[str] = None,
        message_content: str = "",
        date_context_str: Optional[str] = None,
        user: Optional[dict] = None,
        chat_data: Optional[dict] = None,
        currency_context: str = "display_currency: USD",
        needs_onboarding: bool = False,
        summaries_str: str = "",
        message_history_str: str = "",
        is_bare_help: bool = False,
        help_text: Optional[str] = None,
        module_name: Optional[str] = None,
        module_response: Optional[str] = None,
        modules: Optional[list[str]] = None,
        module_responses: Optional[dict[str, str]] = None,
        interim_messages: Optional[list[str]] = None,
        unresolved_triggers: Optional[list[str]] = None,
        router_decision: Optional["RoutingDecision"] = None,
    ):
        self.chat_id = chat_id
        self.message_content = message_content
        self.date_context_str = date_context_str
        self.user = user
        self.chat_data = chat_data
        self.currency_context = currency_context
        self.needs_onboarding = needs_onboarding
        self.summaries_str = summaries_str
        self.message_history_str = message_history_str
        self.is_bare_help = is_bare_help
        self.help_text = help_text
        # Backward compatibility: single-module fields
        self.module_name = module_name
        self.module_response = module_response
        # Multi-module support
        self.modules: list[str] = modules or []
        self.module_responses: dict[str, str] = module_responses or {}
        self.interim_messages: list[str] = interim_messages or []
        self.unresolved_triggers: list[str] = unresolved_triggers or []
        self.router_decision = router_decision


async def run_preprocessing(context: ResponseContext) -> PreprocessingResult:
    """
    Run all shared preprocessing steps for AI response generation.

    This includes:
    - Date preprocessor (if date references detected)
    - User message storage
    - Chat auto-resolution
    - Bare &help fast path detection
    - &help prefix stripping
    - DB fetch (user and chat)
    - Watchlist inference (fire-and-forget)
    - Currency inference
    - Profile ensure
    - Summary and message history preparation
    - Module detection and invocation
    - Unresolved trigger detection

    Args:
        context: The ResponseContext containing message and user information

    Returns:
        PreprocessingResult with all collected data
    """
    logger.info(f"Starting preprocessing for {context.channel} message in chat {context.chat_id}")

    # --- PHASE 1: Kick off date preprocessor + store message concurrently ---

    # Start date preprocessor in background (don't await yet)
    date_task = None
    if has_date_references(context.message_content):
        logger.info("Date references detected, starting date preprocessor concurrently")
        date_preprocessor_agent = get_date_preprocessor_agent()
        date_preprocessor_context = DatePreprocessorContext()
        date_task = asyncio.create_task(
            date_preprocessor_agent.run(context.message_content, deps=date_preprocessor_context)
        )
    else:
        logger.info("No date references detected, skipping date preprocessor")

    # Store the user message (original content, before date enrichment)
    message_args: dict = {
        "userId": context.user_id,
        "role": "user",
        "channel": context.channel,
        "content": context.message_content,
    }

    created_message = await context.async_convex_client.mutation("messages:createMessage", message_args)

    # Get chat_id from created message if not provided (auto-created by createMessage)
    chat_id = context.chat_id or created_message["chat"]
    if not context.chat_id:
        context.chat_id = chat_id
        logger.info(f"Chat auto-created with ID: {chat_id}")

    logger.info(f"Stored user message in database for chat {chat_id}")

    # --- FAST PATH: bare &help ---
    # The help overview is fully deterministic (built from the in-memory
    # module registry + pyproject.toml metadata). Running it through the LLM
    # added ~25s of pure rewording latency and risked dropping the markdown
    # link. Short-circuit here: store, deliver, and return without any LLM
    # calls or downstream agent work.
    stripped_content = context.message_content.strip().lower()
    if stripped_content == "&help":
        logger.info("Bare &help detected, returning canonical help overview without LLM")
        help_text = build_help_overview()
        return PreprocessingResult(
            chat_id=chat_id,
            message_content=context.message_content,
            is_bare_help=True,
            help_text=help_text,
        )

    # --- PHASE 2: Immediately fire DB fetch + watchlist inference ---

    # Start DB fetch now (don't await — we'll collect results before step 6)
    db_fetch_task = asyncio.ensure_future(asyncio.gather(
        context.async_convex_client.query("users:getUser", {"userId": context.user_id}),
        context.async_convex_client.query("chats:getChat", {
            "userId": context.user_id,
            "chatId": chat_id
        }),
    ))

    # Fire-and-forget watchlist inference (non-blocking)
    asyncio.create_task(
        _infer_watchlist(context.convex_client, context.user_id, context.message_content)
    )

    # Start currency inference concurrently (awaited before agent runs).
    currency_task = asyncio.create_task(
        infer_display_currency(context.message_content, context.user_id, context.async_convex_client)
    )

    # Normalize &help prefix when followed by a real question.
    # Bare "&help" was already handled above by the FAST PATH and will not
    # reach this point. For "&help <rest>" we strip the prefix and let the
    # agent route the trailing question normally (e.g. to get_all_alerts,
    # get_user_watchlist, a specialist module, etc.).
    stripped = context.message_content.strip()
    if stripped.lower().startswith("&help "):
        context.message_content = stripped[len("&help "):].strip()
        logger.info("Detected &help prefix with trailing question; stripped prefix and preserved the rest")

    # --- PHASE 3: Await date preprocessor, then run module if triggered ---

    # Resolve date context before module invoke (modules may need it)
    date_context_str = None
    if date_task:
        date_preprocessor_result = await date_task
        date_context: DateContext = date_preprocessor_result.output
        date_context_str = date_context.to_context_string()
        logger.info(f"Date context: {date_context_str}")

    # Use the new unified router for module detection and routing
    from src.modules.router import route_to_modules, RoutingDecision
    
    module_registry = get_module_registry()
    
    # Get routing decision from the router
    routing_decision: RoutingDecision = route_to_modules(
        context.message_content,
        module_registry,
        enable_llm_classification=False  # For now, only use mention-based routing in preprocessing
    )
    
    # Multi-module support: invoke all detected modules concurrently
    modules = routing_decision.modules
    module_responses: dict[str, str] = {}
    
    # For backward compatibility, also set single-module fields
    module_name = modules[0] if modules else None
    module_response = None
    
    # For Telegram channel with multiple modules: short-circuit to avoid wasted invocations
    # Telegram will handle disambiguation separately
    if modules and context.channel == "telegram" and len(modules) > 1:
        logger.info(f"Multiple modules detected for Telegram channel: {modules}. "
                   "Skipping module invocation to avoid wasted calls; Telegram handler will disambiguate.")
        # Still populate modules list so Telegram handler can detect the case
        # module_responses remains empty dict
    elif modules:
        logger.info(f"Modules detected via router: {modules}, invoking all concurrently")
        
        # Send interim "working on it" messages for real-time channels
        for module_name_iter in modules:
            await _send_interim_message(context, module_name_iter, module_registry)
        
        # Invoke all modules concurrently
        module_tasks = []
        for module_name_iter in modules:
            task = asyncio.create_task(
                _invoke_module_with_error_handling(
                    module_registry,
                    module_name_iter,
                    context.message_content,
                    date_context_str,
                    context.user_id
                )
            )
            module_tasks.append(task)
        
        # Wait for all modules to complete
        module_results = await asyncio.gather(*module_tasks, return_exceptions=True)
        
        # Process results
        for module_name_iter, result in zip(modules, module_results):
            if isinstance(result, Exception):
                error_msg = f"Module '{module_name_iter}' failed: {str(result)}"
                logger.error(error_msg, exc_info=True)
                module_responses[module_name_iter] = f"ERROR: {error_msg}"
            else:
                module_responses[module_name_iter] = result
                logger.info(f"Module '{module_name_iter}' returned response")
        
        # For backward compatibility, set single-module fields to first module
        if modules:
            module_name = modules[0]
            module_response = module_responses.get(modules[0])
    
    # Use unresolved triggers from the router
    interim_messages = []
    unresolved_triggers = routing_decision.unresolved_triggers
    
    if unresolved_triggers:
        triggers_list = ", ".join(unresolved_triggers)
        not_found_text = f"The module {triggers_list} could not be found. I'll still try to answer your question."
        await _send_interim_message(context, text=not_found_text)
        interim_messages.append(not_found_text)

    # --- PHASE 4: Await DB fetch results (should already be complete by now) ---

    user, chat_data = await db_fetch_task
    needs_onboarding = user and not user.get("onboarding_complete")

    # Ensure the user has a profile (auto-creates with defaults if missing).
    # Awaits so that any subsequent tool call reading the profile will find it.
    if user:
        try:
            await context.async_convex_client.mutation(
                "profiles:ensureProfile",
                {"userId": context.user_id},
            )
        except Exception as e:
            logger.warning(f"ensureProfile failed for user {context.user_id}: {e}")

    # Process Summaries (Oldest to Newest)
    summaries_list = []
    if chat_data.get("summaries"):
        for summary in chat_data["summaries"]:
            range_start_ms = summary["range_start"]
            range_end_ms = summary["range_end"]
            range_start_iso = datetime.fromtimestamp(range_start_ms / 1000).isoformat()
            range_end_iso = datetime.fromtimestamp(range_end_ms / 1000).isoformat()
            summaries_list.append(f"<summary range='{range_start_iso} to {range_end_iso}'>{summary['content']}</summary>")

    summaries_str = "\n".join(summaries_list)

    # Process Recent Messages (Oldest to Newest)
    message_history = []
    recent_messages = chat_data.get("recent_messages", [])

    for message in recent_messages:
        timestamp_iso = datetime.fromtimestamp(message["_creationTime"] / 1000).isoformat() if message.get("_creationTime") else None
        message_history.append({
            "role": message["role"],
            "content": message["content"],
            "timestamp": timestamp_iso
        })

    # Convert to JSON string for context
    message_history_str = json.dumps(message_history)

    # Await currency inference (should already be complete by now)
    currency_context = await currency_task

    return PreprocessingResult(
        chat_id=chat_id,
        message_content=context.message_content,
        date_context_str=date_context_str,
        user=user,
        chat_data=chat_data,
        currency_context=currency_context,
        needs_onboarding=needs_onboarding,
        summaries_str=summaries_str,
        message_history_str=message_history_str,
        is_bare_help=False,
        module_name=module_name,
        module_response=module_response,
        modules=modules,
        module_responses=module_responses,
        interim_messages=interim_messages,
        unresolved_triggers=unresolved_triggers,
        router_decision=routing_decision,
    )


async def _invoke_module_with_error_handling(
    module_registry: "ModuleRegistry",
    module_name: str,
    message_content: str,
    date_context: Optional[str],
    user_id: str
) -> str:
    """
    Invoke a single module with error handling.
    
    This helper is used by the multi-module concurrent invocation to 
    run each module independently with proper error handling.
    
    Args:
        module_registry: The module registry
        module_name: Name of the module to invoke
        message_content: The user message to process
        date_context: Optional resolved date context
        user_id: The user ID to forward to the module
        
    Returns:
        The module response string
        
    Raises:
        Exception: If module invocation fails (will be caught by caller)
    """
    return await module_registry.invoke_module(
        module_name,
        message_content,
        date_context=date_context,
        user_id=user_id,
    )


async def _send_interim_message(context: ResponseContext, module_name: Optional[str] = None, module_registry=None, text: Optional[str] = None) -> None:
    """
    Send an interim message to the user.
    Non-blocking — errors are logged but never propagated.

    Either provide `text` directly, or `module_name` + `module_registry` to build
    a "working on it" message for a specialist module.
    """
    try:
        if text is None:
            if module_registry is None:
                # Fallback if registry is not provided
                display_name = f"&{module_name}" if module_name else "module"
            else:
                # Build a user-friendly display name for the module
                meta = module_registry.metadata.get(module_name, {})
                display_name = meta.get("trigger", f"&{module_name}").lstrip("&")

                # For lens modules, extract the specific lens name (e.g., "Proof-of-Words")
                if module_name == "lens":
                    match = re.search(r"&lens:(\S+)", context.message_content)
                    if match:
                        display_name = match.group(1)

            text = f"**{display_name}** 🔍 is working on this..."

        if context.channel == "telegram" and context.telegram_id:
            from ...clients.telegram_client import TelegramClient
            telegram_client = TelegramClient()
            await telegram_client.send_message(
                chat_id=int(context.telegram_id),
                text=text
            )
            await telegram_client.close()
            logger.info(f"Sent interim message to Telegram {context.telegram_id}: {text}")
        else:
            logger.info(f"Interim message (non-Telegram channel '{context.channel}'): {text}")
    except Exception as e:
        logger.warning(f"Failed to send interim message: {e}")


async def _infer_watchlist(convex_client: ConvexClient, user_id: str, message: str):
    """
    Run watchlist inference to detect asset mentions in the user's message.
    Fire-and-forget — errors are logged but never propagated.
    """
    try:
        logger.info(f"Watchlist inferrer starting for user {user_id}: {message!r}")
        result = await infer_watchlist(convex_client, user_id, message)
        logger.info(f"Watchlist inferrer completed for user {user_id}: {result}")
    except Exception as e:
        logger.error(f"Watchlist inference failed for user {user_id}: {str(e)}", exc_info=True)
