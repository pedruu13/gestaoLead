"""Cost calculation for AI model tokens."""

from typing import Dict, Tuple

# Preços por 1 Milhão de tokens (USD)
MODEL_PRICING_USD_PER_MILLION: Dict[str, Dict[str, float]] = {
    # Google Gemini
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Anthropic Claude
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    # Modelos locais / heurísticos
    "ollama": {"input": 0.0, "output": 0.0},
    "local": {"input": 0.0, "output": 0.0},
    "default": {"input": 0.10, "output": 0.40},
}

DEFAULT_USD_BRL_RATE = 5.80


def calculate_model_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    usd_brl_rate: float = DEFAULT_USD_BRL_RATE,
) -> Tuple[float, float]:
    """
    Calcula o custo estimado de uma chamada de modelo em USD e BRL.
    Retorna (cost_usd, cost_brl).
    """
    normalized_name = (model_name or "default").lower().strip()
    pricing = MODEL_PRICING_USD_PER_MILLION.get("default")
    for key, val in MODEL_PRICING_USD_PER_MILLION.items():
        if key in normalized_name:
            pricing = val
            break

    input_cost = (prompt_tokens / 1_000_000.0) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000.0) * pricing["output"]
    total_cost_usd = round(input_cost + output_cost, 6)
    total_cost_brl = round(total_cost_usd * usd_brl_rate, 4)

    return total_cost_usd, total_cost_brl
