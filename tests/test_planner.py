import json
import pytest
from unittest.mock import MagicMock, patch

from curriculum_engine.planner import generate_plan, get_client
from curriculum_engine.models import LearningPlan

SAMPLE_PLAN = {
    "subject": "Python",
    "total_hours": 10,
    "overview": "A concise Python learning journey.",
    "phases": [
        {
            "phase": 1,
            "title": "Foundations",
            "hours": 5,
            "description": "Core syntax and data structures.",
            "resources": [
                {
                    "title": "Python Basics",
                    "resource_type": "video",
                    "estimated_minutes": 60,
                    "search_query": "python basics tutorial beginners",
                    "preferred_source": "YouTube",
                    "description": "Covers variables, loops, and functions.",
                }
            ],
            "milestone": "Write simple Python scripts.",
        }
    ],
}


def _make_client_mock(response_text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_generate_plan_returns_learning_plan():
    client = _make_client_mock(json.dumps(SAMPLE_PLAN))
    plan = generate_plan("Python", 10, client)
    assert isinstance(plan, LearningPlan)
    assert plan.subject == "Python"
    assert plan.total_hours == 10


def test_generate_plan_parses_phases():
    client = _make_client_mock(json.dumps(SAMPLE_PLAN))
    plan = generate_plan("Python", 10, client)
    assert len(plan.phases) == 1
    assert plan.phases[0].title == "Foundations"


def test_generate_plan_parses_resources():
    client = _make_client_mock(json.dumps(SAMPLE_PLAN))
    plan = generate_plan("Python", 10, client)
    resource = plan.phases[0].resources[0]
    assert resource.resource_type == "video"
    assert resource.search_query == "python basics tutorial beginners"


def test_generate_plan_strips_code_fences():
    fenced = f"```json\n{json.dumps(SAMPLE_PLAN)}\n```"
    client = _make_client_mock(fenced)
    plan = generate_plan("Python", 10, client)
    assert plan.subject == "Python"


def test_generate_plan_raises_on_invalid_json():
    client = _make_client_mock("not json at all")
    with pytest.raises(ValueError, match="invalid JSON"):
        generate_plan("Python", 10, client)


def test_generate_plan_passes_subject_and_hours_to_llm():
    client = _make_client_mock(json.dumps(SAMPLE_PLAN))
    generate_plan("Stoicism", 20, client)
    call_kwargs = client.messages.create.call_args[1]
    user_content = call_kwargs["messages"][0]["content"]
    assert "Stoicism" in user_content
    assert "20" in user_content


def test_generate_plan_uses_prompt_caching():
    client = _make_client_mock(json.dumps(SAMPLE_PLAN))
    generate_plan("Python", 10, client)
    system_arg = client.messages.create.call_args[1]["system"]
    assert isinstance(system_arg, list)
    assert system_arg[0].get("cache_control") == {"type": "ephemeral"}


def test_get_client_raises_when_api_key_missing():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_client()


def test_get_client_returns_anthropic_instance():
    import anthropic
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        client = get_client()
    assert isinstance(client, anthropic.Anthropic)
