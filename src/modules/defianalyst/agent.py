from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
import logging
from typing import Optional
from datetime import datetime

from .coingecko_client import CoinGeckoClient
from ..base import BaseModule

logger = logging.getLogger(__name__)


class DeFiAnalystContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    coingecko_client: CoinGeckoClient


agent = Agent(
    "mistral:mistral-medium",
    deps_type=DeFiAnalystContext
)


@agent.tool
async def get_coin_price_and_market_data(
    ctx: RunContext[DeFiAnalystContext],
    coin_id: str,
    date: Optional[str] = None
) -> str:
    """
    Get price and market capitalization data for a cryptocurrency.
    
    Args:
        coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum", "solana")
        date: Optional date in dd-mm-yyyy format. If not provided, uses today's data.
        
    Returns:
        Formatted string with price and market cap data
    """
    logger.info(f"Tool called: get_coin_price_and_market_data for {coin_id}, date={date}")
    
    try:
        if date:
            data = await ctx.deps.coingecko_client.get_coin_history(coin_id, date)
        else:
            data = await ctx.deps.coingecko_client.get_current_price(coin_id)
        
        market_data = data.get("market_data", {})
        current_price = market_data.get("current_price", {})
        market_cap = market_data.get("market_cap", {})
        total_volume = market_data.get("total_volume", {})
        
        price_usd = current_price.get("usd", "N/A")
        mcap_usd = market_cap.get("usd", "N/A")
        volume_usd = total_volume.get("usd", "N/A")
        
        coin_name = data.get("name", coin_id)
        coin_symbol = data.get("symbol", "").upper()
        
        result = f"{coin_name} ({coin_symbol}):\n"
        result += f"Price: ${price_usd:,.2f}\n" if isinstance(price_usd, (int, float)) else f"Price: {price_usd}\n"
        result += f"Market Cap: ${mcap_usd:,.0f}\n" if isinstance(mcap_usd, (int, float)) else f"Market Cap: {mcap_usd}\n"
        result += f"24h Volume: ${volume_usd:,.0f}" if isinstance(volume_usd, (int, float)) else f"24h Volume: {volume_usd}"
        
        if date:
            result += f"\n(Data from {date})"
        
        logger.info(f"Tool result: Successfully retrieved data for {coin_id}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve data for {coin_id}: {str(e)}"
        logger.error(f"Tool error: get_coin_price_and_market_data - {error_msg}")
        return error_msg


@agent.tool
async def search_coin_by_name_or_symbol(
    ctx: RunContext[DeFiAnalystContext],
    query: str
) -> str:
    """
    Search for a cryptocurrency by name or symbol to find its CoinGecko ID.
    Use this when the user mentions a coin but you're unsure of the exact CoinGecko coin ID.
    
    Args:
        query: Coin name or symbol to search for (e.g., "bitcoin", "BTC", "ethereum")
        
    Returns:
        String containing matching coin IDs and names
    """
    logger.info(f"Tool called: search_coin_by_name_or_symbol for query='{query}'")
    
    try:
        coins_list = await ctx.deps.coingecko_client.get_coins_list()
        
        query_lower = query.lower()
        exact_matches = []
        partial_matches = []
        
        for coin in coins_list:
            coin_id = coin.get("id", "").lower()
            coin_symbol = coin.get("symbol", "").lower()
            coin_name = coin.get("name", "").lower()
            
            # Prioritize exact matches
            if (query_lower == coin_id or 
                query_lower == coin_symbol or 
                query_lower == coin_name):
                exact_matches.append(coin)
            # Then collect partial matches
            elif (query_lower in coin_id or 
                  query_lower in coin_symbol or 
                  query_lower in coin_name):
                partial_matches.append(coin)
                if len(partial_matches) >= 20:
                    break
        
        # Combine results: exact matches first, then partials
        matches = exact_matches + partial_matches
        
        if not matches:
            return f"No coins found matching '{query}'"
        
        # Display top 5 results
        result = f"Found {len(matches)} match(es):\n"
        for coin in matches[:5]:
            result += f"- {coin.get('name')} ({coin.get('symbol', '').upper()}): ID = {coin.get('id')}\n"
        
        logger.info(f"Tool result: Found {len(exact_matches)} exact + {len(partial_matches)} partial matches for '{query}'")
        return result
        
    except Exception as e:
        error_msg = f"Failed to search for coin '{query}': {str(e)}"
        logger.error(f"Tool error: search_coin_by_name_or_symbol - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
You are DeFi Analyst, a cryptocurrency market data specialist powered by CoinGecko.

Your role is to provide accurate, current price and market capitalization data for cryptocurrencies.

CAPABILITIES:
- Get current price, market cap, and 24h volume for any cryptocurrency
- Get historical data for specific dates (within last 365 days on demo plan)
- Search for coins by name or symbol to find the correct CoinGecko ID

IMPORTANT GUIDELINES:
1. Use search_coin_by_name_or_symbol first if you're unsure of the exact coin ID
2. Common coin IDs: bitcoin, ethereum, solana, cardano, polkadot, avalanche-2, etc.
3. Always provide data in clear, formatted responses with proper currency formatting
4. If data is unavailable or an error occurs, clearly state the issue
5. Keep responses concise and data-focused
6. Do not provide investment advice or speculation about future prices

When answering questions, focus solely on providing the requested market data.
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[DeFiAnalystContext]) -> str:
    return PROMPT_TEMPLATE


class DeFiAnalystModule(BaseModule):
    """
    DeFi Analyst module for cryptocurrency market data analysis.
    Integrates with CoinGecko API to provide price and market cap information.
    """
    
    def __init__(self):
        super().__init__(name="defianalyst", trigger="@defianalyst")
        self.coingecko_client = CoinGeckoClient()
    
    async def invoke(self, message: str) -> str:
        """
        Process a user message and return cryptocurrency market data.
        
        Args:
            message: The full user message (including @defianalyst mention)
            
        Returns:
            Market data response as a string
        """
        try:
            logger.info(f"DeFiAnalyst invoked with message: {message}")
            
            context = DeFiAnalystContext(coingecko_client=self.coingecko_client)
            
            result = await agent.run(message, deps=context)
            
            response = result.output
            logger.info(f"DeFiAnalyst response: {response}")
            
            return response
            
        except Exception as e:
            error_msg = f"DeFi Analyst error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)
    
    async def close(self):
        """Clean up resources."""
        await self.coingecko_client.close()


def get_defianalyst_module() -> DeFiAnalystModule:
    """Factory function to create a DeFiAnalyst module instance."""
    return DeFiAnalystModule()
