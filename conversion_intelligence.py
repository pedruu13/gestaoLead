from collections import defaultdict

from target_intelligence import normalize


POSITIVE_OUTCOMES = {"Respondeu", "Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"}
VALID_OUTCOMES = {"Contatado", *POSITIVE_OUTCOMES, "Sem interesse"}


def calculate_conversion_metrics(rows, minimum_sample=10):
    groups = defaultdict(lambda: {"contacted": 0, "responses": 0, "interest": 0, "meetings": 0, "proposals": 0, "closed": 0, "no_interest": 0})
    for row in rows:
        outcome = str(row.get("commercial_outcome") or "").strip()
        if outcome not in VALID_OUTCOMES:
            continue
        dimensions = (
            ("niche", normalize(row.get("nicho"))),
            ("city", normalize(row.get("bairro"))),
            ("source", normalize(row.get("lead_source") or "desconhecida")),
        )
        for dimension, value in dimensions:
            if not value:
                continue
            metrics = groups[(dimension, value)]
            metrics["contacted"] += 1
            metrics["responses"] += int(outcome in POSITIVE_OUTCOMES)
            metrics["interest"] += int(outcome in {"Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"})
            metrics["meetings"] += int(outcome in {"Reunião agendada", "Proposta enviada", "Contrato fechado"})
            metrics["proposals"] += int(outcome in {"Proposta enviada", "Contrato fechado"})
            metrics["closed"] += int(outcome == "Contrato fechado")
            metrics["no_interest"] += int(outcome == "Sem interesse")
    result = {}
    for key, metrics in groups.items():
        sample = metrics["contacted"]
        metrics.update({
            "sufficient_sample": sample >= minimum_sample,
            "response_rate": round(metrics["responses"] * 100 / sample, 1) if sample else 0,
            "interest_rate": round(metrics["interest"] * 100 / sample, 1) if sample else 0,
            "close_rate": round(metrics["closed"] * 100 / sample, 1) if sample else 0,
        })
        result[key] = metrics
    return result


def performance_adjustment(metrics, niche, city, source, minimum_sample=10):
    values = []
    for key in (("niche", normalize(niche)), ("city", normalize(city)), ("source", normalize(source))):
        item = metrics.get(key)
        if item and item["contacted"] >= minimum_sample:
            values.append(min(8, item["response_rate"] * 0.05 + item["close_rate"] * 0.15 - item["no_interest"] * 0.15))
    return round(sum(values) / len(values), 1) if values else 0
