import re
import time
import urllib.parse

from target_intelligence import MARKETS, has_own_site, search_terms_for_niche


def _external_url(value):
    if not value:
        return ""
    url = str(value).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("google.com"):
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", params.get("q", [url]))[0]
    return url if url.startswith(("http://", "https://")) else ""


def _review_count(page):
    elements = page.locator("[aria-label]")
    for index in range(min(elements.count(), 300)):
        text = elements.nth(index).get_attribute("aria-label") or ""
        match = re.search(r"([\d.,]+)\s*(?:avalia(?:cao|coes|ção|ções)|reviews?)", text.casefold())
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            return int(digits) if digits else 0
    return 0


def probe_google_maps(plan, headless=True, sample_per_pair=3, progress=None, cancelled=None, max_seconds=35):
    from playwright.sync_api import sync_playwright
    progress = progress or (lambda *_: None)
    cancelled = cancelled or (lambda: False)
    observations = []
    started_at = time.monotonic()
    total_samples = max(1, len(plan) * sample_per_pair)
    completed_samples = 0

    def time_exhausted():
        return time.monotonic() - started_at >= max_seconds

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-setuid-sandbox", "--disable-software-rasterizer"])
        context = browser.new_context(locale=MARKETS[plan[0]["region"]]["locale"], viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.set_default_timeout(4000)
        if headless:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "media", "font") else route.continue_())
        for pair_index, pair in enumerate(plan):
            if cancelled() or time_exhausted():
                break
            progress(completed_samples, total_samples, f"Investigando {pair['niche']} em {pair['city']}...")
            result = {
                "region": pair["region"], "niche": pair["niche"], "city": pair["city"],
                "results_count": 0, "sample_size": 0, "verified_count": 0,
                "own_site_count": 0, "confirmed_no_site_count": 0, "probable_no_site_count": 0, "weak_site_count": 0,
                "site_unknown_count": 0, "no_site_count": 0, "contactable_count": 0,
                "active_count": 0, "mature_count": 0, "qualified_count": 0,
                "duplicate_count": 0, "discarded_count": 0,
                "sources": ["Google Maps"], "examples": [],
            }
            try:
                hrefs = []
                for search_term in search_terms_for_niche(pair["region"], pair["niche"]):
                    if time_exhausted():
                        break
                    query = urllib.parse.quote(f"{search_term} {pair['city']}")
                    page.goto(f"https://www.google.com/maps/search/{query}", wait_until="domcontentloaded", timeout=14000)
                    try:
                        page.wait_for_selector("a.hfpxzc, a[href*='/maps/place/']", timeout=3000)
                    except Exception:
                        pass
                    links = page.locator("a.hfpxzc")
                    if not links.count():
                        links = page.locator("a[href*='/maps/place/']")
                    for index in range(min(links.count(), 20)):
                        href = links.nth(index).get_attribute("href")
                        if href and href not in hrefs:
                            hrefs.append(href)
                    if len(hrefs) >= sample_per_pair:
                        break
                result["results_count"] = len(hrefs)
                seen_places = set()
                for href in hrefs[:sample_per_pair]:
                    if cancelled() or time_exhausted():
                        break
                    try:
                        page.goto(href, wait_until="domcontentloaded", timeout=12000)
                        page.wait_for_selector("h1", timeout=3500)
                        page.wait_for_timeout(350)
                        canonical_href = href.split("?", 1)[0]
                        if canonical_href in seen_places:
                            result["duplicate_count"] += 1
                            continue
                        seen_places.add(canonical_href)
                        name = (page.locator("h1").first.inner_text() or "").strip()
                        website = page.locator("a[data-item-id='authority'], a[data-tooltip='Abrir website'], a[data-tooltip='Open website']").first
                        website_url = _external_url(website.get_attribute("href")) if website.count() else ""
                        review_count = _review_count(page)
                        has_phone = page.locator("button[data-item-id^='phone']").count() > 0
                        result["sample_size"] += 1
                        result["verified_count"] += 1
                        if has_own_site(website_url):
                            result["own_site_count"] += 1
                            site_status = "site próprio informado"
                        else:
                            result["site_unknown_count"] += 1
                            result["no_site_count"] += 1
                            site_status = "site não localizado, ainda não confirmado"
                        result["contactable_count"] += int(has_phone)
                        result["active_count"] += int(review_count > 0)
                        result["mature_count"] += int(review_count >= 10)
                        if len(result["examples"]) < 5:
                            result["examples"].append({
                                "name": name or "Empresa sem nome extraído", "city": pair["city"],
                                "site_status": site_status,
                                "contact": "telefone público" if has_phone else "não localizado",
                                "source_url": href,
                            })
                    except Exception:
                        pass
                    finally:
                        completed_samples += 1
                        progress(completed_samples, total_samples, f"{completed_samples} de {total_samples} empresas analisadas...")
            except Exception as error:
                result["error"] = str(error)[:240]
            observations.append(result)
        browser.close()
    return observations
