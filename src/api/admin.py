"""
Admin API endpoints.

All endpoints under /api/admin/* are excluded from Hanko auth middleware
and instead require a valid X-Admin-Key header via the require_admin_key dependency.

Organized by domain:
- Users (listing, creation, contribution updates)
- Messages (search)
- Assets (creation, bulk creation)
- Countries (all mutations)
- Diagnostics (version, latency testing)
- Oracle (manual poll triggers)
- Notifications (testing and management)
- Lenses (content ingestion)
"""

from __future__ import annotations

import time
import logging
from typing import List, Dict, Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks, status
from pydantic import BaseModel, Field
from convex import ConvexError

from ..middleware.auth import require_admin_key
from ..clients.convex_client import get_client
from ..agents.mistral_helpers import (
    get_shared_client,
    build_messages,
    extract_text_from_content,
    MODEL_SMALL,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# USERS
# ============================================================================

class ContributionUpdate(BaseModel):
    office_hours: Optional[float] = Field(None, ge=0, description="New total office hours value")
    product_improvements: Optional[float] = Field(None, ge=0, description="New total product improvements value")


@router.get("/users")
async def get_all_users(_: None = Depends(require_admin_key)) -> List[Dict[str, Any]]:
    """List all users."""
    client = get_client()
    return client.query("users:getUsers", {})


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    first_name: str = Query(..., max_length=100),
    last_name: str = Query(..., max_length=100),
    email: str = Query(..., max_length=50),
    phone: str = Query(..., max_length=20),
    _: None = Depends(require_admin_key),
) -> Dict[str, Any]:
    """Admin-only user creation. Superseded by lazy creation via Hanko for normal flows."""
    client = get_client()
    try:
        created_user = client.mutation("users:createUser", {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
        })
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})
    return created_user


@router.put("/users/{user_id}/contributions")
async def update_contributions(
    user_id: str,
    update: ContributionUpdate,
    _: None = Depends(require_admin_key),
) -> Dict[str, Any]:
    """
    Update a user's contribution fields.
    Pass the new total value for office_hours and/or product_improvements.
    The contribution_score is recalculated automatically by Convex.
    """
    if update.office_hours is None and update.product_improvements is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "Must provide at least one of: office_hours, product_improvements"},
        )

    try:
        args: Dict[str, Any] = {"user": user_id}
        if update.office_hours is not None:
            args["office_hours"] = update.office_hours
        if update.product_improvements is not None:
            args["product_improvements"] = update.product_improvements

        client = get_client()
        updated_profile = client.mutation("profiles:updateProfile", args)
        return updated_profile
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


# ============================================================================
# MESSAGES
# ============================================================================

class MessageSearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200, description="Word or phrase to search for")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of results")
    role: str = Field("user", description="Filter by role: 'user', 'assistant', or 'any'")


@router.post("/messages/search")
async def search_messages(
    request: MessageSearchRequest,
    _: None = Depends(require_admin_key),
) -> List[Dict[str, Any]]:
    """Search all messages for a keyword."""
    try:
        client = get_client()
        results = client.query("messages:searchMessages", {
            "keyword": request.keyword,
            "limit": request.limit,
            "role": request.role,
        })
        return results
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


# ============================================================================
# ASSETS
# ============================================================================

class CreateAssetRequest(BaseModel):
    ticker: Optional[str] = None
    name: Optional[str] = None
    liquid: bool = True
    asset_category: str  # cryptotoken, stock, currency, commodity
    price_feed: Optional[str] = None


def _build_create_asset_args(request: CreateAssetRequest) -> dict:
    args: dict = {
        "liquid": request.liquid,
        "asset_category": request.asset_category,
    }
    if request.ticker is not None:
        args["ticker"] = request.ticker
    if request.name is not None:
        args["name"] = request.name
    if request.price_feed is not None:
        args["price_feed"] = request.price_feed
    return args


@router.post("/assets/create")
async def create_asset(request: CreateAssetRequest, _: None = Depends(require_admin_key)):
    """Create a new asset. If an asset with the same ticker exists, returns the existing one."""
    try:
        client = get_client()
        args = _build_create_asset_args(request)
        result = client.mutation("assets:createAsset", args)
        return {"asset": result}
    except Exception as e:
        logger.error(f"Error creating asset: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assets/bulk-create")
async def bulk_create_assets(
    assets: list[CreateAssetRequest],
    _: None = Depends(require_admin_key),
):
    """Create multiple assets in one request."""
    try:
        client = get_client()
        results = []
        for asset_req in assets:
            args = _build_create_asset_args(asset_req)
            result = client.mutation("assets:createAsset", args)
            results.append(result)
        return {"assets": results}
    except Exception as e:
        logger.error(f"Error bulk creating assets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COUNTRIES (mutations only — reads stay in countries.py)
# ============================================================================

from ..models.country import (
    BulkCountriesRequest,
    BulkCurrencyUpdateRequest,
    BulkCurrencyUpdateResult,
    BulkUpsertResult,
    Country,
    CountryUpdate,
)


@router.post("/countries", status_code=status.HTTP_201_CREATED)
async def create_country(country: Country, _: None = Depends(require_admin_key)) -> Dict[str, Any]:
    """Create a new country."""
    try:
        client = get_client()
        return client.mutation("countries:createCountry", country.model_dump())
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})


@router.post("/countries/bulk", status_code=status.HTTP_200_OK)
async def bulk_upsert_countries(
    request: BulkCountriesRequest,
    _: None = Depends(require_admin_key),
) -> BulkUpsertResult:
    """Bulk insert or update countries, upserting on country_code."""
    try:
        client = get_client()
        countries_data = [c.model_dump() for c in request.countries]
        result = client.mutation("countries:bulkUpsertCountries", {"countries": countries_data})
        return BulkUpsertResult(**result)
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})


@router.put("/countries/bulk-currencies")
async def bulk_update_currencies(
    request: BulkCurrencyUpdateRequest,
    _: None = Depends(require_admin_key),
) -> BulkCurrencyUpdateResult:
    """Bulk update currency codes on existing country records."""
    client = get_client()
    updated = 0
    errors: List[str] = []

    for country_code, currency in request.currencies.items():
        try:
            client.mutation(
                "countries:updateCountry",
                {"country_code": country_code, "currency": currency},
            )
            updated += 1
        except ConvexError as e:
            errors.append(f"{country_code}: {str(e.data)}")
        except Exception as e:
            errors.append(f"{country_code}: {str(e)}")

    return BulkCurrencyUpdateResult(updated=updated, errors=errors)


@router.put("/countries/{country_code}")
async def update_country(
    country_code: str,
    country: CountryUpdate,
    _: None = Depends(require_admin_key),
) -> Dict[str, Any]:
    """Update an existing country."""
    if country.country_code.upper() != country_code.upper():
        raise HTTPException(
            status_code=400,
            detail={"error": "country_code in path and body must match"},
        )

    update_data = {k: v for k, v in country.model_dump().items() if v is not None}

    try:
        client = get_client()
        return client.mutation("countries:updateCountry", update_data)
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})


@router.delete("/countries/{country_code}")
async def delete_country(country_code: str, _: None = Depends(require_admin_key)) -> Dict[str, Any]:
    """Delete a country by code."""
    try:
        client = get_client()
        return client.mutation("countries:deleteCountry", {"country_code": country_code})
    except ConvexError as e:
        raise HTTPException(status_code=400, detail={"error": str(e.data)})


# ============================================================================
# DIAGNOSTICS
# ============================================================================

@router.get("/diagnostics/version", status_code=status.HTTP_200_OK)
async def get_version(_: None = Depends(require_admin_key)):
    """Return the current service version."""
    return {
        "version": "2026.03",
        "service": "ampr-core-backend",
    }


# Models tested in the latency diagnostic
MODELS = [
    "mistral-small-latest",
    "mistral-large-latest",
]

TEST_PROMPT = "Reply with exactly one word: hello."

# Dummy tool schemas used to test tool-calling latency
DUMMY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "Get stock price by ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
]


@router.get("/diagnostics/mistral-latency", status_code=status.HTTP_200_OK)
async def test_mistral_latency(_: None = Depends(require_admin_key)):
    """Test Mistral API response latency across models.

    Uses the shared Mistral SDK client (see AMPRFI-120) instead of raw
    httpx calls. Preserves the per-model, no-tools, and dummy-tools
    latency result shape.
    """
    results = []

    try:
        client = get_shared_client()
    except ValueError:
        logger.error("MISTRAL_API_KEY not configured; latency test unavailable")
        return {"results": [], "error": "MISTRAL_API_KEY not configured"}

    for model in MODELS:
        for mode, tools in [("no_tools", None), ("with_tools", DUMMY_TOOLS)]:
            start = time.monotonic()
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "user", "content": TEST_PROMPT}],
                    "max_tokens": 10,
                }
                # In no_tools mode, omit the tools argument entirely so the
                # SDK does not serialize "tools": null. In with_tools mode,
                # pass the dummy tool schemas.
                if tools is not None:
                    kwargs["tools"] = tools
                response = await client.chat.complete_async(**kwargs)
                elapsed = round(time.monotonic() - start, 3)

                reply = ""
                resolved_model = getattr(response, "model", "unknown")
                if response.choices:
                    content = response.choices[0].message.content
                    reply = extract_text_from_content(content)

                results.append({
                    "model_requested": model,
                    "model_resolved": resolved_model,
                    "mode": mode,
                    "status": 200,
                    "latency_seconds": elapsed,
                    "reply": reply,
                })
            except Exception as e:
                elapsed = round(time.monotonic() - start, 3)
                logger.error(f"Mistral latency test failed for model={model} mode={mode}: {e}", exc_info=True)
                results.append({
                    "model_requested": model,
                    "mode": mode,
                    "status": "error",
                    "latency_seconds": elapsed,
                    "error": str(e),
                })

    return {"results": results}


# ============================================================================
# ORACLE
# ============================================================================

@router.post("/oracle/poll-events", status_code=status.HTTP_200_OK)
async def poll_events(_: None = Depends(require_admin_key)):
    """Manually trigger the oracle event poller."""
    from ..modules.oracle.event_poller import get_event_poller

    convex_client = get_client()
    poller = get_event_poller(convex_client)
    count = await poller.poll_once()
    return {"message": "Event poll complete", "events_processed": count}


# ============================================================================
# NOTIFICATIONS
# ============================================================================

from ..notifications.service import get_notification_service


class SendNotificationRequest(BaseModel):
    user_id: str
    module_id: str
    notification_type_id: str
    content: str


class SendNotificationResponse(BaseModel):
    success: bool
    delivered: bool
    message_id: Optional[str] = None
    queue_id: Optional[str] = None
    error: Optional[str] = None


@router.post("/notifications/send", response_model=SendNotificationResponse)
async def send_notification(request: SendNotificationRequest, _: None = Depends(require_admin_key)):
    """Send a test notification to a user."""
    logger.info(f"Sending test notification to user {request.user_id}")

    try:
        convex_client = get_client()
        service = get_notification_service(convex_client)

        result = await service.send(
            user_id=request.user_id,
            module_id=request.module_id,
            notification_type_id=request.notification_type_id,
            content=request.content,
        )

        return SendNotificationResponse(
            success=result.success,
            delivered=result.delivered,
            message_id=result.message_id,
            queue_id=result.queue_id,
            error=result.error,
        )
    except Exception as e:
        logger.error(f"Error sending notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class RegisterModuleRequest(BaseModel):
    name: str
    description: Optional[str] = None


class RegisterNotificationTypeRequest(BaseModel):
    module_id: str
    name: str
    description: str
    default_enabled: bool = True
    priority: str = "medium"


@router.post("/notifications/modules/register")
async def register_module(request: RegisterModuleRequest, _: None = Depends(require_admin_key)):
    """Register a module (for testing)."""
    try:
        convex_client = get_client()
        module_id = convex_client.mutation("notifications:registerModule", {
            "name": request.name,
            "description": request.description or f"Test module: {request.name}",
        })
        return {"module_id": module_id}
    except Exception as e:
        logger.error(f"Error registering module: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/types/register")
async def register_notification_type(
    request: RegisterNotificationTypeRequest,
    _: None = Depends(require_admin_key),
):
    """Register a notification type for a module (for testing)."""
    try:
        convex_client = get_client()
        type_id = convex_client.mutation("notifications:registerNotificationType", {
            "module": request.module_id,
            "name": request.name,
            "description": request.description,
            "default_enabled": request.default_enabled,
            "priority": request.priority,
        })
        return {"notification_type_id": type_id}
    except Exception as e:
        logger.error(f"Error registering notification type: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/modules")
async def list_modules(_: None = Depends(require_admin_key)):
    """List all registered modules."""
    try:
        convex_client = get_client()
        modules = convex_client.query("notifications:getAllModules", {})
        return {"modules": modules}
    except Exception as e:
        logger.error(f"Error listing modules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/types/{module_id}")
async def list_notification_types(module_id: str, _: None = Depends(require_admin_key)):
    """List notification types for a module."""
    try:
        convex_client = get_client()
        types = convex_client.query("notifications:getNotificationTypesByModule", {
            "module": module_id,
        })
        return {"notification_types": types}
    except Exception as e:
        logger.error(f"Error listing notification types: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class ModuleSendRequest(BaseModel):
    user_id: str
    module_name: str
    notification_type_name: str
    content: str
    asset_ref: Optional[str] = None


class ModuleSendResponse(BaseModel):
    success: bool
    delivered: bool
    message_id: Optional[str] = None
    queue_id: Optional[str] = None
    error: Optional[str] = None


@router.post("/notifications/module-send", response_model=ModuleSendResponse)
async def module_send_notification(request: ModuleSendRequest, _: None = Depends(require_admin_key)):
    """Module callback endpoint for remote modules to send notifications."""
    logger.info(f"Module callback: sending notification for user {request.user_id}")

    try:
        convex_client = get_client()

        # Resolve module ID by name
        module = convex_client.query("notifications:getModuleByName", {
            "name": request.module_name,
        })
        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Module '{request.module_name}' not found",
            )
        module_id = module["_id"]

        # Resolve notification type ID by module + name
        notification_type = convex_client.query("notifications:getNotificationTypeByName", {
            "module": module_id,
            "name": request.notification_type_name,
        })
        if not notification_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Notification type '{request.notification_type_name}' not found for module '{request.module_name}'",
            )
        notification_type_id = notification_type["_id"]

        # Route through existing notification service
        service = get_notification_service(convex_client)
        result = await service.send(
            user_id=request.user_id,
            module_id=module_id,
            notification_type_id=notification_type_id,
            content=request.content,
            asset_ref=request.asset_ref,
        )

        return ModuleSendResponse(
            success=result.success,
            delivered=result.delivered,
            message_id=result.message_id,
            queue_id=result.queue_id,
            error=result.error,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error sending module notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LENSES
# ============================================================================

class IngestDocumentRequest(BaseModel):
    url: str
    lens_id: str
    title: str
    summary: str
    source_type: str  # blog, newsletter, report, podcast
    author_name: Optional[str] = None
    published_at: Optional[int] = None
    tags: Optional[list[str]] = None


class IngestDocumentResponse(BaseModel):
    message: str
    lens_id: str
    url: str


async def fetch_and_extract(url: str) -> str:
    """Fetch a URL and extract article content as markdown."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as http_client:
        response = await http_client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AmprBot/1.0)"
        })
        response.raise_for_status()
        html = response.text

    import trafilatura
    extracted = trafilatura.extract(
        html,
        include_links=True,
        include_images=False,
        include_tables=True,
        output_format="txt",
    )

    if not extracted:
        raise ValueError("Could not extract content from the provided URL")

    return extracted


# System prompt for the markdown cleaner
CLEANER_SYSTEM_PROMPT = (
    "You are a content formatter. You receive raw text extracted from a webpage. "
    "Your job is to return ONLY the article/essay content as clean markdown. "
    "Remove any navigation, sidebars, footers, ads, cookie notices, author bios, "
    "social sharing prompts, related article links, and other non-article text. "
    "Preserve the article's structure (headings, lists, emphasis, blockquotes). "
    "Do not add commentary. Return only the cleaned markdown."
)


async def clean_with_mistral(raw_text: str) -> str:
    """Use a one-shot Mistral call to clean extracted content into well-structured markdown.

    Uses the shared Mistral SDK client (see AMPRFI-120) instead of raw httpx.

    Fail-closed behavior: on any failure — missing API key, SDK/API error, or
    empty/whitespace-only cleaned output — this function raises an exception
    rather than returning a fallback. Callers (e.g. ``_run_ingestion``) should
    catch the exception, log it, and abort ingestion without calling
    ``lenses:ingestFromText``.
    """
    client = get_shared_client()  # raises ValueError if MISTRAL_API_KEY not set

    messages = build_messages(CLEANER_SYSTEM_PROMPT, raw_text)

    response = await client.chat.complete_async(
        model=MODEL_SMALL,
        messages=messages,
        temperature=0.3,
        reasoning_effort="none",
    )

    content = response.choices[0].message.content
    cleaned = extract_text_from_content(content)

    if not cleaned or not cleaned.strip():
        raise RuntimeError(
            "Mistral cleaning returned empty or whitespace-only content"
        )

    logger.info(f"Cleaned markdown: {len(cleaned)} chars")
    return cleaned


async def _run_ingestion(request: IngestDocumentRequest):
    """Background task: fetch URL, extract content, clean with Mistral, and ingest into Convex."""
    try:
        logger.info(f"Ingestion started for URL: {request.url}")

        raw_text = await fetch_and_extract(request.url)
        logger.info(f"Extracted {len(raw_text)} chars from {request.url}")

        cleaned_markdown = await clean_with_mistral(raw_text)
        logger.info(f"Cleaned markdown: {len(cleaned_markdown)} chars")

        convex_client = get_client()

        args: dict = {
            "lensId": request.lens_id,
            "title": request.title,
            "sourceType": request.source_type,
            "sourceUrl": request.url,
            "summary": request.summary,
            "markdownText": cleaned_markdown,
        }
        if request.author_name is not None:
            args["authorName"] = request.author_name
        if request.published_at is not None:
            args["publishedAt"] = request.published_at
        if request.tags is not None:
            args["tags"] = request.tags

        result = convex_client.action("lenses:ingestFromText", args)
        logger.info(f"Ingestion complete for {request.url}: {result}")

    except Exception as e:
        logger.error(f"Ingestion failed for {request.url}: {e}", exc_info=True)


@router.post("/lenses/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(
    request: IngestDocumentRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_admin_key),
):
    """Ingest a web page into a lens. Processing happens in the background."""
    try:
        convex_client = get_client()
        lens = convex_client.query("lenses:getLens", {"id": request.lens_id})
        if not lens:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lens '{request.lens_id}' not found",
            )

        valid_types = {"blog", "newsletter", "report", "podcast"}
        if request.source_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid source_type '{request.source_type}'. Valid: {', '.join(valid_types)}",
            )

        background_tasks.add_task(_run_ingestion, request)

        return IngestDocumentResponse(
            message="Ingestion queued",
            lens_id=request.lens_id,
            url=request.url,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error queuing ingestion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
