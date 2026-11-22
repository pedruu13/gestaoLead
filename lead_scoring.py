import re
import unicodedata

from contact_quality import assess_phone, normalize_email, validate_phone_city_compatibility


SCORE_VERSION = "4.0"
DEFAULT_WEIGHTS = {
    "necessidade_digital": 30,
    "adequacao_servico": 25,
    "capacidade_contato": 20,
    "atividade_publica": 15,
    "qualidade_evidencia": 10,
}

HIGH_FIT_TERMS = (
    "advoc", "advogad", "arquitet", "clinic", "dent", "odont", "dermat",
    "engenh", "imob", "moveis", "planejad", "reforma", "solar", "oftalm", "cirurg",
    "ortoped", "ortodont", "implant", "psiquiat", "blindag", "seguranca eletr", "pericia",
    "interiores", "decor",
)
MEDIUM_FIT_TERMS = (
    "contab", "consult", "constru", "educa", "fisi", "manuten", "restaur", "seguro",
    "terap", "veter", "academ", "escola", "treinamento", "hotel", "pousada", "grafica",
)
LOW_FIT_TERMS = (
    "chaveir", "borrach", "banca", "ambul", "lanchon", "brecho",
    "papelaria", "sucata", "reciclagem", "pesqueiro", "bar de bairro",
)

AESTHETIC_HIGH_FIT_MARKERS = (
    "harmonizac", "biomedic", "injetav", "botox", "toxina", "preenchiment",
    "bioestimulador", "fios de sustentacao", "dermatolog", "cirurgi", "plastica",
    "emagrecimento", "estetica medica", "clinica de estetica",
    "clinica estetica", "instituto de estetica", "centro de estetica", "laser",
    "ozonioterapia",
)

AESTHETIC_REDUCED_FIT_MARKERS = (
    "sobrancelh", "cilio", "lash", "microblading", "micropigment",
    "unha", "nail", "manicure", "pedicure", "depilacao simples",
    "depiladora", "depilacao com cera", "maquiagem definitiva",
    "salao de sobrancelh", "designer de sobrancelh", "alongamento de unha",
)

AESTHETIC_CONTEXT_MARKERS = (
    "estet", "beleza", "sobrancelh", "cilio", "lash", "microblading", "micropigment",
    "unha", "nail", "manicure", "pedicure", "depila", "harmonizac", "biomedic",
    "injetav", "botox", "toxina", "preenchiment", "bioestimulador", "dermatolog",
    "maquiagem", "salao de beleza", "centro de saude e beleza", "centro de beleza",
    "spa",
)

SOCIAL_BIO_DOMAINS = (
    "instagram.com", "instagr.am", "facebook.com", "fb.me", "wa.me", "api.whatsapp.com",
    "linktr.ee", "linktree", "bio.site", "beacons.ai", "campsite.bio", "flowcode.com",
    "taplink.cc", "heylink.me", "app.linkr.bio",
)


def _normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return text.casefold().strip()


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


def score_lead(lead, has_own_site, configured_weights=None, performance_adjustment=0):
    weights = _weights(configured_weights)
    category_raw = str(lead.get("Categoria Maps") or lead.get("Nicho") or lead.get("nicho") or "")
    category = _normalize_text(category_raw)
    name_raw = str(lead.get("Nome") or lead.get("name") or "")
    name = _normalize_text(name_raw)
    services_raw = str(lead.get("Serviços") or lead.get("servicos") or lead.get("services") or "")
    services = _normalize_text(services_raw)
    location = str(lead.get("Bairro") or lead.get("bairro") or "").strip()
    phone = str(lead.get("Telefone") or lead.get("telefone") or "").strip()
    email = str(lead.get("E-mail Encontrado") or lead.get("email") or "").strip()
    instagram = str(lead.get("Instagram") or lead.get("instagram") or "").strip()
    facebook = str(lead.get("Facebook") or lead.get("facebook") or "").strip()
    linkedin = str(lead.get("LinkedIn") or lead.get("linkedin") or "").strip()
    website = str(lead.get("Link Inicial") or lead.get("link_inicial") or lead.get("website") or "").strip().casefold()
    rating = _rating(lead.get("Nota Maps") or lead.get("nota"))
    reviews = _number(lead.get("Qtd Avaliacoes") or lead.get("avaliacoes"))
    validation_status = str(lead.get("Status Validação") or lead.get("validation_status") or "NÃO VERIFICADO").upper()
    site_confidence = str(lead.get("Confiança do Site") or lead.get("site_confidence") or "NÃO VERIFICADO").upper()
    source_count = max(1, _number(lead.get("Quantidade de Fontes") or lead.get("source_count") or 1))
    region = str(lead.get("Mercado") or lead.get("region") or "br").lower()
    phone_quality = assess_phone(phone, region if region in {"br", "us"} else "europa")
    city_name = str(lead.get("Cidade") or lead.get("cidade") or "").strip()
    full_location = f"{location} {city_name}".strip()
    phone_compat = validate_phone_city_compatibility(phone, full_location, region)
    ddd_divergent = bool(not phone_compat["compatible"] and phone_compat["level"] == "warning")
    valid_email = normalize_email(email)

    site_opportunity = str(
        lead.get("Oportunidade do Site")
        or lead.get("site_opportunity_status")
        or ""
    ).strip()

    is_social_or_bio = any(domain in website for domain in SOCIAL_BIO_DOMAINS)
    has_social_presence = bool(instagram or facebook or linkedin or is_social_or_bio)

    # 1. Necessidade Digital
    if not has_own_site:
        if is_social_or_bio or has_social_presence:
            need_raw = 10
            need_evidence = "Dependência de rede social (Instagram/Linktree/WhatsApp) sem site próprio estruturado"
        elif site_confidence == "CONFIRMADO":
            need_raw = 10
            need_evidence = "Ausência de site confirmada pelas evidências armazenadas"
        elif site_confidence == "PROVÁVEL":
            need_raw = 9
            need_evidence = "Mais de uma evidência pública não apresentou site próprio"
        else:
            need_raw = 7
            need_evidence = "Nenhum site foi localizado, mas a ausência ainda não está confirmada"
    elif site_opportunity == "Site com oportunidade de melhoria":
        need_raw = 7
        need_evidence = "Site próprio com sinais objetivos de melhoria na auditoria automática"
    elif site_opportunity == "Revisão manual":
        need_raw = 4
        need_evidence = "Site próprio encontrado, mas sem conteúdo suficiente para avaliação automática"
    else:
        need_raw = 2
        need_evidence = "Site próprio encontrado sem fragilidade objetiva confirmada"

    # 2. Adequação ao Serviço (Ticket e fit comercial)
    full_niche_context = f"{name} {category} {services}".strip()
    is_aesthetic_context = any(m in full_niche_context for m in AESTHETIC_CONTEXT_MARKERS)

    if is_aesthetic_context:
        has_high_markers = any(m in full_niche_context for m in AESTHETIC_HIGH_FIT_MARKERS)
        has_doctor = (
            any(t in f"{name} {instagram} {website}" for t in ("dra.", "dra ", "dr.", "dr ", "doutor", "doutora", "dra_"))
            and any(t in full_niche_context for t in ("estet", "harmoniz", "pele", "facial", "corporal"))
        )
        is_structured_clinic = (
            any(c in category for c in ("clinica especializada", "clinica medica", "clinica dermatologica", "servico de emagrecimento", "clinica de estetica", "clinica estetica", "instituto de estetica", "centro de estetica"))
            and any(t in full_niche_context for t in ("estet", "harmoniz", "facial", "corporal", "emagrecimento"))
        )
        is_high_potential = has_high_markers or has_doctor or is_structured_clinic

        has_reduced_markers = any(m in full_niche_context for m in AESTHETIC_REDUCED_FIT_MARKERS)
        is_simple_salon = "salao de beleza" in category and not is_high_potential
        is_reduced_potential = has_reduced_markers or is_simple_salon

        # Regra de Proteção: Não penalizar clínicas completas que também ofereçam serviços básicos
        if is_high_potential:
            fit_raw = 10
            fit_evidence = f"Clínica de estética estruturada / procedimentos de alto valor: {category_raw or name_raw}"
        elif is_reduced_potential:
            fit_raw = 4
            fit_evidence = f"Segmento de microsserviços de beleza/estética de ticket reduzido (sobrancelhas, cílios, unhas ou micropigmentação): {category_raw or name_raw}"
        else:
            # Estética geral sem estrutura clínica avançada nem microsserviços básicos
            fit_raw = 8
            fit_evidence = f"Estética geral ou serviços de beleza intermediários: {category_raw or name_raw}"
    elif any(term in category for term in LOW_FIT_TERMS):
        fit_raw = 4
        fit_evidence = f"Segmento com menor propensão ou ticket médio reduzido: {category_raw or category}"
    elif any(term in category for term in ("fisi", "veter", "terap", "pilates", "academ", "escola", "treinamento", "hotel", "pousada", "restaur", "buffet", "grafica", "contab", "consult")):
        fit_raw = 8
        fit_evidence = f"Segmento de ticket intermediário: {category_raw or category}"
    elif any(term in category for term in HIGH_FIT_TERMS):
        fit_raw = 10
        fit_evidence = f"Segmento de alto valor agregado e alta demanda de captação: {category_raw or category}"
    elif category:
        fit_raw = 6
        fit_evidence = f"Segmento identificado: {category_raw or category}"
    else:
        fit_raw = 3
        fit_evidence = "Segmento não informado"

    # 3. Capacidade de Contato
    has_mobile = bool(phone_quality["valid"] and phone_quality["mobile"])
    has_landline = bool(phone_quality["valid"] and not phone_quality["mobile"])
    contact_points = (
        (5 if has_mobile else 3 if has_landline else 0)
        + (3 if valid_email else 0)
        + (2 if has_social_presence else 0)
    )
    contact_raw = min(10, contact_points)

    # 4. Atividade Pública
    rating_raw = 5 if rating >= 4.5 else 4 if rating >= 4.2 else 3 if rating >= 3.8 else 1 if rating else 0
    reviews_raw = 5 if reviews >= 30 else 4 if reviews >= 15 else 3 if reviews >= 8 else 1 if reviews else 0
    activity_raw = rating_raw + reviews_raw

    # 5. Qualidade das Evidências
    evidence_base = sum((
        3 if validation_status == "CONFIRMADO" else 2 if validation_status == "PROVÁVEL" else 0,
        2 if source_count >= 2 else 1,
        2 if category and location else 0,
        2 if rating or reviews else 0,
        1 if phone_quality["valid"] or valid_email else 0,
    ))
    if ddd_divergent:
        evidence_base = max(1, evidence_base - 2)
    evidence_raw = min(10, evidence_base)

    evidence_text = f"Validação {validation_status}; {source_count} fonte(s); confiança do site {site_confidence}"
    if ddd_divergent:
        evidence_text += f"; Alerta: {phone_compat['warning']}"

    dimensions = {
        "necessidade_digital": {
            "label": "Necessidade digital",
            "score": _scaled(need_raw, 10, weights["necessidade_digital"]),
            "max": weights["necessidade_digital"],
            "evidence": need_evidence,
        },
        "adequacao_servico": {
            "label": "Adequação ao serviço",
            "score": _scaled(fit_raw, 10, weights["adequacao_servico"]),
            "max": weights["adequacao_servico"],
            "evidence": fit_evidence,
        },
        "capacidade_contato": {
            "label": "Capacidade de contato",
            "score": _scaled(contact_raw, 10, weights["capacidade_contato"]),
            "max": weights["capacidade_contato"],
            "evidence": ", ".join(label for label, present in (
                ("WhatsApp/Celular comercial", has_mobile),
                ("Telefone fixo", has_landline),
                ("E-mail corporativo", bool(valid_email)),
                ("Rede social ativa", has_social_presence)
            ) if present) or "Nenhum canal comercial confirmado",
        },
        "atividade_publica": {
            "label": "Atividade pública",
            "score": _scaled(activity_raw, 10, weights["atividade_publica"]),
            "max": weights["atividade_publica"],
            "evidence": f"Nota {rating:g} e {reviews} avaliações públicas" if rating or reviews else "Sem nota ou avaliações confirmadas (0 pontos)",
        },
        "qualidade_evidencia": {
            "label": "Qualidade das evidências",
            "score": _scaled(evidence_raw, 10, weights["qualidade_evidencia"]),
            "max": weights["qualidade_evidencia"],
            "evidence": evidence_text,
        },
    }

    try:
        adjustment = max(-8, min(8, float(performance_adjustment or 0)))
    except (TypeError, ValueError):
        adjustment = 0

    total = max(0, min(100, round(sum(item["score"] for item in dimensions.values()) + adjustment)))

    # Regras de Proteção e Eliminação de Falsos Positivos
    # 1. Trava de Site Existente:
    # Se a empresa já tem site saudável, não há oportunidade imediata (máx 54 pts).
    # Se o site próprio foi auditado com falhas, é uma Boa Oportunidade (máx 78 pts).
    # Alta Prioridade (80+) é reservada estritamente para quem não tem site próprio.
    if has_own_site:
        if site_opportunity == "Site com oportunidade de melhoria":
            total = min(total, 78)
        else:
            total = min(total, 54)

    # 2. Exigência de WhatsApp comercial para Alta Prioridade:
    # Sem canal móvel ágil (apenas fixo ou sem celular), não atinge Alta Prioridade (máx 75 pts).
    if not has_mobile:
        total = min(total, 75)

    # 2b. Telefone fixo sem outros canais de contato:
    # Se a empresa possui apenas telefone fixo tradicional (sem celular/WhatsApp), sem e-mail e sem presença social:
    if has_landline and not has_mobile and not valid_email and not has_social_presence:
        total = min(total, 54)

    # 2c. Alerta de DDD divergente da localidade:
    # Penalização leve (-4 pts) sem descartar automaticamente número legítimo:
    if ddd_divergent:
        total = max(0, total - 4)

    # 3. Exigência de Nicho de Alto Ticket para Alta Prioridade:
    # Nichos de ticket intermediário (academias, pousadas, veterinárias) são Boas Oportunidades (máx 78 pts).
    if fit_raw < 10:
        total = min(total, 78)

    # 4. Nichos informais ou de baixo ticket médio (borracharias, chaveiros, ambulantes, bancas):
    if fit_raw <= 4:
        total = min(total, 54)

    # 5. Ausência de site não é certeza de compra:
    # Sem canal móvel/WhatsApp e com pouca ou nenhuma atividade pública (empresa inativa/fantasma).
    if not has_own_site and not has_mobile and activity_raw <= 2:
        total = min(total, 54)

    # 6. Leads Inalcançáveis / Sem Canal de Contato Comercial Válido:
    # Se não tem celular, fixo nem e-mail, é Baixa Prioridade (máx 39 pts).
    if not has_mobile and not has_landline and not valid_email:
        total = min(total, 39)

    # 7. Telefone comprovadamente inválido na validação:
    if not phone_quality["valid"] and not valid_email:
        total = min(total, 35)

    # 8. Status de validação não verificado:
    if validation_status == "NÃO VERIFICADO":
        if not has_mobile and not valid_email:
            total = min(total, 35)
        else:
            total = min(total, 54)
    elif not has_own_site and site_confidence == "NÃO VERIFICADO":
        total = min(total, 64)

    # Classificação por faixas transparentes
    if total >= 80:
        classification = "Alta prioridade"
    elif total >= 60:
        classification = "Boa oportunidade"
    elif total >= 40:
        classification = "Oportunidade moderada"
    else:
        classification = "Baixa prioridade"

    strongest = sorted(dimensions.values(), key=lambda item: item["score"], reverse=True)[:3]
    reason = "; ".join(f"{item['label']}: {item['score']}/{item['max']}" for item in strongest)

    return {
        "score": total,
        "classification": classification,
        "tier": classification,
        "range": "Prioridade" if total >= 55 else "Oportunidade secundária" if total >= 35 else "Exploração",
        "priority": "Alta" if total >= 70 else "Média" if total >= 45 else "Baixa",
        "reason": reason,
        "version": SCORE_VERSION,
        "dimensions": dimensions,
        "weights": weights,
        "performance_adjustment": adjustment,
        "disclaimer": "Pontuação de priorização comercial, não probabilidade de compra.",
    }
