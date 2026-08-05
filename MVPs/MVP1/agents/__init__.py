"""Agent layer: interpretation, synthesis, and routing.

Nothing in this package computes a metric. Every number an agent uses arrives
pre-computed from the analytics layer.
"""
from . import fueling_agent, orchestrator, strength_agent
from .router import route
from .orchestrator import ask

__all__ = ["strength_agent", "fueling_agent", "orchestrator", "route", "ask"]
