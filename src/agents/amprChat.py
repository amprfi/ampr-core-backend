from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from convex import ConvexClient
from typing import List, Dict, Optional
import logging

from pydantic_ai.agent.abstract import RunOutputDataT
from src.models.user_profile import UserProfile
from src.utils.preprocessing import profile_to_sentences
from src.modules.registry import get_module_registry

logger = logging.getLogger(__name__)

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    date_context: str | None = None
    invoked_modules: list[str] = []
    module_already_invoked: bool = False  # True if &mention already triggered a module
    channel: str | None = None
    telegram_id: str | None = None

agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=TalkerContext,
    output_type=List[str]
)

@agent.tool
async def get_user_country_tool(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the current user's 3-letter country code for location-specific answers.
    """
    logger.info(f"Tool called: get_user_country_tool for user_id={ctx.deps.user_id}")
    try:
        result = ctx.deps.convex_client.query("profiles:getUserCountry", {
            "userId": ctx.deps.user_id
        })
        country = result.get("country") if result else "Unknown"
        logger.info(f"Tool result: get_user_country_tool returned '{country}'")
        return country
    except Exception as e:
        error_msg = f"Error retrieving country: {str(e)}"
        logger.error(f"Tool error: get_user_country_tool - {error_msg}")
        return error_msg

@agent.tool
async def user_investment_preferences(ctx: RunContext[TalkerContext]) -> List[str]:
    """
    Get the user's investment preferences and background information.
    """
    logger.info(f"Tool called: user_investment_preferences for user_id={ctx.deps.user_id}")
    try:
        result = ctx.deps.convex_client.query("profiles:getInvestmentPreferences", {
            "userId": ctx.deps.user_id
        })

        if not result:
            logger.warning("No profile data found")
            return ["No investment preferences found for this user."]

        profile_data = UserProfile(
            country=None,
            kyc_passed=False,
            stated_investment_horizon=result.get("stated_investment_horizon"),
            stated_risk_appetite=result.get("stated_risk_appetite"),
            stated_investment_knowledge=result.get("stated_investment_knowledge"),
            stated_financial_goals=result.get("stated_financial_goals"),

            other_investments=result.get("other_investments"),

            inferred_investment_horizon=result.get("inferred_investment_horizon"),
            inferred_risk_appetite=result.get("inferred_risk_appetite"),
            inferred_investment_knowledge=result.get("inferred_investment_knowledge"),
            inferred_financial_goals=result.get("inferred_financial_goals"),
            inferred_investment_thesis=result.get("inferred_investment_thesis")
        )

        sentences = profile_to_sentences(profile_data)
        logger.info(f"Tool result: user_investment_preferences returned {len(sentences)} sentences")
        return sentences
    except Exception as e:
        error_msg = f"Error retrieving preferences: {str(e)}"
        logger.error(f"Tool error: user_investment_preferences - {error_msg}")
        return [error_msg]

@agent.tool
async def get_help_overview(ctx: RunContext[TalkerContext]) -> str:
    """
    Get an overview of Ampersand's capabilities and all available modules.
    Call this when the user asks for help, says "$help", asks "what can you do",
    or wants to know what features are available.
    """
    logger.info("Tool called: get_help_overview")
    registry = get_module_registry()
    modules = registry.list_modules()

    lines = [
        "Ampersand is your financial co-pilot. Here's what I can help you with:",
        "",
        "General capabilities:",
        "- Answer financial questions and provide market insights",
        "- Manage your watchlist and track assets you're interested in",
        "- Set up price alerts and notifications",
        "- Provide personalized guidance based on your preferences",
        "",
        "Available specialist modules:",
    ]

    for mod in modules:
        trigger = mod.get("trigger", "")
        description = mod.get("description", "")
        lines.append(f"- {trigger} — {description}")
        intents = mod.get("intents", [])
        if intents:
            for intent in intents[:3]:
                lines.append(f"    • {intent}")
            if len(intents) > 3:
                lines.append(f"    • ...and {len(intents) - 3} more")

    lines.append("")
    lines.append("You can invoke a module directly by mentioning its trigger (e.g., &defianalyst what is the price of BTC?) or just ask me naturally and I'll route to the right module.")

    result = "\n".join(lines)
    logger.info(f"Tool result: get_help_overview returned overview with {len(modules)} modules")
    return result

@agent.tool
async def get_user_watchlist(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the user's current watchlist showing all assets they are watching.
    Call this when the user asks about their watchlist, what they're tracking,
    or what assets they're following.
    """
    logger.info(f"Tool called: get_user_watchlist for user_id={ctx.deps.user_id}")
    try:
        items = ctx.deps.convex_client.query("portfolioItems:getWatchlist", {
            "user": ctx.deps.user_id
        })

        if not items:
            return "Your watchlist is currently empty. You can ask me about any asset and I'll start tracking it for you, or tell me to add something to your watchlist."

        lines = []
        for item in items:
            asset = item.get("asset_details", {})
            name = asset.get("name", "Unknown")
            ticker = asset.get("ticker", "")
            status = item.get("asset_status", "watching")
            label = f"{name} ({ticker})" if ticker else name
            status_label = "watching" if status == "stated watch" else "auto-detected"
            lines.append(f"- {label} [{status_label}]")

        return f"Your watchlist ({len(items)} assets):\n" + "\n".join(lines)
    except Exception as e:
        error_msg = f"Error retrieving watchlist: {str(e)}"
        logger.error(f"Tool error: get_user_watchlist - {error_msg}")
        return f"ERROR: {error_msg}"

@agent.tool
async def list_specialist_modules(ctx: RunContext[TalkerContext]) -> List[Dict[str, str]]:
    """
    List all available specialist modules with their names and descriptions.
    Use this when deciding which module best fits a user's request.
    """
    logger.info("Tool called: list_specialist_modules")
    registry = get_module_registry()
    modules = registry.list_modules()
    logger.info(f"Tool result: list_specialist_modules returned {len(modules)} modules")
    return modules

@agent.tool
async def call_specialist_module(
    ctx: RunContext[TalkerContext],
    module_name: str,
    question: str,
) -> str:
    """
    Call a specialist financial module when you need live or detailed data.

    Args:
        module_name: The name of the module to call. See system prompt for available modules.
        question: A focused description of what you want the module to answer,
            derived from the user's request.

    Returns:
        The module's response with the requested data.
    """
    logger.info(f"Tool called: call_specialist_module for module={module_name}")

    if ctx.deps.module_already_invoked:
        logger.info("Module already invoked via &mention, skipping tool call")
        return "A specialist module has already been invoked for this request. Use the data from [MODULE RESPONSE] instead."

    registry = get_module_registry()
    module = registry.get_module(module_name)

    if not module:
        available = [m["name"] for m in registry.list_modules()]
        error_msg = f"Unknown module '{module_name}'. Available modules: {', '.join(available)}"
        logger.warning(f"Tool error: call_specialist_module - {error_msg}")
        return f"ERROR: {error_msg}"

    # Send interim "working on it" message (only on first invocation)
    if module_name not in ctx.deps.invoked_modules:
        await _send_tool_interim_message(ctx.deps, module_name, registry)

    try:
        result = await registry.invoke_module(
            module_name,
            message=question,
            date_context=ctx.deps.date_context,
        )

        if module_name not in ctx.deps.invoked_modules:
            ctx.deps.invoked_modules.append(module_name)

        logger.info(f"Tool result: call_specialist_module for {module_name} succeeded")
        return result
    except Exception as e:
        error_msg = f"Module '{module_name}' failed: {str(e)}"
        logger.error(f"Tool error: call_specialist_module - {error_msg}", exc_info=True)
        return f"ERROR: {error_msg}"

@agent.tool
async def manage_notification_preferences(
    ctx: RunContext[TalkerContext],
    action: str,
    module_name: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> str:
    """
    Manage the user's notification preferences (global or per-module on/off).

    Args:
        action: One of "get_status", "set_global", "set_module".
            - "get_status": Get current notification preferences.
            - "set_global": Enable or disable ALL notifications.
            - "set_module": Enable or disable notifications for a specific module.
        module_name: Required for "set_module". The module name (e.g., "defianalyst").
        enabled: Required for "set_global" and "set_module". True to enable, False to disable.

    Returns:
        Status message describing the result.
    """
    logger.info(f"Tool called: manage_notification_preferences action={action} module_name={module_name} enabled={enabled}")
    convex = ctx.deps.convex_client
    user_id = ctx.deps.user_id

    try:
        if action == "get_status":
            prefs = convex.query("notifications:getUserPreferences", {"user": user_id})
            if not prefs:
                return "No custom notification preferences set. All notifications use default settings."

            lines = []
            for pref in prefs:
                scope = "Global"
                if pref.get("module"):
                    module = convex.query("notifications:getModule", {"id": pref["module"]})
                    scope = f"Module: {module.get('name', 'unknown')}" if module else "Module: unknown"
                status = "enabled" if pref.get("enabled") else "disabled"
                lines.append(f"- {scope}: {status}")
            return "Current notification preferences:\n" + "\n".join(lines)

        elif action == "set_global":
            if enabled is None:
                return "ERROR: 'enabled' parameter is required for set_global."
            convex.mutation("notifications:setGlobalNotificationPreference", {
                "user": user_id,
                "enabled": enabled,
            })
            status = "enabled" if enabled else "disabled"
            return f"All notifications have been {status}."

        elif action == "set_module":
            if not module_name:
                return "ERROR: 'module_name' parameter is required for set_module."
            if enabled is None:
                return "ERROR: 'enabled' parameter is required for set_module."

            module = convex.query("notifications:getModuleByName", {"name": module_name})
            if not module:
                return f"ERROR: Module '{module_name}' not found."

            convex.mutation("notifications:setModuleNotificationPreference", {
                "user": user_id,
                "module": module["_id"],
                "enabled": enabled,
            })
            status = "enabled" if enabled else "disabled"
            return f"Notifications from {module_name} have been {status}."

        else:
            return f"ERROR: Unknown action '{action}'. Use 'get_status', 'set_global', or 'set_module'."

    except Exception as e:
        error_msg = f"Error managing notification preferences: {str(e)}"
        logger.error(f"Tool error: manage_notification_preferences - {error_msg}")
        return f"ERROR: {error_msg}"


@agent.tool
async def manage_price_alert(
    ctx: RunContext[TalkerContext],
    action: str,
    asset_name: str,
    alert_kind: Optional[str] = None,
    threshold_pct: Optional[float] = None,
    target_price: Optional[float] = None,
    direction: Optional[str] = None,
) -> str:
    """
    Manage price alerts for a cryptocurrency asset (DeFiAnalyst module).

    Args:
        action: One of "set", "remove", "list".
            - "set": Create or update a price alert.
            - "remove": Remove price alerts for an asset.
            - "list": List the user's active price alerts.
        asset_name: The asset ticker or name (e.g., "BTC", "Ethereum").
            For "list", pass "all" to show all alerts.
        alert_kind: Required for "set". One of:
            - "percentage_24h": Alert when 24h price change exceeds threshold.
            - "percentage_7d": Alert when 7d price change exceeds threshold.
            - "absolute_price": Alert when price crosses a specific target.
        threshold_pct: Required for percentage alerts. The threshold percentage (e.g., 5.0 for 5%).
        target_price: Required for absolute_price alerts. The target price in USD.
        direction: Required for absolute_price alerts. "above" or "below".

    Returns:
        Status message describing the result.
    """
    logger.info(f"Tool called: manage_price_alert action={action}, asset={asset_name}")
    convex = ctx.deps.convex_client
    user_id = ctx.deps.user_id

    try:
        if action == "list":
            alerts = convex.query("priceAlerts:getUserAlerts", {"user": user_id})
            if not alerts:
                return "You have no active price alerts."

            lines = []
            for alert in alerts:
                asset = convex.query("assets:getAsset", {"id": alert["asset"]}) if alert.get("asset") else None
                label = f"{asset.get('name', '')} ({asset.get('ticker', '')})" if asset else "Default"

                if alert["alert_kind"] == "absolute_price":
                    lines.append(f"- {label}: alert when price goes {alert.get('direction')} ${alert.get('target_price')}")
                else:
                    period = "24h" if alert["alert_kind"] == "percentage_24h" else "7d"
                    lines.append(f"- {label}: {period} change exceeds {alert.get('threshold_pct')}%")

            return "Your active price alerts:\n" + "\n".join(lines)

        # Resolve asset
        asset = convex.query("assets:getAssetByTickerOrName", {"query": asset_name})
        if not asset:
            return f"ERROR: Asset '{asset_name}' not found."

        asset_id = asset["_id"]

        if action == "remove":
            removed = convex.mutation("priceAlerts:removeAlertsByUserAsset", {
                "user": user_id,
                "asset": asset_id,
            })
            label = f"{asset.get('name', '')} ({asset.get('ticker', '')})"
            return f"Removed {removed} price alert(s) for {label}."

        elif action == "set":
            if not alert_kind:
                return "ERROR: 'alert_kind' is required. Use 'percentage_24h', 'percentage_7d', or 'absolute_price'."

            # Resolve notification type
            module = convex.query("notifications:getModuleByName", {"name": "defianalyst"})
            if not module:
                return "ERROR: DeFiAnalyst module not registered."

            if alert_kind == "absolute_price":
                if target_price is None or not direction:
                    return "ERROR: 'target_price' and 'direction' are required for absolute price alerts."

                current_price = asset.get("current_price_usd")
                if current_price is None:
                    return f"ERROR: No current price available for {asset.get('name', asset_name)}."

                type_name = "price_threshold"
                notif_type = convex.query("notifications:getNotificationTypeByName", {
                    "module": module["_id"],
                    "name": type_name,
                })
                if not notif_type:
                    return "ERROR: Notification type 'price_threshold' not registered."

                convex.mutation("priceAlerts:createAbsolutePriceAlert", {
                    "user": user_id,
                    "asset": asset_id,
                    "notification_type": notif_type["_id"],
                    "direction": direction,
                    "target_price": target_price,
                    "current_price": current_price,
                })

                label = f"{asset.get('name', '')} ({asset.get('ticker', '')})"
                return f"Price alert set: you'll be notified when {label} goes {direction} ${target_price}."

            else:
                if threshold_pct is None:
                    return "ERROR: 'threshold_pct' is required for percentage alerts."

                type_name = "price_change_24h" if alert_kind == "percentage_24h" else "price_change_7d"
                notif_type = convex.query("notifications:getNotificationTypeByName", {
                    "module": module["_id"],
                    "name": type_name,
                })
                if not notif_type:
                    return f"ERROR: Notification type '{type_name}' not registered."

                convex.mutation("priceAlerts:setPercentageThreshold", {
                    "user": user_id,
                    "asset": asset_id,
                    "alert_kind": alert_kind,
                    "notification_type": notif_type["_id"],
                    "threshold_pct": threshold_pct,
                })

                label = f"{asset.get('name', '')} ({asset.get('ticker', '')})"
                period = "24-hour" if alert_kind == "percentage_24h" else "7-day"
                return f"Alert set: you'll be notified when {label}'s {period} price change exceeds {threshold_pct}%."

        else:
            return f"ERROR: Unknown action '{action}'. Use 'set', 'remove', or 'list'."

    except Exception as e:
        error_msg = f"Error managing price alert: {str(e)}"
        logger.error(f"Tool error: manage_price_alert - {error_msg}")
        return f"ERROR: {error_msg}"


PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/ampr_chat.md").read_text()

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[TalkerContext]) -> str:
    registry = get_module_registry()
    modules = registry.list_modules()

    lines = ["You MUST call call_specialist_module when the user's message matches ANY of the intents listed below. Do NOT answer without calling the appropriate module first."]
    for mod in modules:
        intents = mod.get("intents", [])
        lines.append(f'\n"{mod["name"]}": {mod["description"]}')
        lines.append("  Call this module when the user's message involves:")
        for intent in intents:
            lines.append(f"  - {intent}")

    specialist_modules_str = "\n".join(lines)
    return PROMPT_TEMPLATE.format(specialist_modules=specialist_modules_str)

async def _send_tool_interim_message(deps: TalkerContext, module_name: str, registry) -> None:
    """Send an interim message when amprChat invokes a module via tool call."""
    try:
        meta = registry.metadata.get(module_name, {})
        display_name = meta.get("trigger", f"&{module_name}").lstrip("&")
        interim_text = f"**{display_name}** 🔍 is working on this..."

        if deps.channel == "telegram" and deps.telegram_id:
            from ..clients.telegram_client import TelegramClient
            telegram_client = TelegramClient()
            await telegram_client.send_message(
                chat_id=int(deps.telegram_id),
                text=interim_text
            )
            await telegram_client.close()
            logger.info(f"Sent interim message to Telegram {deps.telegram_id} for module '{module_name}'")
        else:
            logger.info(f"Interim message (channel '{deps.channel}'): {interim_text}")
    except Exception as e:
        logger.warning(f"Failed to send interim message for module '{module_name}': {e}")


def get_amprChat_agent():
    return agent
