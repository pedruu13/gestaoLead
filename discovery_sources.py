import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from browser_lock import acquire_browser_lock
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


def _clean_external_url(url):
    """
    Desempacota URLs externas de redirecionamentos do Google Maps (ex: google.com/url?q=...).
    """
    if not url:
        return ""
    url = str(url).strip()
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("google.com"):
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("url", params.get("q", [url]))[0]
            if target.startswith(("http://", "https://")):
                return target
    except Exception:
        pass
    return url if url.startswith(("http://", "https://")) else ""


def extract_rating_and_reviews_safely(full_text, phone=""):
    """
    Extrai nota e quantidade de avaliações do Google Maps sem confundir
    o DDD do telefone (ex: (41), (31), (19), (48)) com a quantidade de reviews.
    """
    text = str(full_text or "")
    if phone:
        text = text.replace(phone, " ")
    # Mascara números de telefone brasileiros com ou sem DDD em parênteses
    text = re.sub(r"(?:\+55\s*)?(?:\(?[1-9]{2}\)?\s*)?(?:9?\d{4})[-\s]?\d{4}", " ", text)
    # Remove qualquer DDD isolado entre parênteses
    text = re.sub(r"\([1-9]{2}\)", " ", text)

    rating = 0.0
    reviews = 0

    # 1. Caso A: nota seguida diretamente de parênteses com reviews: ex: "4,8 ★ (120)" ou "5.0 (15)"
    m_combo = re.search(r"([1-5][,\.][0-9])\s*(?:★|estrelas?|\*|\s)?\s*\(([\d\.]+)\)", text, re.I)
    if m_combo:
        try:
            rating = float(m_combo.group(1).replace(",", "."))
            reviews = int(m_combo.group(2).replace(".", ""))
            return rating, reviews
        except Exception:
            pass

    # 2. Caso B: avaliações explícitas com a palavra avaliações/reviews: ex: "140 avaliações"
    m_explicit_rev = re.search(r"([\d\.]+)\s*(?:avaliaç(?:ão|ões|oes)|reviews?)", text, re.I)
    if m_explicit_rev:
        try:
            reviews = int(m_explicit_rev.group(1).replace(".", ""))
        except Exception:
            pass

    # 3. Caso C: nota isolada: ex: "4.8 ★" ou "5,0 estrelas" ou número de nota decimal
    m_isolated_rat = re.search(r"\b([1-5][,\.][0-9])\b", text)
    if m_isolated_rat:
        try:
            rating = float(m_isolated_rat.group(1).replace(",", "."))
        except Exception:
            pass

    return rating, reviews


def tratar_consentimento_cookies(page):
    """
    Fecha janelas modais de consentimento de cookies (GDPR/LGPD) do Google Maps
    em ambientes locais ou instâncias de nuvem.
    """
    try:
        seletores = [
            'button:has-text("Aceitar tudo")',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Concordo")',
            'form[action*="consent"] button',
            'button[aria-label*="Aceitar" i]',
            'button[aria-label*="Accept" i]',
        ]
        for seletor in seletores:
            botao = page.locator(seletor).first
            if botao.count() > 0 and botao.is_visible(timeout=1500):
                botao.click(timeout=2500)
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    pass
                return True
    except Exception:
        pass
    return False


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
            if aria:
                name = aria
            if not name or "Resultado" in name:
                return None

            source_id = hashlib.md5((href or f"{name}:{location}").encode("utf-8")).hexdigest()
            site_btn = card.locator("a[data-value='Website'], a[aria-label*='site' i], a[aria-label*='website' i]").first
            website = site_btn.get_attribute("href") if site_btn.count() else ""

            full_text = " ".join(lines)
            phone = ""
            m_phone = re.search(r"(?:\+55\s*)?(?:\(?([1-9]{2})\)?\s*)?(?:9?\d{4})[-\s]?\d{4}", full_text)
            if m_phone:
                phone = m_phone.group(0).strip()

            rating = 0.0
            reviews = 0

            # 1. Tentar seletores específicos no DOM do card
            try:
                star_el = card.locator("span.MW4etd, span[aria-label*='estrela' i], span[aria-label*='star' i]").first
                if star_el.count():
                    aria = star_el.get_attribute("aria-label") or ""
                    st_text = star_el.inner_text() or ""
                    m_star = re.search(r"(\d[,\.]\d)", aria or st_text)
                    if m_star:
                        rating = float(m_star.group(1).replace(",", "."))
                    m_aria_rev = re.search(r"(\d[\d\.]*)\s*(?:avaliaç|review)", aria, re.I)
                    if m_aria_rev:
                        reviews = int(m_aria_rev.group(1).replace(".", ""))
            except Exception:
                pass

            try:
                if not reviews:
                    rev_el = card.locator("span.UY7F9, [aria-label*='avaliaç' i], [aria-label*='review' i]").first
                    if rev_el.count():
                        rev_text = rev_el.get_attribute("aria-label") or rev_el.inner_text() or ""
                        m_rev_el = re.search(r"\(?(\d[\d\.]*)\)?\s*(?:avaliaç|review|\))?", rev_text, re.I)
                        if m_rev_el:
                            reviews = int(m_rev_el.group(1).replace(".", ""))
            except Exception:
                pass

            # 2. Fallback seguro por regex sem confundir DDD com avaliações
            if not rating or not reviews:
                f_rat, f_rev = extract_rating_and_reviews_safely(full_text, phone)
                if not rating:
                    rating = f_rat
                if not reviews:
                    reviews = f_rev

            category = niche
            address = location
            for line in lines[1:]:
                if any(w in line for w in ["Website", "Rotas", "Salvar", "Ligar", "Agendar", "Aberto", "Fecha"]):
                    continue
                if "·" in line:
                    parts = [p.strip() for p in line.split("·")]
                    if re.match(r"^\d", parts[0]):
                        continue
                    if len(parts) >= 2:
                        category = parts[0] or niche
                        address = parts[-1] or location
                        break
                elif address == location and len(line) > 10 and re.search(r"(Rua|Av|Avenida|Praça|Al\.|Alameda|Rod|Km|N°|Bloco|Sala)", line, re.I):
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
                "business_status": "CLOSED_PERMANENTLY" if "fechado permanentemente" in full_text.casefold() else "UNKNOWN",
                "source_url": href,
                "niche": niche,
                "location": location,
            }
        except Exception:
            return None

    def _extract_detail_panel(self, page, base_candidate=None):
        """
        Extrai informações detalhadas diretamente do painel aberto da empresa no Google Maps
        (h1, telefone, website externo, endereço completo, categoria e status).
        """
        candidate = dict(base_candidate or {})

        # 1. Nome no H1 do painel lateral
        try:
            h1 = page.locator("h1").first
            if h1.count():
                name = (h1.inner_text() or "").strip()
                if name and "Resultado" not in name and "Google Maps" not in name:
                    candidate["name"] = name
        except Exception:
            pass

        # 2. Telefone no botão de contato do painel
        try:
            tel_el = page.locator("button[data-item-id^='phone'], [data-tooltip*='telefone' i], [data-tooltip*='phone' i]").first
            if tel_el.count():
                aria = tel_el.get_attribute("aria-label") or ""
                text = tel_el.inner_text() or ""
                raw_phone = aria or text
                raw_phone = re.sub(r"^(?:telefone|phone|ligar|call):\s*", "", raw_phone, flags=re.I).strip()
                if raw_phone:
                    candidate["phone"] = raw_phone
        except Exception:
            pass

        # 3. Website no botão de autoridade ou link de website
        try:
            link_el = page.locator("a[data-item-id='authority'], a[data-tooltip*='website' i], a[data-tooltip*='site' i], a[aria-label*='website' i], a[aria-label*='site' i]").first
            if link_el.count():
                href = link_el.get_attribute("href") or ""
                clean_href = _clean_external_url(href)
                if clean_href:
                    candidate["website"] = clean_href
        except Exception:
            pass

        # 4. Endereço completo no botão de endereço do painel
        try:
            end_el = page.locator("button[data-item-id='address'], [data-item-id*='address'], [data-tooltip*='endereço' i], [data-tooltip*='address' i]").first
            if end_el.count():
                aria = end_el.get_attribute("aria-label") or ""
                text = end_el.inner_text() or ""
                raw_addr = aria or text
                raw_addr = re.sub(r"^(?:endereço|endereco|address):\s*", "", raw_addr, flags=re.I).strip()
                if len(raw_addr) > 5:
                    candidate["address"] = raw_addr
        except Exception:
            pass

        # 5. Categoria mais refinada
        try:
            cat_el = page.locator("button[jsaction*='pane.rating.category'], span[jsaction*='pane.rating.category'], button[data-item-id='address'] + div button, div.fontBodyMedium button").first
            if cat_el.count():
                cat_text = (cat_el.inner_text() or "").strip()
                if cat_text and len(cat_text) > 2:
                    candidate["category"] = cat_text
        except Exception:
            pass

        # 6. Avaliação e Reviews (se o card não tiver capturado)
        if not candidate.get("rating") or not candidate.get("reviews"):
            try:
                cand_rating = candidate.get("rating") or 0.0
                cand_reviews = candidate.get("reviews") or 0

                # Seletores dedicados do painel
                if not cand_rating:
                    for sel in ("span[aria-label*='estrela' i]", "div.F7nice span[aria-hidden='true']", "span.ceNzKf"):
                        el = page.locator(sel).first
                        if el.count():
                            m_rat = re.search(r"(\d[,\.]\d)", el.get_attribute("aria-label") or el.inner_text() or "")
                            if m_rat:
                                cand_rating = float(m_rat.group(1).replace(",", "."))
                                break

                if not cand_reviews:
                    for sel in ("button[jsaction*='pane.reviewChart']", "span[aria-label*='avaliaç' i]", "button:has-text('avaliaç')"):
                        el = page.locator(sel).first
                        if el.count():
                            m_rev = re.search(r"([\d\.]+)\s*(?:avaliaç|review)", el.get_attribute("aria-label") or el.inner_text() or "", re.I)
                            if m_rev:
                                cand_reviews = int(m_rev.group(1).replace(".", ""))
                                break

                # Fallback seguro sobre texto completo
                if not cand_rating or not cand_reviews:
                    full_text = page.locator("div[role='main'], div.m6QErb, body").first.inner_text() or ""
                    f_rat, f_rev = extract_rating_and_reviews_safely(full_text, candidate.get("phone") or "")
                    if not cand_rating:
                        cand_rating = f_rat
                    if not cand_reviews:
                        cand_reviews = f_rev

                candidate["rating"] = cand_rating
                candidate["reviews"] = cand_reviews
            except Exception:
                pass

        # 7. Status de funcionamento
        try:
            page_text = page.locator("div[role='main'], body").first.inner_text().casefold()
            is_closed = any(pattern in page_text for pattern in (
                "fechado permanentemente", "fechada permanentemente",
                "permanentemente fechado", "permanentemente fechada",
                "permanently closed", "fechado temporariamente",
                "fechada temporariamente", "temporarily closed",
            ))
            if is_closed:
                candidate["business_status"] = "CLOSED_PERMANENTLY"
            elif candidate.get("business_status") in ("", "UNKNOWN"):
                candidate["business_status"] = "OPERATIONAL"
        except Exception:
            pass

        return candidate

    def search(self, niche, location, region, page_token=None, page_size=20, request_budget=None):
        if not self.configured():
            return {"candidates": [], "next_page_token": "", "requests": 0}
        terms = search_terms_for_niche(region, niche)
        terms = terms[:1] if page_token else terms[:max(1, min(2, int(request_budget or 1)))]
        if not terms:
            terms = [niche]

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Playwright não está instalado; busca Google Maps indisponível.") from error

        candidates = []
        seen_ids = set()
        requests_count = 0
        errors = []

        try:
            with acquire_browser_lock(timeout=180, caller=f"GoogleMapsSource:{niche}@{location}"):
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
                            page.goto(url, wait_until="domcontentloaded", timeout=12000)
                            tratar_consentimento_cookies(page)
                            page.wait_for_selector("div.Nv2PK, [role='feed']", timeout=7000)
                            containers = page.locator("div.Nv2PK")
                            stagnant_rounds = 0
                            card_candidates = []
                            for scroll_round in range(5):
                                previous_total = len(card_candidates)
                                for card_index in range(containers.count()):
                                    candidate = self._parse_card(containers.nth(card_index), niche, location)
                                    if candidate and candidate["source_id"] not in seen_ids:
                                        seen_ids.add(candidate["source_id"])
                                        card_candidates.append(candidate)
                                    if len(card_candidates) >= int(page_size):
                                        break
                                stagnant_rounds = stagnant_rounds + 1 if len(card_candidates) == previous_total else 0
                                feed = page.locator("[role='feed']").first
                                if len(card_candidates) >= int(page_size) or stagnant_rounds >= 2 or not feed.count():
                                    break
                                feed.evaluate("element => element.scrollBy(0, element.clientHeight)")
                                page.wait_for_timeout(700)

                            # Enriquecimento abrindo o painel de detalhes para cada candidato coletado
                            for base_cand in card_candidates:
                                final_cand = base_cand
                                detail_url = base_cand.get("source_url")
                                if detail_url and detail_url.startswith("http"):
                                    try:
                                        page.goto(detail_url, wait_until="domcontentloaded", timeout=9000)
                                        tratar_consentimento_cookies(page)
                                        try:
                                            page.wait_for_selector(
                                                "h1, button[data-item-id^='phone'], a[data-item-id='authority']",
                                                timeout=3000,
                                            )
                                        except Exception:
                                            pass
                                        final_cand = self._extract_detail_panel(page, base_cand)
                                    except Exception as detail_err:
                                        errors.append(f"DetailNavError:{type(detail_err).__name__}")
                                candidates.append(final_cand)
                                if len(candidates) >= int(page_size):
                                    break

                            if len(candidates) >= int(page_size):
                                break
                        except Exception as err:
                            errors.append(type(err).__name__)
                            print(f"[GoogleMapsSource] Falha na busca de '{query}': {err}")
                    browser.close()
        except Exception as error:
            raise RuntimeError("Não foi possível executar o navegador da busca Google Maps.") from error

        if errors and not candidates:
            raise RuntimeError("Google Maps não retornou resultados legíveis; verifique conexão, consentimento ou bloqueio da fonte.")
        return {"candidates": candidates, "next_page_token": "", "requests": requests_count, "warnings": errors}


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

    def __init__(self, enabled=True, timeout_seconds=8, max_endpoints=2):
        self.enabled = bool(enabled)
        self.timeout_seconds = max(3, min(15, int(timeout_seconds or 8)))
        self.max_endpoints = max(1, min(len(self.overpass_endpoints), int(max_endpoints or 2)))

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
        endpoints = self.overpass_endpoints[:min(self.max_endpoints, max(1, int(request_budget or 1)))]
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
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
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
    # Google Places é pago e permanece desligado por padrão. Só entra quando
    # houver chave e ativação explícita na configuração do servidor.
    places = GooglePlacesSource(query_variants=config.get("google_places_query_variants", 2))
    paid_places_enabled = str(config.get("enable_google_places", "false")).lower() in {"1", "true", "on", "yes"}
    if paid_places_enabled and places.configured():
        sources.append(places)

    # 2. Google Maps Nativo via Playwright (sempre disponível, 100% de cobertura)
    if str(config.get("enable_google_maps", "true")).lower() not in {"0", "false", "off", "no"}:
        sources.append(GoogleMapsSource(enabled=True, headless=bool(config.get("headless", True))))

    # OpenStreetMap é gratuito, porém o Overpass pode ficar indisponível por
    # minutos. Fica opt-in para não bloquear a entrega dos resultados do Maps.
    osm_opted_in = str(config.get("openstreetmap_opt_in", "false")).lower() in {"1", "true", "on", "yes"}
    if osm_opted_in and str(config.get("enable_openstreetmap", "false")).lower() in {"1", "true", "on", "yes"}:
        sources.append(OpenStreetMapSource(
            enabled=True,
            timeout_seconds=config.get("openstreetmap_timeout_seconds", 8),
            max_endpoints=config.get("openstreetmap_max_endpoints", 2),
        ))

    return sources
