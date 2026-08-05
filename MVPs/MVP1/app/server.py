"""FastAPI backend for Strength Intelligence.

Three endpoints:
  GET  /api/dashboard  -- computed metrics plus the standing intelligence read
  POST /api/ask        -- route a question through the agents
  GET  /api/health     -- whether the LLM path is configured

The dataset is loaded fresh per request. That is deliberate: it means dropping
new CSVs into data/ and refreshing the page picks them up, with no restart and
no cache to invalidate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents import ask as ask_agents  # noqa: E402
from agents.llm import llm_enabled, model_name  # noqa: E402
from agents.orchestrator import current_intelligence  # noqa: E402
from analytics import build_snapshot, load_dataset  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Strength Intelligence", version="0.1.0",
              description="A Helyx Labs project. Code calculates; AI interprets.")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


def _snapshot():
    return build_snapshot(load_dataset())


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_enabled": llm_enabled(),
        "model": model_name() if llm_enabled() else None,
        "reasoning_path": "llm" if llm_enabled() else "deterministic",
        "note": ("Interpretation is model-written." if llm_enabled() else
                 "No ANTHROPIC_API_KEY set — running the deterministic reviewer. "
                 "All metrics are identical either way; only the prose differs."),
    }


@app.get("/api/dashboard")
def dashboard():
    snapshot = _snapshot()
    if not snapshot.get("as_of"):
        raise HTTPException(status_code=503,
                            detail="No data found. Run: python scripts/generate_sample_data.py")

    intelligence = current_intelligence(snapshot)
    strength = snapshot["strength"]
    weight = snapshot["weight"]

    return {
        "as_of": snapshot["as_of"],
        "profile": snapshot["profile"],
        "goal": {
            "goal_type": snapshot["profile"].get("goal_type"),
            "starting_weight": snapshot["profile"].get("starting_weight"),
            "target_weight": snapshot["profile"].get("target_weight"),
            "calorie_target": snapshot["profile"].get("calorie_target"),
            "protein_target": snapshot["profile"].get("protein_target"),
            "carb_target": snapshot["profile"].get("carb_target"),
            "fat_target": snapshot["profile"].get("fat_target"),
            "target_rate_of_change": snapshot["profile"].get("target_rate_of_change"),
        },
        "strength": {
            "as_of": strength.get("as_of"),
            "sessions_per_week_last_30d": strength.get("sessions_per_week_last_30d"),
            "training_days_last_30d": strength.get("training_days_last_30d"),
            "fastest_progressing": strength.get("fastest_progressing"),
            "lifts": [{
                "exercise": l["exercise"],
                "status": l["status"],
                "status_reason": l.get("status_reason"),
                "qualifier": l.get("qualifier"),
                "e1rm_change_30d_pct": l.get("e1rm_change_30d_pct"),
                "current_e1rm": l.get("current_e1rm"),
                "current_working_weight": l.get("current_working_weight"),
                "session_variability_pct": l.get("session_variability_pct"),
                "sessions_last_30d": l.get("sessions_last_30d"),
                "relative_strength": l.get("relative_strength"),
                "recent_exposures": l.get("recent_exposures"),
                "pr": l.get("pr"),
                "history": [{"date": s["date"], "e1rm": s["e1rm"]}
                            for s in (l.get("session_history") or [])],
            } for l in strength.get("lifts", [])],
        },
        "weight": weight,
        "nutrition": {
            "last_7_days": snapshot["nutrition"].get("last_7_days"),
            "last_30_days": snapshot["nutrition"].get("last_30_days"),
            "adherence_30d": snapshot["nutrition"].get("adherence_30d"),
            "targets": snapshot["nutrition"].get("targets"),
        },
        "context": snapshot["context"],
        "intelligence": intelligence,
        "data_coverage": snapshot["data_coverage"],
        "reasoning_path": intelligence.get("path"),
    }


@app.post("/api/ask")
def ask(req: AskRequest):
    snapshot = _snapshot()
    if not snapshot.get("as_of"):
        raise HTTPException(status_code=503,
                            detail="No data found. Run: python scripts/generate_sample_data.py")
    return ask_agents(req.question.strip(), snapshot)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
