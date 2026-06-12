"""
Shared response handler for AI responses to both SMS and chat messages.

This module provides a unified interface for generating AI responses and handling
the storage and delivery of those responses across different channels (SMS, chat).
"""

import asyncio
import logging
import re
from typing import Optional, Sequence, Union
from convex import ConvexClient
import json

from ..agents.amprChat import get_amprChat_agent, TalkerContext, build_help_overview
from ..agents.summarizer import get_summarizer_agent, SummarizerContext
from ..agents.extractor import get_extractor_agent, ExtractorContext, HORIZON_MAP, KNOWLEDGE_MAP
from ..agents.date_preprocessor import get_date_preprocessor_agent, DatePreprocessorContext, has_date_references, DateContext
from ..agents.onboarding import get_onboarding_agent, OnboardingContext
from ..agents.watchlist_inferrer import infer_watchlist
from ..agents.currency_inferrer import infer_display_currency
from ..modules.registry import get_module_registry
from ..clients.async_convex_client import AsyncConvexClient, get_async_client

# Set up logging
logger = logging.getLogger(__name__)

class ResponseContext:
    """
    Context object for generating AI responses.

    Attributes:
        message_content: The content of the user's message
        chat_id: The ID of the chat (optional, will be auto-created if None)
        channel: The channel (telegram, app, web, rest, execution)
        user_id: The ID of the user
        convex_client: Sync Convex client (legacy, used by agents that still need it)
        async_convex_client: Async Convex client for non-blocking DB calls
        telegram_id: Optional Telegram chat ID for Telegram responses
    """
    def __init__(
        self,
        message_content: str,
        chat_id: Optional[str],
        channel: str,
        user_id: str,
        convex_client: ConvexClient,
        telegram_id: Optional[str] = None
    ):
        self.message_content = message_content
        self.chat_id = chat_id
        self.channel = channel
        self.user_id = user_id
        self.convex_client = convex_client
        self.async_convex_client = get_async_client()
        self.telegram_id = telegram_id

async def generate_ai_response(context: ResponseContext) -> Sequence[str]:
    """
    Generate an AI response and handle storage and delivery.

    Args:
        context: ResponseContext object containing all necessary information

    Returns:
        list[str]: The generated AI response messages

    Raises:
        Exception: If any step in the process fails
    """
    try:
        logger.info(f"Generating AI response for {context.channel} message in chat {context.chat_id}")

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
        if not context.chat_id:
            context.chat_id = created_message["chat"]
            logger.info(f"Chat auto-created with ID: {context.chat_id}")

        logger.info(f"Stored user message in database for chat {context.chat_id}")

        # --- FAST PATH: bare &help ---
        # The help overview is fully deterministic (built from the in-memory
        # module registry + pyproject.toml metadata). Running it through the LLM
        # added ~25s of pure rewording latency and risked dropping the markdown
        # link. Short-circuit here: store, deliver, and return without any LLM
        # calls or downstream agent work.
        if context.message_content.strip().lower() == "&help":
            logger.info("Bare &help detected, returning canonical help overview without LLM")
            help_text = build_help_overview()

            await context.async_convex_client.mutation(
                "messages:createMessage",
                {
                    "userId": context.user_id,
                    "role": "assistant",
                    "channel": context.channel,
                    "content": help_text,
                },
            )

            if context.channel == "telegram" and context.telegram_id:
                from ..clients.telegram_client import TelegramClient
                telegram_client = TelegramClient()
                # Match the chunking used elsewhere — one message per paragraph break.
                telegram_chunks = [c.strip() for c in help_text.split("\n\n") if c.strip()]
                for chunk in telegram_chunks:
                    await telegram_client.send_message(chat_id=int(context.telegram_id), text=chunk)
                await telegram_client.close()

            logger.info(f"Stored AI response in database for chat {context.chat_id}")
            return [help_text]

        # --- PHASE 2: Immediately fire DB fetch + watchlist inference ---

        # Start DB fetch now (don't await — we'll collect results before step 6)
        db_fetch_task = asyncio.ensure_future(asyncio.gather(
            context.async_convex_client.query("users:getUser", {"userId": context.user_id}),
            context.async_convex_client.query("chats:getChat", {
                "userId": context.user_id,
                "chatId": context.chat_id
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

        # Check for module triggers
        module_registry = get_module_registry()
        module_name = module_registry.detect_module_trigger(context.message_content)
        module_response = None

        if module_name:
            logger.info(f"Module '{module_name}' detected, invoking module")

            # Send interim "working on it" message for real-time channels
            await _send_interim_message(context, module_name, module_registry)

            try:
                module_response = await module_registry.invoke_module(
                    module_name,
                    context.message_content,
                    date_context=date_context_str
                )
                logger.info(f"Module '{module_name}' returned response")
            except Exception as e:
                error_msg = f"Module '{module_name}' failed: {str(e)}"
                logger.error(error_msg, exc_info=True)
                module_response = f"ERROR: {error_msg}"

        # Detect unresolved module triggers (e.g., &lens, &foo — patterns not matched by any registered module)
        interim_messages = []
        mentioned_triggers = re.findall(r'&(\w+)', context.message_content)
        unresolved_triggers = [
            f"&{mention}" for mention in mentioned_triggers
            if f"&{mention}" not in module_registry.triggers
        ]

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
                from datetime import datetime
                range_start_iso = datetime.fromtimestamp(range_start_ms / 1000).isoformat()
                range_end_iso = datetime.fromtimestamp(range_end_ms / 1000).isoformat()
                summaries_list.append(f"<summary range='{range_start_iso} to {range_end_iso}'>{summary['content']}</summary>")

        summaries_str = "\n".join(summaries_list)

        # Process Recent Messages (Oldest to Newest)
        message_history = []
        recent_messages = chat_data.get("recent_messages", [])

        for message in recent_messages:
            from datetime import datetime
            timestamp_iso = datetime.fromtimestamp(message["_creationTime"] / 1000).isoformat() if message.get("_creationTime") else None
            message_history.append({
                "role": message["role"],
                "content": message["content"],
                "timestamp": timestamp_iso
            })

        # Convert to JSON string for context
        message_history_str = json.dumps(message_history)

        # Build date context section if available
        date_context_section = f"\n\n        {date_context_str}" if date_context_str else ""

        # Create a context string that includes summaries, message history and the current message
        if module_response:
            # Build module-specific presentation instructions if available
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
        {context.message_content}{date_context_section}

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
        {context.message_content}{date_context_section}
        {module_not_found_section}"""

        # Await currency inference (should already be complete by now)
        currency_context = await currency_task

        # Get the agent response with enhanced context (retry on transient LLM errors)
        import time
        max_retries = 3
        talker_context = None  # Track for module attribution
        for attempt in range(max_retries):
            try:
                agent_start = time.monotonic()
                if needs_onboarding:
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
                        date_context=date_context_str,
                        invoked_modules=[module_name] if module_name else [],
                        module_already_invoked=module_name is not None,
                        channel=context.channel,
                        telegram_id=context.telegram_id,
                        currency_context=currency_context,
                    )
                    result = await amprChat_agent.run(
                        context_str,
                        deps=talker_context,
                    )
                agent_elapsed = round(time.monotonic() - agent_start, 2)
                logger.info(f"Agent run completed in {agent_elapsed}s (attempt {attempt + 1})")
                break  # Success, exit retry loop
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

        # Extract the output from the AgentRunResult
        agent_output: str = result.output
        response_messages = interim_messages + [agent_output]

        logger.info(f"Generated AI response: {response_messages}")

        # Determine specialist_module from invoked modules (for amprChat path)
        specialist_module = None
        if talker_context and talker_context.invoked_modules:
            specialist_module = talker_context.invoked_modules[0]  # Primary module
            logger.info(f"Response powered by module: {specialist_module}")

        # Store and send each message
        for response_content in response_messages:
            # Store the assistant's response in the database
            message_data: dict = {
                "userId": context.user_id,
                "role": "assistant",
                "channel": context.channel,
                "content": response_content
            }
            if specialist_module:
                message_data["specialist_module"] = specialist_module

            await context.async_convex_client.mutation("messages:createMessage", message_data)

            # For Telegram responses, split on paragraph breaks and send each as a separate message
            if context.channel == "telegram" and context.telegram_id:
                from ..clients.telegram_client import TelegramClient
                telegram_client = TelegramClient()
                
                # Split on double newlines to keep bullet lists and paragraphs intact
                telegram_chunks = [chunk.strip() for chunk in response_content.split("\n\n") if chunk.strip()]
                
                for chunk in telegram_chunks:
                    telegram_result = await telegram_client.send_message(
                        chat_id=int(context.telegram_id),
                        text=chunk
                    )
                    if telegram_result:
                        logger.info(f"Successfully sent Telegram chunk to {context.telegram_id}")
                    else:
                        logger.error(f"Failed to send Telegram chunk to {context.telegram_id}")
                
                await telegram_client.close()

        logger.info(f"Stored AI response in database for chat {context.chat_id}")

        # --- MEMORY MANAGEMENT (fire-and-forget) ---
        # Run in background so the user gets their response immediately
        asyncio.create_task(
            _manage_chat_memory(context.async_convex_client, context.chat_id, context.user_id)
        )

        # --- PROFILE WATCHER (fire-and-forget) ---
        # For post-onboarding users, watch for profile-relevant info in each message
        if not needs_onboarding:
            asyncio.create_task(
                _watch_profile(context, context.message_content)
            )

        return response_messages

    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}", exc_info=True)
        raise

async def _send_interim_message(context: ResponseContext, module_name: str = None, module_registry=None, text: str = None) -> None:
    """
    Send an interim message to the user.
    Non-blocking — errors are logged but never propagated.

    Either provide `text` directly, or `module_name` + `module_registry` to build
    a "working on it" message for a specialist module.
    """
    try:
        if text is None:
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
            from ..clients.telegram_client import TelegramClient
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


async def _manage_chat_memory(async_client: AsyncConvexClient, chat_id: str, user_id: str):
    """
    Manages the chat memory lifecycle (runs as fire-and-forget background task):
    1. Updates message statuses (Current -> PendingSummary)
    2. Checks if enough PendingSummary messages exist to trigger summarization
    3. Runs summarizer agent if needed
    4. Runs extractor agent to extract user profile information
    5. Creates summary and archives messages
    """
    try:
        # Step 1: Update message statuses and get pending count
        pending_count = await async_client.mutation("messages:updateMessageStatus", {
            "chatId": chat_id
        })

        logger.info(f"Memory Management: Chat {chat_id} has {pending_count} pending messages.")

        # Step 2: Trigger Summarization if threshold met
        if pending_count >= 20:
            logger.info(f"Triggering summarization for chat {chat_id}")

            # Fetch the messages to summarize
            messages_to_summarize = await async_client.query("messages:getMessagesToSummarize", {
                "chatId": chat_id
            })

            if not messages_to_summarize:
                logger.warning("Pending count was high but no messages returned for summarization.")
                return

            # Prepare content for summarizer
            text_lines = []
            message_ids = []

            # Capture time range
            start_msg = messages_to_summarize[0]
            end_msg = messages_to_summarize[-1]

            if not start_msg.get("_creationTime") or not end_msg.get("_creationTime"):
                logger.error(f"Messages missing _creationTime, skipping summarization for chat {chat_id}")
                return

            range_start = start_msg["_creationTime"]
            range_end = end_msg["_creationTime"]

            from datetime import datetime
            for msg in messages_to_summarize:
                ts_ms = msg.get("_creationTime")
                ts = datetime.fromtimestamp(ts_ms / 1000).isoformat() if ts_ms else "UNKNOWN"
                text_lines.append(f"[{ts}] {msg['role'].upper()}: {msg['content']}")
                message_ids.append(msg["_id"])

            conversation_text = "\n".join(text_lines)

            # Run Summarizer and Extractor agents in parallel
            summarizer_agent = get_summarizer_agent()
            summarizer_ctx = SummarizerContext()

            extractor_agent = get_extractor_agent()
            extractor_ctx = ExtractorContext(
                convex_client=get_async_client(),
                user_id=user_id
            )

            summary_result, extraction_result = await asyncio.gather(
                summarizer_agent.run(
                    f"Please summarize these messages:\n\n{conversation_text}",
                    deps=summarizer_ctx
                ),
                extractor_agent.run(
                    f"Extract user profile information from these messages:\n\n{conversation_text}",
                    deps=extractor_ctx
                ),
            )

            summary_content = summary_result.output
            logger.info(f"Generated summary for chat {chat_id}: {summary_content[:50]}...")

            extracted_profile = extraction_result.output
            logger.info(f"Extracted profile data for user {user_id}")

            # Update user profile if any non-null values were extracted
            has_updates = any([
                extracted_profile.inferred_investment_horizon is not None,
                extracted_profile.inferred_risk_appetite is not None,
                extracted_profile.inferred_investment_knowledge is not None,
                extracted_profile.inferred_financial_goals is not None,
                extracted_profile.inferred_investment_thesis is not None,
                extracted_profile.preferred_currency is not None,
            ])

            if has_updates:
                update_data = {}
                if extracted_profile.inferred_investment_horizon is not None:
                    horizon = HORIZON_MAP.get(extracted_profile.inferred_investment_horizon)
                    if horizon:
                        update_data["inferred_investment_horizon"] = horizon
                    else:
                        logger.warning(f"Unknown investment horizon value: {extracted_profile.inferred_investment_horizon}")
                if extracted_profile.inferred_risk_appetite is not None:
                    update_data["inferred_risk_appetite"] = extracted_profile.inferred_risk_appetite
                if extracted_profile.inferred_investment_knowledge is not None:
                    knowledge = KNOWLEDGE_MAP.get(extracted_profile.inferred_investment_knowledge)
                    if knowledge:
                        update_data["inferred_investment_knowledge"] = knowledge
                    else:
                        logger.warning(f"Unknown investment knowledge value: {extracted_profile.inferred_investment_knowledge}")
                if extracted_profile.inferred_financial_goals is not None:
                    update_data["inferred_financial_goals"] = extracted_profile.inferred_financial_goals
                if extracted_profile.inferred_investment_thesis is not None:
                    update_data["inferred_investment_thesis"] = extracted_profile.inferred_investment_thesis
                if extracted_profile.preferred_currency is not None:
                    update_data["preferred_currency"] = extracted_profile.preferred_currency.upper()

                await async_client.mutation("profiles:updateProfile", {
                    "user": user_id,
                    **update_data
                })
                logger.info(f"Updated user profile for user {user_id} with extracted data")
            else:
                logger.info(f"No profile updates extracted for user {user_id}")

            # Handle country extraction (requires country lookup)
            if extracted_profile.country_name:
                await _update_extracted_country(async_client, user_id, extracted_profile.country_name)

            # Handle contact info extraction (update user record)
            contact_updates = {}
            if extracted_profile.email:
                contact_updates["email"] = extracted_profile.email
            if extracted_profile.phone:
                contact_updates["phone"] = extracted_profile.phone
            if contact_updates:
                await async_client.mutation("users:updateUser", {
                    "id": user_id,
                    **contact_updates
                })
                logger.info(f"Updated user contact info for user {user_id}: {list(contact_updates.keys())}")

            # Save Summary and Archive Messages
            await async_client.mutation("messages:createSummaryAndArchive", {
                "chatId": chat_id,
                "content": summary_content,
                "range_start": range_start,
                "range_end": range_end,
                "messageIds": message_ids
            })

            logger.info(f"Successfully archived {len(message_ids)} messages for chat {chat_id}")

    except Exception as e:
        # Log but don't fail — this runs as a background task
        logger.error(f"Error in memory management for chat {chat_id}: {str(e)}", exc_info=True)


async def _update_extracted_country(async_client: AsyncConvexClient, user_id: str, country_name: str):
    """
    Look up a country by name or code and update the user's profile.
    Used by both the memory management extractor and the profile watcher.
    """
    try:
        # Try by code first
        country = await async_client.query("countries:getCountryByCode", {
            "country_code": country_name.upper()
        })

        if not country:
            all_countries = await async_client.query("countries:getCountries", {})
            for c in all_countries:
                if country_name.lower() in c["country_name"].lower():
                    country = c
                    break

        if country:
            await async_client.mutation("profiles:updateProfile", {
                "user": user_id,
                "country": country["_id"]
            })
            logger.info(f"Updated country for user {user_id} to {country['country_name']}")
        else:
            logger.warning(f"Could not find country '{country_name}' for user {user_id}")
    except Exception as e:
        logger.error(f"Error updating extracted country for user {user_id}: {str(e)}", exc_info=True)


async def _watch_profile(context: ResponseContext, message: str):
    """
    Run the extractor on a single message to detect profile-relevant information.
    If detected, send a follow-up suggestion message to the user (non-blocking).
    Only runs for post-onboarding users.
    """
    try:
        extractor_agent = get_extractor_agent()
        extractor_ctx = ExtractorContext(
            convex_client=context.async_convex_client,
            user_id=context.user_id
        )

        result = await extractor_agent.run(
            f"Extract user profile information from this single message. Only extract fields where the user clearly reveals personal information about themselves:\n\n{message}",
            deps=extractor_ctx
        )

        extracted = result.output

        # Skip if no watchable fields were detected
        if not any([extracted.country_name, extracted.preferred_currency, extracted.email, extracted.phone]):
            return

        # Fetch current profile and user data to compare against stored values
        current_profile = await context.async_convex_client.query(
            "profiles:getProfileByUser", {"userId": context.user_id}
        )
        current_user = await context.async_convex_client.query(
            "users:getUser", {"userId": context.user_id}
        )

        # Only suggest updates for fields that differ from what's already stored
        suggestions = []
        if extracted.preferred_currency:
            current_currency = (current_profile or {}).get("preferred_currency", "") or ""
            if extracted.preferred_currency.upper() != current_currency.upper():
                suggestions.append(f"your preferred currency to {extracted.preferred_currency.upper()}")
        if extracted.country_name:
            current_country_data = await context.async_convex_client.query(
                "profiles:getUserCountry", {"userId": context.user_id}
            )
            current_country = (current_country_data or {}).get("country")
            current_country_name = (current_country or {}).get("country_name", "") or ""
            if extracted.country_name.lower() != current_country_name.lower():
                suggestions.append(f"your country to {extracted.country_name}")
        if extracted.email:
            current_email = (current_user or {}).get("email", "") or ""
            if extracted.email.lower() != current_email.lower():
                suggestions.append(f"your email to {extracted.email}")
        if extracted.phone:
            current_phone = (current_user or {}).get("phone", "") or ""
            if extracted.phone != current_phone:
                suggestions.append(f"your phone number to {extracted.phone}")

        if not suggestions:
            return

        # Build the suggestion message
        if len(suggestions) == 1:
            suggestion_text = f"By the way, would you like me to update {suggestions[0]} on your profile?"
        else:
            items = ", ".join(suggestions[:-1]) + f" and {suggestions[-1]}"
            suggestion_text = f"By the way, would you like me to update {items} on your profile?"

        logger.info(f"Profile watcher detected updates for user {context.user_id}: {suggestions}")

        # Store the suggestion as an assistant message
        await context.async_convex_client.mutation("messages:createMessage", {
            "userId": context.user_id,
            "role": "assistant",
            "channel": context.channel,
            "content": suggestion_text
        })

        # Send via Telegram if applicable
        if context.channel == "telegram" and context.telegram_id:
            from ..clients.telegram_client import TelegramClient
            telegram_client = TelegramClient()
            await telegram_client.send_message(
                chat_id=int(context.telegram_id),
                text=suggestion_text
            )
            await telegram_client.close()

    except Exception as e:
        logger.error(f"Profile watcher failed for user {context.user_id}: {str(e)}", exc_info=True)
