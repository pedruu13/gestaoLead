import re


SCORE_VERSION = "2.0"
DEFAULT_WEIGHTS = {
    "necessidade_digital": 30,
    "adequacao_servico": 25,
    "capacidade_contato": 20,
    "atividade_publica": 15,
    "qualidade_evidencia": 10,
}

HIGH_FIT_TERMS = (
    "advoc", "arquitet", "clinic", "clín", "dent", "dermat", "estét", "estet",
    "engenh", "imob", "móveis", "moveis", "planejad", "reforma", "solar",
)
MEDIUM_FIT_TERMS = (
    "contab", "consult", "constru", "educa", "fisi", "manuten", "restaur", "seguro",
    "terap", "veter",
)


def _number(value):
    digits = re.findall(r"\d+", str(value or "").replace(".", "").replace(",", ""))
    return int("".join(digits)) if digits else 0


def _rating(value):
    try:
        return max(0.0, min(5.0, float(str(value or "0").replace(",", "."))))
    except (TypeError, ValueError):
        return 0.0


def _weights(configured=None):
    if not isinstance(configured, dict):
        return dict(DEFAULT_WEIGHTS)
    try:
        candidate = {key: int(configured.get(key, value)) for key, value in DEFAULT_WEIGHTS.items()}
    except (TypeError, ValueError):
        return dict(DEFAULT_WEIGHTS)
    if any(value < 0 for value in candidate.values()) or sum(candidate.values()) != 100:
        return dict(DEFAULT_WEIGHTS)
    return candidate


def _scaled(points, maximum, weight):
    return round((points / maximum) * weight) if maximum else 0


def score_lead(lead, has_own_site, configured_weights=None):
    weights = _weights(configured_weights)
    category = str(lead.get("Categoria Maps") or lead.get("Nicho") or lead.get("nicho") or "").casefold()
    location = str(lead.get("Bairro") or lead.get("bairro") or "").strip()
    phone = str(lead.get("Telefone") or lead.get("telefone") or "").strip()
    email = str(lead.get("E-mail Encontrado") or lead.get("email") or "").strip()
    instagram = str(lead.get("Instagram") or lead.get("instagram") or "").strip()
    facebook = str(lead.get("Facebook") or lead.get("facebook") or "").strip()
    linkedin = str(lead.get("LinkedIn") or lead.get("linkedin") or "").strip()
    rating = _rating(lead.get("Nota Maps") or lead.get("nota"))
    reviews = _number(lead.get("Qtd Avaliacoes") or lead.get("avaliacoes"))

    need_raw = 10 if not has_own_site else 2
    fit_raw = 10 if any(term in category for term in HIGH_FIT_TERMS) else 8 if any(term in category for term in MEDIUM_FIT_TERMS) else 6 if category else 3
    contact_raw = min(10, (4 if phone else 0) + (4 if email else 0) + (2 if instagram or facebook or linkedin else 0))
    rating_raw = 5 if rating >= 4.5 else 4 if rating >= 4.2 else 3 if rating >= 3.8 else 1 if rating else 0
    reviews_raw = 5 if reviews >= 30 else 4 if reviews >= 15 else 3 if reviews >= 8 else 1 if reviews else 0
    activity_raw = rating_raw + reviews_raw
    evidence_raw = min(10, sum((
        2 if category else 0,
        2 if location else 0,
        2 if rating else 0,
        2 if reviews else 0,
        2 if phone or email else 0,
    )))

    dimensions = {
        "necessidade_digital": {
            "label": "Necessidade digital",
            "score": _scaled(need_raw, 10, weights["necessidade_digital"]),
            "max": weights["necessidade_digital"],
            "evidence": "Nenhum site próprio identificado no perfil consultado" if not has_own_site else "Site próprio identificado; qualidade ainda não auditada",
        },
        "adequacao_servico": {
            "label": "Adequação ao serviço",
            "score": _scaled(fit_raw, 10, weights["adequacao_servico"]),
            "max": weights["adequacao_servico"],
            "evidence": f"Segmento identificado: {category or 'não informado'}",
        },
        "capacidade_contato": {
            "label": "Capacidade de contato",
            "score": _scaled(contact_raw, 10, weights["capacidade_contato"]),
            "max": weights["capacidade_contato"],
            "evidence": ", ".join(label for label, present in (("telefone", phone), ("e-mail", email), ("rede social", instagram or facebook or linkedin)) if present) or "Nenhum canal comercial confirmado",
        },
        "atividade_publica": {
            "label": "Atividade pública",
            "score": _scaled(activity_raw, 10, weights["atividade_publica"]),
            "max": weights["atividade_publica"],
            "evidence": f"Nota {rating:g} e {reviews} avaliações públicas" if rating or reviews else "Sem nota ou avaliações confirmadas",
        },
        "qualidade_evidencia": {
            "label": "Qualidade das evidências",
            "score": _scaled(evidence_raw, 10, weights["qualidade_evidencia"]),
            "max": weights["qualidade_evidencia"],
            "evidence": "Pontua somente campos públicos preenchidos; não representa chance garantida de compra",
        },
    }
    total = min(100, sum(item["score"] for item in dimensions.values()))
    strongest = sorted(dimensions.values(), key=lambda item: item["score"], reverse=True)[:3]
    reason = "; ".join(f"{item['label']}: {item['score']}/{item['max']}" for item in strongest)
    return {
        "score": total,
        "range": "Prioridade" if total >= 55 else "Oportunidade secundária" if total >= 35 else "Exploração",
        "reason": reason,
        "version": SCORE_VERSION,
        "dimensions": dimensions,
        "weights": weights,
        "disclaimer": "Pontuação de priorização comercial, não probabilidade de compra.",
    }
