# Curriculum Engine — Architecture

## Overview

Curriculum Engine generates structured learning plans that are both **LLM-designed** and
**grounded in live, validated resources**. The core insight is a two-stage pipeline that
separates concerns cleanly: Claude designs the curriculum structure, and external search APIs
supply the actual links. This sidesteps the most common failure mode of LLM-based content
generation — hallucinated URLs — without sacrificing the quality of the curriculum itself.

```
POST /plan
    │
    ▼
┌─────────────────────────────┐
│  Stage 1: Plan Generation   │
│  Claude (Haiku)             │
│  Input:  subject + hours    │
│  Output: phases + search    │
│          queries (no URLs)  │
└────────────┬────────────────┘
             │  LearningPlan with search_query per resource
             ▼
┌─────────────────────────────┐
│  Stage 2: Link Enrichment   │
│  YouTube API + Serper API   │
│  Input:  search_query       │
│  Output: validated live URL │
└────────────┬────────────────┘
             │  Enriched LearningPlan with real, reachable URLs
             ▼
         Response
```

---

## Stage 1: Curriculum Generation

### Claude generates structure, not links

The system prompt instructs Claude to produce a structured JSON plan where every resource has a
`search_query` field — a precise query that a search API can use to find the best current
version of that resource. Claude never produces URLs directly.

This constraint exists because LLMs are unreliable URL generators: they hallucinate paths,
version numbers, and slugs. But they are excellent at describing *what to look for*. Separating
"what to find" (Claude's job) from "where to find it" (retrieval's job) gives the best of both.

### Prompt engineering for reliable JSON

The system prompt is designed for deterministic, parseable output:

- Explicitly forbids markdown, prose, and code fences
- Specifies the exact JSON schema with every required field
- Provides domain-specific guidance on `search_query` construction (e.g., `site:plato.stanford.edu`
  for philosophy, `site:khanacademy.org` for math) so queries are targeted and likely to hit
  high-quality free resources
- Caps at 5 phases and 4 resources per phase to keep output within a predictable token budget

A lightweight cleanup pass (`removeprefix("```json")`) handles the rare case where the model
wraps output in a code fence despite instructions not to. Pydantic validation on the parsed dict
catches any structural issues before the response is returned.

### Model choice

The service uses `claude-haiku-4-5` rather than Sonnet or Opus. Haiku is fast and cheap, and
structured JSON generation from a clear schema is well within its capability — the heavy lifting
is done by the prompt and schema, not model reasoning. For a user-facing API where latency
matters, Haiku is the right tradeoff.

### Prompt caching

The system prompt is marked with `cache_control: ephemeral`. On repeated requests (which share
the same large system prompt), this avoids re-processing the prompt tokens on every call, reducing
both latency and cost. Haiku's context window is billed at cache hit prices after the first call.

---

## Stage 2: Resource Enrichment

### Per-resource enrichment via async concurrency

Each resource in a phase is enriched concurrently using `asyncio.gather`. Phases are processed
sequentially. This gives good throughput on the inner loop (multiple API calls per phase in
parallel) while keeping the outer loop simple and rate-limit-friendly.

```python
# resources within a phase: concurrent
enriched_resources = await asyncio.gather(
    *[enrich_resource(r, client) for r in phase.resources]
)
```

Full pipeline concurrency (all phases at once) would reduce latency slightly but makes rate
limiting harder to reason about. The current approach is a deliberate tradeoff.

### Routing by resource type

Video resources go to the YouTube Data API first. Non-video resources (articles, books, courses,
practice) go to the Serper web search API. If YouTube fails to return a result, the service falls
back to Serper so the resource still gets a URL rather than returning empty.

```
resource_type == "video"  →  YouTube API  →  (fallback) Serper
resource_type != "video"  →  Serper
```

### URL validation before returning

For Serper results, each candidate URL is validated with an HTTP HEAD request (2s timeout,
redirect-following) before being selected. This ensures that returned URLs are actually reachable,
not just present in a search index. The first valid result from the top 3 Serper hits is used.

YouTube URLs are not HEAD-validated — YouTube's CDN is reliable enough that a valid video ID
from the API is guaranteed to resolve.

### Site-operator fallback

When a search query uses a `site:` operator (e.g., `site:plato.stanford.edu epistemology`) and
Serper returns no valid results, the service retries the query with the `site:` term stripped.
This handles the case where the preferred source doesn't cover the specific topic well.

### Graceful degradation

All external API calls are wrapped in try/except. If an API key is missing or a call fails, the
resource is returned without a URL rather than failing the entire request. This means the service
never returns a 500 due to a missing `YOUTUBE_API_KEY` — the plan is still useful, just without
video links.

---

## Data Model

```
LearningPlan
  subject: str
  total_hours: float
  overview: str
  phases: list[Phase]

Phase
  phase: int
  title: str
  hours: float
  description: str
  milestone: str
  resources: list[Resource]

Resource
  title: str
  resource_type: "video" | "article" | "book" | "course" | "practice"
  estimated_minutes: int
  search_query: str          # Claude-generated, used internally
  preferred_source: str      # Hint to Claude during generation
  description: str
  url: str | None            # Populated by retrieval stage
  retrieved_title: str | None
  channel: str | None        # YouTube only
```

The `search_query` and `preferred_source` fields are generation-time inputs that drive the
retrieval stage. They are exposed in the response, which makes the pipeline transparent and
debuggable: if a resource URL is wrong, you can see exactly what query produced it.

---

## Key Design Decisions and Tradeoffs

| Decision | What was chosen | What was traded off |
|---|---|---|
| Claude generates queries, not URLs | Eliminates URL hallucination | Extra retrieval latency (1 API round trip per resource) |
| Haiku over Sonnet | Lower latency and cost | Slightly less nuanced curriculum descriptions |
| Prompt caching | Lower cost on repeated calls | Ephemeral cache only; not persistent across cold starts |
| Async enrichment within phases | Good throughput without complex rate limiting | Phases still sequential; not the absolute fastest possible |
| HEAD validation on Serper results | Returns only reachable URLs | Adds up to 2s per candidate URL checked |
| Graceful degradation on missing keys | Service always returns a plan | Plans without URLs are less useful |

---

## What Would Change at Scale

**Caching plans:** Identical `(subject, hours)` pairs would return the same plan from a cache
(Redis, DynamoDB) rather than calling Claude every time. LLM calls are the dominant cost.

**Persistent prompt caching:** Switching to `cache_control: persistent` (when available) or
pre-warming the cache on startup would eliminate the first-call latency spike.

**Rate limiting:** At volume, YouTube and Serper quotas become a bottleneck. A queue-based
enrichment worker with retry and backoff would be preferable to firing all requests inline.

**Result quality feedback loop:** Storing which resources users actually click on would allow
fine-tuning the `search_query` prompt to bias toward higher-engagement results over time.

**Model routing:** For complex subjects (graduate-level math, niche domains), routing to Sonnet
or Opus and using the result as a cache seed would improve curriculum quality without paying
the per-request premium.
