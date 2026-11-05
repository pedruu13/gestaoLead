import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime

from target_intelligence import MARKETS, normalize


NICHE_ENGINE_VERSION = "8.0"
MIN_CONVERSION_SAMPLE = 10
POSITIVE_OUTCOMES = {"Respondeu", "Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"}
VALID_OUTCOMES = {"Contatado", *POSITIVE_OUTCOMES, "Sem interesse"}

EQUIVALENT_NICHES = {
    "odontologia": ("dentista", "clinica odontologica", "odontologia", "dental", "cosmetic dentist"),
    "estetica": ("clinica de estetica", "estetica", "med spa", "medical aesthetics", "beauty clinic"),
    "advocacia": ("advogado", "advocacia", "law firm", "lawyer", "attorney"),
    "arquitetura": ("arquitetura", "arquiteto", "architecture studio", "interior design"),
    "contabilidade": ("contabilidade", "contador", "accountant", "accounting firm"),
    "academia": ("academia", "fitness centre", "fitness center", "treinamento funcional", "gym"),
    "reformas": ("reforma", "construcao", "construction", "renovation", "builder", "contractor"),
    "fisioterapia": ("fisioterapia", "fisioterapeuta", "physiotherapy", "physical therapy"),
    "veterinaria": ("veterinaria", "veterinario", "veterinary clinic"),
    "imobiliaria": ("imobiliaria", "real estate", "estate agent", "realtor"),
}

FAMILY_MARKERS = {
    "saude": ("clinic", "clinica", "dent", "fisi", "psic", "veter", "terapia", "health", "medical", "estet"),
    "profissional": ("advoc", "law", "contab", "account", "consult", "arquitet", "engineer"),
    "casa": ("reforma", "constr", "builder", "roof", "solar", "moveis", "furniture", "landscap", "pool"),
    "educacao": ("escola", "school", "educ", "idioma", "training"),
    "imobiliario": ("imobili", "real estate", "property"),
    "bem_estar": ("academ", "fitness", "gym", "beauty", "spa"),
}


def canonical_niche_key(value):
    normalized = normalize(value)
    for canonical, aliases in EQUIVALENT_NICHES.items():
        if any(normalize(alias) in normalized or normalized in normalize(alias) for alias in aliases):
            return canonical
    return normalized


def niche_family(value):
    normalized = normalize(value)
    for family, markers in FAMILY_MARKERS.items():
        if any(normalize(marker) in normalized for marker in markers):
            return family
    return canonical_niche_key(value).split(" ")[0] or "outros"


def catalog_profile(region, niche_name):
    market = MARKETS[region]
    key = canonical_niche_key(niche_name)
    for item in market["niches"]:
        if canonical_niche_key(item["name"]) == key:
            return item
    return {
        "name": niche_name,
        "ticket": 65,
        "need": 70,
        "gap": 50,
        "reason": "pode usar um site para apresentar serviços, gerar confiança e organizar contatos comerciais",
    }


def build_candidate_pool(region, catalog_names, crm_names=None, discovered=None, history=None, limit=8):
    history = history or []
    exposure = Counter(canonical_niche_key(item.get("niche")) for item in history)
    candidates = {}
    for source, values in (("catálogo inicial", catalog_names), ("CRM", crm_names or [])):
        for name in values:
            key = canonical_niche_key(name)
            if key:
                candidates.setdefault(key, {"name": str(name).strip(), "key": key, "sources": set(), "observed_businesses": 0})
                candidates[key]["sources"].add(source)
    for item in discovered or []:
        name = item.get("name")
        key = canonical_niche_key(name)
        if not key:
            continue
        candidate = candidates.setdefault(key, {"name": name, "key": key, "sources": set(), "observed_businesses": 0})
        candidate["sources"].add(item.get("source") or "fonte pública")
        candidate["observed_businesses"] += int(item.get("count") or 0)
        if candidate["sources"] == {"catálogo inicial"}:
            candidate["name"] = name
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            exposure[item["key"]],
            -int(item["observed_businesses"]),
            -len(item["sources"]),
            item["name"].casefold(),
        ),
    )
    output = []
    for item in ranked[:max(1, limit)]:
        output.append({**item, "sources": sorted(item["sources"]), "previous_recommendations": exposure[item["key"]]})
    return output


def _aggregate_observations(observations):
    groups = defaultdict(lambda: {
        "searched": 0, "verified": 0, "own_site": 0, "confirmed_no_site": 0, "probable_no_site": 0,
        "weak_site": 0, "site_unknown": 0, "contactable": 0, "active": 0,
        "qualified": 0, "duplicates": 0, "discarded": 0, "sources": set(),
        "examples": [], "cities": set(), "latest": "", "runs": set(),
    })
    for row in observations:
        key = canonical_niche_key(row.get("niche"))
        group = groups[key]
        group["name"] = row.get("niche")
        group["searched"] += int(row.get("results_count") or 0)
        group["verified"] += int(row.get("verified_count") if row.get("verified_count") is not None else row.get("sample_size") or 0)
        group["own_site"] += int(row.get("own_site_count") or 0)
        group["confirmed_no_site"] += int(row.get("confirmed_no_site_count") or 0)
        group["probable_no_site"] += int(row.get("probable_no_site_count") or 0)
        group["weak_site"] += int(row.get("weak_site_count") or 0)
        has_detailed_site_counts = any(row.get(field) is not None for field in ("confirmed_no_site_count", "probable_no_site_count", "weak_site_count"))
        group["site_unknown"] += int(row.get("site_unknown_count") if row.get("site_unknown_count") is not None else (row.get("no_site_count") or 0) if not has_detailed_site_counts else 0)
        group["contactable"] += int(row.get("contactable_count") or 0)
        group["active"] += int(row.get("active_count") if row.get("active_count") is not None else row.get("mature_count") or 0)
        group["qualified"] += int(row.get("qualified_count") or 0)
        group["duplicates"] += int(row.get("duplicate_count") or 0)
        group["discarded"] += int(row.get("discarded_count") or 0)
        group["cities"].add(row.get("city"))
        group["runs"].add(row.get("run_id"))
        group["latest"] = max(str(group["latest"] or ""), str(row.get("created_at") or ""))
        try:
            group["sources"].update(json.loads(row.get("sources_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            pass
        try:
            for example in json.loads(row.get("examples_json") or "[]"):
                if example.get("name") and example.get("name") not in {item.get("name") for item in group["examples"]}:
                    group["examples"].append(example)
        except (TypeError, json.JSONDecodeError):
            pass
    return groups


def _latest_history_by_key(history):
    latest = {}
    for item in history or []:
        key = item.get("niche_key") or canonical_niche_key(item.get("niche"))
        if key not in latest:
            latest[key] = item
    return latest


def _conversion_by_canonical_niche(rows):
    groups = defaultdict(lambda: {"contacted": 0, "responses": 0, "closed": 0})
    for row in rows:
        outcome = str(row.get("commercial_outcome") or "").strip()
        if outcome not in VALID_OUTCOMES:
            continue
        metrics = groups[canonical_niche_key(row.get("nicho"))]
        metrics["contacted"] += 1
        metrics["responses"] += int(outcome in POSITIVE_OUTCOMES)
        metrics["closed"] += int(outcome == "Contrato fechado")
    for metrics in groups.values():
        sample = metrics["contacted"]
        metrics["response_rate"] = round(metrics["responses"] * 100 / sample, 1) if sample else 0
        metrics["close_rate"] = round(metrics["closed"] * 100 / sample, 1) if sample else 0
    return groups


def _confidence(verified, target):
    if verified >= target:
        return "alta", 1.0
    if verified >= max(20, target * 0.6):
        return "média-alta", 0.88
    if verified >= 10:
        return "média", 0.72
    if verified > 0:
        return "baixa", max(0.35, math.sqrt(verified / max(target, 1)) * 0.65)
    return "inconclusiva", 0.2


def rank_niche_opportunities(region, observations, crm_rows, history=None, sample_target=50, limit=4):
    groups = _aggregate_observations(observations)
    conversions = _conversion_by_canonical_niche(crm_rows)
    latest_history = _latest_history_by_key(history)
    recommendations = []
    for key, data in groups.items():
        verified = data["verified"]
        if not verified:
            continue
        profile = catalog_profile(region, data.get("name") or key)
        opportunity_count = data["confirmed_no_site"] + data["probable_no_site"] + data["weak_site"]
        weighted_opportunity = data["confirmed_no_site"] + data["weak_site"] + data["probable_no_site"] * 0.65
        digital_rate = weighted_opportunity * 100 / verified
        contact_rate = data["contactable"] * 100 / verified
        active_rate = data["active"] * 100 / verified
        qualified_rate = data["qualified"] * 100 / verified
        own_site_rate = data["own_site"] * 100 / verified
        competition_rate = min(100, own_site_rate + data["duplicates"] * 35 / max(data["searched"], 1))
        confidence_label, confidence_factor = _confidence(verified, sample_target)
        conversion = conversions.get(key, {})
        conversion_sample = int(conversion.get("contacted") or 0)
        conversion_signal = 0
        if conversion_sample >= MIN_CONVERSION_SAMPLE:
            conversion_signal = min(100, float(conversion.get("response_rate") or 0) * 0.55 + float(conversion.get("close_rate") or 0) * 1.6)
        estimated_site_return = (float(profile.get("need") or 70) + float(profile.get("ticket") or 65)) / 2
        observed_score = (
            digital_rate * 0.28 + qualified_rate * 0.18 + contact_rate * 0.14 + active_rate * 0.12
            + estimated_site_return * 0.16 + (100 - own_site_rate) * 0.04 + conversion_signal * 0.08
        )
        saturation_penalty = competition_rate * 0.06
        score = observed_score * (0.58 + 0.42 * confidence_factor) - saturation_penalty
        metrics = {
            "searched": data["searched"], "verified": verified, "own_site": data["own_site"],
            "confirmed_no_site": data["confirmed_no_site"], "probable_no_site": data["probable_no_site"], "weak_site": data["weak_site"],
            "site_unknown": data["site_unknown"], "contactable": data["contactable"],
            "active": data["active"], "qualified": data["qualified"],
            "duplicates": data["duplicates"], "discarded": data["discarded"],
        }
        evidence_hash = hashlib.sha256(json.dumps(metrics, sort_keys=True).encode("utf-8")).hexdigest()
        previous = latest_history.get(key)
        repeat_penalty = 0
        comparison = {"status": "primeira pesquisa", "score_delta": None, "sample_delta": None}
        if previous:
            try:
                previous_metrics = json.loads(previous.get("metrics_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                previous_metrics = {}
            comparison = {
                "status": "novas evidências" if previous.get("evidence_hash") != evidence_hash else "sem evidência nova",
                "score_delta": round(score - float(previous.get("score") or 0), 1),
                "sample_delta": verified - int(previous_metrics.get("verified") or 0),
            }
            if previous.get("evidence_hash") == evidence_hash:
                repeat_penalty = 12
        final_score = max(0, min(100, score - repeat_penalty))
        no_site_percent = round(data["confirmed_no_site"] * 100 / verified, 1)
        contact_percent = round(contact_rate, 1)
        saturation_label = "alta" if competition_rate >= 70 else "média" if competition_rate >= 45 else "baixa"
        if conversion_sample >= MIN_CONVERSION_SAMPLE:
            potential_label = f"observado no CRM: {conversion.get('response_rate', 0)}% responderam e {conversion.get('close_rate', 0)}% fecharam em {conversion_sample} contatos"
            potential_type = "histórico real"
        else:
            potential_label = f"potencial estimado para uso de site; histórico comercial insuficiente ({conversion_sample}/{MIN_CONVERSION_SAMPLE})"
            potential_type = "estimativa"
        justification = (
            f"{data['confirmed_no_site']} estavam sem site confirmado, {data['probable_no_site']} tinham ausência provável e {data['weak_site']} possuíam problema verificável; "
            f"{data['contactable']} tinham canal comercial e {data['active']} mostraram atividade pública."
        )
        recommendations.append({
            "niche": data.get("name") or key, "niche_key": key, "family": niche_family(data.get("name") or key),
            "region": region, "cities": sorted(city for city in data["cities"] if city),
            "score": round(final_score, 1), "raw_score": round(score, 1), "repeat_penalty": repeat_penalty,
            "companies_searched": data["searched"], "companies_verified": verified,
            "companies_qualified": data["qualified"], "own_site_count": data["own_site"],
            "confirmed_no_site_count": data["confirmed_no_site"], "weak_site_count": data["weak_site"],
            "probable_no_site_count": data["probable_no_site"],
            "site_unknown_count": data["site_unknown"], "contactable_count": data["contactable"],
            "active_count": data["active"], "duplicate_count": data["duplicates"],
            "discarded_count": data["discarded"], "confirmed_no_site_percent": no_site_percent,
            "contact_availability_percent": contact_percent, "commercial_potential": potential_label,
            "observed_saturation": saturation_label, "observed_competition_percent": round(competition_rate, 1),
            "potential_type": potential_type, "confidence": confidence_label,
            "sample_target": sample_target, "researched_at": data["latest"] or datetime.now().isoformat(timespec="seconds"),
            "sources": sorted(data["sources"]), "justification": justification,
            "examples": data["examples"][:5], "comparison": comparison,
            "evidence_hash": evidence_hash, "metrics": metrics,
            "site_return_reason": profile.get("reason"),
        })
    recommendations.sort(key=lambda item: (-item["score"], -item["companies_verified"], item["niche"].casefold()))
    diversified = []
    used_families = set()
    for item in recommendations:
        if item["family"] in used_families and len(recommendations) > limit:
            continue
        diversified.append(item)
        used_families.add(item["family"])
        if len(diversified) >= limit:
            break
    if len(diversified) < min(limit, len(recommendations)):
        for item in recommendations:
            if item not in diversified:
                diversified.append(item)
            if len(diversified) >= limit:
                break
    return diversified
