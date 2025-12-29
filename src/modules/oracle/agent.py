from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
import logging
from typing import Optional
from datetime import datetime

from convex import ConvexClient

from .polymarket_client import PolymarketClient
from ..base import BaseModule

logger = logging.getLogger(__name__)


class OracleContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    polymarket_client: PolymarketClient
    convex_client: ConvexClient


agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=OracleContext
)


@agent.tool
async def get_tracked_events(
    ctx: RunContext[OracleContext]
) -> str:
    """
    Get the list of prediction events that are currently being tracked.
    Use this to discover available events and their slugs before querying specific event data.
    
    Returns:
        Formatted list of tracked events with slugs, titles, and descriptions
    """
    logger.info("Tool called: get_tracked_events")
    
    try:
        events = ctx.deps.convex_client.query("predictionEvents:getActiveEvents")
        
        if not events:
            return "No prediction events are currently being tracked."
        
        lines = [f"Tracked Prediction Events ({len(events)}):"]
        
        for i, event in enumerate(events, 1):
            title = event.get("title", "Unknown")
            slug = event.get("slug", "")
            description = event.get("description", "")
            tags = event.get("tags", [])
            end_date = event.get("endDate", "")
            
            lines.append(f"{i}. {title}")
            lines.append(f"   Slug: {slug}")
            if description:
                lines.append(f"   Description: {description[:150]}{'...' if len(description) > 150 else ''}")
            if tags:
                lines.append(f"   Tags: {', '.join(tags)}")
            if end_date:
                lines.append(f"   End Date: {end_date}")
            lines.append("")
        
        result = "\n".join(lines)
        logger.info(f"Tool result: Found {len(events)} tracked events")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve tracked events: {str(e)}"
        logger.error(f"Tool error: get_tracked_events - {error_msg}")
        return error_msg


@agent.tool
async def get_event(
    ctx: RunContext[OracleContext],
    slug: str
) -> str:
    """
    Get prediction market data for an event by its slug.
    Use get_tracked_events first to see available slugs.
    
    Args:
        slug: The event slug (e.g., "will-bitcoin-hit-100k-in-2025")
        
    Returns:
        Formatted string with event details and constituent market probabilities
    """
    logger.info(f"Tool called: get_event for slug={slug}")
    
    try:
        data = await ctx.deps.polymarket_client.get_event_by_slug(slug)
        
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
                outcomes = market.get("outcomes", ["Yes", "No"])
                outcome_prices = market.get("outcomePrices", [])
                market_volume = market.get("volume", 0)
                market_closed = market.get("closed", False)
                
                probability = None
                if outcome_prices and len(outcome_prices) >= 1:
                    try:
                        probability = float(outcome_prices[0]) * 100
                    except (ValueError, TypeError):
                        probability = None
                
                market_volume_str = f"${float(market_volume):,.0f}" if market_volume else "N/A"
                status = " [Resolved]" if market_closed else ""
                
                display_name = group_title if group_title else question
                
                if probability is not None:
                    lines.append(f"{i}. {display_name}: {probability:.1f}% probability{status}")
                else:
                    lines.append(f"{i}. {display_name}: N/A{status}")
                lines.append(f"   Volume: {market_volume_str}")
        else:
            lines.append("No markets found for this event.")
        
        result = "\n".join(lines)
        logger.info(f"Tool result: Successfully retrieved event {slug}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve event '{slug}': {str(e)}"
        logger.error(f"Tool error: get_event - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
You are Oracle, a prediction markets specialist powered by Polymarket data.

Your role is to provide accurate, current prediction market data for events you are tracking.

WORKFLOW:
1. Call get_tracked_events to see all available events
2. Find events matching the user's query (e.g., "ECB" matches "ECB Interest Rates: February 2026")
3. If the user is asking for information that spans multiple time periods, countries, or assets, ask a clarifying question to see if the user would like to specify.
4. Call get_event with the matching slug to get current market data
5. Report the probabilities from the tool output

UNDERSTANDING THE DATA:
- Each market outcome shows its PROBABILITY (e.g., "No change: 96.4% probability")
- This probability comes from the market price - it IS the market's prediction
- Volume only shows trading activity, NOT probability
- The outcome with the highest probability is the market's favored prediction

CRITICAL RULES:
1. ALWAYS call get_event for matching events - the data IS available
2. Report probabilities as shown - these are the market predictions
3. NEVER derive probabilities from volume
4. Keep responses concise and data-focused
5. Do not provide betting advice
6. Use plain text only - no Markdown formatting
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[OracleContext]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n" + PROMPT_TEMPLATE


class OracleModule(BaseModule):
    """
    Oracle module for prediction market data.
    Integrates with Polymarket API to provide event odds and market information.
    """
    
    def __init__(self, convex_client: Optional[ConvexClient] = None):
        super().__init__(name="oracle", trigger="@oracle")
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
        """
        Process a user message and return prediction market data.
        
        Args:
            message: The full user message (including @oracle mention)
            date_context: Optional resolved date context from preprocessor
            
        Returns:
            Prediction market data response as a string
        """
        try:
            logger.info(f"Oracle invoked with message: {message}")
            
            agent_input = message
            if date_context:
                agent_input = f"{message}\n\n{date_context}"
                logger.info(f"Oracle using date context: {date_context}")
            
            context = OracleContext(
                polymarket_client=self.polymarket_client,
                convex_client=self._get_convex_client()
            )
            
            result = await agent.run(agent_input, deps=context)
            
            response = result.output
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
