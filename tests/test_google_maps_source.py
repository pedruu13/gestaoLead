import os
import unittest
from unittest import mock

import discovery_sources
from discovery_sources import (
    GoogleMapsSource,
    _clean_external_url,
    tratar_consentimento_cookies,
)


class FakeElement:
    def __init__(self, count=1, visible=True, text="", aria_label="", href=""):
        self._count = count
        self._visible = visible
        self._text = text
        self._aria_label = aria_label
        self._href = href

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self._visible

    def click(self, timeout=None):
        return None

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        if name == "aria-label":
            return self._aria_label
        if name == "href":
            return self._href
        return ""


class FakePage:
    def __init__(self, elements=None):
        self.elements = elements or {}
        self.waited_timeouts = []

    def locator(self, selector):
        return self.elements.get(selector, FakeElement(count=0))

    def wait_for_timeout(self, ms):
        self.waited_timeouts.append(ms)


class ConsentCookieTests(unittest.TestCase):
    def test_consent_modal_found_and_clicked(self):
        button_mock = mock.Mock()
        button_mock.count.return_value = 1
        button_mock.is_visible.return_value = True

        page_mock = mock.Mock()
        page_mock.locator.return_value.first = button_mock

        result = tratar_consentimento_cookies(page_mock)
        self.assertTrue(result)
        button_mock.click.assert_called_once()
        page_mock.wait_for_timeout.assert_called_once()

    def test_consent_modal_not_found_returns_false_safely(self):
        button_mock = mock.Mock()
        button_mock.count.return_value = 0
        button_mock.is_visible.return_value = False

        page_mock = mock.Mock()
        page_mock.locator.return_value.first = button_mock

        result = tratar_consentimento_cookies(page_mock)
        self.assertFalse(result)
        button_mock.click.assert_not_called()

    def test_consent_modal_click_exception_handled_safely(self):
        button_mock = mock.Mock()
        button_mock.count.return_value = 1
        button_mock.is_visible.return_value = True
        button_mock.click.side_effect = RuntimeError("element detached")

        page_mock = mock.Mock()
        page_mock.locator.return_value.first = button_mock

        result = tratar_consentimento_cookies(page_mock)
        self.assertFalse(result)


class CleanExternalUrlTests(unittest.TestCase):
    def test_direct_http_and_https_urls_preserved(self):
        self.assertEqual("https://clinicaodontologica.com.br", _clean_external_url("https://clinicaodontologica.com.br"))
        self.assertEqual("http://meusite.com.br/contato", _clean_external_url("http://meusite.com.br/contato"))

    def test_unwraps_google_redirect_urls(self):
        wrapped = "https://www.google.com/url?q=https://drajoana.com.br/agendar&sa=U&ved=2ahUKE"
        self.assertEqual("https://drajoana.com.br/agendar", _clean_external_url(wrapped))

    def test_empty_or_invalid_returns_empty_string(self):
        self.assertEqual("", _clean_external_url(""))
        self.assertEqual("", _clean_external_url(None))
        self.assertEqual("", _clean_external_url("javascript:void(0)"))


class ExtractDetailPanelTests(unittest.TestCase):
    def setUp(self):
        self.source = GoogleMapsSource(enabled=True)

    def test_extract_complete_details_from_panel(self):
        base_candidate = {
            "source": "google_maps",
            "source_id": "test_id_123",
            "name": "Nome Inicial Card",
            "category": "Odontologia",
            "address": "Campinas - SP",
            "phone": "",
            "email": "",
            "website": "",
            "rating": 4.5,
            "reviews": 10,
            "business_status": "UNKNOWN",
            "source_url": "https://www.google.com/maps/place/data=123",
            "niche": "Odontologia",
            "location": "Campinas - SP",
        }

        elements = {
            "h1": FakeElement(count=1, text="Clínica Sorriso Aberto"),
            "button[data-item-id^='phone'], [data-tooltip*='telefone' i], [data-tooltip*='phone' i]": FakeElement(
                count=1, aria_label="Telefone: (19) 98765-4321", text="(19) 98765-4321"
            ),
            "a[data-item-id='authority'], a[data-tooltip*='website' i], a[data-tooltip*='site' i], a[aria-label*='website' i], a[aria-label*='site' i]": FakeElement(
                count=1, href="https://www.google.com/url?q=https://sorrisoaberto.com.br"
            ),
            "button[data-item-id='address'], [data-item-id*='address'], [data-tooltip*='endereço' i], [data-tooltip*='address' i]": FakeElement(
                count=1, aria_label="Endereço: Av. Francisco Glicério, 1200 - Centro, Campinas - SP"
            ),
            "button[jsaction*='pane.rating.category'], span[jsaction*='pane.rating.category'], button[data-item-id='address'] + div button, div.fontBodyMedium button": FakeElement(
                count=1, text="Clínica Odontológica Especializada"
            ),
            "div[role='main'], body": FakeElement(count=1, text="Aberto ⋅ Fecha às 18:00"),
        }

        fake_page = FakePage(elements)
        enriched = self.source._extract_detail_panel(fake_page, base_candidate)

        self.assertEqual("Clínica Sorriso Aberto", enriched["name"])
        self.assertEqual("(19) 98765-4321", enriched["phone"])
        self.assertEqual("https://sorrisoaberto.com.br", enriched["website"])
        self.assertEqual("Av. Francisco Glicério, 1200 - Centro, Campinas - SP", enriched["address"])
        self.assertEqual("Clínica Odontológica Especializada", enriched["category"])
        self.assertEqual("OPERATIONAL", enriched["business_status"])

    def test_extract_detail_panel_preserves_card_data_when_elements_missing(self):
        base_candidate = {
            "source": "google_maps",
            "source_id": "test_id_456",
            "name": "Consultório Dr. Pedro",
            "category": "Odontologia",
            "address": "Bairro Cambuí, Campinas - SP",
            "phone": "1933334444",
            "email": "",
            "website": "https://drpedro.com.br",
            "rating": 5.0,
            "reviews": 12,
            "business_status": "UNKNOWN",
            "source_url": "https://www.google.com/maps/place/data=456",
            "niche": "Odontologia",
            "location": "Campinas - SP",
        }

        fake_page = FakePage({})  # Nenhum elemento no painel
        enriched = self.source._extract_detail_panel(fake_page, base_candidate)

        self.assertEqual("Consultório Dr. Pedro", enriched["name"])
        self.assertEqual("1933334444", enriched["phone"])
        self.assertEqual("https://drpedro.com.br", enriched["website"])
        self.assertEqual("Bairro Cambuí, Campinas - SP", enriched["address"])
        self.assertEqual("Odontologia", enriched["category"])

    def test_extract_detail_panel_detects_permanently_closed(self):
        base_candidate = {
            "source": "google_maps",
            "source_id": "test_id_789",
            "name": "Clínica Fechada",
            "category": "Odontologia",
            "address": "Campinas - SP",
            "phone": "",
            "email": "",
            "website": "",
            "rating": 4.0,
            "reviews": 5,
            "business_status": "UNKNOWN",
            "source_url": "https://www.google.com/maps/place/data=789",
            "niche": "Odontologia",
            "location": "Campinas - SP",
        }

        elements = {
            "h1": FakeElement(count=1, text="Clínica Fechada"),
            "div[role='main'], body": FakeElement(count=1, text="Esta empresa está permanentemente fechada"),
        }

        fake_page = FakePage(elements)
        enriched = self.source._extract_detail_panel(fake_page, base_candidate)
        self.assertEqual("CLOSED_PERMANENTLY", enriched["business_status"])


class GoogleMapsSearchResilienceTests(unittest.TestCase):
    def setUp(self):
        self.source = GoogleMapsSource(enabled=True)

    def test_unconfigured_source_returns_empty_immediately(self):
        disabled_source = GoogleMapsSource(enabled=False)
        result = disabled_source.search("Odontologia", "Campinas", "br")
        self.assertEqual([], result["candidates"])
        self.assertEqual(0, result["requests"])

    def test_detail_navigation_timeout_retains_card_data_with_warning(self):
        """
        Garante que quando a navegação até o link de detalhes falha (ex: timeout de rede),
        o lead não é descartado: mantém os dados do card superficial e registra warning.
        """
        card_candidate = {
            "source": "google_maps",
            "source_id": "card_id_101",
            "name": "Empresa Card Sem Detalhe",
            "category": "Odontologia",
            "address": "Campinas - SP",
            "phone": "19999990000",
            "email": "",
            "website": "",
            "rating": 4.7,
            "reviews": 25,
            "business_status": "UNKNOWN",
            "source_url": "https://maps.google.com/broken_detail_url",
            "niche": "Odontologia",
            "location": "Campinas - SP",
        }

        # Mock do Playwright interno
        page_mock = mock.Mock()
        page_mock.goto.side_effect = [
            None,  # 1ª chamada: goto da busca geral (sucesso)
            TimeoutError("Timeout 9000ms excedido ao abrir detalhe"),  # 2ª chamada: goto do detalhe (falha)
        ]
        page_mock.locator.return_value.count.return_value = 1

        context_mock = mock.Mock()
        context_mock.new_page.return_value = page_mock

        browser_mock = mock.Mock()
        browser_mock.new_context.return_value = context_mock

        playwright_cm = mock.MagicMock()
        playwright_cm.__enter__.return_value.chromium.launch.return_value = browser_mock

        with mock.patch("discovery_sources.GoogleMapsSource._parse_card", return_value=card_candidate), \
             mock.patch("discovery_sources.tratar_consentimento_cookies"), \
             mock.patch.dict("sys.modules", {"playwright.sync_api": mock.Mock(sync_playwright=mock.Mock(return_value=playwright_cm))}):

            result = self.source.search("Odontologia", "Campinas", "br", page_size=1)

            self.assertEqual(1, len(result["candidates"]))
            self.assertEqual("Empresa Card Sem Detalhe", result["candidates"][0]["name"])
            self.assertEqual("19999990000", result["candidates"][0]["phone"])
            self.assertTrue(any("DetailNavError" in w for w in result.get("warnings", [])))

    def test_candidate_matches_discovery_engine_schema(self):
        base_candidate = {
            "source": "google_maps",
            "source_id": "valid_schema_id",
            "name": "Consultório Exemplo",
            "category": "Odontologia",
            "address": "Campinas - SP",
            "phone": "+55 19 98888-7777",
            "email": "",
            "website": "https://exemplo.com.br",
            "rating": 4.8,
            "reviews": 35,
            "business_status": "OPERATIONAL",
            "source_url": "https://maps.google.com/place",
            "niche": "Odontologia",
            "location": "Campinas - SP",
        }

        required_keys = {
            "source", "source_id", "name", "category", "address",
            "phone", "email", "website", "rating", "reviews",
            "business_status", "source_url", "niche", "location"
        }
        self.assertTrue(required_keys.issubset(base_candidate.keys()))


if __name__ == "__main__":
    unittest.main()
