"""Deterministic analytics layer.

Everything quantitative in Strength Intelligence happens here, in plain Python,
before any model is called. The agents receive the structured output of these
functions -- never raw CSV rows -- so no number in a response can be an LLM
hallucination.
"""
from .loaders import Dataset, load_dataset, load_profile
from .strength_metrics import strength_summary
from .nutrition_metrics import nutrition_summary
from .weight_metrics import weight_summary
from .context_metrics import context_summary
from .snapshot import build_snapshot

__all__ = [
    "Dataset",
    "load_dataset",
    "load_profile",
    "strength_summary",
    "nutrition_summary",
    "weight_summary",
    "context_summary",
    "build_snapshot",
]
