from pathlib import Path
from pydantic_ai import Agent
from pydantic import BaseModel
from typing import Optional
from convex import ConvexClient
import logging
import re

from ..modules.defianalyst.coingecko_client import CoinGeckoClient
from ..modules.defianalyst.utils import is_asset_reference

logger = logging.getLogger(__name__)

# Cached CoinGecko coins list for resolving external IDs
_coingecko_coins_cache: Optional[list[dict]] = None

# Cached asset identifiers from the database
_asset_identifiers_cache: Optional[list[dict]] = None


async def _get_coingecko_coins() -> list[dict]:
    """Fetch and cache the CoinGecko coins list."""
    global _coingecko_coins_cache
    if _coingecko_coins_cache is None:
        async with CoinGeckoClient() as client:
            _coingecko_coins_cache = await client.get_coins_list()
    return _coingecko_coins_cache


def _resolve_coingecko_id(coins_list: list[dict], ticker: str | None, name: str | None) -> str | None:
    """
    Resolve a CoinGecko coin ID from a ticker and/or name.
    Uses a prioritized matching strategy to avoid false positives from
    obscure coins sharing a ticker symbol (e.g. "Batcat" with symbol "BTC").

    Priority:
      1. Exact match on both ticker AND name (most precise)
      2. Exact name match only
      3. Exact ticker match only
    """
    if not ticker and not name:
        return None

    ticker_lower = ticker.lower() if ticker else None
    name_lower = name.lower() if name else None

    ticker_match: str | None = None
    name_match: str | None = None

    for coin in coins_list:
        coin_symbol = coin.get("symbol", "").lower()
        coin_name = coin.get("name", "").lower()
        coin_id = coin.get("id", "")

        symbol_matches = ticker_lower and coin_symbol == ticker_lower
        name_matches = name_lower and coin_name == name_lower

        # Best case: both ticker and name match — return immediately
        if symbol_matches and name_matches:
            return coin_id

        # Track first ticker-only and name-only matches as fallbacks
        if symbol_matches and ticker_match is None:
            ticker_match = coin_id
        if name_matches and name_match is None:
            name_match = coin_id

    return name_match or ticker_match


def _get_asset_identifiers(convex_client: ConvexClient) -> list[dict]:
    """Fetch and cache all asset identifiers from the database."""
    global _asset_identifiers_cache
    if _asset_identifiers_cache is None:
        _asset_identifiers_cache = convex_client.query("assets:getAllAssetIdentifiers", {})
    return _asset_identifiers_cache


def _scan_message_for_assets(message: str, asset_identifiers: list[dict]) -> list[dict]:
    """
    Scan a message for mentions of known assets by ticker or name.
    Returns a list of matched asset dicts (with _id, ticker, name).
    Each dict gets an extra '_match_type' key: "ticker" or "name".
    Uses word-boundary matching to avoid false positives.
    """
    message_lower = message.lower()
    matched = {}

    for asset in asset_identifiers:
        asset_id = asset["_id"]
        if asset_id in matched:
            continue

        # Check ticker match (word boundary, uppercase only)
        ticker = asset.get("ticker")
        if ticker and len(ticker) >= 2:
            pattern = r'\b' + re.escape(ticker) + r'\b'
            if re.search(pattern, message):
                matched[asset_id] = {**asset, "_match_type": "ticker"}
                continue

        # Check name match (word boundary, case-insensitive)
        name = asset.get("name")
        if name and len(name) >= 2:
            pattern = r'\b' + re.escape(name.lower()) + r'\b'
            if re.search(pattern, message_lower):
                matched[asset_id] = {**asset, "_match_type": "name"}

    return list(matched.values())


# Agent is only used for intent classification — no tools needed
_intent_agent = Agent(
    "mistral:mistral-small-latest",
    output_type=bool,
    system_prompt=(Path(__file__).parent / "prompts/watchlist_inferrer.md").read_text(),
)


class WatchlistInferenceResult(BaseModel):
    """Result of a watchlist inference run."""
    assets_found: list[str]
    is_explicit_watch: bool


async def infer_watchlist(convex_client: ConvexClient, user_id: str, message: str) -> str:
    """
    Main entry point for watchlist inference.
    1. Scan the message against DB assets (deterministic).
    2. If assets found, use the agent to classify intent (stated vs inferred).
    3. Track all matched assets accordingly.
    """
    # Step 1: DB scan for asset mentions
    asset_identifiers = _get_asset_identifiers(convex_client)
    matched_assets = _scan_message_for_assets(message, asset_identifiers)

    if not matched_assets:
        logger.info(f"No assets found in message for user {user_id}")
        return "No assets mentioned."

    # Filter out short name matches that are common words, not asset references
    verified_assets = []
    for asset in matched_assets:
        name = asset.get("name", "")
        if asset["_match_type"] == "name" and len(name) <= 5:
            try:
                is_ref = await is_asset_reference(message, name)
                if not is_ref:
                    logger.info(f"Filtered ambiguous name match '{name}' for user {user_id}")
                    continue
            except Exception as e:
                logger.error(f"Asset reference check failed for '{name}': {e}")
                continue
        verified_assets.append(asset)
    matched_assets = verified_assets

    if not matched_assets:
        logger.info(f"All matches filtered as common words for user {user_id}")
        return "No assets mentioned."

    asset_labels = [a.get("ticker") or a.get("name") or a["_id"] for a in matched_assets]
    logger.info(f"Found assets in message for user {user_id}: {asset_labels}")

    # Step 2: Classify intent via agent
    intent_prompt = f"User message: \"{message}\"\nAssets found: {', '.join(asset_labels)}"
    try:
        result = await _intent_agent.run(intent_prompt)
        is_explicit = result.output
    except Exception as e:
        logger.error(f"Intent classification failed for user {user_id}: {e}")
        is_explicit = False

    # Step 3: Track each matched asset
    for asset in matched_assets:
        asset_id = asset["_id"]
        asset_label = asset.get("ticker") or asset.get("name") or asset_id

        try:
            # Ensure priceFeedMapping exists for crypto assets
            full_asset = convex_client.query("assets:getAsset", {"id": asset_id})
            if full_asset and full_asset.get("asset_category") == "cryptotoken" and full_asset.get("price_feed") == "defianalyst":
                existing_mappings = convex_client.query(
                    "priceFeedMappings:getMappingsByAsset", {"asset": asset_id}
                )
                if not existing_mappings:
                    try:
                        coins_list = await _get_coingecko_coins()
                        coingecko_id = _resolve_coingecko_id(
                            coins_list, full_asset.get("ticker"), full_asset.get("name")
                        )
                        if coingecko_id:
                            convex_client.mutation("priceFeedMappings:upsertMapping", {
                                "asset": asset_id,
                                "price_feed": "defianalyst",
                                "external_id": coingecko_id,
                            })
                            logger.info(f"Created priceFeedMapping for {asset_label} -> {coingecko_id}")
                        else:
                            logger.warning(f"Could not resolve CoinGecko ID for {asset_label}")
                    except Exception as e:
                        logger.error(f"Error creating priceFeedMapping for {asset_label}: {e}")

            # Stamp last_mentioned_at on every mention (resets 30-day expiration clock)
            convex_client.mutation("portfolioItems:stampMentioned", {
                "user": user_id,
                "asset": asset_id,
            })

            # Check current status — never modify owned assets
            existing = convex_client.query("portfolioItems:getPortfolioItem", {
                "user": user_id,
                "asset": asset_id,
            })

            if existing and existing.get("asset_status") == "owned":
                logger.info(f"Asset {asset_label} is owned, skipping")
                continue

            if is_explicit:
                result = convex_client.mutation("portfolioItems:addToWatchlist", {
                    "user": user_id,
                    "asset": asset_id,
                })
                logger.info(f"Added stated watch for {asset_label}: {result.get('asset_status')}")
            else:
                result = convex_client.mutation("portfolioItems:addInferredWatch", {
                    "user": user_id,
                    "asset": asset_id,
                })
                logger.info(f"Inferred watch for {asset_label}: {result.get('asset_status')}")

            # Auto-associate notification_modules for crypto assets on watchlist
            new_status = result.get("asset_status") if result else None
            if new_status in ("stated watch", "inferred watch") and full_asset:
                await _auto_associate_notification_modules(
                    convex_client, user_id, asset_id, full_asset
                )

        except Exception as e:
            logger.error(f"Error tracking asset {asset_label}: {e}")

    action = "Watched" if is_explicit else "Tracked"
    return f"{action} {', '.join(asset_labels)}"


async def _auto_associate_notification_modules(
    convex_client: ConvexClient,
    user_id: str,
    asset_id: str,
    asset: dict,
) -> None:
    """
    Auto-associate notification modules on a portfolioItem based on asset category.
    Crypto assets with price_feed="defianalyst" get the defianalyst module associated,
    and default alert registrations are created via the module's register_notifications().
    """
    if asset.get("asset_category") != "cryptotoken" or asset.get("price_feed") != "defianalyst":
        return

    try:
        module_record = convex_client.query("notifications:getModuleByName", {"name": "defianalyst"})
        if not module_record:
            logger.warning("defianalyst module not registered, skipping notification_modules association")
            return

        convex_client.mutation("portfolioItems:addNotificationModule", {
            "user": user_id,
            "asset": asset_id,
            "module": module_record["_id"],
        })
        logger.info(f"Auto-associated defianalyst module for asset {asset_id}")

        # Create default alert registrations via the module
        from ..modules.registry import get_module_registry
        module_instance = get_module_registry().get_module("defianalyst")
        if module_instance and hasattr(module_instance, "register_notifications"):
            await module_instance.register_notifications(user_id, asset_id)
        else:
            logger.warning("defianalyst module instance not found in registry, skipping alert registration")

    except Exception as e:
        logger.error(f"Error auto-associating notification module for asset {asset_id}: {e}")
