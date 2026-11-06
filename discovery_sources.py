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


class GoogleMapsSource(DiscoverySource):
    """
    Fonte nativa com Playwright headless no Google Maps.
    Permite encontrar qualquer empresa no Brasil e no exterior sem necessidade de chaves de API pagas.
    """
    name = "google_maps"
    estimated_cost_micros = 0

    def __init__(self, enabled=True, headless=True):
        self.enabled = bool(enabled)
        self.headless = bool(headless)

    def configured(self):
        return self.enabled

    def _parse_card(self, card, niche, location):
        try:
            text = card.inner_text()
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if not lines:
                return None
            name = lines[0]
            link_el = card.locator("a.hfpxzc").first
            href = link_el.get_attribute("href") if link_el.count() else ""
            aria = link_el.get_attribute("aria-label") if link_el.count() else ""
            if aria and not name:
                name = aria
            if not name or "Resultado" in name:
                return None

            source_id = hashlib.md5((href or f"{name}:{location}").encode("utf-8")).hexdigest()
            site_btn = card.locator("a[data-value='Website'], a[aria-label*='site' i], a[aria-label*='website' i]").first
            website = site_btn.get_attribute("href") if site_btn.count() else ""

            full_text = " ".join(lines)
            rating = 0.0
            reviews = 0
            m_rating = re.search(r"(\d[,\.]\d)\s*(?:estrelas|\u2605|\*|\()?", full_text)
            if m_rating:
                try:
                    rating = float(m_rating.group(1).replace(",", "."))
                except Exception:
                    pass
            m_reviews = re.search(r"\(([\d\.]+)\)", full_text)
            if m_reviews:
                try:
                    reviews = int(m_reviews.group(1).replace(".", ""))
                except Exception:
                    pass

            phone = ""
            m_phone = re.search(r"(?:\+55\s*)?(?:\(?([1-9]{2})\)?\s*)?(?:9?\d{4})[-\s]?\d{4}", full_text)
            if m_phone:
                phone = m_phone.group(0).strip()

            category = niche
            address = location
            for line in lines[1:]:
                if any(w in line for w in ["Website", "Rotas", "Salvar", "Ligar", "Agendar", "Aberto", "Fecha"]):
                    continue
                if "·" in line:
                    parts = [p.strip() for p in line.split("·")]
                    if len(parts) >= 2:
                        category = parts[0] or niche
                        address = parts[-1] or location
                        break
                elif not address and len(line) > 10 and re.search(r"(Rua|Av|Avenida|Praça|Al\.|Alameda|Rod|Km|N°|Bloco|Sala)", line, re.I):
                    address = line

            return {
                "source": self.name,
                "source_id": source_id,
                "name": name,
                "category": category,
                "address": address,
                "phone": phone,
                "email": "",
                "website": website,
                "rating": rating,
                "reviews": reviews,
                "business_status": "OPERATIONAL",
                "source_url": href,
                "niche": niche,
                "location": location,
            }
        except Exception:
            return None

    def search(self, niche, location, region, page_token=None, page_size=20, request_budget=None):
        if not self.configured():
            return {"candidates": [], "next_page_token": "", "requests": 0}
        terms = search_terms_for_niche(region, niche)
        terms = terms[:1] if page_token else terms[:max(1, min(2, int(request_budget or 1)))]
        if not terms:
            terms = [niche]

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"candidates": [], "next_page_token": "", "requests": 0}

        candidates = []
        seen_ids = set()
        requests_count = 0

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-software-rasterizer"],
                )
                context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 800})
                page = context.new_page()
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

                for term in terms:
                    requests_count += 1
                    query = f"{term} em {location}" if region == "br" else f"{term} in {location}"
                    url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=18000)
                        page.wait_for_timeout(1000)
                        containers = page.locator("div.Nv2PK")
                        count = containers.count()
                        for i in range(min(count, int(page_size))):
                            candidate = self._parse_card(containers.nth(i), niche, location)
                            if candidate and candidate["source_id"] not in seen_ids:
                                seen_ids.add(candidate["source_id"])
                                candidates.append(candidate)
                        if len(candidates) >= int(page_size):
                            break
                    except Exception as err:
                        print(f"[GoogleMapsSource] Falha na busca de '{query}': {err}")
                browser.close()
        except Exception as error:
            print(f"[GoogleMapsSource] Erro geral ao executar Playwright: {error}")

        return {"candidates": candidates, "next_page_token": "", "requests": requests_count}


OSM_FILTERS = {
    "odont": (("amenity", "dentist"),),
    "dent": (("amenity", "dentist"),),
    "imobili": (("office", "estate_agent"), ("shop", "estate_agent")),
    "corretor": (("office", "estate_agent"),),
    "advoc": (("office", "lawyer"),),
    "direito": (("office", "lawyer"),),
    "juridic": (("office", "lawyer"),),
    "arquitet": (("office", "architect"),),
    "urbanis": (("office", "architect"),),
    "contab": (("office", "accountant"),),
    "fiscal": (("office", "accountant"),),
    "academ": (("leisure", "fitness_centre"),),
    "treinamento": (("leisure", "fitness_centre"),),
    "crossfit": (("leisure", "fitness_centre"),),
    "pilates": (("leisure", "fitness_centre"),),
    "veter": (("amenity", "veterinary"),),
    "pet": (("shop", "pet"), ("amenity", "veterinary")),
    "fisi": (("healthcare", "physiotherapist"),),
    "psic": (("healthcare", "psychotherapist"),),
    "medic": (("amenity", "doctors"), ("amenity", "clinic"), ("healthcare", "clinic")),
    "clinic": (("amenity", "clinic"), ("healthcare", "clinic"), ("amenity", "doctors")),
    "dermat": (("amenity", "clinic"), ("healthcare", "clinic"), ("amenity", "doctors")),
    "cirurg": (("amenity", "clinic"), ("healthcare", "hospital"), ("healthcare", "clinic")),
    "oftalm": (("amenity", "clinic"), ("healthcare", "clinic")),
    "estet": (("shop", "beauty"), ("healthcare", "clinic")),
    "beleza": (("shop", "beauty"), ("shop", "hairdresser")),
    "salao": (("shop", "hairdresser"), ("shop", "beauty")),
    "solar": (("craft", "electrician"), ("office", "energy_supplier")),
    "eletric": (("craft", "electrician"),),
    "moveis": (("craft", "carpenter"), ("shop", "furniture")),
    "marcen": (("craft", "carpenter"),),
    "reforma": (("craft", "builder"), ("office", "construction_company")),
    "construt": (("office", "construction_company"), ("craft", "builder")),
    "engenhar": (("office", "engineer"), ("office", "construction_company")),
    "restaur": (("amenity", "restaurant"),),
    "pizz": (("amenity", "restaurant"), ("amenity", "fast_food")),
    "bar": (("amenity", "bar"), ("amenity", "pub")),
    "cafe": (("amenity", "cafe"),),
    "gastron": (("amenity", "restaurant"), ("amenity", "cafe")),
    "hotel": (("tourism", "hotel"), ("tourism", "guest_house")),
    "pousada": (("tourism", "guest_house"), ("tourism", "hotel")),
    "auto": (("shop", "car_repair"), ("shop", "car")),
    "oficina": (("shop", "car_repair"),),
    "mecanic": (("shop", "car_repair"),),
    "concessionar": (("shop", "car"),),
    "escola": (("amenity", "school"), ("amenity", "college")),
    "curso": (("amenity", "language_school"), ("amenity", "school")),
    "idioma": (("amenity", "language_school"),),
    "seguro": (("office", "insurance"),),
    "agencia": (("office", "advertising_agency"), ("office", "company")),
    "market": (("office", "advertising_agency"), ("office", "company")),
    "consultor": (("office", "consulting"), ("office", "company")),
    "ti": (("office", "it"), ("office", "telecommunication")),
    "software": (("office", "it"), ("office", "company")),
    "logist": (("office", "logistics"), ("office", "transportation")),
    "transp": (("office", "logistics"), ("office", "transportation")),
}


def osm_filters_for_niche(niche):
    normalized = normalize(niche)
    for marker, filters in OSM_FILTERS.items():
        if marker in normalized:
            return filters
    # Fallback amplo para nichos não mapeados
    return (("office", None), ("shop", None), ("amenity", None), ("craft", None))


class OpenStreetMapSource(DiscoverySource):
    name = "openstreetmap"
    geocode_endpoint = "https://nominatim.openstreetmap.org/search"
    overpass_endpoints = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
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
        if not self.configured() or page_token or (request_budget is not None and int(request_budget) < 1):
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
        endpoints = self.overpass_endpoints[:max(1, min(len(self.overpass_endpoints), int(request_budget or 3)))]
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
                with urllib.request.urlopen(request, timeout=25) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                last_error = error
                continue
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
    sources = []
    # 1. Google Places Oficial (se houver API key)
    places = GooglePlacesSource(query_variants=config.get("google_places_query_variants", 2))
    if places.configured():
        sources.append(places)

    # 2. Google Maps Nativo via Playwright (sempre disponível, 100% de cobertura)
    if str(config.get("enable_google_maps", "true")).lower() not in {"0", "false", "off", "no"}:
        sources.append(GoogleMapsSource(enabled=True, headless=bool(config.get("headless", True))))

    # 3. OpenStreetMap
    if str(config.get("enable_openstreetmap", "true")).lower() not in {"0", "false", "off", "no"}:
        sources.append(OpenStreetMapSource(enabled=True))

    return sources
