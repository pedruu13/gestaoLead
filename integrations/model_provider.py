"""Unified model provider gateway for interchangeable AI models."""

import os
import math
from typing import Dict, Any, Optional


class ModelGateway:
    """
    Roteador de modelos intercambiáveis (Gemini, OpenAI, Claude, Local).
    Fornece:
    - Normalização de nomes de modelos
    - Estimativa e contagem de tokens
    - Verificação de chaves e disponibilidade
    """

    MODEL_ALIASES: Dict[str, str] = {
        "flash": "gemini-2.0-flash",
        "gemini-flash": "gemini-2.0-flash",
        "gemini-2.0": "gemini-2.0-flash",
        "gemini-pro": "gemini-1.5-pro",
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-mini": "gpt-4o-mini",
        "gpt-4o": "gpt-4o",
        "claude-haiku": "claude-3-5-haiku",
        "claude-sonnet": "claude-3-5-sonnet",
        "local": "local",
        "ollama": "ollama",
    }

    @classmethod
    def resolve_model_name(cls, alias: Optional[str]) -> str:
        if not alias:
            return "gemini-2.0-flash"
        normalized = alias.lower().strip()
        return cls.MODEL_ALIASES.get(normalized, alias)

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Estimativa conservadora de tokens baseada em caracteres (~4 chars/token)."""
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 3.8))

    @classmethod
    def provider_status(cls) -> Dict[str, Any]:
        """Informa quais provedores possuem credenciais ativas."""
        has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
        has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

        return {
            "gemini": {
                "available": has_gemini,
                "preferred_model": "gemini-2.0-flash",
                "default": True,
            },
            "openai": {
                "available": has_openai,
                "preferred_model": "gpt-4o-mini",
                "default": False,
            },
            "anthropic": {
                "available": has_anthropic,
                "preferred_model": "claude-3-5-haiku",
                "default": False,
            },
            "local": {
                "available": True,
                "preferred_model": "local",
                "default": False,
            },
        }
