import re
import unicodedata
import urllib.parse


SOCIAL_OR_DIRECTORY_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "linktr.ee",
    "wa.me",
    "api.whatsapp",
    "yelp.",
    "tripadvisor.",
    "yellowpages.",
    "foursquare.",
)


MARKETS = {
    "br": {
        "label": "Brasil",
        "niches": (
            {"name": "Clínica de estética", "aliases": ("estetica", "med spa"), "ticket": 90, "need": 91, "gap": 44},
            {"name": "Odontologia", "aliases": ("dentista", "odont"), "ticket": 84, "need": 89, "gap": 36},
            {"name": "Advocacia empresarial", "aliases": ("advogado", "advocacia", "jurid"), "ticket": 88, "need": 83, "gap": 38},
            {"name": "Móveis planejados", "aliases": ("moveis planejados", "marcenaria"), "ticket": 86, "need": 88, "gap": 48},
            {"name": "Arquitetura e interiores", "aliases": ("arquitet", "interiores"), "ticket": 87, "need": 86, "gap": 43},
            {"name": "Energia solar", "aliases": ("energia solar", "solar"), "ticket": 91, "need": 85, "gap": 40},
        ),
        "cities": (
            {"name": "Moema - São Paulo", "aliases": ("moema sao paulo",), "power": 91, "gap": 31},
            {"name": "Campinas - SP", "aliases": ("campinas sp",), "power": 84, "gap": 42},
            {"name": "Tatuapé - São Paulo", "aliases": ("tatuape sao paulo",), "power": 82, "gap": 40},
            {"name": "Pinheiros - São Paulo", "aliases": ("pinheiros sao paulo",), "power": 89, "gap": 28},
            {"name": "Ribeirão Preto - SP", "aliases": ("ribeirao preto sp",), "power": 82, "gap": 46},
            {"name": "Goiânia - GO", "aliases": ("goiania go",), "power": 80, "gap": 48},
            {"name": "Alphaville - SP", "aliases": ("alphaville sp", "barueri sp"), "power": 94, "gap": 25},
            {"name": "São José dos Campos - SP", "aliases": ("sao jose dos campos sp",), "power": 83, "gap": 41},
        ),
    },
    "us": {
        "label": "Estados Unidos",
        "niches": (
            {"name": "Med Spa", "aliases": ("med spa", "medical spa", "aesthetic clinic"), "ticket": 93, "need": 92, "gap": 36},
            {"name": "Roofing Company", "aliases": ("roofing", "roofer"), "ticket": 91, "need": 89, "gap": 43},
            {"name": "Personal Injury Lawyer", "aliases": ("personal injury", "lawyer", "attorney"), "ticket": 95, "need": 91, "gap": 24},
            {"name": "Custom Home Builder", "aliases": ("home builder", "general contractor"), "ticket": 94, "need": 88, "gap": 39},
            {"name": "Cosmetic Dentist", "aliases": ("cosmetic dentist", "dentist", "dental"), "ticket": 89, "need": 90, "gap": 29},
            {"name": "HVAC Contractor", "aliases": ("hvac", "air conditioning"), "ticket": 87, "need": 86, "gap": 45},
        ),
        "cities": (
            {"name": "Tampa - FL", "aliases": ("tampa fl",), "power": 85, "gap": 42},
            {"name": "Charlotte - NC", "aliases": ("charlotte nc",), "power": 84, "gap": 43},
            {"name": "Austin - TX", "aliases": ("austin tx",), "power": 90, "gap": 32},
            {"name": "Phoenix - AZ", "aliases": ("phoenix az",), "power": 84, "gap": 44},
            {"name": "Miami - FL", "aliases": ("miami fl", "brickell miami"), "power": 92, "gap": 28},
            {"name": "Orlando - FL", "aliases": ("orlando fl",), "power": 82, "gap": 45},
            {"name": "Dallas - TX", "aliases": ("dallas tx",), "power": 89, "gap": 33},
            {"name": "Scottsdale - AZ", "aliases": ("scottsdale az",), "power": 91, "gap": 29},
        ),
    },
    "europa": {
        "label": "Europa",
        "niches": (
            {"name": "Clínica de estética", "aliases": ("estetica", "aesthetic clinic", "beauty clinic"), "ticket": 90, "need": 91, "gap": 39},
            {"name": "Arquitetura e interiores", "aliases": ("arquitet", "architect", "interior design"), "ticket": 89, "need": 87, "gap": 40},
            {"name": "Odontologia estética", "aliases": ("dentista", "odont", "dentist", "dental"), "ticket": 88, "need": 90, "gap": 31},
            {"name": "Imobiliária premium", "aliases": ("imobiliaria", "real estate", "estate agent"), "ticket": 92, "need": 88, "gap": 29},
            {"name": "Energia solar", "aliases": ("energia solar", "solar installer"), "ticket": 91, "need": 85, "gap": 43},
            {"name": "Contabilidade para empresas", "aliases": ("contabilidade", "accountant", "accounting"), "ticket": 83, "need": 84, "gap": 42},
        ),
        "cities": (
            {"name": "Porto - Portugal", "aliases": ("porto portugal",), "power": 80, "gap": 46},
            {"name": "Valencia - Spain", "aliases": ("valencia spain", "valencia espanha"), "power": 82, "gap": 43},
            {"name": "Braga - Portugal", "aliases": ("braga portugal",), "power": 76, "gap": 51},
            {"name": "Málaga - Spain", "aliases": ("malaga spain", "malaga espanha"), "power": 83, "gap": 41},
            {"name": "Lisbon - Portugal", "aliases": ("lisbon portugal", "lisboa portugal"), "power": 88, "gap": 33},
            {"name": "Madrid - Spain", "aliases": ("madrid spain", "madrid espanha"), "power": 90, "gap": 28},
            {"name": "Milan - Italy", "aliases": ("milan italy", "milao italia"), "power": 91, "gap": 27},
            {"name": "Dublin - Ireland", "aliases": ("dublin ireland", "dublin irlanda"), "power": 89, "gap": 25},
        ),
    },
}


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _matches(value, aliases):
    normalized = _normalize(value)
    return any(_normalize(alias) in normalized for alias in aliases)


def _has_own_site(value):
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


def _collect_pair_evidence(rows, niche, city):
    matches = [
        row for row in rows
        if _matches(row.get("nicho"), niche["aliases"])
        and _matches(row.get("bairro"), city["aliases"])
    ]
    sample = len(matches)
    no_site = sum(not _has_own_site(row.get("link_inicial")) for row in matches)
    contactable = sum(bool(
        str(row.get("telefone") or "").strip()
        or str(row.get("whatsapp_link") or "").strip()
        or str(row.get("email") or "").strip()
    ) for row in matches)
    mature = sum(_to_int(row.get("avaliacoes")) >= 10 for row in matches)
    return {
        "sample": sample,
        "no_site": no_site,
        "site_gap": (100 * no_site / sample) if sample else None,
        "contact_rate": (100 * contactable / sample) if sample else 55,
        "maturity_rate": (100 * mature / sample) if sample else 50,
    }


def _score_pair(niche, city, evidence):
    sample = evidence["sample"]
    prior_gap = (niche["gap"] + city["gap"]) / 2
    blended_gap = prior_gap
    if sample:
        blended_gap = ((evidence["site_gap"] * sample) + (prior_gap * 4)) / (sample + 4)
    score = (
        niche["ticket"] * 0.23
        + niche["need"] * 0.20
        + city["power"] * 0.18
        + blended_gap * 0.28
        + evidence["contact_rate"] * 0.06
        + evidence["maturity_rate"] * 0.05
        + min(sample, 10) * 0.45
    )
    return round(min(score, 100), 1)


def _evidence_label(evidence):
    sample = evidence["sample"]
    if sample >= 8:
        return (
            "validado",
            f"{round(evidence['site_gap'])}% sem site próprio em {sample} leads já analisados neste recorte.",
        )
    if sample:
        return (
            "sinal inicial",
            f"Amostra inicial de {sample} lead{'s' if sample != 1 else ''}; confirme a tendência na próxima busca.",
        )
    return (
        "busca-piloto",
        "Estimativa estratégica sem histórico local suficiente; use a primeira busca para validar a taxa real.",
    )


def suggest_targets(region, rows):
    if region not in MARKETS:
        raise ValueError("Mercado inválido.")
    market = MARKETS[region]
    pairs = []
    for niche in market["niches"]:
        for city in market["cities"]:
            evidence = _collect_pair_evidence(rows, niche, city)
            pairs.append({
                "niche": niche,
                "city": city,
                "evidence": evidence,
                "score": _score_pair(niche, city, evidence),
            })

    niche_rank = []
    for niche in market["niches"]:
        niche_pairs = sorted(
            (pair for pair in pairs if pair["niche"]["name"] == niche["name"]),
            key=lambda pair: (-pair["score"], pair["city"]["name"]),
        )
        observed = sum(pair["evidence"]["sample"] for pair in niche_pairs)
        rank_score = sum(pair["score"] for pair in niche_pairs[:4]) / 4 + min(observed, 20) * 0.35
        niche_rank.append((round(rank_score, 1), niche))
    selected_niches = [item[1] for item in sorted(niche_rank, key=lambda item: (-item[0], item[1]["name"]))[:2]]

    selected_pairs = [pair for pair in pairs if pair["niche"] in selected_niches]
    city_rank = []
    for city in market["cities"]:
        candidates = [pair for pair in selected_pairs if pair["city"]["name"] == city["name"]]
        best = sorted(candidates, key=lambda pair: (-pair["score"], pair["niche"]["name"]))[0]
        city_rank.append(best)
    top_places = sorted(city_rank, key=lambda pair: (-pair["score"], pair["city"]["name"]))[:4]

    places = []
    for pair in top_places:
        confidence, evidence_text = _evidence_label(pair["evidence"])
        places.append({
            "nome": pair["city"]["name"],
            "regiao": region,
            "nicho_principal": pair["niche"]["name"],
            "score": round(pair["score"]),
            "confianca": confidence,
            "amostra": pair["evidence"]["sample"],
            "evidencia": evidence_text,
        })

    recommendations = []
    for niche in selected_niches:
        niche_places = [place for place in places if place["nicho_principal"] == niche["name"]]
        if not niche_places:
            niche_places = places[:2]
        recommendations.append({
            "nicho": niche["name"],
            "motivo": "Serviço de valor relevante, decisão baseada em confiança e espaço claro para um site apoiar a venda.",
            "cidades": [place["nome"] for place in niche_places],
        })

    return {
        "mercado": market["label"],
        "nichos": [niche["name"] for niche in selected_niches],
        "cidades": [place["nome"] for place in places],
        "pracas": places,
        "recomendacoes": recommendations,
        "total_combinacoes": len(selected_niches) * len(places),
        "metodologia": "Ranking por lacuna de site, valor do serviço, força comercial da praça, contato disponível e histórico da plataforma.",
    }
