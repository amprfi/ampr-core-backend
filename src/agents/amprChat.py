import tomllib
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
from src.agents.currency_converter import convert_currency

logger = logging.getLogger(__name__)

# Path to the project's pyproject.toml — used by get_help_overview to surface
# the current version and latest update summary/link defined under [tool.ampr].
_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_project_metadata() -> Dict[str, str]:
    """Read [project].version and [tool.ampr] fields from pyproject.toml.

    Returns an empty-ish dict on any read/parse failure so the help tool
    degrades gracefully rather than failing the whole chat response.
    """
    try:
        with _PYPROJECT_PATH.open("rb") as f:
            data = tomllib.load(f)
        version = data.get("project", {}).get("version", "")
        ampr = data.get("tool", {}).get("ampr", {})
        return {
            "version": version,
            "latest_update_summary": ampr.get("latest_update_summary", "") or "",
            "latest_update_link": ampr.get("latest_update_link", "") or "",
        }
    except Exception as e:
        logger.warning(f"Could not read project metadata from pyproject.toml: {e}")
        return {"version": "", "latest_update_summary": "", "latest_update_link": ""}

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    date_context: str | None = None
    invoked_modules: list[str] = []
    module_already_invoked: bool = False  # True if &mention already triggered a module
    channel: str | None = None
    telegram_id: str | None = None
    currency_context: str = "display_currency: USD"

agent = Agent(
    "mistral:mistral-medium-latest",
    deps_type=TalkerContext,
    output_type=str
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

def build_help_overview() -> str:
    """
    Build the static help-overview text for Ampersand.

    Pure function (no side effects, no LLM, no DB) — produced from the in-memory
    module registry and `[tool.ampr]` fields in pyproject.toml. Exposed at module
    scope so it can be called both from the `get_help_overview` agent tool and
    from a fast-path in `src/api/responses.py` that bypasses the LLM for bare
    `&help` (since the content is fully deterministic).
    """
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

    # Append a "Latest update" footer when both version and summary are configured.
    # Link is optional — if missing, we still show the summary line.
    meta = _load_project_metadata()
    version = meta["version"]
    summary = meta["latest_update_summary"]
    link = meta["latest_update_link"]
    if version and summary:
        if link:
            lines.append("")
            lines.append(f"**Latest update ({version}):** {summary} — [Read more]({link})")
        else:
            lines.append("")
            lines.append(f"**Latest update ({version}):** {summary}")

    return "\n".join(lines)


@agent.tool
async def get_help_overview(ctx: RunContext[TalkerContext]) -> str:
    """
    Get an overview of Ampersand's capabilities and all available modules.
    Call this when the user asks for help, says "&help", asks "what can you do",
    or wants to know what features are available.
    """
    logger.info("Tool called: get_help_overview")
    result = build_help_overview()
    logger.info("Tool result: get_help_overview returned overview")
    return result


# ---------------------------------------------------------------------------
# Shared formatters for watchlist/alert listings.
# Used by both the dedicated tools (get_user_watchlist, manage_price_alert,
# manage_prediction_alert, manage_notification_preferences) and the unified
# views (get_all_alerts) to avoid duplicating formatting logic.
# ---------------------------------------------------------------------------

def _format_asset_watchlist(items: list) -> str:
    """Render the asset watchlist (portfolioItems:getWatchlist) for display."""
    if not items:
        return "Your asset watchlist is currently empty."
    lines = []
    for item in items:
        asset = item.get("asset_details", {}) or {}
        name = asset.get("name", "Unknown")
        ticker = asset.get("ticker", "")
        status = item.get("asset_status", "watching")
        label = f"{name} ({ticker})" if ticker else name
        status_label = "watching" if status == "stated watch" else "auto-detected"
        lines.append(f"- {label} [{status_label}]")
    return f"Asset watchlist ({len(items)}):\n" + "\n".join(lines)


def _format_event_watchlist(items: list) -> str:
    """Render the prediction-event watchlist (watchlistEvents:getWatchlistByUser)."""
    if not items:
        return "Your prediction event watchlist is currently empty."
    lines = []
    for item in items:
        event = item.get("event_details") or {}
        title = event.get("title", "Unknown event")
        status = item.get("event_status", "watching")
        # Map raw statuses to user-friendly labels (mirrors the asset watchlist tone).
        status_label = {
            "stated watch": "watching",
            "inferred watch": "auto-detected",
            "pending inferred watch": "auto-detected (pending)",
        }.get(status, status)
        lines.append(f"- {title} [{status_label}]")
    return f"Prediction event watchlist ({len(items)}):\n" + "\n".join(lines)


def _format_price_alerts(convex, user_id: str) -> str:
    """Render the user's active price alerts. Returns a human-readable string."""
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


def _format_prediction_alerts(convex, user_id: str) -> str:
    """Render the user's active prediction alerts."""
    alerts = convex.query("predictionAlerts:getUserAlerts", {"user": user_id})
    if not alerts:
        return "You have no active prediction alerts."
    lines = []
    for alert in alerts:
        event = convex.query("predictionEvents:getEvent", {"id": alert["event"]}) if alert.get("event") else None
        label = event.get("title", "Unknown") if event else "Default"
        period = "24h" if alert["alert_kind"] == "percentage_24h" else "7d"
        threshold = alert.get("threshold_pct", 0)
        lines.append(f"- {label}: {period} probability change exceeds {threshold:.0%}")
    return "Your active prediction alerts:\n" + "\n".join(lines)


def _format_notification_prefs(convex, user_id: str) -> str:
    """Render the user's notification preferences (global + per-module)."""
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


# Allowed values for the watchlist `types` parameter.
_WATCHLIST_TYPES = ("asset", "event")
# Allowed values for the alerts `types` parameter.
_ALERT_TYPES = ("price", "prediction", "preferences")


@agent.tool
async def get_user_watchlist(
    ctx: RunContext[TalkerContext],
    types: Optional[List[str]] = None,
) -> str:
    """
    Get the user's current watchlist(s).

    Args:
        types: Optional list filtering which kinds of watchlists to include.
            Allowed values: "asset" (cryptocurrencies tracked via DeFiAnalyst),
            "event" (prediction-market events tracked via Oracle).
            Defaults to all types when omitted.

    Returns:
        A human-readable summary covering each requested watchlist type.
        Use type-specific calls (e.g., types=["asset"]) when the user asks
        narrowly about one kind of watchlist; default to both for general
        "what am I tracking?" questions.
    """
    logger.info(
        f"Tool called: get_user_watchlist for user_id={ctx.deps.user_id} types={types}"
    )

    requested = list(types) if types else list(_WATCHLIST_TYPES)
    invalid = [t for t in requested if t not in _WATCHLIST_TYPES]
    if invalid:
        return (
            f"ERROR: Unknown watchlist type(s): {', '.join(invalid)}. "
            f"Valid types: {', '.join(_WATCHLIST_TYPES)}."
        )

    sections: List[str] = []
    try:
        if "asset" in requested:
            items = ctx.deps.convex_client.query(
                "portfolioItems:getWatchlist", {"user": ctx.deps.user_id}
            )
            sections.append(_format_asset_watchlist(items or []))
        if "event" in requested:
            items = ctx.deps.convex_client.query(
                "watchlistEvents:getWatchlistByUser", {"user": ctx.deps.user_id}
            )
            sections.append(_format_event_watchlist(items or []))
    except Exception as e:
        error_msg = f"Error retrieving watchlist: {str(e)}"
        logger.error(f"Tool error: get_user_watchlist - {error_msg}")
        return f"ERROR: {error_msg}"

    return "\n\n".join(sections)


@agent.tool
async def get_all_alerts(
    ctx: RunContext[TalkerContext],
    types: Optional[List[str]] = None,
) -> str:
    """
    Get a consolidated view of the user's active alerts and notification settings.

    Use this when the user asks broadly about "my alerts" or "my notifications"
    and you want a single response covering everything. For narrow operations
    (set/remove an alert), keep using manage_price_alert or manage_prediction_alert.

    Args:
        types: Optional list filtering which sections to include. Allowed values:
            "price" (cryptocurrency price alerts),
            "prediction" (prediction-market probability alerts),
            "preferences" (global / per-module notification on/off settings).
            Defaults to all sections when omitted.

    Returns:
        A human-readable summary with one section per requested type.
    """
    logger.info(
        f"Tool called: get_all_alerts for user_id={ctx.deps.user_id} types={types}"
    )

    requested = list(types) if types else list(_ALERT_TYPES)
    invalid = [t for t in requested if t not in _ALERT_TYPES]
    if invalid:
        return (
            f"ERROR: Unknown alert type(s): {', '.join(invalid)}. "
            f"Valid types: {', '.join(_ALERT_TYPES)}."
        )

    convex = ctx.deps.convex_client
    user_id = ctx.deps.user_id
    sections: List[str] = []
    try:
        if "price" in requested:
            sections.append(_format_price_alerts(convex, user_id))
        if "prediction" in requested:
            sections.append(_format_prediction_alerts(convex, user_id))
        if "preferences" in requested:
            sections.append(_format_notification_prefs(convex, user_id))
    except Exception as e:
        error_msg = f"Error retrieving alerts: {str(e)}"
        logger.error(f"Tool error: get_all_alerts - {error_msg}")
        return f"ERROR: {error_msg}"

    return "\n\n".join(sections)

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
            user_id=ctx.deps.user_id,
        )

        if module_name not in ctx.deps.invoked_modules:
            ctx.deps.invoked_modules.append(module_name)

        logger.info(f"Tool result: call_specialist_module for {module_name} succeeded")

        # Prepend module-specific response instructions and constraints if available
        response_instructions = registry.get_response_instructions(module_name)
        constraints = registry.get_constraints_for_module(module_name)
        instructions_block = ""
        if response_instructions:
            instructions_block += f"[RESPONSE FORMATTING INSTRUCTIONS]\n{response_instructions}\n"
        if constraints:
            instructions_block += "[MODULE CONSTRAINTS]\n" + "\n".join(f"- {c}" for c in constraints) + "\n"
        if instructions_block:
            result = f"{instructions_block}[MODULE DATA]\n{result}"

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
            return _format_notification_prefs(convex, user_id)

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
            return _format_price_alerts(convex, user_id)

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

                label = f"{asset.get('name', '')} ({asset.get('ticker', '')})"
                formatted_price = f"${current_price:,.2f}"

                if direction == "above" and current_price >= target_price:
                    return (
                        f"{label} is already above ${target_price:,.2f} "
                        f"(currently {formatted_price}). No alert was set."
                    )
                if direction == "below" and current_price <= target_price:
                    return (
                        f"{label} is already below ${target_price:,.2f} "
                        f"(currently {formatted_price}). No alert was set."
                    )

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

                return f"Price alert set: you'll be notified when {label} goes {direction} ${target_price:,.2f}."

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


@agent.tool
async def manage_prediction_alert(
    ctx: RunContext[TalkerContext],
    action: str,
    event_query: str,
    event_slug: Optional[str] = None,
    alert_kind: Optional[str] = None,
    threshold_pct: Optional[float] = None,
) -> str:
    """
    Manage prediction market alerts for a prediction event (Oracle module).

    Args:
        action: One of "set", "remove", "list".
            - "set": Add event to watchlist and create default alerts (24h: 5%, 7d: 10%).
              Optionally override a specific threshold with alert_kind + threshold_pct.
            - "remove": Remove prediction alerts for an event.
            - "list": List the user's active prediction alerts.
        event_query: The event title or search query to find the event.
            For "list", pass "all" to show all alerts.
        event_slug: Optional Polymarket event slug for exact lookup (e.g., "fed-decision-in-july-181").
            Preferred over event_query when available from a prior Oracle response.
            Always pass the slug if the Oracle module already resolved the event.
        alert_kind: Optional for "set". One of:
            - "percentage_24h": Override the 24h probability change threshold.
            - "percentage_7d": Override the 7d probability change threshold.
            If omitted, both default thresholds are created automatically.
        threshold_pct: Optional for "set". Custom threshold as a decimal (e.g., 0.05 for 5%).
            Only used when alert_kind is also provided.

    Returns:
        Status message describing the result.
    """
    logger.info(f"Tool called: manage_prediction_alert action={action}, event={event_query}, slug={event_slug}")
    convex = ctx.deps.convex_client
    user_id = ctx.deps.user_id

    try:
        if action == "list":
            return _format_prediction_alerts(convex, user_id)

        # Resolve event: prefer slug lookup, fall back to search
        event = None
        if event_slug:
            event = convex.query("predictionEvents:getEventBySlug", {"slug": event_slug})

        if not event:
            events = convex.query("predictionEvents:searchEvents", {"query": event_query, "limit": 1})
            if events:
                event = events[0]

        if not event:
            return f"ERROR: No prediction event found matching '{event_query}'."

        event_id = event["_id"]

        if action == "remove":
            removed = convex.mutation("predictionAlerts:removeAlertsByUserEvent", {
                "user": user_id,
                "event": event_id,
            })
            return f"Removed {removed} prediction alert(s) for '{event.get('title', event_query)}'."

        elif action == "set":
            # Add event to watchlistEvents as stated watch
            convex.mutation("watchlistEvents:addToWatchlist", {
                "user": user_id,
                "event": event_id,
            })

            # Register default alerts (both 24h and 7d) via the oracle module
            registry = get_module_registry()
            oracle_module = registry.get_module("oracle")
            if oracle_module and hasattr(oracle_module, "register_notifications"):
                await oracle_module.register_notifications(user_id, event_id)

            # If custom alert_kind/threshold provided, override that specific default
            if alert_kind and threshold_pct is not None:
                # Normalize: LLM may pass 5 instead of 0.05 for "5%"
                if threshold_pct >= 1:
                    threshold_pct = threshold_pct / 100
                module = convex.query("notifications:getModuleByName", {"name": "oracle"})
                if not module:
                    return "ERROR: Oracle module not registered."

                type_name = "probability_change_24h" if alert_kind == "percentage_24h" else "probability_change_7d"
                notif_type = convex.query("notifications:getNotificationTypeByName", {
                    "module": module["_id"],
                    "name": type_name,
                })
                if not notif_type:
                    return f"ERROR: Notification type '{type_name}' not registered."

                convex.mutation("predictionAlerts:setPercentageThreshold", {
                    "user": user_id,
                    "event": event_id,
                    "alert_kind": alert_kind,
                    "notification_type": notif_type["_id"],
                    "threshold_pct": threshold_pct,
                })

                period = "24-hour" if alert_kind == "percentage_24h" else "7-day"
                return (
                    f"Alert set for '{event.get('title', event_query)}': "
                    f"{period} probability change threshold set to {threshold_pct:.0%}. "
                    f"Default alert also created for the other timeframe."
                )

            title = event.get("title", event_query)
            return (
                f"Alerts set for '{title}': you'll be notified when any market's "
                f"probability shifts by 5%+ in 24 hours or 10%+ in 7 days."
            )

        else:
            return f"ERROR: Unknown action '{action}'. Use 'set', 'remove', or 'list'."

    except Exception as e:
        error_msg = f"Error managing prediction alert: {str(e)}"
        logger.error(f"Tool error: manage_prediction_alert - {error_msg}")
        return f"ERROR: {error_msg}"


@agent.tool
async def get_contribution_score(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the user's contribution score with a breakdown of how it was calculated.
    Call this when the user asks about their contribution score, points, or how they've contributed.
    """
    logger.info(f"Tool called: get_contribution_score for user_id={ctx.deps.user_id}")
    try:
        result = ctx.deps.convex_client.query("profiles:getContributionScore", {
            "userId": ctx.deps.user_id
        })
        if not result:
            return "This user does not have a contribution score yet. Tell them they can earn points through referrals (4 pts each), office hours (0.5 pts each), and product improvements (2 pts each). Do not invent a score or rank."

        score = result["contribution_score"]
        referrals = result["referrals"]
        office_hours = result["office_hours"]
        product_improvements = result["product_improvements"]
        referral_code = result.get("referral_code", "N/A")

        lines = [
            f"Contribution score: {score}",
            f"Breakdown: {referrals} referral(s) × 4 + {office_hours} office hour(s) × 0.5 + {product_improvements} product improvement(s) × 2 = {score}",
        ]
        if referral_code and referral_code != "N/A":
            lines.append(f"Referral code: {referral_code}")

        return "\n".join(lines)
    except Exception as e:
        error_msg = f"Error retrieving contribution score: {str(e)}"
        logger.error(f"Tool error: get_contribution_score - {error_msg}")
        return error_msg


@agent.tool
async def update_user_profile(
    ctx: RunContext[TalkerContext],
    country_name: Optional[str] = None,
    preferred_currency: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> str:
    """
    Update the user's profile information. Use this when the user confirms they want to update
    their profile (e.g., after a profile update suggestion, or when they directly ask to update
    their country, currency, email, or phone).

    Args:
        country_name: Country name or ISO 3166-1 alpha-3 code (e.g., "Canada", "CAN")
        preferred_currency: ISO 4217 currency code (e.g., "USD", "CAD", "EUR")
        email: User's email address
        phone: User's phone number
    """
    logger.info(f"Tool called: update_user_profile for user_id={ctx.deps.user_id}")
    convex = ctx.deps.convex_client
    results = []

    if country_name:
        # Look up country
        country = convex.query("countries:getCountryByCode", {
            "country_code": country_name.upper()
        })
        if not country:
            all_countries = convex.query("countries:getCountries", {})
            for c in all_countries:
                if country_name.lower() in c["country_name"].lower():
                    country = c
                    break
        if country:
            convex.mutation("profiles:updateProfile", {
                "user": ctx.deps.user_id,
                "country": country["_id"]
            })
            results.append(f"country to {country['country_name']}")
        else:
            results.append(f"could not find country '{country_name}'")

    if preferred_currency:
        code = preferred_currency.upper().strip()
        convex.mutation("profiles:updateProfile", {
            "user": ctx.deps.user_id,
            "preferred_currency": code
        })
        results.append(f"preferred currency to {code}")

    if email:
        convex.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            "email": email
        })
        results.append(f"email to {email}")

    if phone:
        convex.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            "phone": phone
        })
        results.append(f"phone to {phone}")

    if not results:
        return "No profile fields to update."

    return f"Successfully updated: {', '.join(results)}"

@agent.tool
async def convert_module_currency(
    ctx: RunContext[TalkerContext],
    module_response: str,
    target_currency: str,
) -> str:
    """
    Convert USD monetary values in a module response to a target currency.
    Use this after receiving financial data from a specialist module when the
    currency_context indicates the user wants results in a non-USD currency.

    Args:
        module_response: The financial text containing USD values to convert
        target_currency: The ISO 4217 currency code to convert to (e.g., "EUR", "GBP")
    """
    logger.info(f"Tool called: convert_module_currency to {target_currency} for user_id={ctx.deps.user_id}")
    try:
        converted = await convert_currency(module_response, target_currency)
        return converted
    except Exception as e:
        logger.warning(f"Currency conversion failed: {e}")
        return module_response


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
    prompt = PROMPT_TEMPLATE.format(specialist_modules=specialist_modules_str)
    prompt += f"\n\nCURRENCY CONTEXT:\n{ctx.deps.currency_context}"
    return prompt

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
