# Curriculum Engine

A FastAPI service that generates verified, structured learning plans using Claude AI. The engine designs multi-phase curricula with live-validated resource links sourced from YouTube and web search APIs.

## How it works

1. A POST request with a subject and optional hour budget is sent to `/plan`
2. Claude generates a structured curriculum (up to 5 phases, 4 resources each) using only search queries — no hallucinated URLs
3. Each resource's search query is resolved against YouTube or Serper APIs to retrieve real, validated links
4. The completed plan with live URLs is returned

## Tech stack

- **Python 3.12** / **FastAPI** / **Uvicorn**
- **Anthropic Claude** (claude-haiku-4-5) — curriculum generation with prompt caching
- **YouTube Data API v3** — video resource discovery
- **Serper API** — article and web resource discovery
- **httpx** — async HTTP for all external calls
- **Pydantic** — response validation

## Prerequisites

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access |
| `YOUTUBE_API_KEY` | No | Video resource lookup |
| `SERPER_API_KEY` | No | Article/web resource lookup |

The service degrades gracefully when optional API keys are absent — resources will be returned without enriched URLs.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
uvicorn api:app --reload
```

The API will be available at `http://localhost:8000`.

## Docker

```bash
docker build -t curriculum-engine .
docker run -p 8000:8000 --env-file .env curriculum-engine
```

## API

### `POST /plan`

Generate a learning plan.

**Request body:**
```json
{
  "subject": "Linear algebra",
  "hours": 20
}
```

- `subject` — required, non-empty string
- `hours` — optional integer, 1–200 (default: 10)

**Response:** a `LearningPlan` object with phases and validated resources.

```json
{
  "subject": "Linear algebra",
  "total_hours": 20,
  "overview": "...",
  "phases": [
    {
      "phase": 1,
      "title": "Foundations",
      "hours": 5,
      "description": "...",
      "milestone": "...",
      "resources": [
        {
          "title": "Essence of Linear Algebra",
          "resource_type": "video",
          "estimated_minutes": 60,
          "url": "https://youtube.com/...",
          "retrieved_title": "Essence of linear algebra - 3Blue1Brown",
          "channel": "3Blue1Brown"
        }
      ]
    }
  ]
}
```

**Status codes:** `200` success · `400` validation error · `502` upstream API error · `500` internal error

### `GET /health`

```json
{ "status": "ok" }
```

## Project structure

```
curriculum-engine/
├── api.py                  # FastAPI app, endpoints, lifespan management
├── curriculum_engine/
│   ├── models.py           # Pydantic models: LearningPlan, Phase, Resource
│   ├── planner.py          # Claude-based curriculum generation
│   └── retrieval.py        # Resource enrichment via YouTube & Serper
└── tests/
    ├── test_planner.py     # Curriculum generation tests (8)
    └── test_retrieval.py   # Resource enrichment tests (10+)
```

## Running tests

```bash
pytest
pytest tests/test_planner.py -v
pytest tests/test_retrieval.py -v
```

Tests use `unittest.mock` and `pytest-asyncio`. No live API calls are made during the test suite.
