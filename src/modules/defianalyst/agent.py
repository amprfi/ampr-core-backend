from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
import logging
from typing import Optional
from datetime import datetime

from .coingecko_client import CoinGeckoClient
from ..base import BaseModule
from . import utils

logger = logging.getLogger(__name__)


class DeFiAnalystContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    coingecko_client: CoinGeckoClient


agent = Agent(
    "mistral:mistral-large-latest",
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
        
        price_str = f"${price_usd:,.2f}" if isinstance(price_usd, (int, float)) else str(price_usd)
        mcap_str = f"${mcap_usd:,.0f}" if isinstance(mcap_usd, (int, float)) else str(mcap_usd)
        volume_str = f"${volume_usd:,.0f}" if isinstance(volume_usd, (int, float)) else str(volume_usd)
        
        result = f"{coin_name} ({coin_symbol}) is trading at {price_str} with a market cap of {mcap_str} and 24h volume of {volume_str}"
        
        if date:
            result += f" (data from {date})"
        else:
            result += "."
        
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
        
        # Split query on common separators to handle formats like "Scroll, SCR" or "BTC/Bitcoin"
        import re
        query_terms = [term.strip().lower() for term in re.split(r'[,/\s]+', query) if term.strip()]
        
        exact_matches = []
        partial_matches = []
        
        for coin in coins_list:
            coin_id = coin.get("id", "").lower()
            coin_symbol = coin.get("symbol", "").lower()
            coin_name = coin.get("name", "").lower()
            
            # Check if any query term matches
            for query_term in query_terms:
                # Prioritize exact matches
                if (query_term == coin_id or 
                    query_term == coin_symbol or 
                    query_term == coin_name):
                    if coin not in exact_matches:
                        exact_matches.append(coin)
                    break
                # Then collect partial matches
                elif (query_term in coin_id or 
                      query_term in coin_symbol or 
                      query_term in coin_name):
                    if coin not in partial_matches and coin not in exact_matches:
                        partial_matches.append(coin)
                    if len(partial_matches) >= 20:
                        break
        
        # Combine results: exact matches first, then partials
        matches = exact_matches + partial_matches
        
        if not matches:
            return f"No coins found matching '{query}'"
        
        # Display top 5 results
        result = f"Found {len(matches)} match(es): "
        coin_strs = [f"{coin.get('name')} ({coin.get('symbol', '').upper()}) with ID {coin.get('id')}" for coin in matches[:5]]
        result += ", ".join(coin_strs) + "."
        
        logger.info(f"Tool result: Found {len(exact_matches)} exact + {len(partial_matches)} partial matches for '{query}'")
        return result
        
    except Exception as e:
        error_msg = f"Failed to search for coin '{query}': {str(e)}"
        logger.error(f"Tool error: search_coin_by_name_or_symbol - {error_msg}")
        return error_msg


@agent.tool
async def get_top_performing_coins(
    ctx: RunContext[DeFiAnalystContext],
    timeframe: str = "7d",
    top_n: int = 5,
    direction: str = "gainers",
    top_coins: str = "500"
) -> str:
    """
    Get top performing (gainers or losers) cryptocurrencies by timeframe.
    
    Args:
        timeframe: Time period (1h, 24h, 7d, 14d, 30d, 60d, 1y)
        top_n: Number of results to display (default 5, max 30)
        direction: "gainers" for best performers, "losers" for worst
        top_coins: Market cap scope to search within (300, 500, 1000, all). Default: 500
        
    Returns:
        Formatted string with coin rankings and performance data
    """
    logger.info(f"Tool called: get_top_performing_coins, timeframe={timeframe}, n={top_n}, direction={direction}, top_coins={top_coins}")
    
    try:
        # Validate timeframe
        valid_timeframes = ["1h", "24h", "7d", "14d", "30d", "60d", "1y"]
        if timeframe not in valid_timeframes:
            return f"Invalid timeframe '{timeframe}'. Valid options: {', '.join(valid_timeframes)}"
        
        # Validate top_coins
        valid_top_coins = ["300", "500", "1000", "all"]
        if top_coins not in valid_top_coins:
            return f"Invalid top_coins '{top_coins}'. Valid options: {', '.join(valid_top_coins)}"
        
        # Validate top_n
        if top_n < 1 or top_n > 30:
            return "Invalid top_n. Must be between 1 and 30."
        
        # Fetch top gainers and losers using Pro API endpoint
        data = await ctx.deps.coingecko_client.get_top_gainers_losers(
            vs_currency="usd",
            duration=timeframe,
            top_coins=top_coins
        )
        
        # Extract the appropriate list based on direction
        if direction == "gainers":
            coins = data.get("top_gainers", [])
        elif direction == "losers":
            coins = data.get("top_losers", [])
        else:
            return f"Invalid direction '{direction}'. Valid options: gainers, losers"
        
        if not coins:
            return "No coins found"
        
        # Take top N results (avoid shadowing top_coins parameter)
        selected_coins = coins[:top_n]
        
        # Format response as ordered list with percentage changes
        lines = [f"Top {top_n} {direction} over {timeframe}:"]
        
        for i, coin in enumerate(selected_coins, 1):
            name = coin.get("name", "Unknown")
            symbol = coin.get("symbol", "").upper()
            price = coin.get("price", coin.get("current_price", 0))
            change = coin.get("price_change_percentage", 0)
            market_cap_rank = coin.get("market_cap_rank", "N/A")
            
            price_str = f"${price:,.2f}" if price >= 0.01 else f"${price:.6f}"
            change_str = f"{change:+.2f}%"
            rank_str = f"#{market_cap_rank}" if market_cap_rank != "N/A" else "N/A"
            
            lines.append(f"{i}. {name} ({symbol}): {price_str}, Change: {change_str}, Rank: {rank_str}")
        
        result = "\n".join(lines)
        
        logger.info(f"Tool result: Successfully retrieved top {top_n} {direction} for {timeframe}")
        return result
        
    except NotImplementedError:
        error_msg = "Pro API required for top_gainers_losers endpoint. Upgrade CoinGecko API plan to use this feature."
        logger.warning(f"Tool error: get_top_performing_coins - {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Failed to retrieve top performing coins: {str(e)}"
        logger.error(f"Tool error: get_top_performing_coins - {error_msg}")
        return error_msg


@agent.tool
async def compare_coin_performance(
    ctx: RunContext[DeFiAnalystContext],
    coin_ids: str,
    start_date: str,
    end_date: Optional[str] = None
) -> str:
    """
    Compare price performance of multiple cryptocurrencies between two dates.
    
    Args:
        coin_ids: Comma-separated list of CoinGecko IDs (e.g., "bitcoin,ethereum,solana")
        start_date: Start date in dd-mm-yyyy format (e.g., "01-01-2024")
        end_date: End date in dd-mm-yyyy format. If not provided, uses current price.
        
    Returns:
        Formatted comparison with start/end prices and percentage changes for each coin
    """
    logger.info(f"Tool called: compare_coin_performance, coins={coin_ids}, start={start_date}, end={end_date}")
    
    try:
        # Split and clean coin IDs
        coin_id_list = [cid.strip() for cid in coin_ids.split(",") if cid.strip()]
        
        if not coin_id_list:
            return "No valid coin IDs provided"
        
        if len(coin_id_list) > 10:
            return "Too many coins specified. Maximum 10 coins for comparison."
        
        comparisons = []
        
        # Fetch historical data for each coin
        for coin_id in coin_id_list:
            try:
                # Get start date snapshot
                start_data = await ctx.deps.coingecko_client.get_coin_history(
                    coin_id=coin_id,
                    date=start_date
                )
                
                start_market_data = start_data.get("market_data", {})
                start_price = start_market_data.get("current_price", {}).get("usd")
                
                if start_price is None:
                    raise ValueError(f"No price data available for {coin_id} on {start_date}")
                
                # Get end date snapshot or current price
                if end_date:
                    end_data = await ctx.deps.coingecko_client.get_coin_history(
                        coin_id=coin_id,
                        date=end_date
                    )
                    end_market_data = end_data.get("market_data", {})
                    end_price = end_market_data.get("current_price", {}).get("usd")
                    actual_end_date = end_date
                else:
                    end_data = await ctx.deps.coingecko_client.get_current_price(coin_id)
                    end_market_data = end_data.get("market_data", {})
                    end_price = end_market_data.get("current_price", {}).get("usd")
                    actual_end_date = datetime.now().strftime("%d-%m-%Y")
                
                if end_price is None:
                    raise ValueError(f"No price data available for {coin_id} on {actual_end_date}")
                
                # Calculate changes
                absolute_change, percentage_change = utils.calculate_price_change(start_price, end_price)
                
                # Get coin metadata
                coin_name = start_data.get("name", coin_id)
                coin_symbol = start_data.get("symbol", "")
                
                comparisons.append({
                    "coin_id": coin_id,
                    "name": coin_name,
                    "symbol": coin_symbol,
                    "start_price": start_price,
                    "end_price": end_price,
                    "start_date": start_date,
                    "end_date": actual_end_date,
                    "absolute_change": absolute_change,
                    "percentage_change": percentage_change
                })
                
            except Exception as e:
                logger.warning(f"Failed to fetch data for {coin_id}: {str(e)}")
                comparisons.append({
                    "coin_id": coin_id,
                    "name": coin_id,
                    "symbol": "",
                    "error": str(e)
                })
        
        # Format the comparison
        result = utils.format_comparison_summary(comparisons)
        
        logger.info(f"Tool result: Successfully compared {len(comparisons)} coins")
        return result
        
    except Exception as e:
        error_msg = f"Failed to compare coin performance: {str(e)}"
        logger.error(f"Tool error: compare_coin_performance - {error_msg}")
        return error_msg


@agent.tool
async def get_coins_by_market_cap(
    ctx: RunContext[DeFiAnalystContext],
    top_n: int = 10,
    vs_currency: str = "usd"
) -> str:
    """
    Get top cryptocurrencies ranked by current market capitalization.
    
    Args:
        top_n: Number of results to return (default 10, max 250)
        vs_currency: Target currency (default "usd")
        
    Returns:
        Formatted ranking with coin names, symbols, market caps, and prices
    """
    logger.info(f"Tool called: get_coins_by_market_cap, n={top_n}, currency={vs_currency}")
    
    try:
        # Validate top_n
        if top_n < 3 or top_n > 20:
            return "Invalid top_n. Must be between 3 and 20."
        
        # Fetch market data sorted by market cap
        coins = await ctx.deps.coingecko_client.get_coins_markets(
            vs_currency=vs_currency,
            order="market_cap_desc",
            per_page=top_n,
            page=1
        )
        
        # Filter by minimum volume ($50k)
        coins = utils.filter_by_min_volume(coins, min_volume=50000)
        
        if not coins:
            return "No coins found matching criteria"
        
        # Take top N results
        top_coins = coins[:top_n]
        
        # Format response
        lines = [f"Top {len(top_coins)} cryptocurrencies by market cap:"]
        
        for i, coin in enumerate(top_coins, 1):
            name = coin.get("name", "Unknown")
            symbol = coin.get("symbol", "").upper()
            price = coin.get("current_price", 0)
            market_cap = coin.get("market_cap", 0)
            rank = coin.get("market_cap_rank", i)
            
            price_str = f"${price:,.2f}" if price >= 0.01 else f"${price:.6f}"
            mcap_str = f"${market_cap:,.0f}"
            
            lines.append(f"{rank}. {name} ({symbol}): {price_str}, Market Cap: {mcap_str}")
        
        result = "\n".join(lines)
        
        logger.info(f"Tool result: Successfully retrieved top {len(top_coins)} coins by market cap")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve coins by market cap: {str(e)}"
        logger.error(f"Tool error: get_coins_by_market_cap - {error_msg}")
        return error_msg


@agent.tool
async def get_coins_by_fdv(
    ctx: RunContext[DeFiAnalystContext],
    top_n: int = 10,
    vs_currency: str = "usd"
) -> str:
    """
    Get top cryptocurrencies ranked by fully diluted valuation (FDV).
    
    Args:
        top_n: Number of results to return (default 10, max 250)
        vs_currency: Target currency (default "usd")
        
    Returns:
        Formatted ranking with coin names, symbols, FDVs, and prices
    """
    logger.info(f"Tool called: get_coins_by_fdv, n={top_n}, currency={vs_currency}")
    
    try:
        # Validate top_n
        if top_n < 3 or top_n > 25:
            return "Invalid top_n. Must be between 3 and 25."
        
        # Fetch market data (get more than needed to account for filtering)
        coins = await ctx.deps.coingecko_client.get_coins_markets(
            vs_currency=vs_currency,
            order="market_cap_desc",
            per_page=top_n,
            page=1
        )
        
        # Filter by minimum volume ($50k) and non-null FDV
        coins = utils.filter_by_min_volume(coins, min_volume=50000)
        coins = [c for c in coins if c.get("fully_diluted_valuation") is not None]
        
        if not coins:
            return "No coins found matching criteria"
        
        # Sort by fully diluted valuation
        coins_sorted = utils.sort_by_metric(coins, "fully_diluted_valuation", reverse=True)
        
        # Take top N results
        top_coins = coins_sorted[:top_n]
        
        # Format response
        lines = [f"Top {len(top_coins)} cryptocurrencies by fully diluted valuation:"]
        
        for i, coin in enumerate(top_coins, 1):
            name = coin.get("name", "Unknown")
            symbol = coin.get("symbol", "").upper()
            price = coin.get("current_price", 0)
            fdv = coin.get("fully_diluted_valuation", 0)
            rank = coin.get("market_cap_rank", "N/A")
            
            price_str = f"${price:,.2f}" if price >= 0.01 else f"${price:.6f}"
            fdv_str = f"${fdv:,.0f}"
            rank_str = f"#{rank}" if rank != "N/A" else "N/A"
            
            lines.append(f"{i}. {name} ({symbol}): {price_str}, FDV: {fdv_str}, MCap Rank: {rank_str}")
        
        result = "\n".join(lines)
        
        logger.info(f"Tool result: Successfully retrieved top {len(top_coins)} coins by FDV")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve coins by FDV: {str(e)}"
        logger.error(f"Tool error: get_coins_by_fdv - {error_msg}")
        return error_msg


@agent.tool
async def get_coin_ath_atl(
    ctx: RunContext[DeFiAnalystContext],
    coin_id: str,
    vs_currency: str = "usd"
) -> str:
    """
    Get all-time high (ATH) and all-time low (ATL) data for a cryptocurrency.
    
    Args:
        coin_id: CoinGecko coin ID (e.g., "bitcoin", "ethereum", "solana")
        vs_currency: Target currency (default "usd")
        
    Returns:
        Formatted string with ATH/ATL prices, dates, and percentage changes from current price
    """
    logger.info(f"Tool called: get_coin_ath_atl for {coin_id}, currency={vs_currency}")
    
    try:
        data = await ctx.deps.coingecko_client.get_current_price(coin_id)
        
        market_data = data.get("market_data", {})
        
        ath = market_data.get("ath", {}).get(vs_currency)
        ath_date = market_data.get("ath_date", {}).get(vs_currency)
        ath_change_pct = market_data.get("ath_change_percentage", {}).get(vs_currency)
        
        atl = market_data.get("atl", {}).get(vs_currency)
        atl_date = market_data.get("atl_date", {}).get(vs_currency)
        atl_change_pct = market_data.get("atl_change_percentage", {}).get(vs_currency)
        
        current_price = market_data.get("current_price", {}).get(vs_currency)
        
        coin_name = data.get("name", coin_id)
        coin_symbol = data.get("symbol", "").upper()
        
        if ath is None and atl is None:
            return f"No ATH/ATL data available for {coin_name} ({coin_symbol})"
        
        lines = [f"{coin_name} ({coin_symbol}) All-Time Data:"]
        
        if current_price is not None:
            current_price_str = f"${current_price:,.2f}" if current_price >= 0.01 else f"${current_price:.6f}"
            lines.append(f"Current Price: {current_price_str}")
        
        if ath is not None:
            ath_str = f"${ath:,.2f}" if ath >= 0.01 else f"${ath:.6f}"
            ath_date_str = ath_date[:10] if ath_date else "Unknown"
            lines.append(f"All-Time High: {ath_str} on {ath_date_str}")
            
            if ath_change_pct is not None:
                lines.append(f"Down {abs(ath_change_pct):.2f}% from ATH")
        
        if atl is not None:
            atl_str = f"${atl:,.2f}" if atl >= 0.01 else f"${atl:.6f}"
            atl_date_str = atl_date[:10] if atl_date else "Unknown"
            lines.append(f"All-Time Low: {atl_str} on {atl_date_str}")
            
            if atl_change_pct is not None:
                lines.append(f"Up {abs(atl_change_pct):.2f}% from ATL")
        
        result = "\n".join(lines)
        
        logger.info(f"Tool result: Successfully retrieved ATH/ATL data for {coin_id}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to retrieve ATH/ATL data for {coin_id}: {str(e)}"
        logger.error(f"Tool error: get_coin_ath_atl - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
You are DeFi Analyst, a cryptocurrency market data specialist powered by CoinGecko.

Your role is to provide accurate, current price and market capitalization data for cryptocurrencies.

CAPABILITIES:
- Get current price, market cap, and 24h volume for any cryptocurrency
- Get historical data for specific dates (within last 365 days on demo plan)
- Search for coins by name or symbol to find the correct CoinGecko ID
- Get top performing coins (gainers/losers) over various timeframes
- Compare price performance between multiple cryptocurrencies
- Rank coins by market capitalization or fully diluted valuation
- Get all-time high (ATH) and all-time low (ATL) data with dates and percentage changes

IMPORTANT GUIDELINES:
1. Use search_coin_by_name_or_symbol first if you're unsure of the exact coin ID
2. Common coin IDs: bitcoin, ethereum, solana, cardano, polkadot, avalanche-2, etc.
3. Always provide data in clear responses with proper currency formatting
4. If data is unavailable or an error occurs, clearly state the issue
5. Keep responses concise and data-focused
6. Do not provide investment advice or speculation about future prices
7. Use plain text only - no Markdown formatting (**, *, _, etc.), no bullet points, no headers
8. All rankings automatically filter for coins with 24h volume >= $50,000

TOOL SELECTION GUIDE:

For "which coins performed best/worst" → use get_top_performing_coins
  * Supported timeframes: 1h, 24h, 7d, 14d, 30d, 60d, 1y
  * Use direction="gainers" for best, direction="losers" for worst
  * Returns ordered list with price, percentage change, and market cap rank

For "compare X vs Y" or "how did X perform vs Y" → use compare_coin_performance
  * Requires start_date in dd-mm-yyyy format
  * Optional end_date in dd-mm-yyyy format (if omitted, uses current price)
  * Returns start/end prices with absolute and percentage changes
  * Maximum 10 coins per comparison

For "largest/top coins by market cap" → use get_coins_by_market_cap
  * Returns current rankings by market capitalization
  * Shows market cap rank, price, and market cap value

For "largest/top coins by FDV" or "fully diluted" → use get_coins_by_fdv
  * Returns rankings by fully diluted valuation
  * Shows FDV value and market cap rank for reference

For "all-time high/low" or "ATH/ATL" questions → use get_coin_ath_atl
  * Returns ATH price, ATH date, and percentage down from ATH
  * Returns ATL price, ATL date, and percentage up from ATL
  * Shows current price for reference

RESPONSE FORMAT:
Your responses should include the structured data returned by the tool with a brief summary.
Do not embellish or add conversational flair - amprChat will handle that.

When answering questions, focus solely on providing the requested market data.
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[DeFiAnalystContext]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n" + PROMPT_TEMPLATE


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
