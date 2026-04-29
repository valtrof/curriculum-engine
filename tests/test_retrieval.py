import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_engine.models import LearningPlan, Phase, Resource
from curriculum_engine.retrieval import enrich_plan, enrich_resource, _validate_url


def _make_resource(resource_type="video", **kwargs) -> Resource:
    defaults = dict(
        title="Test Resource",
        resource_type=resource_type,
        estimated_minutes=30,
        search_query="python tutorial",
        preferred_source="YouTube",
        description="A test resource.",
    )
    return Resource(**{**defaults, **kwargs})


def _make_http_client(get_json=None, post_json=None, head_ok=True) -> MagicMock:
    client = MagicMock()

    get_response = MagicMock()
    get_response.is_success = True
    get_response.raise_for_status = MagicMock()
    get_response.json = MagicMock(return_value=get_json or {})
    client.get = AsyncMock(return_value=get_response)

    post_response = MagicMock()
    post_response.is_success = True
    post_response.raise_for_status = MagicMock()
    post_response.json = MagicMock(return_value=post_json or {})
    client.post = AsyncMock(return_value=post_response)

    head_response = MagicMock()
    head_response.is_success = head_ok
    client.head = AsyncMock(return_value=head_response)

    return client


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_url_returns_true_on_success():
    client = _make_http_client(head_ok=True)
    result = await _validate_url(client, "https://example.com")
    assert result is True


@pytest.mark.asyncio
async def test_validate_url_returns_false_on_failure():
    client = _make_http_client(head_ok=False)
    result = await _validate_url(client, "https://example.com/404")
    assert result is False


@pytest.mark.asyncio
async def test_validate_url_returns_false_on_exception():
    client = MagicMock()
    client.head = AsyncMock(side_effect=Exception("connection refused"))
    result = await _validate_url(client, "https://example.com")
    assert result is False


# ---------------------------------------------------------------------------
# enrich_resource — video
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_resource_video_uses_youtube():
    yt_response = {
        "items": [{"id": {"videoId": "abc123"}, "snippet": {"title": "Python Tutorial", "channelTitle": "PyChannel"}}]
    }
    client = _make_http_client(get_json=yt_response)

    with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake-key", "SERPER_API_KEY": "fake-key"}):
        resource = await enrich_resource(_make_resource("video"), client)

    assert resource.url == "https://www.youtube.com/watch?v=abc123"
    assert resource.retrieved_title == "Python Tutorial"
    assert resource.channel == "PyChannel"


@pytest.mark.asyncio
async def test_enrich_resource_video_falls_back_to_serper_when_youtube_empty():
    yt_response = {"items": []}
    serper_response = {"organic": [{"link": "https://example.com/article", "title": "Python Article"}]}
    client = _make_http_client(get_json=yt_response, post_json=serper_response)

    with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake-key", "SERPER_API_KEY": "fake-key"}):
        resource = await enrich_resource(_make_resource("video"), client)

    assert resource.url == "https://example.com/article"


@pytest.mark.asyncio
async def test_enrich_resource_returns_original_when_no_api_keys():
    client = _make_http_client()
    with patch.dict("os.environ", {}, clear=True):
        resource = await enrich_resource(_make_resource("video"), client)
    assert resource.url is None


# ---------------------------------------------------------------------------
# enrich_resource — article
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_resource_article_uses_serper():
    serper_response = {"organic": [{"link": "https://wiki.example.com/python", "title": "Python Wiki"}]}
    client = _make_http_client(post_json=serper_response)

    with patch.dict("os.environ", {"SERPER_API_KEY": "fake-key"}):
        resource = await enrich_resource(_make_resource("article"), client)

    assert resource.url == "https://wiki.example.com/python"
    assert resource.retrieved_title == "Python Wiki"


@pytest.mark.asyncio
async def test_enrich_resource_article_retries_without_site_operator():
    serper_calls = []

    async def fake_post(url, **kwargs):
        serper_calls.append(kwargs["json"]["q"])
        resp = MagicMock()
        resp.is_success = True
        resp.raise_for_status = MagicMock()
        if len(serper_calls) == 1:
            resp.json = MagicMock(return_value={"organic": []})
        else:
            resp.json = MagicMock(return_value={"organic": [{"link": "https://example.com", "title": "Fallback"}]})
        return resp

    client = _make_http_client()
    client.post = fake_post

    with patch.dict("os.environ", {"SERPER_API_KEY": "fake-key"}):
        resource = await enrich_resource(
            _make_resource("article", search_query="site:plato.stanford.edu Stoicism"),
            client,
        )

    assert len(serper_calls) == 2
    assert "site:" not in serper_calls[1]


# ---------------------------------------------------------------------------
# enrich_plan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_plan_enriches_all_resources():
    yt_response = {
        "items": [{"id": {"videoId": "vid1"}, "snippet": {"title": "Vid", "channelTitle": "Chan"}}]
    }
    serper_response = {"organic": [{"link": "https://example.com", "title": "Article"}]}
    client = _make_http_client(get_json=yt_response, post_json=serper_response)

    plan = LearningPlan(
        subject="Python",
        total_hours=5,
        overview="Learn Python.",
        phases=[
            Phase(
                phase=1,
                title="Basics",
                hours=5,
                description="Foundations.",
                milestone="Write scripts.",
                resources=[
                    _make_resource("video"),
                    _make_resource("article"),
                ],
            )
        ],
    )

    with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake-key", "SERPER_API_KEY": "fake-key"}):
        enriched = await enrich_plan(plan, client)

    assert all(r.url is not None for r in enriched.phases[0].resources)
