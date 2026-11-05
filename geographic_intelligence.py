import json
import gzip
import math
import os
import re
import tempfile
import unicodedata
import urllib.request
from datetime import datetime, timedelta


IBGE_MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=nome"
COORDINATES_URL = "https://raw.githubusercontent.com/kelvins/Municipios-Brasileiros/main/json/municipios.json"
DEFAULT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "ibge_municipalities.json")
GEOGRAPHY_VERSION = "1.0"


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _download_json(url, timeout=90):
    request = urllib.request.Request(url, headers={"User-Agent": "GestaoLead/1.0 geographic-cache", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding") == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return json.loads(payload.decode("utf-8-sig"))


def refresh_catalog(cache_path=DEFAULT_CACHE_PATH, downloader=None):
    downloader = downloader or _download_json
    official_rows = downloader(IBGE_MUNICIPALITIES_URL)
    coordinate_rows = downloader(COORDINATES_URL)
    coordinates = {int(row["codigo_ibge"]): row for row in coordinate_rows}
    municipalities = []
    for row in official_rows:
        immediate = row.get("regiao-imediata") or {}
        intermediate = immediate.get("regiao-intermediaria") or {}
        micro = row.get("microrregiao") or {}
        meso = micro.get("mesorregiao") or {}
        state = intermediate.get("UF") or meso.get("UF") or {}
        region = state.get("regiao") or {}
        coordinate = coordinates.get(int(row["id"]), {})
        municipalities.append({
            "id": int(row["id"]), "name": row["nome"],
            "uf_id": int(state.get("id") or 0), "uf": state.get("sigla") or "",
            "state": state.get("nome") or "", "region_id": int(region.get("id") or 0),
            "region": region.get("nome") or "", "immediate_region": immediate.get("nome") or "",
            "intermediate_region": intermediate.get("nome") or "",
            "latitude": coordinate.get("latitude"), "longitude": coordinate.get("longitude"),
        })
    municipalities.sort(key=lambda item: (item["uf"], item["name"].casefold(), item["id"]))
    states = {}
    regions = {}
    for item in municipalities:
        states[item["uf"]] = {"id": item["uf_id"], "code": item["uf"], "name": item["state"], "region": item["region"]}
        regions[item["region"]] = {"id": item["region_id"], "name": item["region"]}
    payload = {
        "version": GEOGRAPHY_VERSION, "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "official_source": IBGE_MUNICIPALITIES_URL, "coordinates_source": COORDINATES_URL,
        "states": sorted(states.values(), key=lambda item: item["code"]),
        "regions": sorted(regions.values(), key=lambda item: item["id"]),
        "municipalities": municipalities,
    }
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix="ibge-", suffix=".json", dir=os.path.dirname(cache_path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary_path, cache_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return payload


def load_catalog(cache_path=DEFAULT_CACHE_PATH, max_age_days=30, allow_refresh=True):
    cached = None
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as file:
                cached = json.load(file)
        except (OSError, json.JSONDecodeError):
            cached = None
    stale = True
    if cached:
        try:
            stale = datetime.fromisoformat(cached["fetched_at"]) < datetime.now() - timedelta(days=max_age_days)
        except (KeyError, TypeError, ValueError):
            stale = True
    if allow_refresh and (not cached or stale):
        try:
            return refresh_catalog(cache_path)
        except Exception:
            if not cached:
                raise
    return cached


def catalog_index(catalog):
    return {int(item["id"]): item for item in catalog.get("municipalities", [])}


def municipality_label(item):
    return f"{item['name']} - {item['uf']}"


def search_municipalities(catalog, query="", uf="", region="", limit=50):
    term = normalize(query)
    output = []
    for item in catalog.get("municipalities", []):
        if uf and item["uf"] != uf.upper():
            continue
        if region and normalize(item["region"]) != normalize(region):
            continue
        if term and term not in normalize(item["name"]) and term not in normalize(municipality_label(item)):
            continue
        output.append(item)
        if len(output) >= max(1, min(int(limit), 1000)):
            break
    return output


def haversine_km(latitude_a, longitude_a, latitude_b, longitude_b):
    radius = 6371.0088
    lat_a, lat_b = math.radians(float(latitude_a)), math.radians(float(latitude_b))
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(float(longitude_b) - float(longitude_a))
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def select_municipalities(catalog, mode="custom", state_codes=None, regions=None, municipality_ids=None,
                          excluded_ids=None, center_id=None, radius_km=None):
    state_codes = {str(value).upper() for value in state_codes or []}
    region_keys = {normalize(value) for value in regions or []}
    selected_ids = {int(value) for value in municipality_ids or []}
    excluded_ids = {int(value) for value in excluded_ids or []}
    index = catalog_index(catalog)
    if mode == "brazil":
        selected = list(index.values())
    elif mode == "state":
        selected = [item for item in index.values() if item["uf"] in state_codes]
    else:
        selected = [item for item in index.values() if item["id"] in selected_ids or item["uf"] in state_codes or normalize(item["region"]) in region_keys]
    if center_id and radius_km:
        center = index.get(int(center_id))
        if not center or center.get("latitude") is None or center.get("longitude") is None:
            raise ValueError("Município central sem coordenadas disponíveis.")
        selected = [item for item in index.values() if item.get("latitude") is not None and item.get("longitude") is not None
                    and haversine_km(center["latitude"], center["longitude"], item["latitude"], item["longitude"]) <= float(radius_km)]
    return sorted((item for item in selected if item["id"] not in excluded_ids), key=lambda item: (item["uf"], item["name"].casefold()))


def rank_smart_locations(catalog, evidence_rows, conversion_rows, coverage_rows, limit=20):
    by_label = {}
    for item in catalog.get("municipalities", []):
        by_label[normalize(municipality_label(item))] = item
        by_label.setdefault(normalize(item["name"]), item)
    metrics = {}
    for row in evidence_rows or []:
        item = by_label.get(normalize(row.get("city")))
        if not item:
            continue
        current = metrics.setdefault(item["id"], {"verified": 0, "qualified": 0, "contactable": 0, "researches": 0})
        current["verified"] += int(row.get("verified_count") or row.get("sample_size") or 0)
        current["qualified"] += int(row.get("qualified_count") or 0)
        current["contactable"] += int(row.get("contactable_count") or 0)
        current["researches"] += 1
    conversions = {}
    for row in conversion_rows or []:
        item = by_label.get(normalize(row.get("bairro")))
        if not item:
            continue
        current = conversions.setdefault(item["id"], {"contacts": 0, "positive": 0, "closed": 0})
        outcome = str(row.get("commercial_outcome") or "")
        current["contacts"] += 1
        current["positive"] += int(outcome in {"Respondeu", "Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"})
        current["closed"] += int(outcome == "Contrato fechado")
    coverage = {int(row.get("municipality_id")): float(row.get("coverage_percent") or 0) for row in coverage_rows or []}
    ranked = []
    for municipality_id, observed in metrics.items():
        item = catalog_index(catalog)[municipality_id]
        verified = observed["verified"]
        qualified_rate = observed["qualified"] * 100 / verified if verified else 0
        contact_rate = observed["contactable"] * 100 / verified if verified else 0
        conversion = conversions.get(municipality_id, {})
        conversion_sample = int(conversion.get("contacts") or 0)
        conversion_signal = (conversion.get("positive", 0) * 100 / conversion_sample) if conversion_sample >= 10 else 0
        coverage_gap = 100 - coverage.get(municipality_id, 0)
        confidence = "alta" if verified >= 50 else "média" if verified >= 20 else "baixa"
        score = qualified_rate * 0.38 + contact_rate * 0.25 + conversion_signal * 0.17 + coverage_gap * 0.20
        ranked.append({**item, "score": round(score, 1), "confidence": confidence, "verified": verified,
                       "qualified": observed["qualified"], "contact_rate": round(contact_rate, 1),
                       "coverage_percent": round(coverage.get(municipality_id, 0), 1),
                       "conversion_sample": conversion_sample,
                       "reason": f"{observed['qualified']} de {verified} empresas qualificadas; contatos em {round(contact_rate, 1)}% da amostra; cobertura atual de {round(coverage.get(municipality_id, 0), 1)}%."})
    ranked.sort(key=lambda item: (-item["score"], -item["verified"], item["name"].casefold()))
    return ranked[:max(1, min(int(limit), 100))]
