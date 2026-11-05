import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import app as application
from location_intelligence import expand_locations
from target_intelligence import search_term_for_niche


class LocationIntelligenceTests(unittest.TestCase):
    def authenticate(self, client):
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["user"] = "teste"
            session["csrf_token"] = "location-test-token"
        return {"X-CSRF-Token": "location-test-token"}

    def test_brazilian_state_abbreviation_expands_to_commercial_cities(self):
        result = expand_locations("br", ["MG"], per_group=5)
        self.assertEqual(5, len(result["locations"]))
        self.assertEqual("Belo Horizonte - MG", result["locations"][0])
        self.assertTrue(all(location.endswith("- MG") for location in result["locations"]))
        self.assertEqual("Minas Gerais", result["expansions"][0]["grupo"])

    def test_ambiguous_capital_can_be_explicit_city_or_state(self):
        city = expand_locations("br", ["São Paulo - SP"])
        state = expand_locations("br", ["São Paulo"], per_group=5)
        self.assertEqual(["São Paulo - SP"], city["locations"])
        self.assertEqual(5, len(state["locations"]))
        self.assertIn("Campinas - SP", state["locations"])

    def test_us_state_expands_without_mixing_other_states(self):
        result = expand_locations("us", ["FL"], per_group=5)
        self.assertEqual(5, len(result["locations"]))
        self.assertTrue(all(location.endswith("- FL") for location in result["locations"]))

    def test_commercial_label_is_converted_to_google_friendly_search_term(self):
        self.assertEqual("academia", search_term_for_niche("br", "Academia e treinamento"))
        self.assertEqual("empresa de reformas", search_term_for_niche("br", "Reformas e construção"))
        self.assertEqual("Lavanderia premium", search_term_for_niche("br", "Lavanderia premium"))

    def test_discovered_but_unsaved_places_can_be_retried(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "discoveries.db")
            try:
                application.init_db()
                connection = sqlite3.connect(application.DB_NAME)
                connection.executemany(
                    """INSERT INTO lead_discovery_history (place_id, outcome)
                       VALUES (?, ?)""",
                    [("saved-place", "saved"), ("filtered-place", "site_filtered"), ("pending-place", "discovered")],
                )
                connection.commit()
                connection.close()
                existing = application.load_existing_place_ids()
                self.assertIn("saved-place", existing)
                self.assertNotIn("filtered-place", existing)
                self.assertNotIn("pending-place", existing)
            finally:
                application.DB_NAME = old_db

    def test_search_route_expands_state_before_starting_worker(self):
        old_db = application.DB_NAME
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "state-search.db")
            application.load_config = lambda: {}
            try:
                application.init_db()
                client = application.app.test_client()
                headers = self.authenticate(client)
                with mock.patch.object(application, "ler_status", return_value={"rodando": False}), \
                     mock.patch.object(application, "ler_status_investigacao", return_value={"rodando": False}), \
                     mock.patch.object(application, "atualizar_status"), \
                     mock.patch.object(application.threading, "Thread") as thread:
                    response = client.post("/api/search", headers=headers, json={
                        "mercado": "br", "nichos": "Academia", "bairros": "SC",
                        "site_filter_mode": "only_without_site",
                    })
                data = response.get_json()
                self.assertEqual(200, response.status_code, data)
                self.assertEqual(5, len(data["locations"]))
                self.assertEqual("Santa Catarina", data["location_expansions"][0]["grupo"])
                worker_payload = thread.call_args.kwargs["args"][0]
                self.assertIn("Florianópolis - SC", worker_payload["bairros"])
                connection = sqlite3.connect(application.DB_NAME)
                stored = connection.execute("SELECT locations_json FROM search_runs").fetchone()[0]
                connection.close()
                self.assertEqual(data["locations"], json.loads(stored))
            finally:
                application.DB_NAME = old_db
                application.load_config = old_load_config

    def test_target_suggestion_uses_cities_from_informed_state(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "state-targets.db")
            try:
                application.init_db()
                client = application.app.test_client()
                self.authenticate(client)
                response = client.get("/api/sugerir_alvos?regiao=br&cidades=MG")
                data = response.get_json()
                self.assertEqual(200, response.status_code, data)
                self.assertEqual(4, len(data["cidades"]))
                self.assertTrue(all(location.endswith("- MG") for location in data["cidades"]))
                self.assertEqual(3, len(data["nichos"]))
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
