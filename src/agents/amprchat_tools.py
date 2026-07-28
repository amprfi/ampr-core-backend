"""
AmprChat tool definitions for Mistral SDK runner.

This module provides:
- Pydantic args models for all 12 amprChat tools
- Tool functions with closure-based dependency injection
- Factory functions to build the tool registry and runner config

The currency_context is passed via build_context_string (in context_builder.py)
alongside date_context, not as part of the static/system prompt template. That
keeps the shared tool_runner free of amprChat-specific prompt conventions.

See AMPRFI-117 for design context.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING, Literal

# tomllib is Python 3.11+. For 3.10, use tomli as a fallback.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        # If tomli is not installed, we'll handle the ImportError when it's used
        tomllib = None

from pydantic import BaseModel, Field, ConfigDict

if TYPE_CHECKING:
    from src.agents.amprChat import TalkerContext
from convex import ConvexClient

from src.models.user_profile import UserProfile
from src.utils.preprocessing import profile_to_sentences
from src.modules.registry import get_module_registry
from src.agents.currency_converter import convert_currency
from src.agents.tool_runner import Tool, RunnerConfig, create_tool

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Path to the project's pyproject.toml
_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"

# Canonical model name (dash form, per AMPRFI-113)
AMPCHAT_MODEL = "mistral-medium-3-5"


# =============================================================================
# Project Metadata (shared with original amprChat.py)
# =============================================================================

def _load_project_metadata() -> dict[str, str]:
    """Read [project].version and [tool.ampr] fields from pyproject.toml."""
    try:
        if tomllib is None:
            raise ImportError("tomllib/tomli is not available for Python < 3.11")
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


# =============================================================================
# Pydantic Args Models for all 12 tools
# =============================================================================

class GetUserCountryArgs(BaseModel):
    """Arguments for get_user_country_tool - no args, uses closure context."""
    model_config = ConfigDict(extra="forbid")


class UserInvestmentPreferencesArgs(BaseModel):
    """Arguments for user_investment_preferences - no args, uses closure context."""
    model_config = ConfigDict(extra="forbid")


class GetHelpOverviewArgs(BaseModel):
    """Arguments for get_help_overview - no args, uses closure context."""
    model_config = ConfigDict(extra="forbid")


class GetUserWatchlistArgs(BaseModel):
    """Arguments for get_user_watchlist."""
    types: Optional[list[Literal["asset", "event"]]] = Field(
        default=None,
        description="Optional list filtering which kinds of watchlists to include. "
                    "Allowed values: 'asset', 'event'. Defaults to all types when omitted."
    )
    model_config = ConfigDict(extra="forbid")


class GetAllAlertsArgs(BaseModel):
    """Arguments for get_all_alerts."""
    types: Optional[list[Literal["price", "prediction", "preferences"]]] = Field(
        default=None,
        description="Optional list filtering which sections to include. "
                    "Allowed values: 'price', 'prediction', 'preferences'. "
                    "Defaults to all sections when omitted."
    )
    model_config = ConfigDict(extra="forbid")


class ListSpecialistModulesArgs(BaseModel):
    """Arguments for list_specialist_modules - no args, uses closure context."""
    model_config = ConfigDict(extra="forbid")


class ManageNotificationPreferencesArgs(BaseModel):
    """Arguments for manage_notification_preferences."""
    action: Literal["get_status", "set_global", "set_module"] = Field(
        description="One of: 'get_status', 'set_global', 'set_module'"
    )
    module_name: Optional[str] = Field(
        default=None,
        description="Required for 'set_module'. The module name (e.g., 'defianalyst')."
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Required for 'set_global' and 'set_module'. True to enable, False to disable."
    )
    model_config = ConfigDict(extra="forbid")


class ManagePriceAlertArgs(BaseModel):
    """Arguments for manage_price_alert."""
    action: Literal["set", "remove", "list"] = Field(
        description="One of: 'set', 'remove', 'list'"
    )
    asset_name: str = Field(
        description="The asset ticker or name (e.g., 'BTC', 'Ethereum'). "
                    "For 'list', pass 'all' to show all alerts."
    )
    alert_kind: Optional[Literal["percentage_24h", "percentage_7d", "absolute_price"]] = Field(
        default=None,
        description="Required for 'set'. One of: 'percentage_24h', 'percentage_7d', 'absolute_price'"
    )
    threshold_pct: Optional[float] = Field(
        default=None,
        description="Required for percentage alerts. The threshold percentage (e.g., 5.0 for 5%)."
    )
    target_price: Optional[float] = Field(
        default=None,
        description="Required for absolute_price alerts. The target price in USD."
    )
    direction: Optional[Literal["above", "below"]] = Field(
        default=None,
        description="Required for absolute_price alerts. 'above' or 'below'."
    )
    model_config = ConfigDict(extra="forbid")


class ManagePredictionAlertArgs(BaseModel):
    """Arguments for manage_prediction_alert."""
    action: Literal["set", "remove", "list"] = Field(
        description="One of: 'set', 'remove', 'list'"
    )
    event_query: str = Field(
        description="The event title or search query to find the event. "
                    "For 'list', pass 'all' to show all alerts."
    )
    event_slug: Optional[str] = Field(
        default=None,
        description="Optional Polymarket event slug for exact lookup (e.g., 'fed-decision-in-july-181')."
    )
    alert_kind: Optional[Literal["percentage_24h", "percentage_7d"]] = Field(
        default=None,
        description="Optional for 'set'. One of: 'percentage_24h', 'percentage_7d'"
    )
    threshold_pct: Optional[float] = Field(
        default=None,
        description="Optional for 'set'. Custom threshold as a decimal (e.g., 0.05 for 5%). "
                    "Only used when alert_kind is also provided."
    )
    model_config = ConfigDict(extra="forbid")


class GetContributionScoreArgs(BaseModel):
    """Arguments for get_contribution_score - no args, uses closure context."""
    model_config = ConfigDict(extra="forbid")


class UpdateUserProfileArgs(BaseModel):
    """Arguments for update_user_profile."""
    country_name: Optional[str] = Field(
        default=None,
        description="Country name or ISO 3166-1 alpha-3 code (e.g., 'Canada', 'CAN')"
    )
    preferred_currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g., 'USD', 'CAD', 'EUR')"
    )
    email: Optional[str] = Field(
        default=None,
        description="User's email address"
    )
    phone: Optional[str] = Field(
        default=None,
        description="User's phone number"
    )
    model_config = ConfigDict(extra="forbid")


class ConvertModuleCurrencyArgs(BaseModel):
    """Arguments for convert_module_currency."""
    module_response: str = Field(
        description="The financial text containing USD values to convert"
    )
    target_currency: str = Field(
        description="The ISO 4217 currency code to convert to (e.g., 'EUR', 'GBP')"
    )
    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Shared Formatters (moved from original amprChat.py)
# =============================================================================

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
        status_label = {
            "stated watch": "watching",
            "inferred watch": "auto-detected",
            "pending inferred watch": "auto-detected (pending)",
        }.get(status, status)
        lines.append(f"- {title} [{status_label}]")
    return f"Prediction event watchlist ({len(items)}):\n" + "\n".join(lines)


def _format_price_alerts(convex: ConvexClient, user_id: str) -> str:
    """Render the user's active price alerts."""
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


def _format_prediction_alerts(convex: ConvexClient, user_id: str) -> str:
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


def _format_notification_prefs(convex: ConvexClient, user_id: str) -> str:
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


# Allowed values for validation
_WATCHLIST_TYPES = ("asset", "event")
_ALERT_TYPES = ("price", "prediction", "preferences")


# =============================================================================
# Tool Implementations
# =============================================================================

def _build_amprchat_tools(ctx: "TalkerContext") -> dict[str, Tool]:
    """
    Build the amprChat tool dictionary using closure-based dependency injection.
    
    Each tool function closes over the provided TalkerContext, so tools can
    access ctx.convex_client, ctx.user_id, etc. without them being in the
    args model.
    
    Args:
        ctx: TalkerContext containing convex_client, user_id, and other runtime context
        
    Returns:
        Dictionary mapping tool names to Tool instances
    """
    convex = ctx.convex_client
    user_id = ctx.user_id
    
    async def get_user_country_tool(**kwargs: Any) -> str:
        """Get the current user's 3-letter country code."""
        logger.info(f"Tool called: get_user_country_tool for user_id={user_id}")
        try:
            result = convex.query("profiles:getUserCountry", {"userId": user_id})
            if result and result.get("country"):
                country = result["country"]
                logger.info(f"Tool result: get_user_country_tool returned '{country}'")
                return country
            logger.info("Tool result: get_user_country_tool returned 'no country set'")
            return "No country set on profile"
        except Exception as e:
            error_msg = f"Error retrieving country: {str(e)}"
            logger.error(f"Tool error: get_user_country_tool - {error_msg}")
            return error_msg

    async def user_investment_preferences(**kwargs: Any) -> list[str]:
        """Get the user's investment preferences and background information."""
        logger.info(f"Tool called: user_investment_preferences for user_id={user_id}")
        try:
            result = convex.query("profiles:getInvestmentPreferences", {"userId": user_id})
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

    async def get_help_overview(**kwargs: Any) -> str:
        """Get an overview of Ampersand's capabilities and all available modules."""
        logger.info("Tool called: get_help_overview")
        result = build_help_overview()
        logger.info("Tool result: get_help_overview returned overview")
        return result

    async def get_user_watchlist(types: Optional[list[str]] = None, **kwargs: Any) -> str:
        """Get the user's current watchlist(s)."""
        logger.info(f"Tool called: get_user_watchlist for user_id={user_id} types={types}")
        
        requested = list(types) if types else list(_WATCHLIST_TYPES)
        # Note: type validation is handled by the Pydantic args model (GetUserWatchlistArgs)
        # which uses Literal["asset", "event"] to restrict values.

        sections: list[str] = []
        try:
            if "asset" in requested:
                items = convex.query("portfolioItems:getWatchlist", {"user": user_id})
                sections.append(_format_asset_watchlist(items or []))
            if "event" in requested:
                items = convex.query("watchlistEvents:getWatchlistByUser", {"user": user_id})
                sections.append(_format_event_watchlist(items or []))
        except Exception as e:
            error_msg = f"Error retrieving watchlist: {str(e)}"
            logger.error(f"Tool error: get_user_watchlist - {error_msg}")
            return f"ERROR: {error_msg}"

        return "\n\n".join(sections)

    async def get_all_alerts(types: Optional[list[str]] = None, **kwargs: Any) -> str:
        """Get a consolidated view of the user's active alerts and notification settings."""
        logger.info(f"Tool called: get_all_alerts for user_id={user_id} types={types}")
        
        requested = list(types) if types else list(_ALERT_TYPES)
        # Note: type validation is handled by the Pydantic args model (GetAllAlertsArgs)
        # which uses Literal["price", "prediction", "preferences"] to restrict values.

        sections: list[str] = []
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

    async def list_specialist_modules(**kwargs: Any) -> list[dict[str, str]]:
        """List all available specialist modules with their names and descriptions."""
        logger.info("Tool called: list_specialist_modules")
        registry = get_module_registry()
        modules = registry.list_modules()
        logger.info(f"Tool result: list_specialist_modules returned {len(modules)} modules")
        return modules

    async def manage_notification_preferences(
        action: str,
        module_name: Optional[str] = None,
        enabled: Optional[bool] = None,
        **kwargs: Any
    ) -> str:
        """Manage the user's notification preferences."""
        logger.info(f"Tool called: manage_notification_preferences action={action} module_name={module_name} enabled={enabled}")
        
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

    async def manage_price_alert(
        action: str,
        asset_name: str,
        alert_kind: Optional[str] = None,
        threshold_pct: Optional[float] = None,
        target_price: Optional[float] = None,
        direction: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """Manage price alerts for a cryptocurrency asset."""
        logger.info(f"Tool called: manage_price_alert action={action}, asset={asset_name}")
        
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

    async def manage_prediction_alert(
        action: str,
        event_query: str,
        event_slug: Optional[str] = None,
        alert_kind: Optional[str] = None,
        threshold_pct: Optional[float] = None,
        **kwargs: Any
    ) -> str:
        """Manage prediction market alerts for a prediction event."""
        logger.info(f"Tool called: manage_prediction_alert action={action}, event={event_query}, slug={event_slug}")
        
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

    async def get_contribution_score(**kwargs: Any) -> str:
        """Get the user's contribution score with a breakdown."""
        logger.info(f"Tool called: get_contribution_score for user_id={user_id}")
        try:
            result = convex.query("profiles:getContributionScore", {"userId": user_id})
            if not result:
                return (
                    "This user does not have a contribution score yet. "
                    "Tell them they can earn points through referrals (4 pts each), "
                    "office hours (0.5 pts each), and product improvements (2 pts each). "
                    "Do not invent a score or rank. There is NO referral webpage or referral link — "
                    "a referral code is just a short code to share directly with others. "
                    "NEVER generate or reference any URL or webpage for referrals. "
                    "Do NOT fabricate links like ampersand.finance/referral or ampr.fi/referral."
                )

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

    async def update_user_profile(
        country_name: Optional[str] = None,
        preferred_currency: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """Update the user's profile information."""
        logger.info(f"Tool called: update_user_profile for user_id={user_id}")
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
                    "user": user_id,
                    "country": country["_id"]
                })
                results.append(f"country to {country['country_name']}")
            else:
                results.append(f"could not find country '{country_name}'")

        if preferred_currency:
            code = preferred_currency.upper().strip()
            convex.mutation("profiles:updateProfile", {
                "user": user_id,
                "preferred_currency": code
            })
            results.append(f"preferred currency to {code}")

        if email:
            convex.mutation("users:updateUser", {
                "id": user_id,
                "email": email
            })
            results.append(f"email to {email}")

        if phone:
            convex.mutation("users:updateUser", {
                "id": user_id,
                "phone": phone
            })
            results.append(f"phone to {phone}")

        if not results:
            return "No profile fields to update."

        return f"Successfully updated: {', '.join(results)}"

    async def convert_module_currency(
        module_response: str,
        target_currency: str,
        **kwargs: Any
    ) -> str:
        """Convert USD monetary values in a module response to a target currency."""
        logger.info(f"Tool called: convert_module_currency to {target_currency} for user_id={user_id}")
        try:
            converted = await convert_currency(module_response, target_currency)
            return converted
        except Exception as e:
            logger.warning(f"Currency conversion failed: {e}")
            return module_response

    # Build the tools dictionary
    tools = {}
    
    # Tools with no args (use closure context only)
    tools["get_user_country_tool"] = create_tool(
        name="get_user_country_tool",
        description="Get the current user's 3-letter country code for location-specific answers.",
        args_model=GetUserCountryArgs
    )(get_user_country_tool)
    
    tools["user_investment_preferences"] = create_tool(
        name="user_investment_preferences",
        description="Get the user's investment preferences and background information.",
        args_model=UserInvestmentPreferencesArgs
    )(user_investment_preferences)
    
    tools["get_help_overview"] = create_tool(
        name="get_help_overview",
        description="Get an overview of Ampersand's capabilities and all available modules. "
                    "Call this when the user asks for help, says '&help', asks 'what can you do', "
                    "or wants to know what features are available.",
        args_model=GetHelpOverviewArgs
    )(get_help_overview)
    
    tools["list_specialist_modules"] = create_tool(
        name="list_specialist_modules",
        description="List all available specialist modules with their names and descriptions. "
                    "Use this when deciding which module best fits a user's request.",
        args_model=ListSpecialistModulesArgs
    )(list_specialist_modules)
    
    tools["get_contribution_score"] = create_tool(
        name="get_contribution_score",
        description="Get the user's contribution score with a breakdown of how it was calculated. "
                    "Call this when the user asks about their contribution score, points, or how they've contributed.",
        args_model=GetContributionScoreArgs
    )(get_contribution_score)
    
    # Tools with args
    tools["get_user_watchlist"] = create_tool(
        name="get_user_watchlist",
        description="Get the user's current watchlist(s).",
        args_model=GetUserWatchlistArgs
    )(get_user_watchlist)
    
    tools["get_all_alerts"] = create_tool(
        name="get_all_alerts",
        description="Get a consolidated view of the user's active alerts and notification settings. "
                    "Use this when the user asks broadly about 'my alerts' or 'my notifications'.",
        args_model=GetAllAlertsArgs
    )(get_all_alerts)
    
    tools["manage_notification_preferences"] = create_tool(
        name="manage_notification_preferences",
        description="Enable/disable notifications globally or per-module on/off.",
        args_model=ManageNotificationPreferencesArgs
    )(manage_notification_preferences)
    
    tools["manage_price_alert"] = create_tool(
        name="manage_price_alert",
        description="Set, remove, or list price alerts for cryptocurrency assets (DeFiAnalyst module).",
        args_model=ManagePriceAlertArgs
    )(manage_price_alert)
    
    tools["manage_prediction_alert"] = create_tool(
        name="manage_prediction_alert",
        description="Set, remove, or list prediction-market alerts for prediction events (Oracle module).",
        args_model=ManagePredictionAlertArgs
    )(manage_prediction_alert)
    
    tools["update_user_profile"] = create_tool(
        name="update_user_profile",
        description="Update user's profile information (country, preferred currency, email, phone). "
                    "Use this when the user confirms they want to update their profile.",
        args_model=UpdateUserProfileArgs
    )(update_user_profile)
    
    tools["convert_module_currency"] = create_tool(
        name="convert_module_currency",
        description="Convert USD monetary values in a module response to a target currency. "
                    "Use this after receiving financial data from a specialist module when the "
                    "currency_context indicates the user wants results in a non-USD currency.",
        args_model=ConvertModuleCurrencyArgs
    )(convert_module_currency)
    
    return tools


# Public alias matching the issue wording and intended external API.
build_amprchat_tools = _build_amprchat_tools


# =============================================================================
# System Prompt Building
# =============================================================================

# Load prompt template once at module load time
PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/ampr_chat.md").read_text()


async def _build_system_prompt(ctx: "TalkerContext") -> str:
    """
    Build the system prompt for amprChat dynamically.
    
    This includes:
    - The static template from ampr_chat.md
    - Dynamic list of specialist modules and their intents
    - Does NOT include currency_context (it is already part of the per-turn context string)

    Args:
        ctx: TalkerContext (only used to keep the public signature stable)

    Returns:
        Complete system prompt string
    """
    registry = get_module_registry()
    modules = registry.list_modules()

    lines = [
        "The following specialist modules are available. "
        "Use their data when present in [MODULE RESPONSE], but do NOT call them directly - "
        "module invocation is handled automatically via &mention triggers or the unified router."
    ]
    for mod in modules:
        intents = mod.get("intents", [])
        lines.append(f'\n"{mod["name"]}": {mod["description"]}')
        lines.append("  This module can provide data for:")
        for intent in intents:
            lines.append(f"  - {intent}")

    specialist_modules_str = "\n".join(lines)
    prompt = PROMPT_TEMPLATE.format(specialist_modules=specialist_modules_str)
    
    # Note: currency_context is NOT appended here - it is already present in the
    # per-turn context string built by the response layer.
    return prompt


# =============================================================================
# Help Overview (shared with original amprChat.py)
# =============================================================================

def build_help_overview() -> str:
    """
    Build the static help-overview text for Ampersand.
    
    Pure function (no side effects, no LLM, no DB) — produced from the in-memory
    module registry and `[tool.ampr]` fields in pyproject.toml.
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
    lines.append(
        "You can invoke a module directly by mentioning its trigger "
        "(e.g., &defianalyst what is the price of BTC?) or just ask me naturally "
        "and I'll route to the right module."
    )

    # Append a "Latest update" footer when both version and summary are configured.
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


# =============================================================================
# Runner Configuration
# =============================================================================

from src.agents.mistral_helpers import get_shared_client


async def build_amprchat_config(
    ctx: "TalkerContext",
) -> RunnerConfig:
    """
    Build the complete runner configuration for amprChat.

    This is the main entry point for running amprChat with the Mistral SDK runner.

    The response layer already injects currency_context into build_context_string()
    alongside date_context, so this runner config does not need any extra context messages.

    Args:
        ctx: TalkerContext containing all runtime context
        
    Returns:
        RunnerConfig with tools and system_prompt
    """
    # Build system prompt
    system_prompt = await _build_system_prompt(ctx)
    
    # Build tools dictionary
    tools = build_amprchat_tools(ctx)

    # Build runner config. The response layer already injects currency_context
    # into the per-turn context string, so no extra context_messages are needed here.
    config = RunnerConfig(
        client=get_shared_client(),
        model=AMPCHAT_MODEL,
        tools=tools,
        system_prompt=system_prompt,
        max_iterations=10,
        reasoning_effort="high",
        tool_choice="auto",
    )
    
    return config



