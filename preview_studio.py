import json
import os
import re
from datetime import datetime, timezone
from hashlib import sha256
from html import escape

from commercial_intelligence import analyze_lead, clean_text


REFERENCE_SETS = {
    "care": [
        "https://www.siteinspire.com/websites/category/health-and-fitness",
        "https://www.siteinspire.com/website/11812-decibel-health",
        "https://www.lapa.ninja/post/vibrantpractice/",
        "https://www.awwwards.com/mobile-excellence-guidelines.pdf",
    ],
    "editorial": [
        "https://www.siteinspire.com/websites/selected",
        "https://www.lapa.ninja/category/health-fitness/",
        "https://assets.awwwards.com/awards/gallery/2023/07/HOT-RIGHT-NOW-BOOK-2023.pdf",
    ],
    "authority": [
        "https://www.siteinspire.com/websites/category/minimal",
        "https://www.lapa.ninja/category/business/",
        "https://www.awwwards.com/mobile-excellence-guidelines.pdf",
    ],
    "portfolio": [
        "https://www.siteinspire.com/websites/selected",
        "https://www.lapa.ninja/post/",
        "https://assets.awwwards.com/awards/gallery/2023/07/HOT-RIGHT-NOW-BOOK-2023.pdf",
    ],
    "technical": [
        "https://www.siteinspire.com/websites/category/minimal",
        "https://www.lapa.ninja/category/business/",
        "https://www.awwwards.com/mobile-excellence-guidelines.pdf",
    ],
    "hospitality": [
        "https://www.siteinspire.com/websites/selected",
        "https://www.lapa.ninja/post/",
        "https://assets.awwwards.com/awards/gallery/2023/07/HOT-RIGHT-NOW-BOOK-2023.pdf",
    ],
    "professional": [
        "https://www.siteinspire.com/websites/category/minimal",
        "https://www.lapa.ninja/category/business/",
        "https://www.awwwards.com/mobile-excellence-guidelines.pdf",
    ],
}


SEGMENT_PROFILES = {
    "saúde": {
        "template": "care", "primary": "#16756d", "surface": "#f2f8f5", "ink": "#17312e",
        "headline": "Informação clara para tornar o primeiro contato mais tranquilo.", "cta": "Agendar atendimento",
        "services": ["Atendimentos e especialidades", "Orientações para a primeira consulta", "Equipe e estrutura"],
        "details": ["Organize as opções de atendimento sem sobrecarregar quem está pesquisando.", "Antecipe dúvidas práticas antes do contato com a recepção.", "Apresente ambiente e equipe somente com materiais aprovados."],
        "section_title": "Um caminho simples da pesquisa ao atendimento.", "mood": "acolhedor, sereno e preciso",
        "heading_font": "'Trebuchet MS', Arial, sans-serif", "body_font": "Arial, sans-serif",
    },
    "odontologia": {
        "template": "care", "primary": "#087aa2", "surface": "#f1f8fa", "ink": "#102e3a",
        "headline": "Confiança começa quando o paciente encontra respostas claras.", "cta": "Agendar avaliação",
        "services": ["Tratamentos e indicações", "Como funciona a avaliação", "Estrutura de atendimento"],
        "details": ["Separe os tratamentos por necessidade para facilitar a compreensão.", "Explique o primeiro passo sem prometer diagnóstico ou resultado.", "Use fotos próprias para transmitir segurança antes da visita."],
        "section_title": "Conteúdo pensado para reduzir dúvidas antes do agendamento.", "mood": "clínico, humano e luminoso",
        "heading_font": "'Palatino Linotype', Georgia, serif", "body_font": "Arial, sans-serif",
    },
    "estética": {
        "template": "editorial", "primary": "#9f4662", "surface": "#fff8f5", "ink": "#3a2027",
        "headline": "Uma apresentação digital com o mesmo cuidado da experiência presencial.", "cta": "Solicitar uma avaliação",
        "services": ["Procedimentos e indicações", "Avaliação personalizada", "Cuidados e orientações"],
        "details": ["Apresente cada procedimento com linguagem simples e responsável.", "Mostre como funciona a avaliação inicial sem criar expectativas irreais.", "Organize orientações que ajudem a cliente a chegar mais preparada."],
        "section_title": "Beleza, informação e atendimento em uma composição editorial.", "mood": "editorial, delicado e contemporâneo",
        "heading_font": "Didot, 'Bodoni MT', Georgia, serif", "body_font": "Arial, sans-serif",
    },
    "advocacia": {
        "template": "authority", "primary": "#b28a45", "surface": "#eee9df", "ink": "#171a1f",
        "headline": "Orientação jurídica apresentada com clareza desde o primeiro contato.", "cta": "Falar com o escritório",
        "services": ["Áreas de atuação", "Como funciona o atendimento", "Canal de contato reservado"],
        "details": ["Organize as áreas atendidas sem transformar o site em um texto jurídico extenso.", "Explique o fluxo inicial do atendimento com objetividade.", "Destaque um canal de contato discreto e fácil de localizar."],
        "section_title": "Seriedade visual para quem precisa tomar uma decisão importante.", "mood": "sóbrio, editorial e seguro",
        "heading_font": "Georgia, 'Times New Roman', serif", "body_font": "Arial, sans-serif",
    },
    "arquitetura": {
        "template": "portfolio", "primary": "#a6533c", "surface": "#f3efe8", "ink": "#25211d",
        "headline": "Projetos apresentados com espaço, ritmo e intenção.", "cta": "Apresentar meu projeto",
        "services": ["Projetos selecionados", "Escopo e processo", "Contato para novos projetos"],
        "details": ["Deixe as imagens aprovadas conduzirem a narrativa do portfólio.", "Mostre etapas do processo sem prometer prazos ou escopos não confirmados.", "Crie um caminho direto para quem deseja apresentar uma demanda."],
        "section_title": "Uma vitrine digital que deixa o trabalho falar primeiro.", "mood": "arquitetônico, tátil e minimalista",
        "heading_font": "'Arial Narrow', Arial, sans-serif", "body_font": "Arial, sans-serif",
    },
    "reformas": {
        "template": "technical", "primary": "#d66625", "surface": "#f6f3ed", "ink": "#252321",
        "headline": "Serviços bem explicados para transformar interesse em orçamento.", "cta": "Solicitar orçamento",
        "services": ["Tipos de reforma", "Etapas do atendimento", "Região e orçamento"],
        "details": ["Separe os serviços para o cliente identificar rapidamente o que precisa.", "Apresente um fluxo demonstrativo de contato, visita e proposta.", "Informe cobertura e condições somente depois de confirmadas."],
        "section_title": "Objetividade para quem precisa planejar uma obra.", "mood": "industrial, direto e organizado",
        "heading_font": "Impact, 'Arial Narrow', sans-serif", "body_font": "Arial, sans-serif",
    },
    "contabilidade": {
        "template": "authority", "primary": "#315fa9", "surface": "#f3f6fa", "ink": "#172640",
        "headline": "Serviços contábeis organizados para decisões empresariais mais claras.", "cta": "Falar com a equipe",
        "services": ["Abertura e regularização", "Rotina fiscal e contábil", "Atendimento a empresas"],
        "details": ["Agrupe serviços por momento da empresa e não por jargão interno.", "Explique quais informações normalmente iniciam o atendimento.", "Direcione cada perfil de cliente para o canal correto."],
        "section_title": "Um site que ajuda o empresário a encontrar respostas.", "mood": "corporativo, confiável e acessível",
        "heading_font": "Georgia, serif", "body_font": "Arial, sans-serif",
    },
    "engenharia": {
        "template": "technical", "primary": "#3d6675", "surface": "#f0f4f5", "ink": "#142a33",
        "headline": "Capacidade técnica apresentada com método e precisão.", "cta": "Solicitar análise",
        "services": ["Projetos e escopos", "Documentação técnica", "Consultoria especializada"],
        "details": ["Organize as frentes de atuação de forma escaneável.", "Mostre etapas e documentos sem atribuir certificações não confirmadas.", "Facilite o envio inicial de uma demanda técnica."],
        "section_title": "Informação técnica sem criar barreiras para o cliente.", "mood": "estrutural, preciso e funcional",
        "heading_font": "'Arial Narrow', Arial, sans-serif", "body_font": "Arial, sans-serif",
    },
    "manutenção": {
        "template": "technical", "primary": "#d35128", "surface": "#f7f4ee", "ink": "#28221f",
        "headline": "Quem precisa resolver rápido encontra o serviço e o contato certo.", "cta": "Pedir atendimento",
        "services": ["Serviços disponíveis", "Regiões atendidas", "Chamado e orçamento"],
        "details": ["Dê prioridade aos problemas que o cliente reconhece no dia a dia.", "Exiba cobertura somente quando a área estiver confirmada.", "Reduza etapas entre a necessidade e o pedido de atendimento."],
        "section_title": "Um site objetivo para demandas que não podem esperar.", "mood": "utilitário, enérgico e direto",
        "heading_font": "Impact, 'Arial Narrow', sans-serif", "body_font": "Arial, sans-serif",
    },
    "gastronomia": {
        "template": "hospitality", "primary": "#b13f2d", "surface": "#fff7ea", "ink": "#301c16",
        "headline": "Uma experiência que começa antes de chegar à mesa.", "cta": "Ver contato e horários",
        "services": ["Especialidades da casa", "Ambiente e experiência", "Localização e contato"],
        "details": ["Use imagens próprias para apresentar os destaques com autenticidade.", "Mostre ambiente e proposta sem inventar cardápio ou avaliações.", "Deixe horário, localização e contato fáceis de encontrar."],
        "section_title": "Sabor, ambiente e informação no mesmo lugar.", "mood": "sensorial, caloroso e editorial",
        "heading_font": "Georgia, 'Times New Roman', serif", "body_font": "Arial, sans-serif",
    },
    "fitness": {
        "template": "technical", "primary": "#d9ff43", "surface": "#f3f5ee", "ink": "#172018",
        "headline": "Treino, estrutura e próximo passo em uma experiência que transmite movimento.", "cta": "Conhecer a academia",
        "services": ["Modalidades e objetivos", "Estrutura e acompanhamento", "Planos e primeiro contato"],
        "details": ["Organize as modalidades pelo objetivo de quem está pesquisando.", "Apresente estrutura e acompanhamento apenas com informações confirmadas.", "Facilite a conversa inicial sem esconder o caminho para começar."],
        "section_title": "Uma presença digital com energia, direção e leitura rápida.", "mood": "atlético, energético e disciplinado",
        "heading_font": "'Arial Narrow', 'Franklin Gothic Medium', Arial, sans-serif", "body_font": "'Trebuchet MS', Arial, sans-serif",
    },
    "pet": {
        "template": "care", "primary": "#ef704d", "surface": "#fff8ef", "ink": "#26332f",
        "headline": "Cuidado que começa com informação simples e uma experiência acolhedora.", "cta": "Falar com a equipe",
        "services": ["Cuidados e serviços", "Como funciona o atendimento", "Contato e orientações"],
        "details": ["Agrupe os serviços pelo que o tutor precisa resolver.", "Explique o primeiro contato sem afirmar procedimentos não confirmados.", "Deixe orientações e canais de atendimento fáceis de encontrar."],
        "section_title": "Uma apresentação amigável para quem cuida de verdade.", "mood": "afetuoso, leve e confiável",
        "heading_font": "'Trebuchet MS', Arial, sans-serif", "body_font": "Verdana, Arial, sans-serif",
    },
    "imobiliário": {
        "template": "portfolio", "primary": "#8b6b45", "surface": "#f4f0e8", "ink": "#202722",
        "headline": "Imóveis e atendimento apresentados com espaço para a decisão certa.", "cta": "Conversar sobre o imóvel",
        "services": ["Imóveis em destaque", "Compra, venda ou locação", "Atendimento e localização"],
        "details": ["Dê protagonismo às imagens autorizadas e às informações essenciais.", "Separe jornadas diferentes para reduzir buscas e dúvidas.", "Crie um contato direto para quem já encontrou uma possibilidade."],
        "section_title": "Uma vitrine organizada para transformar pesquisa em conversa.", "mood": "arquitetônico, elegante e seguro",
        "heading_font": "Optima, Candara, Georgia, serif", "body_font": "'Trebuchet MS', Arial, sans-serif",
    },
    "educação": {
        "template": "editorial", "primary": "#5b57c8", "surface": "#f7f5ef", "ink": "#22213a",
        "headline": "Uma jornada de aprendizado apresentada com clareza desde a primeira pesquisa.", "cta": "Conhecer a proposta",
        "services": ["Cursos e formatos", "Metodologia e rotina", "Matrícula e atendimento"],
        "details": ["Organize opções de curso sem misturar públicos e objetivos.", "Explique a experiência de aprendizagem sem promessas não comprovadas.", "Mostre o próximo passo de matrícula ou conversa com simplicidade."],
        "section_title": "Conteúdo organizado para quem está escolhendo onde aprender.", "mood": "editorial, curioso e contemporâneo",
        "heading_font": "Baskerville, Georgia, serif", "body_font": "'Trebuchet MS', Arial, sans-serif",
    },
    "automotivo": {
        "template": "technical", "primary": "#ef4a32", "surface": "#f1f1ed", "ink": "#171b1d",
        "headline": "Serviço automotivo explicado com precisão para quem precisa voltar à estrada.", "cta": "Solicitar atendimento",
        "services": ["Serviços e diagnóstico", "Etapas do atendimento", "Orçamento e contato"],
        "details": ["Separe os serviços pelos sinais que o motorista reconhece.", "Apresente o fluxo de avaliação sem diagnosticar antes da análise.", "Reduza etapas entre o problema e o pedido de atendimento."],
        "section_title": "Objetividade técnica para decisões que não podem esperar.", "mood": "mecânico, preciso e enérgico",
        "heading_font": "'Arial Narrow', 'Franklin Gothic Medium', Arial, sans-serif", "body_font": "Arial, sans-serif",
    },
}

DEFAULT_PROFILE = {
    "template": "professional", "primary": "#2563eb", "surface": "#f5f7fa", "ink": "#15223a",
    "headline": "Serviços bem apresentados para facilitar a próxima decisão.", "cta": "Falar com a equipe",
    "services": ["Serviços e especialidades", "Como funciona o atendimento", "Contato e orçamento"],
    "details": ["Organize o que a empresa oferece em uma leitura rápida.", "Explique o primeiro passo sem criar compromissos inexistentes.", "Direcione a pessoa interessada para o canal comercial disponível."],
    "section_title": "Informação organizada para quem já está pesquisando.", "mood": "profissional, claro e contemporâneo",
    "heading_font": "Georgia, serif", "body_font": "Arial, sans-serif",
}

VISITOR_COPY = {
    "odontologia": ("Seu próximo passo para cuidar do sorriso.", "Conheça as opções de atendimento e converse com a equipe sobre sua avaliação."),
    "saúde": ("Cuidar da saúde começa com uma conversa.", "Encontre informações de atendimento e tire suas dúvidas com a equipe."),
    "estética": ("Um momento para cuidar de você.", "Converse sobre seus objetivos e conheça as possibilidades de avaliação."),
    "advocacia": ("Clareza para o seu próximo passo.", "Apresente sua questão ao escritório e saiba como iniciar o atendimento jurídico."),
    "arquitetura": ("Espaços para viver novas histórias.", "Conte o que você imagina para seu espaço e converse sobre o projeto."),
    "fitness": ("Seu próximo treino começa aqui.", "Conheça a proposta da academia e converse com a equipe sobre como começar."),
    "pet": ("Um espaço para quem faz parte da família.", "Tire suas dúvidas sobre os cuidados e o atendimento para seu pet."),
    "imobiliário": ("Seu próximo endereço começa com uma escolha.", "Converse sobre o imóvel que você procura e receba informações da equipe."),
    "educação": ("Novos caminhos começam com aprendizado.", "Conheça a proposta de ensino e tire suas dúvidas sobre o próximo passo."),
    "automotivo": ("O próximo passo para cuidar do seu carro.", "Descreva o que seu veículo precisa e converse sobre atendimento e orçamento."),
    "gastronomia": ("Um convite para a próxima visita.", "Converse com a equipe para consultar informações e planejar sua visita."),
}

ALLOWED_TEMPLATES = set(REFERENCE_SETS)
AUTHORIZED_ASSET_STATUSES = {"owned", "authorized", "licensed"}
FORBIDDEN_CLAIMS = ("garantia de resultado", "resultado garantido", "o melhor da cidade", "número 1", "líder absoluto", "100% de sucesso")
SEGMENT_ALIASES = {
    "odontologia": ("dentista", "odontolog", "ortodont", "implante dent"),
    "saúde": ("médic", "clínica", "fisioter", "psicolog", "nutri", "saúde"),
    "estética": ("estética", "estetic", "harmonização", "beleza", "spa"),
    "advocacia": ("advogad", "advocacia", "jurídic", "escritório de direito"),
    "arquitetura": ("arquitet", "interiores", "paisagismo"),
    "reformas": ("reforma", "construtora", "construção civil"),
    "contabilidade": ("contador", "contáb", "contabilidade"),
    "engenharia": ("engenhar", "laudo técnico"),
    "manutenção": ("manutenção", "assistência técnica", "eletricista", "encanador", "refrigeração"),
    "gastronomia": ("restaurante", "pizzaria", "cafeteria", "confeitaria", "gastronomia", "bar "),
    "fitness": ("academia", "crossfit", "personal trainer", "musculação", "centro de treinamento"),
    "pet": ("pet shop", "veterin", "banho e tosa", "clínica animal"),
    "imobiliário": ("imobiliária", "corretor", "imóveis", "imobiliário"),
    "educação": ("escola", "curso", "colégio", "idiomas", "educação"),
    "automotivo": ("oficina", "auto center", "mecânica", "automotivo", "funilaria"),
}


def safe_color(value, fallback):
    value = clean_text(value, 20)
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def safe_data_image(value, max_length=1_800_000):
    value = str(value or "").strip()
    if len(value) > max_length:
        return ""
    return value if re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+", value) else ""


def resolve_profile_key(research):
    haystack = " ".join((research.get("name", ""), research.get("segment", ""), research.get("category", ""))).casefold()
    if research.get("segment") in SEGMENT_PROFILES:
        return research["segment"]
    for profile_key, aliases in SEGMENT_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            return profile_key
    return ""


def _json_list(value):
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _source_item(label, value, source, source_url="", confidence="MÉDIA"):
    return {
        "label": label,
        "value": clean_text(value, 300),
        "source": clean_text(source, 80),
        "source_url": clean_text(source_url, 500),
        "confidence": confidence,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def build_research_context(lead, evidence=None):
    analysis = analyze_lead(lead, preview_available=True)
    evidence_rows = list(evidence or _json_list(lead.get("evidence_json") or lead.get("Evidências")))
    sources = []
    if analysis.get("name"):
        sources.append(_source_item("Nome comercial", analysis["name"], "Cadastro do lead", lead.get("Google Maps", ""), "ALTA"))
    if analysis.get("category"):
        sources.append(_source_item("Segmento", analysis["category"], "Categoria pública", lead.get("Google Maps", ""), "MÉDIA"))
    if analysis.get("location"):
        sources.append(_source_item("Localização", analysis["location"], "Cadastro do lead", lead.get("Google Maps", ""), "MÉDIA"))
    for label, key in (("Site informado", "Link Inicial"), ("Instagram", "Instagram"), ("Facebook", "Facebook"), ("LinkedIn", "LinkedIn")):
        if lead.get(key):
            sources.append(_source_item(label, lead[key], "Canal público", lead[key], "MÉDIA"))
    for row in evidence_rows[:20]:
        if not isinstance(row, dict) or not row.get("value"):
            continue
        sources.append(_source_item(
            row.get("evidence_type") or row.get("type") or "Evidência",
            row.get("value"), row.get("source") or "Fonte registrada",
            row.get("source_url") or row.get("url") or "",
            row.get("confidence") or "MÉDIA",
        ))
    confirmed_services = []
    raw_services = lead.get("Serviços Confirmados") or lead.get("services_confirmed") or []
    if isinstance(raw_services, str):
        confirmed_services = [clean_text(item, 80) for item in re.split(r"[\n;,]", raw_services) if clean_text(item, 80)]
    elif isinstance(raw_services, list):
        confirmed_services = [clean_text(item, 80) for item in raw_services if clean_text(item, 80)]
    return {
        "name": analysis.get("name", "Empresa"),
        "segment": analysis.get("segment", "geral"),
        "category": analysis.get("category", ""),
        "location": analysis.get("location", ""),
        "commercial_benefit": analysis.get("commercial_plan", {}).get("benefit", "organizar os serviços e facilitar o próximo contato"),
        "reception_likely": analysis.get("contact_strategy", {}).get("recommended_mode") == "recepcao",
        "confirmed_services": confirmed_services[:8],
        "sources": sources,
        "confidence": "ALTA" if len(sources) >= 5 else "MÉDIA" if len(sources) >= 3 else "BAIXA",
        "needs_manual_review": len(sources) < 3,
    }


def build_art_direction(research, overrides=None):
    overrides = overrides or {}
    profile_key = resolve_profile_key(research)
    profile = SEGMENT_PROFILES.get(profile_key, DEFAULT_PROFILE)
    selected_template = clean_text(overrides.get("template"), 30)
    if selected_template not in ALLOWED_TEMPLATES:
        selected_template = profile["template"]
    seed = int(sha256(f"{research['name']}|{research['category']}".encode("utf-8")).hexdigest()[:8], 16)
    variants = {
        "care": ("soft-split", "orbital", "rounded"),
        "editorial": ("image-first", "offset-type", "pill"),
        "authority": ("dark-split", "rule-grid", "square"),
        "portfolio": ("gallery-first", "architectural", "square"),
        "technical": ("spec-grid", "blueprint", "square"),
        "hospitality": ("story-first", "menu-lines", "pill"),
        "professional": ("balanced-split", "signal-grid", "rounded"),
    }
    hero_layout, visual_motif, button_style = variants[selected_template]
    return {
        "template": selected_template,
        "profile_key": profile_key or "geral",
        "variant": f"v{seed % 3 + 1}",
        "mood": profile["mood"],
        "primary": safe_color(overrides.get("primary"), profile["primary"]),
        "surface": safe_color(overrides.get("surface"), profile["surface"]),
        "ink": safe_color(overrides.get("ink"), profile["ink"]),
        "heading_font": profile["heading_font"],
        "body_font": profile["body_font"],
        "hero_layout": hero_layout,
        "visual_motif": visual_motif,
        "button_style": button_style,
        "image_treatment": "recorte editorial com contraste controlado" if selected_template in {"editorial", "portfolio", "hospitality"} else "imagem contextual com leitura preservada",
        "sections": ["cabeçalho", "hero", "serviços", "processo ou contexto", "chamada final", "rodapé"],
        "references": list(REFERENCE_SETS[selected_template]),
        "rationale": f"A composição prioriza uma leitura {profile['mood']}, organiza as informações essenciais de {research['category'] or research['segment']} e conduz o visitante a um próximo passo claro.",
    }


def _asset_from_overrides(overrides, key, max_length):
    authorization = clean_text(overrides.get("asset_authorization"), 30).casefold()
    if authorization not in AUTHORIZED_ASSET_STATUSES:
        return ""
    return safe_data_image(overrides.get(key), max_length)


def build_preview_message(config, include_attachment=True):
    seller_name = clean_text(config.get("seller_name"), 80)
    agency_name = clean_text(config.get("agency_name"), 100) or "PH Digital"
    introduction = f"Sou {seller_name.split()[0]}, da {agency_name}." if seller_name else f"Aqui é da {agency_name}."
    benefit = clean_text(config.get("research", {}).get("commercial_benefit"), 180) or "organizar os serviços e facilitar o próximo contato"
    reception_note = (
        "Pode encaminhar à pessoa que decide sobre o site da empresa?"
        if config.get("research", {}).get("reception_likely")
        else "Faz sentido conversarmos sobre um site assim para vocês?"
    )
    return (
        f"Olá! {introduction} Desenvolvemos sites e preparei uma ideia para {config.get('name') or 'a empresa'}: {benefit}.\n\n"
        f"A imagem acompanha esta proposta demonstrativa, não oficial. {reception_note}"
    )


def build_preview_config(lead, overrides=None, evidence=None):
    overrides = overrides or {}
    research = build_research_context(lead, evidence)
    direction = build_art_direction(research, overrides)
    profile = SEGMENT_PROFILES.get(direction["profile_key"], DEFAULT_PROFILE)
    services_value = overrides.get("services")
    if isinstance(services_value, str):
        services = [clean_text(item, 70) for item in services_value.splitlines() if clean_text(item, 70)]
        services_origin = "editado"
    elif isinstance(services_value, list):
        services = [clean_text(item, 70) for item in services_value if clean_text(item, 70)]
        services_origin = "editado"
    elif research["confirmed_services"]:
        services = research["confirmed_services"]
        services_origin = "confirmado"
    else:
        services = list(profile["services"])
        services_origin = "sugerido"
    authorization = clean_text(overrides.get("asset_authorization"), 30).casefold()
    visitor_headline, default_subheadline = VISITOR_COPY.get(direction["profile_key"], ("Vamos conversar sobre o que você precisa.", "Conheça a proposta de atendimento e tire suas dúvidas com a equipe."))
    config = {
        "name": clean_text(overrides.get("name") or research["name"], 90),
        "segment": research["segment"],
        "category": clean_text(research["category"], 120),
        "location": clean_text(research["location"], 120),
        "template": direction["template"],
        "variant": direction["variant"],
        "headline": clean_text(overrides.get("headline") or visitor_headline, 150),
        "subheadline": clean_text(overrides.get("subheadline") or default_subheadline, 280),
        "cta": clean_text(overrides.get("cta") or profile["cta"], 45),
        "services": services[:6] or list(profile["services"]),
        "service_details": [
            "Converse com a equipe para conhecer as opções e esclarecer suas dúvidas.",
            "Consulte como iniciar o atendimento e quais informações são necessárias.",
            "Entre em contato para confirmar disponibilidade e combinar o próximo passo.",
        ],
        "services_origin": services_origin,
        "section_title": clean_text(overrides.get("section_title") or "Conheça as possibilidades.", 150),
        "primary": direction["primary"],
        "surface": direction["surface"],
        "ink": direction["ink"],
        "hero_image": _asset_from_overrides(overrides, "hero_image", 1_800_000),
        "brand_logo": _asset_from_overrides(overrides, "brand_logo", 700_000),
        "asset_authorization": authorization if authorization in AUTHORIZED_ASSET_STATUSES else "none",
        "asset_source": clean_text(overrides.get("asset_source"), 500),
        "seller_name": clean_text(overrides.get("seller_name"), 80),
        "agency_name": clean_text(overrides.get("agency_name"), 100) or "PH Digital",
        "research": research,
        "art_direction": direction,
        "disclaimer": "Demonstração conceitual não oficial — conteúdo e identidade sujeitos à validação da empresa",
    }
    config["message"] = build_preview_message(config, include_attachment=True)
    config["message_with_image"] = config["message"]
    return config


def _visual(config, data):
    hero_image = config.get("hero_image")
    logo = config.get("brand_logo")
    image_style = f' style="background-image:linear-gradient(180deg,transparent 22%,rgba(0,0,0,.7)),url(\'{hero_image}\')"' if hero_image else ""
    logo_html = f'<img class="logo" src="{logo}" alt="Logotipo autorizado para a demonstração">' if logo else f'<span class="wordmark">{escape(config["name"][:2].upper())}</span>'
    label = data.get("location") or data.get("category") or "Conceito de apresentação"
    asset_note = "Imagem autorizada" if hero_image else "Conceito de apresentação"
    service_menu = ""
    if not hero_image:
        items = "".join(f'<li><span>{index:02d}</span>{escape(service)}</li>' for index, service in enumerate(config.get("services", [])[:4], 1))
        menu_label = "Serviços" if config.get("services_origin") == "confirmado" else "Conteúdos sugeridos"
        service_menu = f'<div class="visual-menu"><small>{menu_label}</small><h2>{data["name"]}</h2><ul>{items}</ul></div>'
    return f'<div class="visual {"has-photo" if hero_image else "no-photo"}"{image_style}><div class="visual-top">{logo_html}<span>{data["segment"]}</span></div>{service_menu}<div class="visual-caption"><small>{asset_note}</small><p>{label}</p></div></div>'


def _template_signature(template, data, config):
    name = data["name"]
    location = data.get("location") or "Localização a confirmar"
    category = data.get("category") or data.get("segment") or "Serviços"
    initials = escape("".join(part[0] for part in str(config.get("name") or "E").split()[:2]).upper())
    signatures = {
        "care": f'<div class="signature signature-care"><span>Atendimento com clareza</span><b>{initials}</b><span>{location}</span></div>',
        "editorial": f'<div class="signature signature-editorial"><span>Apresentação editorial</span><strong>{category}</strong><i>Conceito 01</i></div>',
        "authority": f'<div class="signature signature-authority"><span>Informação reservada</span><i></i><strong>{name}</strong></div>',
        "portfolio": f'<div class="signature signature-portfolio"><span>Seleção visual</span><b>01</b><b>02</b><b>03</b><i>{location}</i></div>',
        "technical": f'<div class="signature signature-technical"><span>ESCOPO / 01</span><span>PROCESSO / 02</span><span>CONTATO / 03</span><strong>{category}</strong></div>',
        "hospitality": f'<div class="signature signature-hospitality"><span>Experiência</span><strong>{name}</strong><i>{location}</i></div>',
        "professional": f'<div class="signature signature-professional"><span>Serviços</span><span>Processo</span><span>Contato</span><strong>{initials}</strong></div>',
    }
    return signatures.get(template, signatures["professional"])


def _template_css():
    return r"""
.signature{position:relative;z-index:3}.theme-care header{border:0}.theme-care .hero{padding-top:48px}.theme-care .hero:before{content:"";position:absolute;width:38vw;height:38vw;max-width:560px;max-height:560px;left:-18vw;top:90px;border:1px solid color-mix(in srgb,var(--primary) 22%,transparent);border-radius:50%;pointer-events:none}.theme-care .hero-copy{padding-left:3vw}.theme-care .visual{border-radius:42% 42% 18px 18px;box-shadow:18px 22px 0 color-mix(in srgb,var(--primary) 16%,transparent)}.signature-care{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:18px;margin:0 6vw 26px;padding:15px 20px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font:700 10px/1 var(--body);letter-spacing:.08em;text-transform:uppercase}.signature-care b{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--primary);color:white}.signature-care span:last-child{text-align:right}.theme-care .service{border-radius:18px;margin:8px;border:1px solid var(--line)}.theme-care .services{border:0}.theme-care .contact{border-radius:28px}
.theme-editorial header{padding-top:34px;border-bottom:0}.theme-editorial .brand{font-style:italic}.theme-editorial .hero{grid-template-columns:1.18fr .82fr;gap:3vw;padding-top:24px}.theme-editorial .hero-copy{padding:7vw 2vw 3vw}.theme-editorial h1{font-weight:400;letter-spacing:-.065em}.theme-editorial .visual{transform:rotate(-1.5deg);border-radius:2px;box-shadow:16px 16px 0 color-mix(in srgb,var(--primary) 36%,transparent)}.signature-editorial{display:grid;grid-template-columns:1fr 1.4fr auto;align-items:end;gap:20px;margin:18px 6vw 54px;padding-top:14px;border-top:1px solid var(--ink);text-transform:uppercase}.signature-editorial span,.signature-editorial i{font:700 9px/1.3 var(--body);letter-spacing:.12em}.signature-editorial strong{font:400 clamp(24px,3vw,44px)/1 var(--heading);text-transform:none}.theme-editorial .services{border-left:0}.theme-editorial .service{min-height:270px;border-right:0;padding-left:0;margin-right:34px}.theme-editorial .service h3{font-style:italic}.theme-editorial .context{background:var(--primary)}
.theme-authority{background:#101214;color:#f4efe5}.theme-authority header{border-color:rgba(255,255,255,.13)}.theme-authority .hero{background:#101214;color:#f4efe5;border-bottom:1px solid rgba(255,255,255,.13)}.theme-authority .hero-copy{border-left:1px solid color-mix(in srgb,var(--primary) 72%,white);padding-left:34px}.theme-authority .visual{border:1px solid rgba(255,255,255,.18);box-shadow:none}.signature-authority{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:18px;margin:0 6vw;padding:19px 0;border-bottom:1px solid rgba(255,255,255,.15);font:700 9px/1 var(--body);letter-spacing:.15em;text-transform:uppercase}.signature-authority i{height:1px;background:rgba(255,255,255,.18)}.signature-authority strong{font:500 13px/1 var(--heading);letter-spacing:.04em}.theme-authority .services-wrap{background:#eee9df;color:#171a1f}.theme-authority .service span{color:#82652f}.theme-authority .contact{border:1px solid color-mix(in srgb,var(--primary) 45%,transparent);background:transparent;color:#f4efe5}
.theme-portfolio header{position:relative;z-index:5;border:0}.theme-portfolio .hero{grid-template-columns:1.3fr .7fr;padding-top:20px}.theme-portfolio .hero-copy{order:2}.theme-portfolio .visual{min-height:680px;order:1;border-radius:0;box-shadow:none}.theme-portfolio h1{font-weight:500}.signature-portfolio{display:grid;grid-template-columns:1fr repeat(3,44px) auto;align-items:center;gap:8px;margin:0 6vw 34px;font:700 9px/1 var(--body);text-transform:uppercase;letter-spacing:.12em}.signature-portfolio b{display:grid;place-items:center;height:44px;border:1px solid var(--line)}.signature-portfolio i{text-align:right}.theme-portfolio .services{gap:14px;border:0}.theme-portfolio .service{min-height:300px;border:0;background:color-mix(in srgb,var(--surface) 70%,white);padding:28px}.theme-portfolio .service:nth-child(2){transform:translateY(34px)}.theme-portfolio .context{grid-template-columns:1fr;padding-left:28vw}
.theme-technical .hero{position:relative;background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:40px 40px}.theme-technical .hero:after{content:"SPEC / 01";position:absolute;right:2vw;top:50%;writing-mode:vertical-rl;font:800 9px/1 var(--body);letter-spacing:.18em;color:var(--primary)}.theme-technical h1{text-transform:uppercase;font-weight:900;letter-spacing:-.045em}.theme-technical .visual{clip-path:polygon(0 0,88% 0,100% 12%,100% 100%,0 100%);border-radius:0;box-shadow:14px 14px 0 color-mix(in srgb,var(--primary) 38%,transparent)}.signature-technical{display:grid;grid-template-columns:repeat(3,1fr) 1.4fr;margin:0 6vw 28px;border:1px solid var(--line);font:800 9px/1 var(--body);letter-spacing:.1em;text-transform:uppercase}.signature-technical>*{padding:16px;border-right:1px solid var(--line)}.signature-technical strong{border:0;background:var(--ink);color:var(--surface);text-align:right}.theme-technical .service{position:relative}.theme-technical .service:after{content:"+";position:absolute;right:14px;top:12px;color:var(--primary)}.theme-technical .contact{clip-path:polygon(0 0,96% 0,100% 26%,100% 100%,0 100%)}
.theme-hospitality header{border:0}.theme-hospitality .hero{padding-top:28px}.theme-hospitality .visual{min-height:650px;border-radius:999px 999px 28px 28px;box-shadow:0 24px 60px color-mix(in srgb,var(--ink) 22%,transparent)}.theme-hospitality h1{font-weight:400;font-style:italic}.signature-hospitality{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin:0 6vw 40px;padding:18px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.signature-hospitality span,.signature-hospitality i{font:700 9px/1 var(--body);letter-spacing:.13em;text-transform:uppercase}.signature-hospitality strong{padding:0 28px;font:400 24px/1 var(--heading);font-style:italic}.signature-hospitality i{text-align:right}.theme-hospitality .services{gap:10px;border:0}.theme-hospitality .service{border:1px solid var(--line);border-radius:50% 50% 16px 16px;text-align:center}.theme-hospitality .context{background:var(--primary)}
.signature-professional{display:flex;align-items:center;gap:22px;margin:0 6vw 28px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font:700 9px/1 var(--body);text-transform:uppercase;letter-spacing:.1em}.signature-professional strong{margin-left:auto;display:grid;place-items:center;width:32px;height:32px;background:var(--primary);color:white}.variant-v2 .visual.no-photo:after{left:auto;right:16%;top:15%;width:240px;height:240px}.variant-v3 .visual.no-photo:before{right:auto;left:-180px;bottom:-190px}.variant-v3 .visual.no-photo:after{left:auto;right:12%;top:18%}
@media(max-width:760px){.signature{margin-left:5vw;margin-right:5vw}.signature-care,.signature-hospitality{grid-template-columns:1fr auto}.signature-care span:last-child,.signature-hospitality i{display:none}.signature-editorial{grid-template-columns:1fr auto}.signature-editorial strong{grid-column:1/-1;grid-row:2}.signature-portfolio{grid-template-columns:1fr repeat(3,36px)}.signature-portfolio i{display:none}.signature-technical{grid-template-columns:1fr 1fr}.signature-technical strong{grid-column:1/-1;text-align:left}.theme-care .hero-copy{padding-left:0}.theme-authority .hero-copy{padding-left:20px}.theme-portfolio .hero{grid-template-columns:1fr}.theme-portfolio .visual{min-height:430px}.theme-portfolio .service:nth-child(2){transform:none}.theme-portfolio .context{padding-left:5vw}.theme-technical .hero:after{display:none}.theme-hospitality .visual{min-height:430px}.theme-editorial .hero{grid-template-columns:1fr}.theme-editorial .hero-copy{padding:20px 0 0}}
"""


def render_preview_html(config):
    data = {key: escape(str(value)) for key, value in config.items() if key not in {"services", "service_details", "hero_image", "brand_logo", "research", "art_direction"}}
    details = list(config.get("service_details") or DEFAULT_PROFILE["details"])
    cards = "".join(
        f'<article class="service"><span>0{index}</span><h3>{escape(service)}</h3><p>{escape(details[(index - 1) % len(details)])}</p></article>'
        for index, service in enumerate(config.get("services", []), 1)
    )
    visual = _visual(config, data)
    template = config.get("template", "professional")
    if template in {"portfolio", "hospitality", "editorial"}:
        hero = f'<section class="hero hero-image-first">{visual}<div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><a class="button" href="#contato">{data["cta"]}</a></div></section>'
    elif template == "authority":
        hero = f'<section class="hero hero-authority"><div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><div class="actions"><a class="button" href="#contato">{data["cta"]}</a><span>Informação objetiva<br>e contato reservado</span></div></div>{visual}</section>'
    elif template == "technical":
        hero = f'<section class="hero hero-technical"><div class="hero-copy"><div class="eyebrow">Conceito técnico · {data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><a class="button" href="#contato">{data["cta"]}</a></div>{visual}</section>'
    else:
        hero = f'<section class="hero"><div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><a class="button" href="#contato">{data["cta"]}</a></div>{visual}</section>'
    direction = config.get("art_direction") or {}
    signature = _template_signature(template, data, config)
    variant = clean_text(direction.get("variant") or config.get("variant") or "v1", 8)
    if variant not in {"v1", "v2", "v3"}:
        variant = "v1"
    heading_font = direction.get("heading_font") or DEFAULT_PROFILE["heading_font"]
    body_font = direction.get("body_font") or DEFAULT_PROFILE["body_font"]
    suggested_note = "Conteúdos sugeridos para validação" if config.get("services_origin") != "confirmado" else "Serviços registrados nas fontes disponíveis"
    radius = "999px" if direction.get("button_style") == "pill" else "4px"
    visual_radius = "30px 8px 30px 8px" if template == "care" else "2px"
    accent_text = "#ffffff" if contrast_ratio(config["primary"], "#ffffff") >= 4.5 else "#111111"
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{data['name']} — demonstração</title><style>
:root{{--primary:{data['primary']};--surface:{data['surface']};--ink:{data['ink']};--line:color-mix(in srgb,var(--ink) 16%,transparent);--heading:{heading_font};--body:{body_font}}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--surface);color:var(--ink);font-family:var(--body)}}a{{color:inherit;text-decoration:none}}.shell{{min-height:100vh;overflow:hidden}}.notice{{padding:9px 5vw;background:var(--ink);color:white;text-align:center;font:700 10px/1.4 var(--body);letter-spacing:.13em;text-transform:uppercase}}header{{display:flex;align-items:center;justify-content:space-between;padding:24px 6vw;border-bottom:1px solid var(--line)}}.brand{{font:800 22px/1 var(--heading);letter-spacing:-.035em}}nav{{display:flex;gap:28px;font:700 11px/1 var(--body);text-transform:uppercase;letter-spacing:.1em}}.button{{display:inline-flex;align-items:center;justify-content:center;padding:15px 22px;border:1px solid transparent;border-radius:{radius};background:var(--primary);color:white;font:800 11px/1 var(--body);text-transform:uppercase;letter-spacing:.09em}}
.hero{{display:grid;grid-template-columns:1.05fr .95fr;gap:6vw;align-items:center;padding:72px 6vw 82px;min-height:650px}}.hero-copy{{position:relative;z-index:2}}.eyebrow{{color:var(--primary);font:900 10px/1.4 var(--body);text-transform:uppercase;letter-spacing:.2em}}h1,h2,h3{{font-family:var(--heading)}}h1{{font-size:clamp(47px,6.2vw,90px);line-height:.96;letter-spacing:-.055em;margin:24px 0 28px;max-width:950px}}.hero-copy>p{{font:400 clamp(16px,1.7vw,20px)/1.65 var(--body);max-width:670px;opacity:.74;margin:0 0 34px}}.visual{{min-height:480px;border-radius:{visual_radius};background:var(--ink);color:white;padding:28px;background-size:cover;background-position:center;display:flex;flex-direction:column;justify-content:space-between;box-shadow:24px 28px 0 color-mix(in srgb,var(--primary) 20%,transparent)}}.visual.no-photo{{background-image:linear-gradient(145deg,color-mix(in srgb,var(--primary) 76%,var(--ink)),var(--ink));position:relative;overflow:hidden}}.visual.no-photo:before,.visual.no-photo:after{{content:"";position:absolute;border:1px solid rgba(255,255,255,.2);border-radius:50%}}.visual.no-photo:before{{width:420px;height:420px;right:-170px;bottom:-170px}}.visual.no-photo:after{{width:180px;height:180px;left:17%;top:24%;background:rgba(255,255,255,.04)}}.visual-top{{display:flex;justify-content:space-between;align-items:center;font:800 10px/1 var(--body);text-transform:uppercase;letter-spacing:.13em;position:relative;z-index:1}}.logo{{display:block;max-width:150px;max-height:70px;object-fit:contain;background:white;padding:8px}}.wordmark{{display:grid;place-items:center;width:64px;height:64px;border:1px solid rgba(255,255,255,.38);font:900 24px/1 var(--body)}}.visual-caption{{position:relative;z-index:1}}.visual-caption small{{font:700 9px/1.3 var(--body);letter-spacing:.1em;text-transform:uppercase;opacity:.65}}.visual-caption p{{font:700 13px/1.5 var(--body);max-width:280px;margin:8px 0 0}}
.hero-image-first{{grid-template-columns:1.12fr .88fr;padding-top:46px}}.hero-image-first .visual{{min-height:610px;order:0}}.hero-image-first .hero-copy{{order:1}}.hero-authority{{background:var(--ink);color:white}}.hero-authority .visual{{box-shadow:24px 28px 0 color-mix(in srgb,var(--primary) 45%,transparent)}}.hero-technical{{background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:42px 42px}}.actions{{display:flex;align-items:center;gap:28px}}.actions span{{font:600 10px/1.5 var(--body);opacity:.62;text-transform:uppercase;letter-spacing:.09em}}.services-wrap{{padding:76px 6vw 96px;background:white}}.section-head{{display:flex;justify-content:space-between;gap:34px;align-items:end;margin-bottom:46px}}h2{{font-size:clamp(35px,5vw,62px);letter-spacing:-.05em;line-height:1;margin:0;max-width:780px}}.section-head p{{font:400 14px/1.7 var(--body);max-width:410px;opacity:.64}}.section-note{{display:inline-flex;margin-bottom:18px;padding:8px 11px;border:1px solid var(--line);font:800 9px/1 var(--body);letter-spacing:.11em;text-transform:uppercase}}.services{{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-left:1px solid var(--line)}}.service{{padding:34px;min-height:235px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}}.service span{{color:var(--primary);font:900 11px/1 var(--body)}}.service h3{{font-size:25px;line-height:1.1;margin:48px 0 14px}}.service p{{font:400 13px/1.65 var(--body);opacity:.65}}.context{{display:grid;grid-template-columns:.7fr 1.3fr;gap:8vw;padding:80px 6vw;background:var(--ink);color:white}}.context span{{color:var(--primary);font:800 10px/1 var(--body);letter-spacing:.13em;text-transform:uppercase}}.context p{{font:400 clamp(20px,2.5vw,34px)/1.35 var(--heading);margin:0}}.contact{{margin:0 6vw 76px;padding:58px;background:var(--primary);color:white;display:flex;align-items:center;justify-content:space-between;gap:42px}}.contact h2{{max-width:760px}}.contact .button{{background:white;color:var(--ink);flex:none}}footer{{padding:30px 6vw;border-top:1px solid var(--line);display:flex;justify-content:space-between;font:600 11px/1.4 var(--body);opacity:.65}}
@media(max-width:760px){{nav,header>.button{{display:none}}header{{padding:18px 5vw}}.hero,.hero-image-first{{grid-template-columns:1fr;padding:54px 5vw 64px;min-height:auto}}.hero-image-first .visual{{min-height:390px;order:1}}.hero-image-first .hero-copy{{order:0}}h1{{font-size:46px}}.visual{{min-height:340px;box-shadow:12px 14px 0 color-mix(in srgb,var(--primary) 20%,transparent)}}.services-wrap{{padding:58px 5vw}}.section-head{{display:block}}.section-head p{{margin-top:18px}}.services{{grid-template-columns:1fr}}.service{{min-height:170px}}.service h3{{margin-top:30px}}.context{{grid-template-columns:1fr;padding:58px 5vw}}.contact{{margin:0 5vw 50px;padding:34px;display:block}}.contact .button{{margin-top:24px}}footer{{padding:24px 5vw;gap:18px;flex-direction:column}}}}
{_template_css()}
.button,.contact{{color:{accent_text}}}.theme-care .visual.no-photo{{border-radius:24px}}.theme-technical .eyebrow,.service span{{color:var(--ink)}}.contact .button{{color:#111111}}
.visual-menu{{position:relative;z-index:1;margin:40px 0}}.visual-menu small{{font:600 10px/1.5 var(--body);letter-spacing:.16em;text-transform:uppercase;opacity:.7}}.visual-menu h2{{font-size:clamp(26px,3.2vw,48px);line-height:1.1;margin:14px 0 28px;overflow-wrap:anywhere}}.visual-menu ul{{list-style:none;padding:0;margin:0}}.visual-menu li{{display:flex;gap:18px;padding:14px 0;border-top:1px solid rgba(255,255,255,.25);font:500 15px/1.4 var(--body)}}.visual-menu li span{{opacity:.5;font-size:11px}}.visual.no-photo:after{{display:none}}
</style></head><body class="theme-{template} variant-{variant}"><div class="shell"><div class="notice">{data['disclaimer']}</div><header><a class="brand" href="#">{data['name']}</a><nav><a href="#servicos">Serviços</a><a href="#conceito">Atendimento</a><a href="#contato">Contato</a></nav><a class="button" href="#contato">{data['cta']}</a></header><main>{hero}{signature}<section class="services-wrap" id="servicos"><span class="section-note">{suggested_note}</span><div class="section-head"><h2>{data['section_title']}</h2><p>Consulte a equipe para confirmar serviços, disponibilidade e condições de atendimento.</p></div><div class="services">{cards}</div></section><section class="context" id="conceito"><span>Vamos conversar</span><p>{data['subheadline']}</p></section><section class="contact" id="contato"><h2>{data['cta']}</h2><a class="button" href="#">Entrar em contato</a></section></main><footer><strong>{data['name']}</strong><span>{data['location'] or 'Localização a confirmar'} · Demonstração não oficial</span></footer></div></body></html>"""


def _hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(value):
    channels = [channel / 12.92 if channel <= .03928 else ((channel + .055) / 1.055) ** 2.4 for channel in _hex_rgb(value)]
    return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]


def contrast_ratio(first, second):
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return round((light + .05) / (dark + .05), 2)


def validate_preview_html(html, config):
    errors = []
    warnings = []
    lowered = html.casefold()
    for required in ("<main", "id=\"contato\"", "class=\"button\"", "demonstração conceitual não oficial", "@media(max-width:760px)"):
        if required not in lowered:
            errors.append(f"Elemento obrigatório ausente: {required}")
    if "lorem ipsum" in lowered:
        errors.append("Lorem ipsum não é permitido.")
    if re.search(r"url\(['\"]?https?://", html, re.IGNORECASE) or re.search(r"src=[\"']https?://", html, re.IGNORECASE):
        errors.append("A prévia contém ativo remoto sem controle de licença.")
    for claim in FORBIDDEN_CLAIMS:
        if claim in lowered:
            errors.append(f"Afirmação comercial não comprovada: {claim}")
    if config.get("hero_image") and config.get("asset_authorization") not in AUTHORIZED_ASSET_STATUSES:
        errors.append("Imagem sem autorização registrada.")
    if config.get("research", {}).get("needs_manual_review"):
        warnings.append("Poucas fontes disponíveis; revisar conteúdo antes de aprovar.")
    text_ratio = contrast_ratio(config.get("ink", "#111111"), config.get("surface", "#ffffff"))
    if text_ratio < 4.5:
        errors.append(f"Contraste de texto insuficiente ({text_ratio}:1).")
    score = max(0, 100 - len(errors) * 25 - len(warnings) * 5)
    return {"approved": not errors and score >= 80, "score": score, "errors": errors, "warnings": warnings, "contrast_ratio": text_ratio}


def _inspect_page(page):
    return page.evaluate("""() => {
        const brokenImages = [...document.images].filter(img => !img.complete || img.naturalWidth === 0).length;
        const cta = document.querySelector('#contato .button');
        const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 2;
        const clipped = [...document.querySelectorAll('h1,h2,h3,.button')].filter(el => el.scrollWidth > el.clientWidth + 2).length;
        return {broken_images: brokenImages, cta_visible: !!cta && !!cta.getClientRects().length, horizontal_overflow: overflow, clipped_text: clipped};
    }""")


def _capture_screenshot_resilient(page, destination, full_page):
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    last_error = None
    for _ in range(2):
        try:
            page.screenshot(path=destination, full_page=full_page, animations="disabled", timeout=30_000)
            return "full" if full_page else "viewport"
        except Exception as error:
            last_error = error
            page.wait_for_timeout(180)
    if full_page:
        try:
            page.screenshot(path=destination, full_page=False, animations="disabled", timeout=30_000)
            return "viewport_fallback"
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Falha ao capturar a imagem renderizada: {last_error}")


def generate_preview_assets(html, output_dir, preview_key, static_report=None):
    from playwright.sync_api import sync_playwright

    os.makedirs(output_dir, exist_ok=True)
    paths = {
        "desktop": os.path.join(output_dir, f"{preview_key}-desktop.png"),
        "mobile": os.path.join(output_dir, f"{preview_key}-mobile.png"),
        "share": os.path.join(output_dir, f"{preview_key}-whatsapp.png"),
    }
    report = dict(static_report or {"approved": True, "score": 100, "errors": [], "warnings": []})
    report["errors"] = list(report.get("errors", []))
    report["warnings"] = list(report.get("warnings", []))
    report["render_checks"] = {}
    console_errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for variant, viewport, full_page in (
                ("desktop", {"width": 1440, "height": 1000}, True),
                ("mobile", {"width": 390, "height": 844}, True),
                ("share", {"width": 1080, "height": 1080}, False),
            ):
                page = browser.new_page(viewport=viewport, device_scale_factor=1)
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.set_content(html, wait_until="load")
                page.emulate_media(reduced_motion="reduce")
                page.wait_for_timeout(120)
                checks = _inspect_page(page)
                report["render_checks"][variant] = checks
                capture_mode = _capture_screenshot_resilient(page, paths[variant], full_page)
                if capture_mode == "viewport_fallback":
                    report["warnings"].append(f"{variant}: captura completa indisponível; primeira dobra utilizada.")
                page.close()
        finally:
            browser.close()
    report["console_errors"] = console_errors
    for variant, checks in report["render_checks"].items():
        if checks["broken_images"]:
            report["errors"].append(f"{variant}: imagem ausente ou quebrada.")
        if checks["horizontal_overflow"]:
            report["errors"].append(f"{variant}: rolagem horizontal indevida.")
        if checks["clipped_text"]:
            report["errors"].append(f"{variant}: texto cortado em {checks['clipped_text']} elemento(s).")
        if not checks["cta_visible"]:
            report["errors"].append(f"{variant}: CTA não visível.")
    if console_errors:
        report["errors"].append("Erros de console durante a renderização.")
    report["errors"] = list(dict.fromkeys(report["errors"]))
    report["approved"] = not report["errors"] and report.get("score", 0) >= 80
    if report["errors"]:
        report["score"] = max(0, report.get("score", 100) - 15 * len(report["errors"]))
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return paths, report


def capture_preview_png(html, destination, width=1440, height=1100):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            page.emulate_media(reduced_motion="reduce")
            page.screenshot(path=destination, full_page=True, animations="disabled")
        finally:
            browser.close()
    return destination
