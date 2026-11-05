import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from target_intelligence import normalize, search_terms_for_niche


USER_AGENT = os.environ.get(
    "DISCOVERY_USER_AGENT",
    "GestaoLead/1.0 (+https://github.com/pedruu13/gestaoLead)",
)


def _request_json(url, method="GET", payload=None, headers=None, timeout=20):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {error.code}: {details}") from error


def stable_cache_key(source, payload):
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{source}:{serialized}".encode("utf-8")).hexdigest()


class DiscoverySource:
    name = "base"
    estimated_cost_micros = 0

    def configured(self):
        return True

    def search(self, niche, location, region, page_token=None, page_size=20, request_budget=None):
        raise NotImplementedError


class GooglePlacesSource(DiscoverySource):
    name = "google_places"
    estimated_cost_micros = 32000
    endpoint = "https://places.googleapis.com/v1/places:searchText"
    field_mask = ",".join((
        "places.id", "places.displayName", "places.formattedAddress",
        "places.nationalPhoneNumber", "places.internationalPhoneNumber",
        "places.websiteUri", "places.rating", "places.userRatingCount",
        "places.businessStatus", "places.googleMapsUri", "places.primaryTypeDisplayName",
        "nextPageToken",
    ))

    def __init__(self, api_key=None, query_variants=2):
        self.api_key = (api_key or os.environ.get("GOOGLE_PLACES_API_KEY", "")).strip()
        try:
            self.query_variants = max(1, min(3, int(query_variants or 1)))
        except (TypeError, ValueError):
            self.query_variants = 2

    def configured(self):
        return bool(self.api_key)

    def search(self, niche, location, region, page_token=None, page_size=20, request_budget=None):
        if not self.configured():
            return {"candidates": [], "next_page_token": "", "requests": 0}
        terms = search_terms_for_niche(region, niche)
        terms = terms[:1] if page_token else terms[:self.query_variants]
        if request_budget is not None:
            terms = terms[:max(0, int(request_budget))]
        if not terms:
            return {"candidates": [], "next_page_token": "", "requests": 0}
        candidates = []
        seen = set()
        next_page_token = ""
        for index, term in enumerate(terms):
            payload = {"textQuery": f"{term} em {location}" if region == "br" else f"{term} in {location}", "pageSize": min(20, max(1, int(page_size)))}
            if page_token:
                payload["pageToken"] = page_token
            data = _request_json(
                self.endpoint, method="POST", payload=payload,
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": self.field_mask},
            )
            if index == 0:
                next_page_token = str(data.get("nextPageToken") or "")
            for place in data.get("places", []):
                source_id = str(place.get("id") or "").strip()
                name = str((place.get("displayName") or {}).get("text") or "").strip()
                if not source_id or not name or source_id in seen:
                    continue
                seen.add(source_id)
                candidates.append({
                    "source": self.name, "source_id": source_id, "name": name,
                    "category": str((place.get("primaryTypeDisplayName") or {}).get("text") or niche),
                    "address": str(place.get("formattedAddress") or location),
                    "phone": str(place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""),
                    "email": "", "website": str(place.get("websiteUri") or ""),
                    "rating": place.get("rating") or 0, "reviews": place.get("userRatingCount") or 0,
                    "business_status": str(place.get("businessStatus") or ""),
                    "source_url": str(place.get("googleMapsUri") or ""),
                    "niche": niche, "location": location, "query_term": term, "raw": place,
                })
        return {"candidates": candidates, "next_page_token": next_page_token, "requests": len(terms)}


OSM_FILTERS = {
    "odont": (("amenity", "dentist"),),
    "dent": (("amenity", "dentist"),),
    "advoc": (("office", "lawyer"),),
    "arquitet": (("office", "architect"),),
    "contab": (("office", "accountant"),),
    "academ": (("leisure", "fitness_centre"),),
    "treinamento": (("leisure", "fitness_centre"),),
    "veter": (("amenity", "veterinary"),),
    "fisi": (("healthcare", "physiotherapist"),),
    "psic": (("healthcare", "psychotherapist"),),
    "estet": (("shop", "beauty"), ("healthcare", "clinic")),
    "solar": (("craft", "electrician"), ("office", "energy_supplier")),
    "moveis": (("craft", "carpenter"), ("shop", "furniture")),
    "reforma": (("craft", "builder"), ("office", "construction_company")),
}


def osm_filters_for_niche(niche):
    normalized = normalize(niche)
    for marker, filters in OSM_FILTERS.items():
        if marker in normalized:
            return filters
    return ()


class OpenStreetMapSource(DiscoverySource):
    name = "openstreetmap"
    geocode_endpoint = "https://nominatim.openstreetmap.org/search"
    overpass_endpoints = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)

    def configured(self):
        return self.enabled

    def _bbox(self, location, region):
        countrycodes = {"br": "br", "us": "us"}.get(region)
        params = {"q": location, "format": "jsonv2", "limit": 1}
        if countrycodes:
            params["countrycodes"] = countrycodes
        data = _request_json(f"{self.geocode_endpoint}?{urllib.parse.urlencode(params)}")
        if not data:
            return None
        south, north, west, east = map(float, data[0]["boundingbox"])
        return south, west, north, east

    def search(self, niche, location, region, page_token=None, page_size=50, request_budget=None):
        if not self.configured() or page_token or request_budget is not None and int(request_budget) < 2:
            return {"candidates": [], "next_page_token": "", "requests": 0}
        bbox = self._bbox(location, region)
        if not bbox:
            return {"candidates": [], "next_page_token": "", "requests": 1}
        filters = osm_filters_for_niche(niche)
        if not filters:
            return {"candidates": [], "next_page_token": "", "requests": 0}
        clauses = []
        for key, value in filters:
            selector = f'["{key}"]' if value is None else f'["{key}"="{value}"]'
            clauses.append(f"nwr{selector}{bbox};")
        query = f"[out:json][timeout:25];({''.join(clauses)});out center {min(100, max(1, int(page_size)))};"
        endpoints = self.overpass_endpoints[:max(1, min(len(self.overpass_endpoints), int(request_budget or 3) - 1))]
        last_error = None
        attempts = 0
        data = None
        for endpoint in endpoints:
            attempts += 1
            request = urllib.request.Request(
                endpoint,
                data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                last_error = error
        if data is None:
            code = getattr(last_error, "code", "indisponível")
            raise RuntimeError(f"Overpass HTTP {code}") from last_error
        candidates = []
        for element in data.get("elements", []):
            tags = element.get("tags") or {}
            name = str(tags.get("name") or "").strip()
            if not name:
                continue
            source_id = f"{element.get('type')}:{element.get('id')}"
            address = ", ".join(filter(None, (
                tags.get("addr:street"), tags.get("addr:housenumber"),
                tags.get("addr:city"), tags.get("addr:state"),
            ))) or location
            phone = tags.get("contact:phone") or tags.get("phone") or ""
            email = tags.get("contact:email") or tags.get("email") or ""
            website = tags.get("contact:website") or tags.get("website") or ""
            candidates.append({
                "source": self.name, "source_id": source_id, "name": name,
                "category": niche, "address": address, "phone": phone, "email": email,
                "website": website, "rating": 0, "reviews": 0,
                "business_status": "OPERATIONAL" if tags.get("disused") != "yes" else "CLOSED",
                "source_url": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
                "niche": niche, "location": location,
                "raw": {"tags": tags, "lat": element.get("lat") or (element.get("center") or {}).get("lat"), "lon": element.get("lon") or (element.get("center") or {}).get("lon")},
            })
        return {"candidates": candidates, "next_page_token": "", "requests": 1 + attempts}


def source_registry(config=None):
    config = config or {}
    return [
        GooglePlacesSource(query_variants=config.get("google_places_query_variants", 2)),
        OpenStreetMapSource(enabled=str(config.get("enable_openstreetmap", "true")).lower() not in {"0", "false", "off", "no"}),
    ]
