"""Agents package for gestaoLead AI Workforce."""

from .registry import AGENT_ROSTER, get_agent_metadata, list_available_agents
from .base_agent import BaseAgent

__all__ = [
    "AGENT_ROSTER",
    "get_agent_metadata",
    "list_available_agents",
    "BaseAgent",
]
