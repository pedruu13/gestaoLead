import json
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from discovery_engine import DiscoveryEngine, candidate_identity
from discovery_sources import USER_AGENT, OpenStreetMapSource
from lead_validation import validate_candidate
from niche_intelligence import canonical_niche_key
from target_intelligence import normalize
from target_research import probe_google_maps


OSM_CATEGORY_LABELS = {
    "dentist": "Odontologia", "lawyer": "Advocacia", "accountant": "Contabilidade para empresas",
    "architect": "Arquitetura e interiores", "fitness_centre": "Academia e treinamento",
    "veterinary": "Clínica veterinária", "physiotherapist": "Fisioterapia",
    "psychotherapist": "Psicologia", "beauty": "Clínica de estética", "furniture": "Móveis planejados",
    "carpenter": "Marcenaria", "builder": "Reformas e construção", "construction_company": "Reformas e construção",
    "electrician": "Serviços elétricos", "photographer": "Fotografia profissional",
    "estate_agent": "Imobiliária", "language_school": "Escola de idiomas",
    "cleaning": "Limpeza comercial", "hvac": "Climatização e ar-condicionado",
    "car_repair": "Oficina mecânica", "hotel": "Hotelaria independente",
    "restaurant": "Restaurante", "bakery": "Padaria artesanal", "optician": "Ótica",
}


def _overpass_public_categories(location, region, limit=12):
    source = OpenStreetMapSource()
    bbox = source._bbox(location, region)
    if not bbox:
        return []
    keys = ("amenity", "office", "shop", "craft", "healthcare", "leisure", "tourism")
    clauses = "".join(f'nwr["name"]["{key}"]{bbox};' for key in keys)
    query = f"[out:json][timeout:25];({clauses});out tags 350;"
    encoded = urllib.parse.urlencode({"data": query}).encode("utf-8")
    data = None
    for endpoint in source.overpass_endpoints:
        request = urllib.request.Request(
            endpoint, data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    if data is None:
        return []
    counts = Counter()
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        for key in keys:
            value = normalize(tags.get(key))
            if value in OSM_CATEGORY_LABELS:
                counts[OSM_CATEGORY_LABELS[value]] += 1
                break
    return [
        {"name": name, "count": count, "source": "OpenStreetMap"}
        for name, count in counts.most_common(limit) if count >= 2
    ]


def discover_public_niches(db_name, region, locations, catalog_names, refresh=False, limit=12, config=None):
    config = config or {}
    connection = sqlite3.connect(db_name)
    connection.row_factory = sqlite3.Row
    try:
        cached = [dict(row) for row in connection.execute(
            """SELECT niche_name AS name, observed_businesses AS count, source
               FROM dynamic_niche_catalog
               WHERE region = ? AND last_seen_at >= datetime('now', '-7 days')
               ORDER BY observed_businesses DESC LIMIT ?""",
            (region, limit),
        ).fetchall()]
        crm_names = [row[0] for row in connection.execute(
            "SELECT DISTINCT nicho FROM leads WHERE trim(coalesce(nicho, '')) != ''"
        ).fetchall()]
        usage_row = connection.execute(
            "SELECT requests FROM source_usage WHERE usage_date = date('now') AND source = 'openstreetmap'"
        ).fetchone()
    finally:
        connection.close()
    discovered = [] if refresh else cached
    try:
        osm_daily_limit = max(1, int(config.get("openstreetmap_daily_limit", 30) or 30))
    except (TypeError, ValueError):
        osm_daily_limit = 30
    usage_today = int(usage_row[0]) if usage_row else 0
    if not discovered and locations and usage_today < osm_daily_limit:
        query_failed = False
        try:
            discovered = _overpass_public_categories(locations[0], region, limit=limit)
        except Exception:
            discovered = []
            query_failed = True
        connection = sqlite3.connect(db_name)
        try:
            connection.execute(
                """INSERT INTO source_usage (usage_date, source, requests, candidates, errors)
                   VALUES (date('now'), 'openstreetmap', 1, ?, ?)
                   ON CONFLICT(usage_date, source) DO UPDATE SET
                   requests = requests + 1, candidates = candidates + excluded.candidates,
                   errors = errors + excluded.errors""",
                (sum(int(item.get("count") or 0) for item in discovered), int(query_failed)),
            )
            if discovered:
                for item in discovered:
                    connection.execute(
                        """INSERT INTO dynamic_niche_catalog
                           (region, niche_key, niche_name, source, observed_businesses)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(region, niche_key, source) DO UPDATE SET
                           niche_name = excluded.niche_name,
                           observed_businesses = excluded.observed_businesses,
                           last_seen_at = CURRENT_TIMESTAMP""",
                        (region, canonical_niche_key(item["name"]), item["name"], item["source"], item["count"]),
                    )
            connection.commit()
        finally:
            connection.close()
    return {"discovered": discovered, "crm_names": crm_names, "catalog_names": catalog_names}


def _empty_result(pair):
    return {
        "region": pair["region"], "niche": pair["niche"], "city": pair["city"],
        "results_count": 0, "sample_size": 0, "verified_count": 0, "own_site_count": 0,
        "confirmed_no_site_count": 0, "probable_no_site_count": 0, "weak_site_count": 0, "site_unknown_count": 0,
        "no_site_count": 0, "contactable_count": 0, "active_count": 0, "mature_count": 0,
        "qualified_count": 0, "duplicate_count": 0, "discarded_count": 0,
        "sources": [], "examples": [],
    }


def _research_with_modular_engine(db_name, config, plan, sample_target, progress=None, cancelled=None):
    progress = progress or (lambda *_: None)
    cancelled = cancelled or (lambda: False)
    results = []
    niche_pair_counts = Counter(item["niche"] for item in plan)
    seen_by_niche = defaultdict(set)
    verified_by_niche = Counter()
    total_target = max(1, sample_target * len(niche_pair_counts))
    for pair in plan:
        if cancelled() or verified_by_niche[pair["niche"]] >= sample_target:
            continue
        result = _empty_result(pair)
        per_pair_target = max(5, math.ceil(sample_target / niche_pair_counts[pair["niche"]]))
        engine = DiscoveryEngine(db_name, config)
        job_id = engine.create_job({
            "region": pair["region"], "niches": [pair["niche"]], "locations": [pair["city"]],
            "purpose": "niche_research",
        })
        try:
            candidates = engine.run(job_id, cancelled=cancelled)
        except Exception as error:
            result["error"] = str(error)[:240]
            results.append(result)
            continue
        result["results_count"] = len(candidates)
        for candidate in candidates:
            identity = candidate_identity(candidate)
            if identity in seen_by_niche[pair["niche"]]:
                result["duplicate_count"] += 1
                continue
            seen_by_niche[pair["niche"]].add(identity)
            if cancelled() or verified_by_niche[pair["niche"]] >= sample_target or result["verified_count"] >= per_pair_target:
                break
            validation = validate_candidate(
                candidate, region=pair["region"],
                corroborating_sources=len(set(candidate.get("sources") or [candidate.get("source")])),
                inspect_site=True,
            )
            if not validation["valid_business"]:
                result["discarded_count"] += 1
                continue
            result["verified_count"] += 1
            result["sample_size"] += 1
            verified_by_niche[pair["niche"]] += 1
            site = validation["site"]
            if site["present"] and site["working"] and site["belongs"]:
                result["own_site_count"] += 1
                site_label = "site próprio ativo"
            elif site["present"]:
                result["weak_site_count"] += 1
                site_label = "site com problema verificável"
            elif validation["site_confidence"] == "CONFIRMADO":
                result["confirmed_no_site_count"] += 1
                result["no_site_count"] += 1
                site_label = "sem site confirmado"
            elif validation["site_confidence"] == "PROVÁVEL":
                result["probable_no_site_count"] += 1
                result["no_site_count"] += 1
                site_label = "provável ausência de site"
            else:
                result["site_unknown_count"] += 1
                result["no_site_count"] += 1
                site_label = "site não localizado, ainda não confirmado"
            contactable = bool(validation["phone"]["valid"] or validation["email"])
            active = bool(validation["activity_signals"])
            result["contactable_count"] += int(contactable)
            result["active_count"] += int(active)
            result["mature_count"] += int(active)
            qualified = active and contactable and site_label in {"sem site confirmado", "provável ausência de site", "site com problema verificável"}
            result["qualified_count"] += int(qualified)
            for source_name in candidate.get("sources") or [candidate.get("source")]:
                if source_name and source_name not in result["sources"]:
                    result["sources"].append(source_name)
            if len(result["examples"]) < 5:
                result["examples"].append({
                    "name": candidate.get("name"), "city": pair["city"], "site_status": site_label,
                    "contact": validation["phone"]["kind"] if validation["phone"]["valid"] else "e-mail" if validation["email"] else "não localizado",
                    "source_url": candidate.get("source_url", ""),
                })
            completed = sum(verified_by_niche.values())
            progress(completed, total_target, f"{completed} empresa(s) verificadas de um alvo de {total_target}...")
        result["sources"] = sorted(result["sources"])
        results.append(result)
    return results


def research_market_samples(db_name, config, plan, sample_target=50, progress=None, cancelled=None, max_seconds=180):
    started_at = time.monotonic()
    original_cancelled = cancelled or (lambda: False)
    cancelled = lambda: original_cancelled() or time.monotonic() - started_at >= max_seconds
    if os.environ.get("GOOGLE_PLACES_API_KEY", "").strip() and str(config.get("enable_modular_discovery", "true")).lower() not in {"0", "false", "off", "no"}:
        return _research_with_modular_engine(db_name, config, plan, sample_target, progress, cancelled)
    pairs_per_niche = Counter(item["niche"] for item in plan)
    sample_per_pair = max(3, min(25, math.ceil(sample_target / max(pairs_per_niche.values() or [1]))))
    return probe_google_maps(
        plan, headless=config.get("headless", True), sample_per_pair=sample_per_pair,
        progress=progress, cancelled=cancelled, max_seconds=max_seconds,
    )
