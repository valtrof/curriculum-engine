from typing import Literal
from pydantic import BaseModel

ResourceType = Literal["video", "article", "book", "course", "practice"]


class Resource(BaseModel):
    title: str
    resource_type: ResourceType
    estimated_minutes: int
    search_query: str
    preferred_source: str
    description: str
    url: str | None = None
    retrieved_title: str | None = None
    channel: str | None = None


class Phase(BaseModel):
    phase: int
    title: str
    hours: float
    description: str
    resources: list[Resource]
    milestone: str


class LearningPlan(BaseModel):
    subject: str
    total_hours: float
    overview: str
    phases: list[Phase]
