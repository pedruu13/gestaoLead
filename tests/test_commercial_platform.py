import json
import os
import sqlite3
import tempfile
import unittest

import app as application
from commercial_intelligence import analyze_lead, evaluate_pitches, generate_fallback_pitches
from preview_studio import build_preview_config, render_preview_html


BUSINESS_CASES = (
    ("Ateliê Norte Arquitetura", "Arquitetos", "arquitetura"),
    ("Sorriso Centro", "Dentistas", "odontologia"),
    ("Pele Clara", "Clínica de estética", "estética"),
    ("Lima & Ramos", "Advogados", "advocacia"),
    ("Reforma Certa", "Empresa de reformas", "reformas"),
    ("Conta Simples", "Contadores", "contabilidade"),
    ("Eixo Projetos", "Escritório de engenharia", "engenharia"),
    ("Pronto Reparo", "Empresa de manutenção", "manutenção"),
    ("Mesa da Vila", "Restaurante", "gastronomia"),
    ("Apoio Local", "Prestadores de serviços locais", "Prestadores de serviços locais"),
)


def sample_lead(name="Sorriso Centro", category="Dentistas"):
    return {
        "Nome": name,
        "Nicho": category,
        "Categoria Maps": category,
        "Bairro": "Campinas, SP",
        "Nota Maps": "4.7",
        "Qtd Avaliacoes": "32",
        "Telefone": "(19) 99999-9999",
        "E-mail Encontrado": "contato@example.com",
        "Instagram": "https://instagram.com/exemplo",
        "Link Inicial": "",
    }


class CommercialIntelligenceTests(unittest.TestCase):
    def test_ten_business_types_change_opportunity_and_pitch(self):
        opportunities = set()
        personalized = set()
        for name, category, expected_segment in BUSINESS_CASES:
            with self.subTest(category=category):
                analysis = analyze_lead(sample_lead(name, category))
                pitches = generate_fallback_pitches(analysis)
                quality = evaluate_pitches(pitches, analysis)
                self.assertEqual(expected_segment, analysis["segment"])
                self.assertTrue(quality["approved"], quality["reasons"])
                self.assertIn(name, pitches["personalizada"])
                self.assertNotIn("responsável pelo comercial", pitches["consultiva"].casefold())
                self.assertNotIn("prévia", pitches["consultiva"].casefold())
                opportunities.add(analysis["opportunity"])
                personalized.add(pitches["personalizada"])
        self.assertGreaterEqual(len(opportunities), 9)
        self.assertEqual(10, len(personalized))

    def test_preview_pitch_only_exists_after_real_preview(self):
        analysis = analyze_lead(sample_lead(), preview_available=False)
        self.assertNotIn("previa_visual", generate_fallback_pitches(analysis))
        analysis = analyze_lead(sample_lead(), preview_available=True)
        pitches = generate_fallback_pitches(analysis)
        self.assertIn("previa_visual", pitches)
        self.assertTrue(evaluate_pitches(pitches, analysis, require_preview=True)["approved"])


class PreviewStudioTests(unittest.TestCase):
    def test_html_is_responsive_and_has_no_external_resources_or_scripts(self):
        config = build_preview_config(sample_lead())
        html = render_preview_html(config)
        self.assertIn("Demonstração conceitual não oficial", html)
        self.assertIn("@media(max-width:760px)", html)
        self.assertNotIn("<script", html.casefold())
        self.assertNotIn("src=\"http", html.casefold())

    def test_generate_preview_route_persists_version_and_exports_real_png(self):
        old_db = application.DB_NAME
        old_preview_dir = application.PREVIEW_DIR
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "test.db")
            application.PREVIEW_DIR = os.path.join(temp_dir, "previews")
            application.load_config = lambda: {}
            try:
                application.init_db()
                lead = sample_lead()
                lead.update({
                    "WhatsApp Link": "https://wa.me/5519999999999",
                    "Google Maps": "https://maps.google.com/example",
                    "Potencial": 80,
                    "Motivo Potencial": "sem site próprio, reputação alta",
                    "Faixa Potencial": "Prioridade",
                })
                self.assertTrue(application.save_lead_db(lead, "test-place"))
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                response = client.post("/api/leads/test-place/previews", json={"headline": "Um sorriso começa com informação clara"})
                self.assertEqual(200, response.status_code, response.get_data(as_text=True))
                result = response.get_json()
                self.assertTrue(result["success"])
                self.assertTrue(result["screenshot_ready"], result.get("screenshot_error"))
                png_response = client.get(result["png_url"])
                self.assertEqual(200, png_response.status_code)
                self.assertTrue(png_response.data.startswith(b"\x89PNG\r\n\x1a\n"))
                png_response.close()
                conn = sqlite3.connect(application.DB_NAME)
                row = conn.execute("SELECT version, config_json, html_content, screenshot_path FROM preview_versions").fetchone()
                conn.close()
                self.assertEqual(1, row[0])
                self.assertEqual("Um sorriso começa com informação clara", json.loads(row[1])["headline"])
                self.assertIn("Demonstração conceitual não oficial", row[2])
                self.assertTrue(os.path.exists(row[3]))
            finally:
                application.DB_NAME = old_db
                application.PREVIEW_DIR = old_preview_dir
                application.load_config = old_load_config


if __name__ == "__main__":
    unittest.main()
