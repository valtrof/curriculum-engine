import json
import logging
import os

import anthropic

from curriculum_engine.models import LearningPlan

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are an expert learning curriculum designer. Your job is to produce structured JSON learning plans.

CRITICAL RULES:
- Output ONLY a raw JSON object. No markdown, no prose, no code fences.
- Your entire response must start with { and end with }.
- NEVER include any URLs or links.
- For every resource, provide a precise search_query a search API can use to find the best current version.
- For article/book/course resources, bias search_query toward stable, high-quality free domains:
  • Philosophy / humanities → site:plato.stanford.edu or site:iep.utm.edu
  • General education / maths / science → site:khanacademy.org
  • Any topic (overview / reference) → site:en.wikipedia.org
  • University courses / lectures → site:ocw.mit.edu
  • Only use site: when the topic is genuinely covered there.
- Use at most 5 phases regardless of total hours.
- Use at most 4 resources per phase.
- Every resource object must include ALL fields: title, resource_type, estimated_minutes, \
search_query, preferred_source, description.

Output this exact JSON shape:
{
  "subject": string,
  "total_hours": number,
  "overview": string (2-3 sentences describing the learning journey),
  "phases": [
    {
      "phase": number,
      "title": string,
      "hours": number,
      "description": string,
      "resources": [
        {
          "title": string,
          "resource_type": "video" | "article" | "book" | "course" | "practice",
          "estimated_minutes": number,
          "search_query": string,
          "preferred_source": string,
          "description": string
        }
      ],
      "milestone": string
    }
  ]
}"""


def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    return anthropic.Anthropic(api_key=api_key)


def generate_plan(subject: str, hours: int, client: anthropic.Anthropic) -> LearningPlan:
    """Call Claude to generate a structured learning plan with search queries (no URLs)."""
    logger.info("Generating plan: subject=%r hours=%d", subject, hours)

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f'Create a learning plan for "{subject}" in {hours} hours. '
                    "Use only free online resources. Output JSON only."
                ),
            }
        ],
    )

    text = response.content[0].text
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse plan JSON: %s\n%s", e, cleaned[:500])
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    logger.info("Plan generated: %d phases", len(data.get("phases", [])))
    return LearningPlan(**data)
