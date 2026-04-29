import logging
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

load_dotenv()

from curriculum_engine.planner import generate_plan, get_client
from curriculum_engine.retrieval import enrich_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HOURS_MIN = 1
HOURS_MAX = 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.anthropic = get_client()
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="Curriculum Engine",
    description="Generates verified learning plans: Claude structures the curriculum, live APIs supply the resources.",
    version="1.0.0",
    lifespan=lifespan,
)


class PlanRequest(BaseModel):
    subject: str
    hours: int = 10


@app.post("/plan")
async def create_plan(req: PlanRequest, request: Request):
    """Generate a learning plan with live, validated resource links."""
    if not req.subject.strip():
        raise HTTPException(status_code=400, detail="subject must not be empty.")
    if not (HOURS_MIN <= req.hours <= HOURS_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"hours must be between {HOURS_MIN} and {HOURS_MAX}.",
        )

    try:
        plan = generate_plan(req.subject.strip(), req.hours, request.app.state.anthropic)
        plan = await enrich_plan(plan, request.app.state.http)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")

    return plan


@app.get("/health")
def health():
    return {"status": "ok"}
