import os
import tempfile
import unittest

import app as application
from target_intelligence import suggest_targets


class TargetIntelligenceTests(unittest.TestCase):
    def test_suggestions_are_compact_deterministic_and_region_safe(self):
        for region in ("br", "us", "europa"):
            first = suggest_targets(region, [])
            second = suggest_targets(region, [])
            self.assertEqual(first, second)
            self.assertEqual(2, len(first["nichos"]))
            self.assertEqual(4, len(first["cidades"]))
            self.assertEqual(8, first["total_combinacoes"])
            self.assertEqual(len(first["cidades"]), len(set(first["cidades"])))
            self.assertTrue(all(item["regiao"] == region for item in first["pracas"]))

    def test_observed_site_gap_outweighs_same_market_with_more_sites(self):
        rows = []
        for index in range(10):
            rows.append({
                "nicho": "dentista",
                "bairro": "Moema - São Paulo",
                "link_inicial": "" if index < 7 else f"https://clinica{index}.com.br",
                "telefone": "11999999999",
                "whatsapp_link": "https://wa.me/5511999999999",
                "email": "",
                "avaliacoes": "35",
            })
            rows.append({
                "nicho": "dentista",
                "bairro": "Campinas - SP",
                "link_inicial": f"https://consultorio{index}.com.br",
                "telefone": "11999999999",
                "whatsapp_link": "",
                "email": "",
                "avaliacoes": "35",
            })

        result = suggest_targets("br", rows)
        places = {item["nome"]: item for item in result["pracas"]}
        self.assertGreater(places["Moema - São Paulo"]["score"], places["Campinas - SP"]["score"])
        self.assertEqual("validado", places["Moema - São Paulo"]["confianca"])
        self.assertIn("70%", places["Moema - São Paulo"]["evidencia"])

    def test_sparse_history_is_not_presented_as_validated(self):
        rows = [{
            "nicho": "med spa",
            "bairro": "Tampa - FL",
            "link_inicial": "",
            "telefone": "+1 305 555 0100",
            "whatsapp_link": "",
            "email": "contact@example.com",
            "avaliacoes": "18",
        }]
        result = suggest_targets("us", rows)
        tampa = next(item for item in result["pracas"] if item["nome"] == "Tampa - FL")
        self.assertEqual("sinal inicial", tampa["confianca"])
        self.assertNotIn("validado", tampa["evidencia"].casefold())

    def test_api_uses_database_history_and_keeps_hard_limits(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "targets.db")
            try:
                application.init_db()
                connection = application.sqlite3.connect(application.DB_NAME)
                for index in range(8):
                    connection.execute(
                        """INSERT INTO leads
                           (place_id, nome, nicho, bairro, telefone, link_inicial, status, avaliacoes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"lead-{index}",
                            f"Clínica {index}",
                            "dentista",
                            "Moema - São Paulo",
                            "11999999999",
                            "" if index < 5 else f"https://clinica{index}.com.br",
                            "Novo",
                            "24",
                        ),
                    )
                connection.commit()
                connection.close()
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                response = client.get("/api/sugerir_alvos?regiao=br")
                self.assertEqual(200, response.status_code)
                data = response.get_json()
                self.assertEqual(2, len(data["nichos"]))
                self.assertEqual(4, len(data["cidades"]))
                self.assertEqual(8, data["total_combinacoes"])
                self.assertEqual("validado", next(item for item in data["pracas"] if item["nome"] == "Moema - São Paulo")["confianca"])
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
