from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from convex import ConvexClient
import logging

logger = logging.getLogger(__name__)


class WatchlistInferrerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str


class AssetMention(BaseModel):
    ticker: str = Field(description="The ticker symbol (e.g., BTC, ETH, AAPL)")
    name: Optional[str] = Field(None, description="Full name of the asset if mentioned")
    asset_category: str = Field(
        description="One of: cryptotoken, stock, currency, commodity"
    )
    is_explicit_watch: bool = Field(
        False,
        description="True if the user explicitly asked to watch/track/monitor this asset"
    )


class WatchlistInferenceResult(BaseModel):
    assets_mentioned: List[AssetMention] = Field(
        default_factory=list,
        description="List of financial assets mentioned in the message"
    )


agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=WatchlistInferrerContext,
    output_type=WatchlistInferenceResult,
)


@agent.tool
async def resolve_and_track_asset(
    ctx: RunContext[WatchlistInferrerContext],
    ticker: str,
    name: str,
    asset_category: str,
    is_explicit_watch: bool,
) -> str:
    """
    Resolve an asset by ticker and add it to the user's watchlist.
    Call this for each financial asset mentioned in the user's message.

    Args:
        ticker: The ticker symbol (e.g., BTC, ETH, AAPL, EUR)
        name: Full name of the asset (e.g., Bitcoin, Ethereum, Apple Inc.)
        asset_category: One of: cryptotoken, stock, currency, commodity
        is_explicit_watch: True if the user explicitly asked to watch/track/monitor this asset
    """
    logger.info(
        f"Tool called: resolve_and_track_asset ticker={ticker} "
        f"explicit={is_explicit_watch} user={ctx.deps.user_id}"
    )
    try:
        client = ctx.deps.convex_client

        # Look up the asset — if it doesn't exist, skip silently
        asset = client.query("portfolioItems:getAssetByTicker", {"ticker": ticker.upper()})

        if not asset:
            logger.info(f"Asset {ticker.upper()} not found in database, skipping")
            return f"Asset {ticker.upper()} not found, skipping"

        asset_id = asset["_id"]

        # Check current status — never modify owned assets
        existing = client.query("portfolioItems:getPortfolioItem", {
            "user": ctx.deps.user_id,
            "asset": asset_id,
        })

        if existing and existing.get("asset_status") == "owned":
            logger.info(f"Asset {ticker.upper()} is owned, skipping")
            return f"Asset {ticker.upper()} is already owned, no change"

        if is_explicit_watch:
            result = client.mutation("portfolioItems:addToWatchlist", {
                "user": ctx.deps.user_id,
                "asset": asset_id,
            })
            logger.info(f"Added stated watch for {ticker.upper()}: {result.get('asset_status')}")
            return f"Added {ticker.upper()} as stated watch"
        else:
            result = client.mutation("portfolioItems:addInferredWatch", {
                "user": ctx.deps.user_id,
                "asset": asset_id,
            })
            logger.info(f"Inferred watch for {ticker.upper()}: {result.get('asset_status')}")
            return f"Tracked {ticker.upper()} as {result.get('asset_status')}"

    except Exception as e:
        error_msg = f"Error tracking asset {ticker}: {str(e)}"
        logger.error(f"Tool error: resolve_and_track_asset - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
You are an asset mention detector for a financial assistant. Your job is to analyze user messages and identify any financial assets mentioned.

CRITICAL REQUIREMENTS:
1. Identify ALL financial assets mentioned in the message (cryptocurrencies, stocks, currencies, commodities).
2. For each asset found, call resolve_and_track_asset to register it.
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

If no financial assets are mentioned, return an empty assets_mentioned list.
Do NOT fabricate assets that weren't mentioned.
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[WatchlistInferrerContext]) -> str:
    return PROMPT_TEMPLATE


def get_watchlist_inferrer_agent():
    return agent
