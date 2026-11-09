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
