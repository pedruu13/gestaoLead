import json
import re
import unicodedata
from urllib.parse import urlparse


SOCIAL_OR_DIRECTORY_HOSTS = (
    "instagram.com", "facebook.com", "linkedin.com", "linktr.ee",
    "wa.me", "whatsapp.com", "google.com", "goo.gl",
)

REPORT_LANGUAGE = (
    "perfil público consultado", "perfil do google consultado",
    "oportunidade mais clara", "estrutura que recomendaria",
    "com base nos dados coletados", "pelas informações públicas disponíveis",
    "dados públicos coletados", "categoria identificada",
)

PRESSURE_OR_PROMISES = (
    "resultado garantido", "resultados garantidos", "última chance",
    "vagas limitadas", "desconto", "vai aumentar suas vendas",
    "vai trazer mais clientes", "alavanque", "próximo nível",
    "preparei um site completo",
)


SEGMENT_PROFILES = (
    (("odont", "dentist"), "odontologia", "atendimento odontológico", "quem está procurando atendimento odontológico", "dúvidas sobre tratamentos, primeira consulta e agendamento", "explicar os tratamentos com clareza e facilitar o agendamento", ("tratamento", "consulta", "agendamento", "paciente")),
    (("estét", "estet", "dermat", "beleza", "spa"), "estética", "clínica de estética", "quem está comparando procedimentos estéticos", "dúvidas sobre procedimentos, cuidados e forma de agendamento", "apresentar os procedimentos com clareza e conduzir ao agendamento", ("procedimento", "cuidado", "agendamento")),
    (("veterin", "pet shop", "petshop"), "veterinária", "atendimento veterinário", "tutores procurando atendimento para seus animais", "dúvidas sobre atendimentos, horários e agendamento", "organizar os atendimentos e facilitar o agendamento", ("atendimento", "agendamento", "tutor", "animal")),
    (("fisioter", "reabilita"), "fisioterapia", "atendimento de fisioterapia", "quem busca fisioterapia ou reabilitação", "dúvidas sobre tipos de atendimento, avaliação inicial e agendamento", "explicar os atendimentos e facilitar a avaliação inicial", ("atendimento", "avaliação", "agendamento", "reabilita")),
    (("psicol", "terapia", "terapeut"), "psicologia", "atendimento psicológico", "quem procura atendimento psicológico", "dúvidas sobre abordagem, formato das sessões e primeiro contato", "explicar o atendimento com acolhimento e facilitar o primeiro contato", ("atendimento", "sess", "contato", "acolh")),
    (("clín", "clinic", "méd", "medic", "saúde", "saude"), "saúde", "clínica de saúde", "pacientes procurando informações antes de marcar atendimento", "dúvidas sobre especialidades, preparo e forma de agendamento", "reunir as especialidades e facilitar o acesso ao agendamento", ("especialidade", "atendimento", "agendamento", "paciente")),
    (("advoc", "advog", "juríd", "jurid", "direito"), "advocacia", "escritório de advocacia", "quem precisa entender se o escritório atende seu tipo de caso", "dúvidas sobre áreas de atuação e como iniciar o atendimento", "apresentar as áreas de atuação com clareza e facilitar o contato inicial", ("área", "caso", "atuação", "contato")),
    (("arquitet", "interior"), "arquitetura", "escritório de arquitetura", "quem está escolhendo um profissional para seu projeto", "dúvidas sobre estilo, projetos realizados e processo de trabalho", "mostrar o portfólio e facilitar o pedido de orçamento", ("portfólio", "projeto", "orçamento")),
    (("reforma", "constru", "obra"), "reformas", "empresa de reformas", "quem está comparando empresas para uma obra ou reforma", "dúvidas sobre tipos de obra, processo e pedido de orçamento", "apresentar os serviços e tornar o pedido de orçamento mais objetivo", ("obra", "reforma", "orçamento", "serviço")),
    (("contab", "contador"), "contabilidade", "escritório de contabilidade", "empresas e profissionais procurando suporte contábil", "dúvidas sobre serviços, perfil atendido e primeiro contato", "explicar os serviços contábeis e qualificar o primeiro contato", ("contáb", "empresa", "serviço", "contato")),
    (("engenh",), "engenharia", "empresa de engenharia", "quem está avaliando capacidade técnica para um projeto", "dúvidas sobre áreas técnicas, projetos e solicitação de análise", "apresentar a capacidade técnica e facilitar a solicitação de análise", ("técnic", "projeto", "análise")),
    (("manuten", "elétr", "eletr", "hidrául", "hidraul", "reparo"), "manutenção", "serviço de manutenção", "quem precisa resolver um reparo ou solicitar manutenção", "dúvidas sobre serviços, região atendida e disponibilidade", "deixar os serviços e o pedido de orçamento mais acessíveis", ("manutenção", "reparo", "serviço", "orçamento")),
    (("restaur", "pizz", "hamb", "café", "cafe", "bar ", "gastron"), "gastronomia", "restaurante", "quem está escolhendo onde comer ou fazer um pedido", "dúvidas sobre cardápio, horários, reservas e pedidos", "reunir cardápio e horários e encurtar o caminho até a reserva ou pedido", ("cardápio", "reserva", "pedido", "horário")),
    (("imobili", "corretor", "imóveis", "imoveis"), "imobiliária", "imobiliária", "quem está buscando um imóvel ou avaliando opções", "dúvidas sobre imóveis disponíveis, regiões e forma de atendimento", "organizar os imóveis e facilitar o contato de quem já tem interesse", ("imóv", "região", "contato", "interesse")),
    (("solar", "fotovolta"), "energia solar", "empresa de energia solar", "quem está avaliando a instalação de energia solar", "dúvidas sobre projeto, etapas e solicitação de análise", "explicar as etapas e facilitar o pedido de uma análise inicial", ("energia solar", "projeto", "análise", "instala")),
    (("escola", "colégio", "colegio", "educa", "curso"), "educação", "instituição de ensino", "famílias e alunos comparando opções de ensino", "dúvidas sobre proposta, turmas e processo de matrícula", "apresentar a proposta de ensino e facilitar o interesse em matrícula", ("ensino", "turma", "matrícula", "aluno")),
    (("academia", "fitness", "pilates", "crossfit"), "academia", "academia", "quem está comparando opções para começar a treinar", "dúvidas sobre modalidades, horários e como começar", "mostrar modalidades e horários e facilitar a primeira visita", ("modalidade", "horário", "treino", "visita")),
    (("hotel", "pousada", "hostel"), "hotelaria", "hotel ou pousada", "viajantes comparando hospedagens", "dúvidas sobre acomodações, localização e reserva", "apresentar as acomodações e facilitar o pedido de reserva", ("acomoda", "hosped", "reserva", "viaj")),
    (("fotóg", "fotog", "filmagem", "vídeo", "video"), "fotografia", "serviço de fotografia", "quem está escolhendo um profissional para registrar um evento ou projeto", "dúvidas sobre estilo, trabalhos anteriores e orçamento", "mostrar o portfólio e facilitar o pedido de orçamento", ("portfólio", "trabalho", "evento", "orçamento")),
    (("oficina", "auto center", "mecân", "mecan", "automot"), "serviços automotivos", "oficina ou centro automotivo", "motoristas procurando manutenção para o veículo", "dúvidas sobre serviços, atendimento e pedido de orçamento", "apresentar os serviços e facilitar o pedido de orçamento", ("veículo", "serviço", "manutenção", "orçamento")),
    (("consultor", "consultoria", "gestão", "gestao"), "consultoria", "consultoria empresarial", "empresas procurando apoio para uma decisão ou projeto", "dúvidas sobre especialidades, forma de trabalho e primeiro diagnóstico", "explicar a atuação e facilitar uma conversa inicial mais qualificada", ("empresa", "atuação", "diagnóstico", "conversa")),
)

GENERIC_PROFILE = (
    "serviços locais", "negócio local", "quem está pesquisando antes de entrar em contato",
    "dúvidas sobre serviços, atendimento e próximo passo",
    "explicar os serviços e deixar o contato mais objetivo",
    ("serviço", "atendimento", "contato"),
)

SEGMENT_COPY_ANGLES = {
    "odontologia": (
        "Muita gente escolhe onde marcar uma consulta depois de entender os tratamentos e como funciona o primeiro atendimento.",
        "explicar essas etapas com clareza e conduzir o paciente ao agendamento sem transformar o WhatsApp em um balcão de dúvidas",
    ),
    "estética": (
        "Antes de agendar um procedimento, é comum a pessoa querer entender opções, cuidados e como será atendida.",
        "organizar essas respostas, valorizar a forma de atendimento e encurtar o caminho até o agendamento",
    ),
    "veterinária": (
        "Quando um tutor procura atendimento, ele normalmente quer saber rapidamente o que é atendido e como agendar.",
        "reunir essas informações e levar o tutor ao canal certo com menos dúvidas iniciais",
    ),
    "psicologia": (
        "Quem procura apoio psicológico costuma querer entender a abordagem e o formato do atendimento antes de dar o primeiro passo.",
        "apresentar o trabalho com acolhimento e tornar o primeiro contato mais confortável",
    ),
    "fisioterapia": (
        "Antes de marcar uma avaliação, a pessoa costuma buscar clareza sobre os atendimentos e o início do acompanhamento.",
        "explicar esse caminho e facilitar o pedido de uma avaliação inicial",
    ),
    "saúde": (
        "Pacientes costumam decidir onde marcar depois de entender especialidades, orientações iniciais e formas de atendimento.",
        "reunir essas informações e deixar o acesso ao agendamento mais simples",
    ),
    "advocacia": (
        "Quem busca orientação jurídica primeiro precisa saber se o escritório atua naquele tipo de caso e como iniciar a conversa.",
        "apresentar as áreas de atuação com sobriedade e direcionar o contato inicial",
    ),
    "arquitetura": (
        "Na escolha de um escritório, o portfólio e a forma de conduzir cada projeto pesam tanto quanto a lista de serviços.",
        "mostrar projetos, explicar o processo e preparar melhor o pedido de orçamento",
    ),
    "reformas": (
        "Antes de pedir orçamento para uma reforma, o cliente quer entender quais obras a empresa executa e como o trabalho começa.",
        "apresentar os serviços e transformar pedidos vagos em contatos mais objetivos",
    ),
    "contabilidade": (
        "Uma empresa que procura apoio contábil precisa identificar rapidamente se o escritório atende seu perfil e sua necessidade.",
        "explicar as frentes de atendimento e tornar a primeira conversa mais qualificada",
    ),
    "engenharia": (
        "Em serviços de engenharia, projetos anteriores e áreas técnicas ajudam o cliente a saber se vale iniciar uma análise.",
        "demonstrar capacidade técnica e organizar a solicitação de um novo projeto",
    ),
    "manutenção": (
        "Quem precisa de manutenção quer descobrir rápido se o serviço atende o problema, a região e o prazo necessário.",
        "deixar essas respostas acessíveis e facilitar um pedido de orçamento mais completo",
    ),
    "gastronomia": (
        "Cardápio, horário e forma de pedir costumam definir se o cliente avança ou procura outra opção.",
        "concentrar essas informações e reduzir etapas até a reserva ou o pedido",
    ),
    "imobiliária": (
        "Quem procura um imóvel quer filtrar opções e entender a região antes de falar com um corretor.",
        "organizar os imóveis e levar contatos mais preparados para a equipe",
    ),
    "energia solar": (
        "Quem avalia energia solar geralmente quer entender as etapas do projeto antes de solicitar uma análise.",
        "explicar o processo e preparar melhor o pedido de avaliação inicial",
    ),
    "educação": (
        "Famílias e alunos costumam comparar proposta de ensino, turmas e matrícula antes de pedir uma visita.",
        "apresentar esses pontos com clareza e facilitar o interesse em matrícula",
    ),
    "academia": (
        "Quem pensa em começar a treinar costuma comparar modalidades, horários e a experiência da primeira visita.",
        "mostrar modalidades e horários e deixar o próximo passo mais convidativo",
    ),
    "hotelaria": (
        "Na escolha de uma hospedagem, acomodações, localização e facilidade para reservar precisam estar claras.",
        "apresentar esses pontos e encurtar o caminho até o pedido de reserva",
    ),
    "fotografia": (
        "Quem contrata fotografia decide muito pelo estilo dos trabalhos anteriores e pela segurança no primeiro contato.",
        "valorizar o portfólio e preparar um pedido de orçamento mais completo",
    ),
    "serviços automotivos": (
        "Quando surge um problema no veículo, o motorista quer entender serviços e atendimento antes de pedir orçamento.",
        "apresentar o que a oficina faz e facilitar um contato mais objetivo",
    ),
    "consultoria": (
        "Uma empresa só avança com uma consultoria quando entende a especialidade e a forma de trabalho.",
        "explicar a atuação e preparar uma conversa inicial mais qualificada",
    ),
    "serviços locais": (
        "Antes de entrar em contato, o cliente costuma procurar uma resposta simples: o serviço atende ao que ele precisa?",
        "explicar o essencial e deixar o próximo passo mais claro",
    ),
}


def clean_text(value, limit=600):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def field(lead, *names):
    for name in names:
        value = lead.get(name)
        if value not in (None, ""):
            return value
    return ""


def _fold(value):
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def is_own_site(value):
    url = clean_text(value, 500)
    if not url:
        return False
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return bool(host and not any(host == item or host.endswith(f".{item}") for item in SOCIAL_OR_DIRECTORY_HOSTS))


def _profile_for(category):
    folded = _fold(category)
    for terms, segment, commercial_category, audience, friction, benefit, required_terms in SEGMENT_PROFILES:
        if any(_fold(term) in folded for term in terms):
            return {
                "segment": segment,
                "commercial_category": commercial_category,
                "audience": audience,
                "friction": friction,
                "benefit": benefit,
                "required_terms": required_terms,
            }
    segment, commercial_category, audience, friction, benefit, required_terms = GENERIC_PROFILE
    return {
        "segment": segment,
        "commercial_category": commercial_category,
        "audience": audience,
        "friction": friction,
        "benefit": benefit,
        "required_terms": required_terms,
    }


def segment_profile(category):
    profile = _profile_for(category)
    return profile["segment"], profile["audience"], profile["benefit"]


def _short_business_reference(name):
    value = clean_text(name, 100).split(" - ")[0].split("|")[0].strip()
    value = re.sub(r"\b(?:LTDA|ME|EIRELI|S/?A)\.?\b", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" ,-.")
    if re.match(r"^(?:dr|dra|doutor|doutora)\.?\s+", value, re.I):
        return "a equipe"
    if len(value.split()) > 5:
        return "a empresa"
    return value or "a empresa"


def normalize_lead_context(lead, preview_available=False):
    raw_name = clean_text(field(lead, "Nome", "nome"), 100).split(" - ")[0].split("|")[0].strip() or "Empresa"
    raw_category = clean_text(field(lead, "Categoria Maps", "categoria_maps", "Nicho", "nicho"), 140)
    profile = _profile_for(raw_category)
    website = clean_text(field(lead, "Link Inicial", "link_inicial"), 500)
    channels = []
    for label, value in (
        ("WhatsApp ou telefone", field(lead, "Telefone", "telefone")),
        ("e-mail", field(lead, "E-mail Encontrado", "email")),
        ("Instagram", field(lead, "Instagram", "instagram")),
        ("Facebook", field(lead, "Facebook", "facebook")),
        ("LinkedIn", field(lead, "LinkedIn", "linkedin")),
    ):
        if clean_text(value):
            channels.append(label)
    return {
        "raw_name": raw_name,
        "business_reference": _short_business_reference(raw_name),
        "salutation": "Oi, tudo bem?",
        "raw_category": raw_category,
        **profile,
        "location": clean_text(field(lead, "Bairro", "bairro"), 140),
        "services": clean_text(field(lead, "Contexto do Site", "contexto_site"), 320),
        "site_verified": is_own_site(website),
        "site_url": website if is_own_site(website) else "",
        "channels": channels,
        "preview_available": bool(preview_available),
    }


def plan_commercial_angle(context):
    channel = context["channels"][0] if context["channels"] else "canal de atendimento"
    if context["site_verified"]:
        premise = "o site pode ser avaliado pela clareza com que apresenta o serviço e conduz ao contato"
    else:
        premise = "um site pode responder dúvidas importantes antes do primeiro contato, sem substituir os canais atuais"
    hook, site_value = SEGMENT_COPY_ANGLES.get(context["segment"], SEGMENT_COPY_ANGLES["serviços locais"])
    return {
        "audience": context["audience"],
        "friction": context["friction"],
        "benefit": context["benefit"],
        "premise": premise,
        "destination_channel": channel,
        "primary_angle": f"{context['benefit']}, reduzindo {context['friction']}",
        "hook": hook,
        "site_value": site_value,
        "required_terms": context["required_terms"],
        "claims_policy": "Tratar o benefício como possibilidade; não afirmar falhas, resultados ou ausência absoluta de site.",
    }


def analyze_lead(lead, preview_available=False):
    context = normalize_lead_context(lead, preview_available=preview_available)
    plan = plan_commercial_angle(context)
    rating = clean_text(field(lead, "Nota Maps", "nota"), 20)
    reviews = clean_text(field(lead, "Qtd Avaliacoes", "avaliacoes"), 30)
    verified = []
    if context["raw_category"]:
        verified.append({"claim": f"Categoria cadastrada: {context['raw_category']}", "source": "Google", "kind": "verificada"})
    if context["location"]:
        verified.append({"claim": f"Localização cadastrada: {context['location']}", "source": "Google", "kind": "verificada"})
    if rating:
        suffix = f" com {reviews} avaliações" if reviews else ""
        verified.append({"claim": f"Nota {rating}{suffix}", "source": "Google", "kind": "verificada"})
    if context["site_verified"]:
        verified.append({"claim": "Site próprio identificado", "source": context["site_url"], "kind": "verificada"})
    else:
        verified.append({"claim": "Nenhum site próprio identificado no campo de site do perfil", "source": "Google", "kind": "verificada"})
    if context["channels"]:
        verified.append({"claim": f"Canais cadastrados: {', '.join(context['channels'])}", "source": "Dados coletados", "kind": "verificada"})
    unknown = ["Objetivos comerciais atuais", "Responsável pela decisão", "Orçamento e prazo"]
    if not context["site_verified"]:
        unknown.insert(0, "Possível site existente fora do campo verificado")
    return {
        "name": context["raw_name"],
        "business_reference": context["business_reference"],
        "salutation": context["salutation"],
        "segment": context["segment"],
        "category": context["commercial_category"],
        "raw_category": context["raw_category"],
        "location": context["location"],
        "audience": {"value": context["audience"], "kind": "inferida"},
        "services": {"value": context["services"], "kind": "verificada" if context["services"] else "desconhecida"},
        "presence": context["channels"],
        "site": {"status": "identificado" if context["site_verified"] else "não confirmado", "url": context["site_url"], "kind": "verificada"},
        "opportunity": context["benefit"],
        "main_argument": plan["primary_angle"],
        "commercial_plan": plan,
        "normalized_context": context,
        "verified": verified,
        "inferred": [
            {"claim": context["audience"], "source": f"Padrão comercial do segmento {context['segment']}", "kind": "inferida"},
            {"claim": context["benefit"], "source": f"Hipótese comercial para {context['segment']}", "kind": "inferida"},
        ],
        "unknown": unknown,
        "confidence": min(95, 45 + len(verified) * 9),
        "preview_available": context["preview_available"],
    }


def _location_phrase(location):
    location = clean_text(location, 80)
    return f" na região de {location}" if location else ""


def generate_fallback_pitches(analysis, is_intl=False):
    plan = analysis["commercial_plan"]
    context = analysis["normalized_context"]
    if is_intl:
        pitches = {
            "consultiva": f"Hi, how are you? People researching {context['commercial_category']} often have questions before making contact. A clear website can organize the essential information and guide interested visitors to your existing contact channel. Would it help if I sent three practical suggestions for that page?",
            "direta": "Hi! I have a simple website idea for your business: make the service easier to understand and give each visitor a clear next step. It would work alongside your current channels rather than replace them. May I send you a short summary here?",
            "personalizada": f"Hello! For a {context['commercial_category']}, a focused website can help visitors understand the service before contacting the team. The useful angle would be to {plan['benefit']}. Would you like to see how I would organize the main sections?",
            "recepcao": "Hi! Is this number mainly used for customer service or appointments? I have a website suggestion focused on helping visitors understand the service before they message the team. Could you forward it to the person who handles this area?",
            "email": "Subject: A website idea to clarify the customer journey\n\nHello, I would like to share a practical website idea for your business. The page could help visitors understand the service and reach the right contact channel with fewer initial questions. If relevant, reply to this email and I will send a concise outline.",
        }
        if analysis.get("preview_available"):
            pitches["previa_visual"] = "Hi! I created a non-official visual concept using only confirmed information. It is not a finished website, but a way to discuss structure and mobile readability. May I send the image with a short explanation?"
        return pitches

    location = _location_phrase(context["location"])
    destination = plan["destination_channel"]
    pitches = {
        "consultiva": f"Oi, tudo bem? {plan['hook']} Um site bem organizado pode {plan['site_value']}. Se fizer sentido, posso te mandar três ideias práticas para essa página?",
        "direta": f"Oi! Uma página enxuta para {context['commercial_category']} pode {plan['benefit']}. A ideia é reunir o essencial em um só lugar e levar quem já entendeu a proposta ao {destination}. Quer que eu te envie um resumo curto do que entraria nesse site?",
        "personalizada": f"Olá! Pensando em {context['commercial_category']}{location}, há espaço para um site que ajude {plan['audience']} sem complicar o atendimento. O foco seria {plan['site_value']}. Vale eu te mostrar uma sugestão de organização para esse tipo de negócio?",
        "recepcao": f"Oi! Este número é usado para atendimento ou agendamento? Tenho uma ideia de site para {plan['benefit']}, evitando que dúvidas iniciais ocupem a conversa no {destination}. Se outra pessoa cuida dessa parte, você consegue encaminhar a sugestão para ela?",
        "email": f"Assunto: uma ideia de site para {context['commercial_category']}\n\nOlá, tudo bem? {plan['hook']} Minha sugestão seria um site objetivo para {plan['site_value']}. Se esse assunto fizer sentido para a equipe, responda este e-mail e eu envio um resumo prático da proposta.",
    }
    if analysis.get("preview_available"):
        pitches["previa_visual"] = "Oi! Preparei um conceito visual não oficial usando apenas informações confirmadas. Não é um site pronto: é uma imagem para conversar sobre organização, leitura no celular e caminho até o contato. Posso enviar a imagem com uma explicação curta?"
    return pitches


def _last_sentence(text):
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", clean_text(text)) if item.strip()]
    return sentences[-1].casefold() if sentences else ""


def _repeated_content_words(text):
    words = re.findall(r"[a-zá-úç]{5,}", clean_text(text).casefold())
    ignored = {"atendimento", "contato", "pessoa", "equipe", "porque", "antes", "poderia", "vocês"}
    counts = {word: words.count(word) for word in set(words) if word not in ignored}
    return sorted(word for word, count in counts.items() if count >= 4)


def review_pitch(text, analysis, mode):
    value = clean_text(text, 1600)
    folded = value.casefold()
    issues = []
    words = len(value.split())
    is_english = analysis.get("language") == "en"
    if not value:
        return {"approved": False, "score": 0, "issues": ["mensagem ausente"]}
    minimum_words = 25 if mode == "previa_visual" else 35
    if not minimum_words <= words <= 115:
        issues.append(f"tamanho inadequado ({words} palavras)")
    if "site" not in folded and "website" not in folded:
        issues.append("não explica que a proposta envolve um site")
    for phrase in REPORT_LANGUAGE:
        if phrase in folded:
            issues.append(f"usa linguagem de relatório técnico: {phrase}")
    if any(phrase in folded for phrase in PRESSURE_OR_PROMISES):
        issues.append("usa pressão, promessa ou clichê comercial")
    full_name = clean_text(analysis.get("name"), 100).casefold()
    greeting_area = clean_text(value, 180).casefold()
    if full_name and full_name != "empresa" and full_name in greeting_area:
        issues.append("usa o nome completo do lead na saudação")
    raw_category = clean_text(analysis.get("raw_category"), 140).casefold()
    commercial_category = clean_text(analysis.get("category"), 140).casefold()
    if raw_category and _fold(raw_category) not in _fold(commercial_category) and raw_category in folded:
        issues.append("insere a categoria bruta do Google no texto")
    repeated = _repeated_content_words(value)
    if repeated:
        issues.append(f"repete palavras em excesso: {', '.join(repeated[:3])}")
    required_terms = analysis.get("commercial_plan", {}).get("required_terms", ()) if mode != "previa_visual" else ()
    if is_english:
        required_terms = ("service", "appointment", "contact", "project", "booking", "website", "visitor")
    if required_terms and not any(_fold(term) in _fold(value) for term in required_terms):
        issues.append("não traz benefício específico do segmento")
    if ("prévia" in folded or "demonstração" in folded or "conceito visual" in folded) and not analysis.get("preview_available"):
        issues.append("menciona material visual inexistente")
    if mode == "email" and not folded.startswith(("assunto:", "subject:")):
        issues.append("e-mail sem assunto")
    reception_terms = ("forward", "person", "handles") if is_english else ("encaminhar", "outra pessoa", "responsável")
    if mode == "recepcao" and not any(term in folded for term in reception_terms):
        issues.append("não considera que o contato pode ser de recepção")
    return {"approved": not issues, "score": max(0, 100 - len(issues) * 18), "issues": issues}


def evaluate_pitches(pitches, analysis, require_preview=False):
    required = ["consultiva", "direta", "personalizada", "recepcao", "email"]
    if require_preview:
        required.append("previa_visual")
    reasons = {}
    reviews = {}
    for mode in required:
        review = review_pitch(pitches.get(mode, ""), analysis, mode)
        reviews[mode] = review
        reasons[mode] = review["issues"]
    texts = {mode: clean_text(pitches.get(mode)).casefold() for mode in required}
    if len(set(texts.values())) != len(texts):
        reasons.setdefault("geral", []).append("há abordagens repetidas")
    endings = [_last_sentence(pitches.get(mode, "")) for mode in required]
    if len(set(endings)) != len(endings):
        reasons.setdefault("geral", []).append("há encerramentos repetidos")
    for index, left_mode in enumerate(required):
        left_words = set(re.findall(r"[a-zá-úç]{4,}", texts[left_mode]))
        for right_mode in required[index + 1:]:
            right_words = set(re.findall(r"[a-zá-úç]{4,}", texts[right_mode]))
            union = left_words | right_words
            similarity = len(left_words & right_words) / len(union) if union else 0
            if similarity > 0.72:
                reasons.setdefault("geral", []).append(f"{left_mode} e {right_mode} são semelhantes demais")
    total_issues = sum(len(items) for items in reasons.values())
    return {"approved": total_issues == 0, "score": max(0, 100 - total_issues * 12), "reasons": reasons, "reviews": reviews, "attempt_limit": 2}


def build_generation_prompt(analysis, modes, feedback=None, is_intl=False):
    context = analysis["normalized_context"]
    safe_context = {
        "segment": context["segment"],
        "commercial_category": context["commercial_category"],
        "location": context["location"],
        "channels": context["channels"],
        "site_verified": context["site_verified"],
        "preview_available": context["preview_available"],
        "commercial_plan": analysis["commercial_plan"],
    }
    language = "inglês natural" if is_intl else "português brasileiro natural"
    repair = f"\nA versão anterior foi rejeitada por: {json.dumps(feedback, ensure_ascii=False)}\nCorrija esses pontos." if feedback else ""
    output_example = {mode: "..." for mode in modes}
    return f"""Você escreve primeiras mensagens comerciais humanas em {language} para venda consultiva de sites.

Antes de escrever, siga o plano comercial fornecido. Transforme-o em conversa; não copie nomes de campos nem linguagem técnica.

REGRAS OBRIGATÓRIAS:
- 40 a 100 palavras por mensagem e menção clara a site.
- Comece de forma natural, sem nome completo da pessoa ou do estabelecimento na saudação.
- Nunca copie categoria bruta do Google; use somente commercial_category de forma gramatical.
- Use um benefício específico do segmento e trate-o como possibilidade, não como fato comprovado.
- Não afirme que o negócio tem um problema nem que está sem site.
- Não use: perfil público consultado, oportunidade mais clara, estrutura que recomendaria, pelas informações públicas disponíveis.
- Não invente serviços, números, elogios, resultados, urgência, preço ou desconto.
- Não mencione prévia, demonstração ou conceito visual se preview_available for falso.
- Crie argumentos e encerramentos realmente diferentes entre os modos.
- Em recepcao, considere que o número pode ser de atendimento ou agendamento e peça encaminhamento com educação.
- Em email, comece com Assunto: e escreva como e-mail.

MODOS: {', '.join(modes)}
CONTEXTO NORMALIZADO E PLANO:
{json.dumps(safe_context, ensure_ascii=False)}
{repair}
Retorne somente JSON no formato {json.dumps({'versoes': output_example}, ensure_ascii=False)}."""
