import re
from urllib.parse import urlparse


SOCIAL_OR_DIRECTORY_HOSTS = (
    "instagram.com",
    "facebook.com",
    "linkedin.com",
    "linktr.ee",
    "wa.me",
    "whatsapp.com",
    "google.com",
    "goo.gl",
)


def clean_text(value, limit=600):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def field(lead, *names):
    for name in names:
        value = lead.get(name)
        if value not in (None, ""):
            return value
    return ""


def is_own_site(value):
    url = clean_text(value, 500)
    if not url:
        return False
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return bool(host and not any(host == item or host.endswith(f".{item}") for item in SOCIAL_OR_DIRECTORY_HOSTS))


def segment_profile(category):
    value = clean_text(category, 140).casefold()
    profiles = [
        (("odont", "dentist"), "odontologia", "pacientes que pesquisam tratamentos e formas de atendimento", "organizar tratamentos, orientações iniciais e o caminho para agendamento"),
        (("estét", "estet", "dermat", "beleza"), "estética", "pessoas comparando procedimentos, confiança e formas de agendamento", "apresentar procedimentos com clareza e conduzir o visitante ao agendamento"),
        (("clín", "clinic", "méd", "medic", "saúde", "saude"), "saúde", "pacientes procurando informações confiáveis antes de entrar em contato", "reunir especialidades, orientações e acesso ao agendamento"),
        (("advoc", "advog", "juríd", "jurid", "direito"), "advocacia", "pessoas e empresas procurando orientação jurídica", "apresentar áreas de atuação com sobriedade e facilitar o contato inicial"),
        (("arquitet", "interior"), "arquitetura", "clientes avaliando estilo, experiência e projetos anteriores", "organizar portfólio, processo de trabalho e solicitação de orçamento"),
        (("reforma", "constru", "obra"), "reformas", "proprietários buscando referências e segurança para solicitar orçamento", "apresentar tipos de projeto, processo e canal de orçamento"),
        (("contab", "contador"), "contabilidade", "empresas e profissionais buscando suporte contábil", "explicar frentes de atendimento e simplificar o primeiro contato"),
        (("engenh" ,), "engenharia", "clientes avaliando capacidade técnica e áreas de atuação", "organizar serviços, projetos e solicitação de análise"),
        (("manuten", "elétr", "eletr", "hidrául", "hidraul", "reparo"), "manutenção", "pessoas que precisam entender cobertura, disponibilidade e forma de atendimento", "deixar serviços, região atendida e pedido de orçamento mais acessíveis"),
        (("restaur", "pizz", "hamb", "café", "cafe", "bar ", "gastron"), "gastronomia", "clientes consultando cardápio, horários, reservas ou pedidos", "concentrar informações práticas e reduzir etapas até reserva ou pedido"),
    ]
    for terms, label, audience, opportunity in profiles:
        if any(term in value for term in terms):
            return label, audience, opportunity
    label = clean_text(category, 100) or "serviços locais"
    return label, "pessoas que pesquisam o negócio antes de iniciar o contato", "explicar os serviços e deixar o próximo passo mais claro"


def analyze_lead(lead, preview_available=False):
    name = clean_text(field(lead, "Nome", "nome"), 100).split(" - ")[0].split("|")[0].strip() or "Empresa"
    category = clean_text(field(lead, "Categoria Maps", "categoria_maps", "Nicho", "nicho"), 140)
    location = clean_text(field(lead, "Bairro", "bairro"), 140)
    website = clean_text(field(lead, "Link Inicial", "link_inicial"), 500)
    instagram = clean_text(field(lead, "Instagram", "instagram"), 500)
    facebook = clean_text(field(lead, "Facebook", "facebook"), 500)
    linkedin = clean_text(field(lead, "LinkedIn", "linkedin"), 500)
    email = clean_text(field(lead, "E-mail Encontrado", "email"), 180)
    phone = clean_text(field(lead, "Telefone", "telefone"), 100)
    rating = clean_text(field(lead, "Nota Maps", "nota"), 20)
    reviews = clean_text(field(lead, "Qtd Avaliacoes", "avaliacoes"), 30)
    has_site = is_own_site(website)
    segment, audience, opportunity = segment_profile(category)

    verified = []
    if category:
        verified.append({"claim": f"Categoria identificada: {category}", "source": "Perfil do Google", "kind": "verificada"})
    if location:
        verified.append({"claim": f"Localização informada: {location}", "source": "Perfil do Google", "kind": "verificada"})
    if rating:
        suffix = f" com {reviews} avaliações" if reviews else ""
        verified.append({"claim": f"Nota pública {rating}{suffix}", "source": "Perfil do Google", "kind": "verificada"})
    if has_site:
        verified.append({"claim": "Site próprio identificado", "source": website, "kind": "verificada"})
    else:
        verified.append({"claim": "Nenhum site próprio identificado no perfil consultado", "source": "Perfil do Google", "kind": "verificada"})
    channels = []
    for label, value in (("telefone", phone), ("e-mail", email), ("Instagram", instagram), ("Facebook", facebook), ("LinkedIn", linkedin)):
        if value:
            channels.append(label)
    if channels:
        verified.append({"claim": f"Canais identificados: {', '.join(channels)}", "source": "Dados públicos coletados", "kind": "verificada"})

    inferred = [
        {"claim": audience, "source": f"Inferência baseada no segmento {segment}", "kind": "inferida"},
        {"claim": opportunity, "source": f"Hipótese comercial para {segment}", "kind": "inferida"},
    ]
    unknown = []
    if not has_site:
        unknown.append("Não foi verificado se existe site fora do perfil consultado")
    unknown.extend(["Objetivos comerciais atuais", "Responsável pela decisão", "Orçamento e prazo"])
    confidence = min(95, 45 + len(verified) * 9)
    site_status = "identificado" if has_site else "não identificado no perfil consultado"
    argument = opportunity if not has_site else "avaliar se o site atual apresenta os serviços e o próximo passo com clareza no celular"
    return {
        "name": name,
        "segment": segment,
        "category": category or segment,
        "location": location,
        "audience": {"value": audience, "kind": "inferida"},
        "services": {"value": clean_text(field(lead, "Contexto do Site", "contexto_site"), 320), "kind": "verificada" if field(lead, "Contexto do Site", "contexto_site") else "desconhecida"},
        "presence": channels,
        "site": {"status": site_status, "url": website if has_site else "", "kind": "verificada"},
        "opportunity": opportunity,
        "main_argument": argument,
        "verified": verified,
        "inferred": inferred,
        "unknown": unknown,
        "confidence": confidence,
        "preview_available": bool(preview_available),
    }


def _site_observation(analysis):
    if analysis["site"]["status"] == "identificado":
        return "vi que já existe um site e a oportunidade seria avaliar se ele deixa serviços e contato claros no celular"
    return "não identifiquei um site próprio no perfil do Google consultado"


def generate_fallback_pitches(analysis, is_intl=False):
    name = analysis["name"]
    category = analysis["category"]
    location = f" em {analysis['location']}" if analysis["location"] else ""
    observation = _site_observation(analysis)
    opportunity = analysis["main_argument"]
    if is_intl:
        pitches = {
            "consultiva": f"Hi, I found {name}{location} through Google while researching {category} businesses. I noticed an opportunity to make the services and the next contact step easier to understand in one place. A focused website could support that decision without replacing your current channels. I can outline the structure I would recommend for you to review.",
            "direta": f"Hi, I reviewed the public profile for {name}. A clear website could help visitors understand what the business offers and move to the right contact channel with fewer steps. My suggestion would focus on mobile clarity, service presentation and a simple next action. I can send the proposed structure if useful.",
            "personalizada": f"Hi, I found {name}{location}, listed as {category}. Based on the public profile, the clearest website opportunity is to {opportunity}. This would give potential clients a reliable place to understand the business before contacting the team. I can share a concise direction for your review.",
        }
        if analysis.get("preview_available"):
            pitches["previa_visual"] = f"Hi, I created a non-official website concept for {name} based only on the public information available. The preview shows a possible mobile-friendly structure for presenting the business and guiding visitors to contact. It is a visual starting point, not a finished or official site. I can send the image and explain the choices behind it."
        return pitches

    pitches = {
        "consultiva": f"Oi! Encontrei a {name}{location} enquanto pesquisava empresas de {category}. {observation.capitalize()}. Vejo uma oportunidade de {opportunity}. Um site objetivo pode organizar essas informações e ajudar quem já chegou interessado a entender o negócio antes do contato. Posso compartilhar a estrutura que faria mais sentido para vocês avaliarem.",
        "direta": f"Oi! Analisei as informações públicas da {name} e notei espaço para um site que apresente melhor os serviços e conduza o visitante ao canal certo, principalmente no celular. A ideia não é substituir o Google ou as redes, mas reunir o essencial para reduzir dúvidas antes do contato. Se for útil, envio uma sugestão de estrutura.",
        "personalizada": f"Oi! Vi que a {name}{location} aparece como {category}. Com base no perfil público, a oportunidade mais clara é {opportunity}. Um site próprio pode transformar essa informação em uma apresentação mais organizada, mantendo o atendimento atual como destino do contato. Posso encaminhar uma direção objetiva, pensada para esse tipo de negócio.",
    }
    if analysis.get("preview_available"):
        pitches["previa_visual"] = f"Oi! Montei uma demonstração não oficial de site para a {name}, usando somente as informações públicas que encontrei. A prévia mostra uma possível organização mobile para apresentar o negócio e facilitar o contato, sem inventar depoimentos ou resultados. É apenas um ponto de partida visual, não um site oficial. Posso enviar o PNG e explicar as escolhas da proposta."
    return pitches


def evaluate_pitches(pitches, analysis, require_preview=False):
    required = ["consultiva", "direta", "personalizada"]
    if require_preview:
        required.append("previa_visual")
    reasons = {}
    forbidden = ("resultado garantido", "última chance", "desconto", "alavanque", "próximo nível", "preparei um site completo")
    for mode in required:
        text = clean_text(pitches.get(mode), 1400)
        issues = []
        words = len(text.split())
        if not text:
            issues.append("mensagem ausente")
        if text and not 40 <= words <= 105:
            issues.append(f"tamanho fora do intervalo profissional ({words} palavras)")
        if text and "site" not in text.casefold() and "website" not in text.casefold():
            issues.append("não explica que a oportunidade envolve um site")
        if text and analysis["name"].casefold() not in text.casefold():
            issues.append("não identifica o lead")
        if any(item in text.casefold() for item in forbidden):
            issues.append("contém promessa, pressão ou clichê comercial")
        if "prévia" in text.casefold() and not analysis.get("preview_available"):
            issues.append("menciona prévia inexistente")
        reasons[mode] = issues
    normalized = [clean_text(pitches.get(mode)).casefold() for mode in required]
    if len(set(normalized)) != len(normalized):
        reasons.setdefault("geral", []).append("há abordagens repetidas")
    total_issues = sum(len(items) for items in reasons.values())
    return {
        "approved": total_issues == 0,
        "score": max(0, 100 - total_issues * 15),
        "reasons": reasons,
        "attempt_limit": 2,
    }
