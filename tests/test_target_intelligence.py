import os
import tempfile
import time
import unittest
from unittest import mock

import app as application
from target_intelligence import build_research_plan, suggest_targets


class TargetIntelligenceTests(unittest.TestCase):
    def authenticate(self, client):
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["user"] = "teste"
            session["csrf_token"] = "target-test-token"
        return {"X-CSRF-Token": "target-test-token"}

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

        observations = [{
            "region": "br", "niche": "Odontologia", "city": "Moema - São Paulo",
            "sample_size": 10, "no_site_count": 7, "contactable_count": 10,
            "mature_count": 10, "results_count": 12,
        }, {
            "region": "br", "niche": "Odontologia", "city": "Campinas - SP",
            "sample_size": 10, "no_site_count": 0, "contactable_count": 10,
            "mature_count": 10, "results_count": 12,
        }]
        result = suggest_targets("br", rows, observations)
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

    def test_each_research_round_explores_understudied_targets(self):
        first_plan = build_research_plan("br", [])
        observations = [{
            "region": item["region"], "niche": item["niche"], "city": item["city"],
            "sample_size": 5, "no_site_count": 2,
        } for item in first_plan]
        second_plan = build_research_plan("br", observations)
        self.assertNotEqual(
            {(item["niche"], item["city"]) for item in first_plan},
            {(item["niche"], item["city"]) for item in second_plan},
        )
        self.assertGreaterEqual(len({item["niche"] for item in second_plan}), 4)
        self.assertGreaterEqual(len({item["city"] for item in second_plan}), 4)

    def test_focus_niche_returns_that_niche_and_four_ranked_locations(self):
        result = suggest_targets("br", [], focus_niches=["academia"])
        self.assertEqual(["Academia e treinamento"], result["nichos"])
        self.assertEqual(4, len(result["cidades"]))
        self.assertEqual(["Academia e treinamento"], result["contexto"]["nichos_informados"])

    def test_focus_location_returns_exact_location_and_ranked_niches(self):
        result = suggest_targets("br", [], focus_locations=["Batel - Curitiba"])
        self.assertEqual(["Batel - Curitiba"], result["cidades"])
        self.assertEqual(2, len(result["nichos"]))
        self.assertEqual(["Batel - Curitiba"], result["contexto"]["locais_informados"])

    def test_custom_niche_is_preserved_in_research_plan(self):
        plan = build_research_plan("br", [], pair_limit=4, focus_niches=["Lavanderia premium"])
        self.assertEqual(4, len(plan))
        self.assertEqual({"Lavanderia premium"}, {item["niche"] for item in plan})

    def test_existing_lead_saturation_penalizes_already_mined_location(self):
        rows = [{
            "nicho": "academia", "bairro": "Lago Sul - Brasília", "link_inicial": "",
            "telefone": "61999999999", "whatsapp_link": "", "email": "", "avaliacoes": "25",
        } for _ in range(15)]
        result = suggest_targets(
            "br", rows, focus_niches=["academia"],
            focus_locations=["Lago Sul - Brasília", "Águas Claras - DF"],
        )
        places = {item["nome"]: item for item in result["pracas"]}
        self.assertLess(places["Lago Sul - Brasília"]["score"], places["Águas Claras - DF"]["score"])

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
                self.authenticate(client)
                response = client.get("/api/sugerir_alvos?regiao=br")
                self.assertEqual(200, response.status_code)
                data = response.get_json()
                self.assertEqual(2, len(data["nichos"]))
                self.assertEqual(4, len(data["cidades"]))
                self.assertEqual(8, data["total_combinacoes"])
                self.assertIn(next(item for item in data["pracas"] if item["nome"] == "Moema - São Paulo")["confianca"], ("sinal forte", "validado"))
            finally:
                application.DB_NAME = old_db

    def test_post_route_runs_live_investigation_and_persists_result(self):
        old_db = application.DB_NAME
        old_status_file = application.TARGET_RESEARCH_STATUS_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "targets.db")
            application.TARGET_RESEARCH_STATUS_FILE = os.path.join(temp_dir, "target-status.json")
            try:
                application.init_db()

                def fake_probe(plan, **_kwargs):
                    self.assertEqual(4, len(plan))
                    self.assertEqual(3, _kwargs["sample_per_pair"])
                    self.assertEqual(35, _kwargs["max_seconds"])
                    return [{
                        "region": item["region"], "niche": item["niche"], "city": item["city"],
                        "results_count": 9, "sample_size": 5, "no_site_count": 3,
                        "contactable_count": 5, "mature_count": 4,
                    } for item in plan]

                client = application.app.test_client()
                headers = self.authenticate(client)
                with mock.patch.object(application, "probe_google_maps", side_effect=fake_probe):
                    response = client.post("/api/sugerir_alvos", json={"regiao": "br"}, headers=headers)
                    self.assertEqual(202, response.status_code, response.get_data(as_text=True))
                    for _ in range(100):
                        status = client.get("/api/sugerir_alvos/status").get_json()
                        if not status.get("rodando"):
                            break
                        time.sleep(0.02)
                self.assertTrue(status["concluido"], status)
                self.assertEqual(2, len(status["resultado"]["nichos"]))
                self.assertEqual(4, len(status["resultado"]["cidades"]))
                connection = application.sqlite3.connect(application.DB_NAME)
                self.assertEqual(4, connection.execute("SELECT COUNT(*) FROM target_research_observations").fetchone()[0])
                connection.close()
            finally:
                application.DB_NAME = old_db
                application.TARGET_RESEARCH_STATUS_FILE = old_status_file

    def test_post_route_reuses_recent_validated_result_without_live_browser(self):
        old_db = application.DB_NAME
        old_status_file = application.TARGET_RESEARCH_STATUS_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "targets.db")
            application.TARGET_RESEARCH_STATUS_FILE = os.path.join(temp_dir, "target-status.json")
            try:
                application.init_db()
                result = suggest_targets("br", [])
                result["investigacao"]["amostra_nova"] = 20
                connection = application.sqlite3.connect(application.DB_NAME)
                connection.execute(
                    """INSERT INTO target_research_runs
                       (run_id, region, plan_json, result_json, status, finished_at)
                       VALUES ('cached-run', 'br', '[]', ?, 'concluido', CURRENT_TIMESTAMP)""",
                    (application.json.dumps(result, ensure_ascii=False),),
                )
                connection.commit()
                connection.close()
                client = application.app.test_client()
                headers = self.authenticate(client)
                with mock.patch.object(application, "probe_google_maps") as probe:
                    response = client.post("/api/sugerir_alvos", json={"regiao": "br"}, headers=headers)
                self.assertEqual(200, response.status_code)
                self.assertTrue(response.get_json()["cached"])
                self.assertTrue(response.get_json()["resultado"]["investigacao"]["reutilizado"])
                probe.assert_not_called()
            finally:
                application.DB_NAME = old_db
                application.TARGET_RESEARCH_STATUS_FILE = old_status_file

    def test_context_cache_does_not_reuse_another_niche(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "targets.db")
            try:
                application.init_db()
                cached = suggest_targets("br", [], focus_niches=["academia"])
                cached["investigacao"]["amostra_nova"] = 20
                context_key = application.chave_contexto_alvos(["academia"], [])
                connection = application.sqlite3.connect(application.DB_NAME)
                connection.execute(
                    """INSERT INTO target_research_runs
                       (run_id, region, plan_json, result_json, status, context_key, finished_at)
                       VALUES ('academy-cache', 'br', '[]', ?, 'concluido', ?, CURRENT_TIMESTAMP)""",
                    (application.json.dumps(cached, ensure_ascii=False), context_key),
                )
                connection.commit()
                connection.close()
                self.assertIsNotNone(application.carregar_resultado_investigacao_recente("br", context_key))
                other_key = application.chave_contexto_alvos(["fotografia"], [])
                self.assertIsNone(application.carregar_resultado_investigacao_recente("br", other_key))
            finally:
                application.DB_NAME = old_db

    def test_discovery_history_survives_lead_removal(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "targets.db")
            try:
                application.init_db()
                connection = application.sqlite3.connect(application.DB_NAME)
                connection.execute(
                    """INSERT INTO leads (place_id, nome, nicho, bairro, status)
                       VALUES ('historic-place', 'Empresa Antiga', 'academia', 'Batel - Curitiba', 'Novo')"""
                )
                connection.commit()
                connection.close()
                application.init_db()
                self.assertIn("historic-place", application.load_existing_place_ids())
                connection = application.sqlite3.connect(application.DB_NAME)
                connection.execute("DELETE FROM leads WHERE place_id = 'historic-place'")
                connection.commit()
                connection.close()
                self.assertIn("historic-place", application.load_existing_place_ids())
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
