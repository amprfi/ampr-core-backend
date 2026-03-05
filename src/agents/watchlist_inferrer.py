from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from typing import Optional
from convex import ConvexClient
import logging

logger = logging.getLogger(__name__)


class WatchlistInferrerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str


agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=WatchlistInferrerContext,
    output_type=str,
)


@agent.tool
async def resolve_and_track_asset(
    ctx: RunContext[WatchlistInferrerContext],
    is_explicit_watch: bool,
    query: str,
    asset_category: Optional[str] = None,
) -> str:
    """
    Resolve an asset and add it to the user's watchlist.
    Call this for each financial asset mentioned in the user's message.

    Args:
        is_explicit_watch: True if the user explicitly asked to watch/track/monitor this asset
        query: The asset's ticker symbol or name as mentioned by the user (e.g., BTC, Bitcoin, XCH, Solana)
        asset_category: One of: cryptotoken, stock, currency, commodity (if known)
    """
    logger.info(
        f"Tool called: resolve_and_track_asset query={query} "
        f"explicit={is_explicit_watch} user={ctx.deps.user_id}"
    )
    try:
        client = ctx.deps.convex_client

        asset = None

        # 1. Try exact ticker lookup
        asset = client.query("portfolioItems:getAssetByTicker", {"ticker": query.upper()})

        # 2. Fall back to full-text name search
        if not asset:
            asset = client.query("portfolioItems:searchAssetByName", {"name": query})

        if not asset:
            logger.info(f"Asset '{query}' not found in database, skipping")
            return f"Asset '{query}' not found, skipping"

        asset_id = asset["_id"]
        asset_label = asset.get("ticker") or asset.get("name") or asset_id

        # Check current status — never modify owned assets
        existing = client.query("portfolioItems:getPortfolioItem", {
            "user": ctx.deps.user_id,
            "asset": asset_id,
        })

        if existing and existing.get("asset_status") == "owned":
            logger.info(f"Asset {asset_label} is owned, skipping")
            return f"Asset {asset_label} is already owned, no change"

        if is_explicit_watch:
            result = client.mutation("portfolioItems:addToWatchlist", {
                "user": ctx.deps.user_id,
                "asset": asset_id,
            })
            logger.info(f"Added stated watch for {asset_label}: {result.get('asset_status')}")
            return f"Added {asset_label} as stated watch"
        else:
            result = client.mutation("portfolioItems:addInferredWatch", {
                "user": ctx.deps.user_id,
                "asset": asset_id,
            })
            logger.info(f"Inferred watch for {asset_label}: {result.get('asset_status')}")
            return f"Tracked {asset_label} as {result.get('asset_status')}"

    except Exception as e:
        error_msg = f"Error tracking asset '{query}': {str(e)}"
        logger.error(f"Tool error: resolve_and_track_asset - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
Your only job is to watch user messages and identify any financial assets mentioned. Your purpose is to notice these mentions, you do not need to answer any questions or provide information back to the user. Watch for stocks, crypto-assets, commodities, and currencies. Pay close attention to anything that may look like a ticker symbol.

CRITICAL REQUIREMENTS:
1. Identify ALL financial assets mentioned in the message (cryptocurrencies, stocks, currencies, commodities).
2. For each asset found, call resolve_and_track_asset with the ticker symbol or name as the query. Prefer ticker symbols when known (e.g., "BTC" not "Bitcoin").
3. Determine if the mention is an EXPLICIT watch request or just a casual mention.

EXPLICIT WATCH INDICATORS (is_explicit_watch = True):
- "Watch this for me"
- "Keep me updated on X"
- "Track X"
- "Monitor X"
- "Add X to my watchlist"
- "Alert me about X"
- "Follow X for me"
- "Let me know if X changes"

CASUAL MENTION (is_explicit_watch = False):
- "What's the price of Bitcoin?"
- "How is ETH doing?"
- "Tell me about Apple stock"
- "Compare BTC and SOL"
- Any question or discussion about an asset without an explicit watch request

ASSET CATEGORIES:
- cryptotoken: Bitcoin (BTC), Ethereum (ETH), Solana (SOL), etc.
- stock: Apple (AAPL), Tesla (TSLA), etc.
- currency: USD, EUR, GBP, etc.
- commodity: Gold (XAU), Silver (XAG), Oil (WTI), etc.

If no financial assets are mentioned, do not call any tools.
Do NOT fabricate assets that weren't mentioned.
After processing, respond with a short summary of what you tracked (e.g. "Tracked BTC, ETH" or "No assets mentioned").
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[WatchlistInferrerContext]) -> str:
    return PROMPT_TEMPLATE


def get_watchlist_inferrer_agent():
    return agent
