from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import app as application


class ApproachModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(application, 'DB_NAME', str(Path(self.temp.name) / 'test.db')),
            patch.object(application, 'BACKUP_DIR', str(Path(self.temp.name) / 'backups')),
            patch.object(application, 'load_config', return_value={}),
        ]
        for item in self.patches:
            item.start()
        application.init_db()
        application.save_lead_db({
            'Nome': 'Empresa de teste', 'Nicho': 'Dentista', 'Bairro': 'Campinas, SP',
            'Telefone': '5519999999999', 'WhatsApp Link': 'https://wa.me/5519999999999',
            'Nota Maps': 4.6, 'Qtd Avaliacoes': 20,
        }, 'test-approach')
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session['authenticated'] = True

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def add_preview(self, config='{}'):
        with closing(sqlite3.connect(application.DB_NAME)) as connection, connection:
            connection.execute(
                "INSERT INTO preview_versions(place_id, version, config_json, html_content, message_text) VALUES (?,1,?,? ,?)",
                ('test-approach', config, '<html></html>', 'Veja a imagem demonstrativa.'),
            )

    def test_legacy_preview_json_does_not_break_lead_page(self):
        self.add_preview()
        for value in ('{}', 'null', '[]', '"legacy"', '{"art_direction":null}', '{"art_direction":[]}'):
            with self.subTest(value=value):
                with closing(sqlite3.connect(application.DB_NAME)) as connection, connection:
                    connection.execute('UPDATE preview_versions SET config_json=?, validation_json=?, art_direction_json=?', (value, value, value))
                    connection.execute('UPDATE leads SET copies_pitch=?, qualidade_pitch=?, inteligencia_comercial=?, score_breakdown=?', (value, value, value, value))
                response = self.client.get('/leads/test-approach')
                self.assertEqual(200, response.status_code)
                self.assertIn('Só mensagem', response.get_data(as_text=True))

    def test_load_leads_defensive_json_handling(self):
        test_cases = [
            ('valid_dict', '{"direta":"olá"}', '{"contact_strategy":{"recommended_mode":"direta"}}', '{"approved":true}', '{"performance_adjustment":5}', '["revisão"]'),
            ('null_values', None, None, None, None, None),
            ('invalid_json', '{not a json', 'invalid{', 'bad}', 'corrupt', 'broken'),
            ('lists_where_dicts_expected', '["a","b"]', '[1, 2]', '[true]', '[0]', '{"not":"a list"}'),
            ('numbers_and_strings', '123', '"plain_string"', '45.6', '789', '"not_a_list"'),
        ]
        for name, copies, intel, qual, score_bd, site_reasons in test_cases:
            with self.subTest(case=name):
                with closing(sqlite3.connect(application.DB_NAME)) as connection, connection:
                    connection.execute(
                        'UPDATE leads SET copies_pitch=?, inteligencia_comercial=?, qualidade_pitch=?, score_breakdown=?, site_opportunity_reasons=?',
                        (copies, intel, qual, score_bd, site_reasons)
                    )
                leads = application.load_leads()
                self.assertEqual(1, len(leads))
                lead = leads[0]
                self.assertIsInstance(lead['copies_pitch'], dict)
                self.assertIsInstance(lead['inteligencia_comercial'], dict)
                self.assertIsInstance(lead['qualidade_pitch'], dict)
                self.assertIsInstance(lead['score_breakdown'], dict)
                self.assertIsInstance(lead['site_opportunity_reasons'], list)
                crm_response = self.client.get('/crm')
                self.assertEqual(200, crm_response.status_code)

    def test_lead_detail_dimensions_variations(self):
        lead = application.get_lead_by_id('test-approach')
        variations = [
            ('missing_score_breakdown', None, False),
            ('empty_dict', {}, False),
            ('dimensions_as_dict', {"dimensions": {"exp": {"label": "Experiência", "score": 20, "max": 25, "evidence": "10 anos"}}}, True),
            ('dimensions_as_number', {"dimensions": 42}, False),
            ('dimensions_as_text', {"dimensions": "invalido"}, False),
            ('dimensions_as_list', {"dimensions": [1, 2, 3]}, False),
            ('dimensions_null', {"dimensions": None}, False),
            ('dimensions_empty_dict', {"dimensions": {}}, False),
        ]
        with application.app.test_request_context('/leads/test-approach'):
            template = application.app.jinja_env.get_template('lead_detail.html')
            for name, breakdown_val, should_render_section in variations:
                with self.subTest(variation=name):
                    test_lead = dict(lead)
                    test_lead['score_breakdown'] = breakdown_val
                    html = template.render(
                        lead=test_lead, intelligence={}, previews=[], interactions=[],
                        proposal_status_labels={},
                    )
                    if should_render_section:
                        self.assertIn('Composição do Score', html)
                        self.assertIn('Experiência', html)
                    else:
                        self.assertNotIn('Evidências e pesos que geraram a pontuação', html)

    def test_message_default_does_not_switch_to_preview(self):
        self.add_preview()
        response = self.client.get('/leads/test-approach')
        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('const recommendedMode = "previa_visual"', html)
        self.assertIn('id="visual-approach" hidden', html)

    def test_browser_text_without_preview_and_without_clipboard_api(self):
        from playwright.sync_api import sync_playwright

        html = self.client.get('/leads/test-approach').get_data(as_text=True)
        root = Path(application.__file__).parent
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for width in (1440, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.add_init_script("window.tailwind = {}; Object.defineProperty(navigator, 'clipboard', {get: () => undefined});")

                    def serve(route):
                        path = urlparse(route.request.url).path
                        if path == '/leads/test-approach':
                            route.fulfill(body=html, content_type='text/html')
                        elif path.startswith('/static/') and (root / path.lstrip('/')).is_file():
                            route.fulfill(path=str(root / path.lstrip('/')))
                        else:
                            route.fulfill(body='', status=200)

                    page.route('**/*', serve)
                    page.goto('http://gestaolead.test/leads/test-approach')
                    self.assertTrue(page.locator('#message-approach').is_visible())
                    self.assertFalse(page.locator('#visual-approach').is_visible())
                    self.assertNotIn('imagem', page.locator('#pitch-editor').input_value())
                    result = page.evaluate("""() => {
                        const allowed = sendStudioWhatsApp(false);
                        return {allowed, url: document.getElementById('whatsapp-action-text').href};
                    }""")
                    self.assertTrue(result['allowed'])
                    self.assertTrue(result['url'].startswith('https://wa.me/'))
                    page.locator('[data-approach="image"]').click()
                    self.assertTrue(page.locator('#visual-approach').is_visible())
                    self.assertFalse(page.locator('#message-approach').is_visible())
                    page.locator('[data-approach="text"]').click()
                    self.assertTrue(page.locator('#message-approach').is_visible())
                    self.assertEqual([], errors)
                    page.close()
            finally:
                browser.close()
