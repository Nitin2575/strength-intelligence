"""Shared model-call plumbing.

Every agent calls through `complete_json`. If no API key is configured the call
raises `LLMUnavailable` and the agent falls back to its deterministic reviewer,
so the whole system runs end-to-end with zero setup.
"""
from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 1600


class LLMUnavailable(RuntimeError):
    """No API key configured, or the model call failed."""


def llm_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def model_name() -> str:
    return os.environ.get("STRENGTH_INTELLIGENCE_MODEL", DEFAULT_MODEL)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.removeprefix("json").strip()
        if text.endswith("```"):
            text = text[: text.rindex("```")]
    return text.strip()


def complete_json(system: str, payload: dict[str, Any], *,
                  model: str | None = None) -> dict[str, Any]:
    """Send a structured payload, expect a JSON object back."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set.")

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise LLMUnavailable(f"anthropic package not installed: {exc}") from exc

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model or model_name(),
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        result = json.loads(_strip_fences(text))
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        raise LLMUnavailable(str(exc)) from exc

    if not isinstance(result, dict):
        raise LLMUnavailable("Model did not return a JSON object.")
    result["_model"] = model or model_name()
    return result
