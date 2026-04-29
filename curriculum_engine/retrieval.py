import asyncio
import logging
import os

import httpx

from curriculum_engine.models import LearningPlan, Resource

logger = logging.getLogger(__name__)

VALIDATE_TIMEOUT = 2.0
REQUEST_TIMEOUT = 5.0


async def _validate_url(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.head(url, timeout=VALIDATE_TIMEOUT, follow_redirects=True)
        return r.is_success
    except Exception:
        return False


async def _fetch_youtube(client: httpx.AsyncClient, query: str) -> dict | None:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — skipping video retrieval")
        return None

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "videoDuration": "medium",
        "order": "relevance",
        "maxResults": "1",
        "key": api_key,
    }
    try:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("YouTube API error: %s", e)
        return None

    items = r.json().get("items", [])
    if not items:
        return None

    item = items[0]
    return {
        "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
        "retrieved_title": item["snippet"]["title"],
        "channel": item["snippet"]["channelTitle"],
    }


async def _serper_search(client: httpx.AsyncClient, query: str) -> dict | None:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.warning("SERPER_API_KEY not set — skipping article retrieval")
        return None

    try:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 3},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Serper API error for query %r: %s", query, e)
        return None

    results = r.json().get("organic", [])
    for item in results:
        if await _validate_url(client, item["link"]):
            return {"url": item["link"], "retrieved_title": item["title"]}

    return None


async def _fetch_article(client: httpx.AsyncClient, query: str) -> dict | None:
    result = await _serper_search(client, query)
    if result:
        return result

    # If site: operator was used and failed, retry without it
    if "site:" in query:
        fallback = " ".join(w for w in query.split() if not w.startswith("site:")).strip()
        logger.info("Retrying article search without site: operator: %r", fallback)
        return await _serper_search(client, fallback)

    return None


async def enrich_resource(resource: Resource, client: httpx.AsyncClient) -> Resource:
    """Fetch a live, validated URL for a single resource."""
    result: dict | None = None

    if resource.resource_type == "video":
        result = await _fetch_youtube(client, resource.search_query)
        if not result:
            result = await _fetch_article(client, resource.search_query)
    else:
        result = await _fetch_article(client, resource.search_query)

    if result:
        return resource.model_copy(update=result)

    logger.warning("No URL found for resource: %r", resource.title)
    return resource


async def enrich_plan(plan: LearningPlan, client: httpx.AsyncClient) -> LearningPlan:
    """Enrich all resources in all phases concurrently."""
    enriched_phases = []
    for phase in plan.phases:
        enriched_resources = await asyncio.gather(
            *[enrich_resource(r, client) for r in phase.resources]
        )
        enriched_phases.append(phase.model_copy(update={"resources": list(enriched_resources)}))
    return plan.model_copy(update={"phases": enriched_phases})
