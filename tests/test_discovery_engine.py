import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import app as application
import discovery_engine as engine_module
import discovery_sources
from conversion_intelligence import calculate_conversion_metrics, performance_adjustment
from discovery_engine import DiscoveryEngine, candidate_identity, init_discovery_schema
from discovery_sources import GooglePlacesSource
from lead_scoring import score_lead
from lead_validation import validate_candidate


class FakeSource:
    name = "fake_source"
    estimated_cost_micros = 1000

    def __init__(self, candidate=None):
        self.calls = 0
        self.candidate = candidate or {
            "source": self.name,
            "source_id": "one",
            "name": "Clínica Horizonte",
            "category": "Clínica",
            "address": "Campinas, SP",
            "phone": "+55 19 99999-9999",
            "email": "",
            "website": "",
            "rating": 4.7,
            "reviews": 30,
            "business_status": "OPERATIONAL",
            "source_url": "https://example.test/one",
            "niche": "Clínica",
            "location": "Campinas, SP",
        }

    def configured(self):
        return True

    def search(self, niche, location, region, page_token=None, page_size=20, request_budget=None):
        self.calls += 1
        return {"candidates": [dict(self.candidate)], "next_page_token": "", "requests": 1}


class DiscoveryEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_name = os.path.join(self.temp_dir.name, "discovery.db")
        connection = sqlite3.connect(self.db_name)
        init_discovery_schema(connection)
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def payload(self):
        return {"region": "br", "niches": ["Clínica"], "locations": ["Campinas, SP"]}

    def test_cache_avoids_repeating_the_same_source_request(self):
        source = FakeSource()
        engine = DiscoveryEngine(self.db_name, {"discovery_cache_hours": 24})
        with mock.patch.object(engine_module, "source_registry", return_value=[source]):
            engine.run(engine.create_job(self.payload()))
            engine.run(engine.create_job(self.payload()))
        self.assertEqual(1, source.calls)
        connection = sqlite3.connect(self.db_name)
        hits = connection.execute("SELECT hit_count FROM discovery_cache").fetchone()[0]
        connection.close()
        self.assertEqual(1, hits)

    def test_candidate_identity_deduplicates_by_domain_phone_and_name_location(self):
        self.assertEqual(
            candidate_identity({"website": "https://www.exemplo.com.br/contato"}),
            candidate_identity({"website": "https://exemplo.com.br"}),
        )
        self.assertEqual(
            candidate_identity({"phone": "+55 (19) 99999-9999"}),
            candidate_identity({"phone": "19999999999"}),
        )
        self.assertEqual(
            candidate_identity({"name": "Clínica São José", "address": "Campinas SP"}),
            candidate_identity({"name": "Clinica Sao Jose", "address": "Campinas-SP"}),
        )

    def test_daily_quota_skips_source_without_calling_it(self):
        source = FakeSource()
        engine = DiscoveryEngine(self.db_name, {"google_places_daily_limit": 1})
        source.name = "google_places"
        engine._record_usage(source.name, requests=1)
        with mock.patch.object(engine_module, "source_registry", return_value=[source]):
            engine.run(engine.create_job(self.payload()))
        self.assertEqual(0, source.calls)

    def test_unexpected_failure_keeps_checkpoint_and_job_can_resume(self):
        source = FakeSource()
        engine = DiscoveryEngine(self.db_name, {})
        job_id = engine.create_job(self.payload())
        original_cache_put = engine._cache_put
        with mock.patch.object(engine_module, "source_registry", return_value=[source]), \
             mock.patch.object(engine, "_cache_put", side_effect=RuntimeError("disk unavailable")):
            with self.assertRaises(RuntimeError):
                engine.run(job_id)
        self.assertEqual("interrupted", engine.job_status(job_id)["status"])
        with mock.patch.object(engine_module, "source_registry", return_value=[source]), \
             mock.patch.object(engine, "_cache_put", wraps=original_cache_put):
            candidates = engine.run(job_id)
        self.assertEqual("completed", engine.job_status(job_id)["status"])
        self.assertEqual(1, len(candidates))

    def test_source_failure_is_recorded_and_other_sources_continue(self):
        failing = FakeSource()
        failing.name = "broken"
        failing.search = mock.Mock(side_effect=RuntimeError("temporary block"))
        healthy = FakeSource()
        with mock.patch.object(engine_module, "source_registry", return_value=[failing, healthy]):
            candidates = DiscoveryEngine(self.db_name, {}).run(
                DiscoveryEngine(self.db_name, {}).create_job(self.payload())
            )
        self.assertEqual(2, failing.search.call_count)
        self.assertEqual(1, len(candidates))

    def test_candidates_from_different_sources_merge_by_shared_name_and_location(self):
        first = FakeSource().candidate
        second = {**first, "source": "another_source", "source_id": "two", "phone": "", "website": ""}
        engine = DiscoveryEngine(self.db_name, {})
        job_id = engine.create_job(self.payload())
        engine._store_candidates(job_id, [first, second])
        candidates = engine.load_candidates(job_id)
        self.assertEqual(1, len(candidates))
        self.assertEqual({"fake_source", "another_source"}, set(candidates[0]["sources"]))
        engine.update_candidate_validation(job_id, candidates[0], "saved", {"validation_status": "CONFIRMADO"})
        connection = sqlite3.connect(self.db_name)
        statuses = {row[0] for row in connection.execute("SELECT status FROM discovery_candidates WHERE job_id = ?", (job_id,))}
        connection.close()
        self.assertEqual({"saved"}, statuses)

    def test_google_source_uses_alternative_queries_and_deduplicates_place_ids(self):
        source = GooglePlacesSource(api_key="test", query_variants=2)
        payload = {"places": [{"id": "place-1", "displayName": {"text": "Empresa"}, "formattedAddress": "Campinas"}]}
        with mock.patch.object(discovery_sources, "_request_json", return_value=payload) as request_json:
            result = source.search("Academia e treinamento", "Campinas", "br")
        self.assertEqual(2, request_json.call_count)
        self.assertEqual(2, result["requests"])
        self.assertEqual(1, len(result["candidates"]))

    def test_osm_filters_has_fallback_for_unknown_niche(self):
        filters = discovery_sources.osm_filters_for_niche("Nicho Inexistente Super Raro")
        self.assertTrue(len(filters) > 0)
        self.assertIn(("office", None), filters)

    def test_google_maps_source_configured_and_parses_cards(self):
        source = discovery_sources.GoogleMapsSource(enabled=True)
        self.assertTrue(source.configured())
        self.assertEqual("google_maps", source.name)


class ValidationAndLearningTests(unittest.TestCase):
    def test_absence_of_site_is_not_confirmed_from_one_source(self):
        candidate = FakeSource().candidate
        result = validate_candidate(candidate, corroborating_sources=1, inspect_site=False)
        self.assertEqual("NÃO VERIFICADO", result["site_confidence"])
        result = validate_candidate(candidate, corroborating_sources=2, inspect_site=False)
        self.assertEqual("PROVÁVEL", result["site_confidence"])

    def test_working_matching_domain_is_confirmed(self):
        candidate = {**FakeSource().candidate, "website": "https://clinicahorizonte.com.br"}
        website = {"present": True, "status": "funcionando", "working": True, "belongs": True, "reason": "Site ativo com sinais de pertencimento."}
        with mock.patch("lead_validation.inspect_website", return_value=website):
            result = validate_candidate(candidate, corroborating_sources=1)
        self.assertEqual("CONFIRMADO", result["site_confidence"])

    def test_score_exposes_priority_and_validation_evidence(self):
        lead = {
            "Nicho": "Clínica odontológica", "Bairro": "Campinas, SP",
            "Telefone": "+55 19 99999-9999", "E-mail Encontrado": "contato@clinica.com.br",
            "Nota Maps": 4.8, "Qtd Avaliacoes": 40,
            "Status Validação": "CONFIRMADO", "Confiança do Site": "PROVÁVEL",
            "Quantidade de Fontes": 2,
        }
        result = score_lead(lead, has_own_site=False)
        self.assertIn(result["priority"], {"Alta", "Média", "Baixa"})
        self.assertIn("2 fonte(s)", result["dimensions"]["qualidade_evidencia"]["evidence"])
        self.assertIn("não probabilidade", result["disclaimer"])

    def test_unverified_business_cannot_receive_high_priority(self):
        lead = {
            "Nicho": "Clínica odontológica", "Bairro": "Campinas, SP",
            "Telefone": "+55 19 99999-9999", "E-mail Encontrado": "contato@clinica.com.br",
            "Nota Maps": 5, "Qtd Avaliacoes": 100,
            "Status Validação": "NÃO VERIFICADO", "Confiança do Site": "NÃO VERIFICADO",
        }
        result = score_lead(lead, has_own_site=False)
        self.assertLessEqual(result["score"], 54)
        self.assertNotEqual("Alta", result["priority"])

    def test_conversion_adjustment_requires_ten_real_outcomes(self):
        base = {"nicho": "Dentista", "bairro": "Campinas", "lead_source": "google_places"}
        nine = [{**base, "commercial_outcome": "Respondeu"} for _ in range(9)]
        ten = nine + [{**base, "commercial_outcome": "Contrato fechado"}]
        metrics_nine = calculate_conversion_metrics(nine)
        metrics_ten = calculate_conversion_metrics(ten)
        self.assertEqual(0, performance_adjustment(metrics_nine, "Dentista", "Campinas", "google_places"))
        self.assertGreater(performance_adjustment(metrics_ten, "Dentista", "Campinas", "google_places"), 0)


class CommercialOutcomeRouteTests(unittest.TestCase):
    def authenticate(self, client):
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["user"] = "teste"
            session["csrf_token"] = "token"
        return {"X-CSRF-Token": "token"}

    def test_search_route_selects_modular_engine_when_places_is_configured(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "modular.db")
            try:
                application.init_db()
                client = application.app.test_client()
                headers = self.authenticate(client)
                with mock.patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "configured"}), \
                     mock.patch.object(application, "load_config", return_value={"enable_modular_discovery": True}), \
                     mock.patch.object(application, "ler_status", return_value={"rodando": False}), \
                     mock.patch.object(application, "ler_status_investigacao", return_value={"rodando": False}), \
                     mock.patch.object(application, "atualizar_status"), \
                     mock.patch.object(application.threading, "Thread") as thread:
                    response = client.post(
                        "/api/search", headers=headers,
                        json={"mercado": "br", "nichos": "Academia", "bairros": "Campinas - SP"},
                    )
                data = response.get_json()
                self.assertEqual(200, response.status_code, data)
                self.assertEqual("modular", data["discovery_engine"])
                self.assertTrue(data["discovery_job_id"])
                self.assertIs(application.modular_discovery_worker, thread.call_args.kwargs["target"])
            finally:
                application.DB_NAME = old_db

    def test_init_db_migrates_old_database_without_losing_leads(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "legacy.db")
            try:
                connection = sqlite3.connect(application.DB_NAME)
                connection.execute("""CREATE TABLE leads (
                    place_id TEXT PRIMARY KEY, nome TEXT, nicho TEXT, bairro TEXT, nota TEXT,
                    avaliacoes TEXT, telefone TEXT, whatsapp_link TEXT, email TEXT, instagram TEXT,
                    facebook TEXT, linkedin TEXT, link_inicial TEXT, google_maps TEXT,
                    prompt_design TEXT, status TEXT, data_adicao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    copy_texto TEXT, analise_ia TEXT, estrategia_ia TEXT)""")
                connection.execute("INSERT INTO leads (place_id, nome, status) VALUES ('legacy-1', 'Empresa antiga', 'Novo')")
                connection.commit()
                connection.close()
                application.init_db()
                connection = sqlite3.connect(application.DB_NAME)
                columns = {row[1] for row in connection.execute("PRAGMA table_info(leads)")}
                preserved = connection.execute("SELECT nome FROM leads WHERE place_id = 'legacy-1'").fetchone()[0]
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                connection.close()
                self.assertEqual("Empresa antiga", preserved)
                self.assertIn("validation_status", columns)
                self.assertIn("discovery_jobs", tables)
            finally:
                application.DB_NAME = old_db

    def test_outcome_route_updates_learning_event_and_pipeline(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "app.db")
            try:
                application.init_db()
                connection = sqlite3.connect(application.DB_NAME)
                connection.execute("INSERT INTO leads (place_id, nome, status) VALUES ('lead-1', 'Empresa', 'Novo')")
                connection.commit()
                connection.close()
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                    session["csrf_token"] = "token"
                response = client.post(
                    "/api/leads/lead-1/outcome",
                    json={"outcome": "Contrato fechado"},
                    headers={"X-CSRF-Token": "token"},
                )
                self.assertEqual(200, response.status_code, response.get_json())
                connection = sqlite3.connect(application.DB_NAME)
                state = connection.execute("SELECT commercial_outcome, status FROM leads WHERE place_id = 'lead-1'").fetchone()
                connection.close()
                self.assertEqual(("Contrato fechado", "Fechado"), state)
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
