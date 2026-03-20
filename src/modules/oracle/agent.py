import httpx
import json
import logging
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from convex import ConvexClient

from .polymarket_client import PolymarketClient
from ..base import BaseModule

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = "mistral-small-latest"

PROMPT_TEMPLATE = (Path(__file__).parent / "prompt.md").read_text()

# Tool JSON schemas (equivalent to what pydantic-ai auto-generated from docstrings)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": (
                "Search for prediction events by keyword query. "
                "Returns up to 10 matching active events with their slugs. "
                "Use this to find relevant events before fetching detailed market data with get_event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": 'Search terms (e.g., "bitcoin", "ECB interest rates", "gold price")',
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event",
            "description": (
                "Get prediction market data for an event by its slug. "
                "Use search_events first to find relevant events and their slugs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": 'The event slug (e.g., "will-bitcoin-hit-100k-in-2025")',
                    }
                },
                "required": ["slug"],
            },
        },
    },
]


async def _call_mistral(
    messages: list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    """Call the Mistral chat completions API directly via httpx."""
    body: dict = {
        "model": MODEL,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            MISTRAL_API_URL,
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


# ── Tool implementations (same logic as before, without pydantic-ai wrappers) ──


async def _exec_search_events(convex_client: ConvexClient, query: str) -> str:
    """Search for prediction events by keyword query."""
    logger.info(f"Tool called: search_events with query='{query}'")

    try:
        events = convex_client.query(
            "predictionEvents:searchEvents",
            {"query": query, "limit": 10},
        )

        if not events:
            return f"No active prediction events found matching '{query}'."

        lines = [f"Search Results for '{query}' ({len(events)} found):"]

        for i, event in enumerate(events, 1):
            title = event.get("title", "Unknown")
            slug = event.get("slug", "")
            description = event.get("description", "")
            end_date = event.get("endDate", "")
            tags = event.get("tags", [])

            lines.append(f"{i}. {title}")
            lines.append(f"   Slug: {slug}")
            if end_date:
                lines.append(f"   End Date: {end_date[:10]}")
            if description:
                lines.append(f"   Description: {description[:150]}{'...' if len(description) > 150 else ''}")
            if tags:
                lines.append(f"   Tags: {', '.join(tags)}")
            lines.append("")

        result = "\n".join(lines)
        logger.info(f"Tool result: Found {len(events)} events for query '{query}'")
        return result

    except Exception as e:
        error_msg = f"Failed to search events: {str(e)}"
        logger.error(f"Tool error: search_events - {error_msg}")
        return error_msg


async def _exec_get_event(polymarket_client: PolymarketClient, slug: str) -> str:
    """Get prediction market data for an event by its slug."""
    logger.info(f"Tool called: get_event for slug={slug}")

    try:
        data = await polymarket_client.get_event_by_slug(slug)

        title = data.get("title", "Unknown Event")
        description = data.get("description", "")
        end_date = data.get("endDate", "Unknown")
        closed = data.get("closed", False)
        total_liquidity = data.get("liquidity", 0)
        total_volume = data.get("volume", 0)

        if end_date and len(end_date) >= 10:
            end_date = end_date[:10]

        liquidity_str = f"${float(total_liquidity):,.0f}" if total_liquidity else "N/A"
        volume_str = f"${float(total_volume):,.0f}" if total_volume else "N/A"

        lines = [
            f"Event: {title}",
            f"Status: {'Resolved' if closed else 'Active'}",
            f"End Date: {end_date}",
            f"Total Liquidity: {liquidity_str}",
            f"Total Volume: {volume_str}",
        ]

        if description:
            lines.append(f"Description: {description[:200]}{'...' if len(description) > 200 else ''}")

        markets = data.get("markets", [])
        if markets:
            lines.append("")
            lines.append(f"Markets ({len(markets)}):")

            for i, market in enumerate(markets, 1):
                group_title = market.get("groupItemTitle", "")
                question = market.get("question", "Unknown")
                outcome_prices = market.get("outcomePrices", [])
                market_volume = market.get("volume", 0)
                market_closed = market.get("closed", False)
                open_interest = market.get("openInterest", 0)
                one_day_change = market.get("oneDayPriceChange", None)
                one_week_change = market.get("oneWeekPriceChange", None)
                one_month_change = market.get("oneMonthPriceChange", None)

                probability = None
                if outcome_prices and len(outcome_prices) >= 1:
                    try:
                        probability = float(outcome_prices[0]) * 100
                    except (ValueError, TypeError):
                        probability = None

                market_volume_str = f"${float(market_volume):,.0f}" if market_volume else "N/A"
                open_interest_str = f"${float(open_interest):,.0f}" if open_interest else "N/A"
                status = " [Resolved]" if market_closed else ""

                display_name = group_title if group_title else question

                if probability is not None:
                    lines.append(f"{i}. {display_name}: {probability:.1f}% probability{status}")
                else:
                    lines.append(f"{i}. {display_name}: N/A{status}")
                lines.append(f"   Volume: {market_volume_str} | Open Interest: {open_interest_str}")

                changes = []
                if one_day_change is not None:
                    try:
                        changes.append(f"1D: {float(one_day_change):+.1%}")
                    except (ValueError, TypeError):
                        pass
                if one_week_change is not None:
                    try:
                        changes.append(f"1W: {float(one_week_change):+.1%}")
                    except (ValueError, TypeError):
                        pass
                if one_month_change is not None:
                    try:
                        changes.append(f"1M: {float(one_month_change):+.1%}")
                    except (ValueError, TypeError):
                        pass
                if changes:
                    lines.append(f"   Price Change: {' | '.join(changes)}")
        else:
            lines.append("No markets found for this event.")

        result = "\n".join(lines)
        logger.info(f"Tool result: Successfully retrieved event {slug}")
        return result

    except Exception as e:
        error_msg = f"Failed to retrieve event '{slug}': {str(e)}"
        logger.error(f"Tool error: get_event - {error_msg}")
        return error_msg


# ── Tool dispatch ──

TOOL_DISPATCH = {
    "search_events": lambda ctx, args: _exec_search_events(ctx["convex_client"], **args),
    "get_event": lambda ctx, args: _exec_get_event(ctx["polymarket_client"], **args),
}


async def _run_oracle_agent(
    user_input: str,
    convex_client: ConvexClient,
    polymarket_client: PolymarketClient,
) -> str:
    """
    Run the Oracle agent loop using the Mistral API directly.

    Step 1 (search): mistral-small-latest, no reasoning — fast keyword extraction
    Step 2 (select + fetch): mistral-small-latest, reasoning_effort="high" — accurate slug selection
    No final synthesis step — amprChat handles the conversational wrapping.
    """
    today = datetime.now().strftime("%B %d, %Y")
    system_prompt = f"Today's date is {today}.\n\n" + PROMPT_TEMPLATE

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    tool_ctx = {
        "convex_client": convex_client,
        "polymarket_client": polymarket_client,
    }

    # First iteration: no reasoning (fast keyword extraction for search_events)
    # Subsequent iterations: reasoning enabled (accurate slug selection from results)
    max_iterations = 10
    for iteration in range(max_iterations):
        reasoning = "high" if iteration > 0 else None

        response = await _call_mistral(messages, tools=TOOLS, reasoning_effort=reasoning)
        choice = response["choices"][0]
        assistant_msg = choice["message"]

        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls")
        if not tool_calls:
            return assistant_msg.get("content", "")

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"])

            handler = TOOL_DISPATCH.get(fn_name)
            if handler:
                result = await handler(tool_ctx, fn_args)
            else:
                result = f"ERROR: Unknown tool '{fn_name}'"

            messages.append({
                "role": "tool",
                "name": fn_name,
                "content": result,
                "tool_call_id": tc["id"],
            })

    return "Oracle could not resolve the request after multiple tool calls."


# ── Module class (public interface unchanged) ──


class OracleModule(BaseModule):
    """
    Oracle module for prediction market data.
    Integrates with Polymarket API to provide event odds and market information.
    """

    def __init__(self, convex_client: Optional[ConvexClient] = None):
        super().__init__(name="oracle", trigger="&oracle")
        self.polymarket_client = PolymarketClient()
        self._convex_client_instance = convex_client

    def _get_convex_client(self) -> ConvexClient:
        if self._convex_client_instance:
            return self._convex_client_instance
        if self._convex_client:
            return self._convex_client
        from ...clients.convex_client import get_client
        return get_client()

    async def invoke(self, message: str, date_context: Optional[str] = None) -> str:
        try:
            logger.info(f"Oracle invoked with message: {message}")

            agent_input = message
            if date_context:
                agent_input = f"{message}\n\n{date_context}"
                logger.info(f"Oracle using date context: {date_context}")

            response = await _run_oracle_agent(
                agent_input,
                convex_client=self._get_convex_client(),
                polymarket_client=self.polymarket_client,
            )

            logger.info(f"Oracle response: {response}")
            return response

        except Exception as e:
            error_msg = f"Oracle error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    async def close(self):
        """Clean up resources."""
        await self.polymarket_client.close()


def get_oracle_module(convex_client: Optional[ConvexClient] = None) -> OracleModule:
    """Factory function to create an Oracle module instance."""
    return OracleModule(convex_client=convex_client)
