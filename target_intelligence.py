import re
import unicodedata
import urllib.parse
from collections import defaultdict


SOCIAL_OR_DIRECTORY_DOMAINS = (
    "facebook.com", "instagram.com", "linkedin.com", "linktr.ee", "wa.me",
    "api.whatsapp", "yelp.", "tripadvisor.", "yellowpages.", "foursquare.",
)


def _niche(name, aliases, ticket, need, gap, reason):
    return {"name": name, "aliases": aliases, "ticket": ticket, "need": need, "gap": gap, "reason": reason}


def _city(name, aliases, power, gap):
    return {"name": name, "aliases": aliases, "power": power, "gap": gap}


MARKETS = {
    "br": {
        "label": "Brasil", "locale": "pt-BR",
        "niches": (
            _niche("Clínica de estética", ("estetica", "med spa"), 90, 91, 44, "precisa apresentar procedimentos, confiança e um caminho simples para avaliação"),
            _niche("Odontologia", ("dentista", "odont"), 84, 89, 36, "precisa explicar tratamentos, transmitir segurança e facilitar o agendamento"),
            _niche("Advocacia", ("advogado", "advocacia", "jurid"), 88, 83, 38, "precisa deixar áreas de atuação claras e transformar dúvidas em contatos qualificados"),
            _niche("Móveis planejados", ("moveis planejados", "marcenaria"), 86, 88, 48, "precisa mostrar projetos e padrão de acabamento antes do pedido de orçamento"),
            _niche("Arquitetura e interiores", ("arquitet", "interiores"), 87, 86, 43, "precisa apresentar portfólio, processo e diferenciais para projetos de maior valor"),
            _niche("Energia solar", ("energia solar", "solar"), 91, 85, 40, "precisa explicar economia, instalação e captar pedidos de simulação"),
            _niche("Clínica veterinária", ("veterinar", "pet clinic"), 80, 86, 45, "precisa organizar serviços, urgências, localização e agendamentos"),
            _niche("Fisioterapia", ("fisioter", "reabilitacao"), 78, 87, 47, "precisa explicar especialidades e conduzir pacientes até a primeira avaliação"),
            _niche("Psicologia", ("psicolog", "terapia"), 76, 85, 50, "precisa transmitir confiança, explicar abordagens e facilitar o primeiro contato"),
            _niche("Contabilidade para empresas", ("contabilidade", "contador"), 82, 82, 46, "precisa tornar serviços consultivos claros e captar empresas fora da indicação"),
            _niche("Reformas e construção", ("reforma", "construtora", "engenharia"), 89, 87, 49, "precisa provar capacidade com obras realizadas e qualificar pedidos de orçamento"),
            _niche("Climatização e ar-condicionado", ("ar condicionado", "climatizacao", "hvac"), 81, 84, 53, "precisa captar instalações e manutenções com orçamento mais organizado"),
            _niche("Academia e treinamento", ("academia", "personal trainer", "crossfit", "treinamento funcional"), 73, 79, 47, "precisa apresentar estrutura, modalidades, horários e facilitar a matrícula ou aula experimental"),
            _niche("Escola particular", ("escola particular", "colegio", "educacao infantil"), 84, 86, 42, "precisa transmitir confiança às famílias, apresentar a proposta pedagógica e captar visitas ou matrículas"),
            _niche("Fotografia profissional", ("fotografo", "fotografia", "estudio fotografico"), 75, 82, 52, "precisa mostrar portfólio, posicionamento e conduzir pedidos de orçamento"),
        ),
        "cities": (
            _city("Moema - São Paulo", ("moema sao paulo",), 91, 31), _city("Campinas - SP", ("campinas sp",), 84, 42),
            _city("Tatuapé - São Paulo", ("tatuape sao paulo",), 82, 40), _city("Pinheiros - São Paulo", ("pinheiros sao paulo",), 89, 28),
            _city("Ribeirão Preto - SP", ("ribeirao preto sp",), 82, 46), _city("Goiânia - GO", ("goiania go",), 80, 48),
            _city("Alphaville - SP", ("alphaville sp", "barueri sp"), 94, 25), _city("São José dos Campos - SP", ("sao jose dos campos sp",), 83, 41),
            _city("Londrina - PR", ("londrina pr",), 79, 49), _city("Joinville - SC", ("joinville sc",), 81, 47),
            _city("Uberlândia - MG", ("uberlandia mg",), 79, 51), _city("Vila Velha - ES", ("vila velha es",), 78, 50),
            _city("Cambuí - Campinas", ("cambui campinas",), 87, 39), _city("Vila Mariana - São Paulo", ("vila mariana sao paulo",), 88, 34),
            _city("Santana - São Paulo", ("santana sao paulo",), 84, 40), _city("Batel - Curitiba", ("batel curitiba",), 90, 31),
            _city("Água Verde - Curitiba", ("agua verde curitiba",), 84, 42), _city("Savassi - Belo Horizonte", ("savassi belo horizonte",), 88, 35),
            _city("Boa Viagem - Recife", ("boa viagem recife",), 86, 41), _city("Meireles - Fortaleza", ("meireles fortaleza",), 86, 42),
            _city("Águas Claras - DF", ("aguas claras df", "aguas claras brasilia"), 85, 45), _city("Lago Sul - Brasília", ("lago sul brasilia",), 93, 27),
            _city("Barra da Tijuca - Rio de Janeiro", ("barra da tijuca rio de janeiro",), 92, 30), _city("Niterói - RJ", ("niteroi rj",), 84, 42),
            _city("Maringá - PR", ("maringa pr",), 81, 47), _city("Blumenau - SC", ("blumenau sc",), 82, 46),
            _city("São José do Rio Preto - SP", ("sao jose do rio preto sp",), 81, 48), _city("Sorocaba - SP", ("sorocaba sp",), 82, 44),
        ),
    },
    "us": {
        "label": "Estados Unidos", "locale": "en-US",
        "niches": (
            _niche("Med Spa", ("med spa", "medical spa", "aesthetic clinic"), 93, 92, 36, "needs to present treatments, credibility and a direct consultation path"),
            _niche("Roofing Company", ("roofing", "roofer"), 91, 89, 43, "needs to show completed work and capture inspection requests quickly"),
            _niche("Personal Injury Lawyer", ("personal injury", "lawyer", "attorney"), 95, 91, 24, "needs to build trust and qualify urgent case inquiries"),
            _niche("Custom Home Builder", ("home builder", "general contractor"), 94, 88, 39, "needs a strong portfolio and a clear project inquiry process"),
            _niche("Cosmetic Dentist", ("cosmetic dentist", "dentist", "dental"), 89, 90, 29, "needs to explain procedures and convert research into consultations"),
            _niche("HVAC Contractor", ("hvac", "air conditioning"), 87, 86, 45, "needs to capture urgent service and installation requests"),
            _niche("Pool Builder", ("pool builder", "pool contractor"), 90, 88, 47, "needs to show projects and qualify high-value estimates"),
            _niche("Kitchen Remodeling", ("kitchen remodeling", "remodeler"), 90, 87, 46, "needs visual proof and a structured quote request"),
            _niche("Landscaping Company", ("landscaping", "landscape contractor"), 82, 84, 50, "needs to show transformations and generate recurring service inquiries"),
            _niche("Immigration Lawyer", ("immigration lawyer", "immigration attorney"), 91, 89, 34, "needs to clarify services and convert complex questions into consultations"),
            _niche("Physical Therapy", ("physical therapy", "physiotherapy"), 83, 88, 41, "needs to explain specialties, insurance and booking options"),
            _niche("Commercial Cleaning", ("commercial cleaning", "office cleaning"), 79, 82, 53, "needs to present service scope and capture recurring B2B quotes"),
        ),
        "cities": (
            _city("Tampa - FL", ("tampa fl",), 85, 42), _city("Charlotte - NC", ("charlotte nc",), 84, 43),
            _city("Austin - TX", ("austin tx",), 90, 32), _city("Phoenix - AZ", ("phoenix az",), 84, 44),
            _city("Miami - FL", ("miami fl", "brickell miami"), 92, 28), _city("Orlando - FL", ("orlando fl",), 82, 45),
            _city("Dallas - TX", ("dallas tx",), 89, 33), _city("Scottsdale - AZ", ("scottsdale az",), 91, 29),
            _city("Nashville - TN", ("nashville tn",), 84, 44), _city("Raleigh - NC", ("raleigh nc",), 85, 41),
            _city("Jacksonville - FL", ("jacksonville fl",), 80, 49), _city("San Antonio - TX", ("san antonio tx",), 81, 48),
        ),
    },
    "europa": {
        "label": "Europa", "locale": "en-GB",
        "niches": (
            _niche("Clínica de estética", ("estetica", "aesthetic clinic", "beauty clinic"), 90, 91, 39, "precisa apresentar tratamentos, confiança e marcação de consulta"),
            _niche("Arquitetura e interiores", ("arquitet", "architect", "interior design"), 89, 87, 40, "precisa mostrar portfólio e captar projetos de maior valor"),
            _niche("Odontologia estética", ("dentista", "odont", "dentist", "dental"), 88, 90, 31, "precisa explicar tratamentos e converter pesquisas em consultas"),
            _niche("Imobiliária premium", ("imobiliaria", "real estate", "estate agent"), 92, 88, 29, "precisa apresentar imóveis e captar compradores internacionais"),
            _niche("Energia solar", ("energia solar", "solar installer"), 91, 85, 43, "precisa explicar retorno, instalação e captar simulações"),
            _niche("Contabilidade para empresas", ("contabilidade", "accountant", "accounting"), 83, 84, 42, "precisa apresentar serviços e captar empresas além da indicação"),
            _niche("Clínica veterinária", ("veterinar", "veterinary clinic"), 81, 86, 45, "precisa organizar serviços, urgências e marcações"),
            _niche("Fisioterapia", ("fisioter", "physiotherapy"), 82, 87, 44, "precisa explicar especialidades e facilitar a primeira consulta"),
            _niche("Reformas residenciais", ("reforma", "renovation", "home improvement"), 88, 86, 48, "precisa mostrar obras e qualificar pedidos de orçamento"),
            _niche("Advocacia para estrangeiros", ("advogado", "lawyer", "solicitor"), 90, 86, 37, "precisa esclarecer serviços e gerar consultas qualificadas"),
            _niche("Gestão de alojamento local", ("alojamento local", "property management", "holiday rental"), 85, 84, 46, "precisa conquistar proprietários e demonstrar capacidade de gestão"),
            _niche("Escola de idiomas", ("escola de idiomas", "language school"), 77, 83, 50, "precisa apresentar cursos, horários e captar matrículas"),
        ),
        "cities": (
            _city("Porto - Portugal", ("porto portugal",), 80, 46), _city("Valencia - Spain", ("valencia spain", "valencia espanha"), 82, 43),
            _city("Braga - Portugal", ("braga portugal",), 76, 51), _city("Málaga - Spain", ("malaga spain", "malaga espanha"), 83, 41),
            _city("Lisbon - Portugal", ("lisbon portugal", "lisboa portugal"), 88, 33), _city("Madrid - Spain", ("madrid spain", "madrid espanha"), 90, 28),
            _city("Milan - Italy", ("milan italy", "milao italia"), 91, 27), _city("Dublin - Ireland", ("dublin ireland", "dublin irlanda"), 89, 25),
            _city("Coimbra - Portugal", ("coimbra portugal",), 75, 53), _city("Seville - Spain", ("seville spain", "sevilha espanha"), 79, 48),
            _city("Turin - Italy", ("turin italy", "turim italia"), 82, 44), _city("Rotterdam - Netherlands", ("rotterdam netherlands",), 86, 36),
        ),
    },
}


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _matches(value, aliases):
    normalized = normalize(value)
    return any(normalize(alias) in normalized for alias in aliases)


def has_own_site(value):
    url = str(value or "").strip()
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("google.com"):
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", params.get("q", [url]))[0]
    return url.startswith(("http://", "https://")) and not any(domain in url.casefold() for domain in SOCIAL_OR_DIRECTORY_DOMAINS)


def _to_int(value):
    digits = re.findall(r"\d+", str(value or ""))
    return int("".join(digits)) if digits else 0


def _unique_values(values, limit=4):
    result = []
    seen = set()
    for value in values or []:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        key = normalize(cleaned)
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _resolve_niches(market, values):
    resolved = []
    for value in _unique_values(values, 2):
        match = next((item for item in market["niches"] if _matches(value, (item["name"], *item["aliases"]))), None)
        if match:
            resolved.append(match)
        else:
            resolved.append(_niche(value, (value,), 72, 78, 48, "precisa apresentar a empresa com clareza, construir confiança e facilitar o próximo contato comercial"))
    return resolved


def _resolve_cities(market, values):
    resolved = []
    for value in _unique_values(values, 4):
        match = next((item for item in market["cities"] if _matches(value, (item["name"], *item["aliases"]))), None)
        resolved.append(match or _city(value, (value,), 78, 46))
    return resolved


def build_research_plan(region, observations, pair_limit=8, focus_niches=None, focus_locations=None):
    if region not in MARKETS:
        raise ValueError("Mercado inválido.")
    market = MARKETS[region]
    studied = defaultdict(lambda: {"sample": 0, "runs": 0})
    for row in observations:
        if row.get("region") != region:
            continue
        key = (normalize(row.get("niche")), normalize(row.get("city")))
        studied[key]["sample"] += int(row.get("sample_size") or 0)
        studied[key]["runs"] += 1
    niche_exposure = {niche["name"]: sum(studied[(normalize(niche["name"]), normalize(city["name"]))]["sample"] + studied[(normalize(niche["name"]), normalize(city["name"]))]["runs"] * 3 for city in market["cities"]) for niche in market["niches"]}
    city_exposure = {city["name"]: sum(studied[(normalize(niche["name"]), normalize(city["name"]))]["sample"] + studied[(normalize(niche["name"]), normalize(city["name"]))]["runs"] * 3 for niche in market["niches"]) for city in market["cities"]}
    focused_niches = _resolve_niches(market, focus_niches)
    focused_cities = _resolve_cities(market, focus_locations)
    niches = focused_niches or sorted(market["niches"], key=lambda item: (niche_exposure[item["name"]], -(item["ticket"] + item["need"] + item["gap"]), item["name"]))[:4]
    cities = focused_cities or sorted(market["cities"], key=lambda item: (city_exposure[item["name"]], -(item["power"] + item["gap"]), item["name"]))[:4]
    candidates = []
    if focused_niches or focused_cities:
        combinations = ((niche, city) for niche in niches for city in cities)
    else:
        combinations = (
            (niche, cities[(niche_index + offset) % len(cities)])
            for niche_index, niche in enumerate(niches)
            for offset in range(2)
        )
    for niche, city in combinations:
        key = (normalize(niche["name"]), normalize(city["name"]))
        candidates.append({"region": region, "niche": niche["name"], "city": city["name"], "previous_sample": studied[key]["sample"], "why_site": niche["reason"]})
    return sorted(candidates, key=lambda item: item["previous_sample"])[:pair_limit]


def _lead_evidence(rows, niche, city):
    matches = [row for row in rows if _matches(row.get("nicho"), niche["aliases"]) and _matches(row.get("bairro"), city["aliases"])]
    return {
        "sample": len(matches), "no_site": sum(not has_own_site(row.get("link_inicial")) for row in matches),
        "contactable": sum(bool(str(row.get("telefone") or "").strip() or str(row.get("whatsapp_link") or "").strip() or str(row.get("email") or "").strip()) for row in matches),
        "mature": sum(_to_int(row.get("avaliacoes")) >= 10 for row in matches), "results": len(matches),
        "existing_leads": len(matches),
    }


def _research_evidence(observations, region, niche, city):
    matches = [row for row in observations if row.get("region") == region and normalize(row.get("niche")) == normalize(niche["name"]) and normalize(row.get("city")) == normalize(city["name"])]
    return {
        "sample": sum(int(row.get("sample_size") or 0) for row in matches), "no_site": sum(int(row.get("no_site_count") or 0) for row in matches),
        "contactable": sum(int(row.get("contactable_count") or 0) for row in matches), "mature": sum(int(row.get("mature_count") or 0) for row in matches),
        "results": max([int(row.get("results_count") or 0) for row in matches] or [0]),
        "runs": sum(1 for row in matches if int(row.get("sample_size") or 0) > 0),
        "existing_leads": 0,
    }


def _combine_evidence(lead_data, research_data):
    return {"sample": lead_data["sample"] + research_data["sample"], "no_site": lead_data["no_site"] + research_data["no_site"], "contactable": lead_data["contactable"] + research_data["contactable"], "mature": lead_data["mature"] + research_data["mature"], "results": max(lead_data["results"], research_data["results"]), "research_runs": research_data["runs"], "existing_leads": lead_data["existing_leads"]}


def _score_pair(niche, city, evidence):
    sample = evidence["sample"]
    prior_gap = (niche["gap"] + city["gap"]) / 2
    site_gap = (100 * evidence["no_site"] / sample) if sample else prior_gap
    blended_gap = ((site_gap * sample) + (prior_gap * 5)) / (sample + 5)
    contact_rate = (100 * evidence["contactable"] / sample) if sample else 55
    maturity_rate = (100 * evidence["mature"] / sample) if sample else 50
    demand = min(100, evidence["results"] * 12 + maturity_rate * 0.35)
    saturation_penalty = min(30, evidence["existing_leads"] * 2.5)
    score = niche["ticket"] * 0.20 + niche["need"] * 0.19 + city["power"] * 0.15 + blended_gap * 0.25 + demand * 0.13 + contact_rate * 0.08 + min(evidence["research_runs"], 3) * 1.2 - saturation_penalty
    return round(min(score, 100), 1)


def _evidence_label(evidence):
    sample = evidence["sample"]
    if sample >= 8 and evidence["research_runs"]:
        confidence = "validado"
    elif sample >= 4:
        confidence = "sinal forte"
    elif sample:
        confidence = "sinal inicial"
    else:
        confidence = "não investigado"
    if sample:
        gap = round(100 * evidence["no_site"] / sample)
        activity = f"{evidence['results']} resultados localizados" if evidence["results"] else "atividade local ainda limitada"
        saturation = f"; {evidence['existing_leads']} já estão na sua base" if evidence["existing_leads"] else ""
        return confidence, f"{gap}% sem site próprio na amostra de {sample} empresas; {activity}{saturation}."
    return confidence, "Ainda não passou pela investigação ao vivo do Google Maps."


def suggest_targets(region, rows, observations=None, recent_niches=None, focus_niches=None, focus_locations=None):
    if region not in MARKETS:
        raise ValueError("Mercado inválido.")
    observations = observations or []
    recent_niches = {normalize(value) for value in (recent_niches or [])}
    market = MARKETS[region]
    focused_niches = _resolve_niches(market, focus_niches)
    focused_cities = _resolve_cities(market, focus_locations)
    candidate_niches = focused_niches or list(market["niches"])
    candidate_cities = focused_cities or list(market["cities"])
    pairs = []
    for niche in candidate_niches:
        for city in candidate_cities:
            evidence = _combine_evidence(_lead_evidence(rows, niche, city), _research_evidence(observations, region, niche, city))
            score = _score_pair(niche, city, evidence) - (4 if normalize(niche["name"]) in recent_niches else 0)
            pairs.append({"niche": niche, "city": city, "evidence": evidence, "score": round(score, 1)})
    investigated_pairs = [pair for pair in pairs if pair["evidence"]["research_runs"]]
    eligible_pairs = investigated_pairs or [pair for pair in pairs if pair["evidence"]["sample"]] or pairs
    niche_rank = []
    for niche in candidate_niches:
        niche_pairs = sorted((pair for pair in eligible_pairs if pair["niche"]["name"] == niche["name"]), key=lambda pair: (-pair["score"], pair["city"]["name"]))
        if niche_pairs:
            evidence_total = sum(pair["evidence"]["sample"] for pair in niche_pairs)
            rank_score = sum(pair["score"] for pair in niche_pairs[:3]) / min(3, len(niche_pairs)) + min(evidence_total, 20) * 0.25
            niche_rank.append((round(rank_score, 1), niche))
    niche_limit = len(focused_niches) if focused_niches else 2
    selected_niches = focused_niches or [item[1] for item in sorted(niche_rank, key=lambda item: (-item[0], item[1]["name"]))[:niche_limit]]
    if len(selected_niches) < niche_limit:
        fallback_niches = sorted(
            (niche for niche in candidate_niches if niche not in selected_niches),
            key=lambda niche: (-max(pair["score"] for pair in pairs if pair["niche"] == niche), niche["name"]),
        )
        selected_niches.extend(fallback_niches[:niche_limit - len(selected_niches)])
    selected_pairs = [pair for pair in eligible_pairs if pair["niche"] in selected_niches]
    city_best = {}
    for pair in selected_pairs:
        current = city_best.get(pair["city"]["name"])
        if current is None or pair["score"] > current["score"]:
            city_best[pair["city"]["name"]] = pair
    city_limit = len(focused_cities) if focused_cities else 4
    top_places = sorted(city_best.values(), key=lambda pair: (-pair["score"], pair["city"]["name"]))[:city_limit]
    if len(top_places) < city_limit:
        remaining = [pair for pair in pairs if pair["niche"] in selected_niches and pair["city"]["name"] not in {item["city"]["name"] for item in top_places}]
        for pair in sorted(remaining, key=lambda item: (-item["score"], item["city"]["name"])):
            if pair["city"]["name"] not in {item["city"]["name"] for item in top_places}:
                top_places.append(pair)
            if len(top_places) == city_limit:
                break
    places = []
    for pair in top_places:
        confidence, evidence_text = _evidence_label(pair["evidence"])
        places.append({"nome": pair["city"]["name"], "regiao": region, "nicho_principal": pair["niche"]["name"], "score": round(pair["score"]), "confianca": confidence, "amostra": pair["evidence"]["sample"], "evidencia": evidence_text, "necessidade_site": pair["niche"]["reason"]})
    recommendations = []
    for niche in selected_niches:
        niche_places = [place for place in places if place["nicho_principal"] == niche["name"]] or places[:2]
        recommendations.append({"nicho": niche["name"], "motivo": niche["reason"], "cidades": [place["nome"] for place in niche_places]})
    return {
        "mercado": market["label"], "nichos": [niche["name"] for niche in selected_niches], "cidades": [place["nome"] for place in places],
        "pracas": places, "recomendacoes": recommendations, "total_combinacoes": len(selected_niches) * len(places),
        "contexto": {"nichos_informados": [item["name"] for item in focused_niches], "locais_informados": [item["name"] for item in focused_cities]},
        "investigacao": {"combinacoes_estudadas": len(investigated_pairs), "fonte": "Google Maps + histórico da plataforma"},
        "metodologia": "Cruza o alvo informado com presença de site, volume local, atividade das empresas, contato disponível, poder de compra e saturação da sua própria base.",
    }
