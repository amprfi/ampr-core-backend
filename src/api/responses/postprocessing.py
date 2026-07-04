"""
Shared post-processing and delivery helpers for AI response generation.

This module contains the shared post-processing logic for:
- Assistant message storage
- Telegram paragraph chunking and delivery
- Memory-management background task scheduling
- Profile-watcher background task scheduling
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Sequence

from ...agents.extractor import get_extractor_agent, HORIZON_MAP, KNOWLEDGE_MAP
from ...agents.summarizer import get_summarizer_agent
from ...clients.async_convex_client import AsyncConvexClient, get_async_client
from .context import ResponseContext

logger = logging.getLogger(__name__)


async def store_and_deliver_response(
    context: ResponseContext,
    response_messages: Sequence[str],
    specialist_module: Optional[str] = None,
) -> None:
    """
    Store and deliver each response message.

    For each message in the response:
    - Store the assistant's response in the database
    - For Telegram responses, split on paragraph breaks and send each as a separate message

    Args:
        context: The ResponseContext containing channel and user information
        response_messages: List of response message strings to store and deliver
        specialist_module: Optional module name that powered the response (for attribution)
    """
    logger.info(f"Storing and delivering {len(response_messages)} response messages")

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
            from ...clients.telegram_client import TelegramClient
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


def schedule_memory_management(context: ResponseContext) -> None:
    """
    Schedule memory management background task.

    Runs in background so the user gets their response immediately.
    Manages the chat memory lifecycle:
    1. Updates message statuses (Current -> PendingSummary)
    2. Checks if enough PendingSummary messages exist to trigger summarization
    3. Runs summarizer agent if needed
    4. Runs extractor agent to extract user profile information
    5. Creates summary and archives messages

    Args:
        context: The ResponseContext containing chat and user information
    """
    asyncio.create_task(
        _manage_chat_memory(context.async_convex_client, context.chat_id, context.user_id)
    )


def schedule_profile_watcher(context: ResponseContext, message: str) -> None:
    """
    Schedule profile watcher background task.

    For post-onboarding users, watches for profile-relevant info in each message.
    Runs as fire-and-forget background task.

    Args:
        context: The ResponseContext containing user and channel information
        message: The user message to analyze for profile-relevant information
    """
    asyncio.create_task(
        _watch_profile(context, message)
    )


async def _manage_chat_memory(async_client: AsyncConvexClient, chat_id: Optional[str], user_id: str) -> None:
    """
    Manages the chat memory lifecycle (runs as fire-and-forget background task):
    1. Updates message statuses (Current -> PendingSummary)
    2. Checks if enough PendingSummary messages exist to trigger summarization
    3. Runs summarizer agent if needed
    4. Runs extractor agent to extract user profile information
    5. Creates summary and archives messages
    """
    try:
        if chat_id is None:
            logger.warning("chat_id is None in _manage_chat_memory, skipping")
            return

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

            for msg in messages_to_summarize:
                ts_ms = msg.get("_creationTime")
                ts = datetime.fromtimestamp(ts_ms / 1000).isoformat() if ts_ms else "UNKNOWN"
                text_lines.append(f"[{ts}] {msg['role'].upper()}: {msg['content']}")
                message_ids.append(msg["_id"])

            conversation_text = "\n".join(text_lines)

            # Run Summarizer and Extractor agents in parallel
            summarizer_agent = get_summarizer_agent()
            extractor_agent = get_extractor_agent()

            summary_content, extracted_profile = await asyncio.gather(
                summarizer_agent.run(
                    f"Please summarize these messages:\n\n{conversation_text}"
                ),
                extractor_agent.run(
                    f"Extract user profile information from these messages:\n\n{conversation_text}",
                    convex_client=get_async_client(),
                    user_id=user_id
                ),
            )

            logger.info(f"Generated summary for chat {chat_id}: {summary_content[:50]}...")
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


async def _update_extracted_country(async_client: AsyncConvexClient, user_id: str, country_name: str) -> None:
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

        extracted = await extractor_agent.run(
            f"Extract user profile information from this single message. Only extract fields where the user clearly reveals personal information about themselves:\n\n{message}",
            convex_client=context.async_convex_client,
            user_id=context.user_id
        )

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
            from ...clients.telegram_client import TelegramClient
            telegram_client = TelegramClient()
            await telegram_client.send_message(
                chat_id=int(context.telegram_id),
                text=suggestion_text
            )
            await telegram_client.close()

    except Exception as e:
        logger.error(f"Profile watcher failed for user {context.user_id}: {str(e)}", exc_info=True)
