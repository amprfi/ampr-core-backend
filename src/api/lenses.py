"""
Lens API endpoints.

Provides endpoints for:
- Ingesting web content into a lens via URL
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from pydantic import BaseModel

from ..clients.convex_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lenses", tags=["lenses"])


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class IngestDocumentRequest(BaseModel):
    """Request body for ingesting a document from a URL into a lens."""
    url: str
    lens_id: str
    title: str
    summary: str
    source_type: str  # blog, newsletter, report, podcast
    author_name: Optional[str] = None
    published_at: Optional[int] = None
    tags: Optional[list[str]] = None


class IngestDocumentResponse(BaseModel):
    """Response for a queued ingestion job."""
    message: str
    lens_id: str
    url: str


# ============================================================================
# CONTENT EXTRACTION
# ============================================================================

async def fetch_and_extract(url: str) -> str:
    """
    Fetch a URL and extract article content as markdown.

    Uses trafilatura for content extraction and markdownify for
    HTML-to-markdown conversion.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url, headers={
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


async def clean_with_mistral(raw_text: str) -> str:
    """
    Use a one-shot Mistral call to clean extracted content into
    well-structured markdown, removing any non-article artifacts.
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY environment variable not set")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": "mistral-small-latest",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a content formatter. You receive raw text extracted from a webpage. "
                            "Your job is to return ONLY the article/essay content as clean markdown. "
                            "Remove any navigation, sidebars, footers, ads, cookie notices, author bios, "
                            "social sharing prompts, related article links, and other non-article text. "
                            "Preserve the article's structure (headings, lists, emphasis, blockquotes). "
                            "Do not add commentary. Return only the cleaned markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": raw_text,
                    },
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ============================================================================
# BACKGROUND INGESTION
# ============================================================================

async def _run_ingestion(request: IngestDocumentRequest):
    """
    Background task: fetch URL, extract content, clean with Mistral,
    and call Convex ingestFromText action.
    """
    try:
        logger.info(f"Ingestion started for URL: {request.url}")

        # 1. Fetch and extract content
        raw_text = await fetch_and_extract(request.url)
        logger.info(f"Extracted {len(raw_text)} chars from {request.url}")

        # 2. Clean with Mistral
        cleaned_markdown = await clean_with_mistral(raw_text)
        logger.info(f"Cleaned markdown: {len(cleaned_markdown)} chars")

        # 3. Call Convex ingestFromText action
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


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(request: IngestDocumentRequest, background_tasks: BackgroundTasks):
    """
    Ingest a web page into a lens.

    Fetches the URL, extracts article content, cleans it with Mistral,
    and stores/embeds it in Convex. Processing happens in the background.
    """
    try:
        # Validate lens exists
        convex_client = get_client()
        lens = convex_client.query("lenses:getLens", {"id": request.lens_id})
        if not lens:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lens '{request.lens_id}' not found",
            )

        # Validate source_type
        valid_types = {"blog", "newsletter", "report", "podcast"}
        if request.source_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid source_type '{request.source_type}'. Valid: {', '.join(valid_types)}",
            )

        # Queue background ingestion
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
