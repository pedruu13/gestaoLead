import json
import os
import tempfile
import unittest
from unittest import mock

import app as application
import niche_research
from niche_intelligence import build_candidate_pool, canonical_niche_key, rank_niche_opportunities


def observation(niche="Academia", verified=50, confirmed=20, probable=5, weak=5, own=15, unknown=5, city="Campinas - SP"):
    return {
        "run_id": "run-1", "region": "br", "niche": niche, "city": city,
        "results_count": 60, "sample_size": verified, "verified_count": verified,
        "own_site_count": own, "confirmed_no_site_count": confirmed,
        "probable_no_site_count": probable, "weak_site_count": weak,
        "site_unknown_count": unknown, "no_site_count": confirmed + probable + unknown,
        "contactable_count": 40, "active_count": 42, "mature_count": 42,
        "qualified_count": 28, "duplicate_count": 3, "discarded_count": 7,
        "sources_json": json.dumps(["Google Places", "OpenStreetMap"]),
        "examples_json": json.dumps([{"name": "Empresa real", "city": city}]),
        "created_at": "2026-11-05 10:00:00",
    }


class NicheIntelligenceTests(unittest.TestCase):
    def test_equivalent_niches_share_one_identity(self):
        self.assertEqual("odontologia", canonical_niche_key("Clínica odontológica"))
        self.assertEqual("odontologia", canonical_niche_key("Dentista"))
        pool = build_candidate_pool("br", ["Dentista"], discovered=[{"name": "Clínica odontológica", "count": 18, "source": "OpenStreetMap"}])
        self.assertEqual(1, len(pool))
        self.assertEqual(18, pool[0]["observed_businesses"])

    def test_small_sample_is_signaled_and_percent_uses_verified_sample(self):
        item = rank_niche_opportunities("br", [observation(verified=8, confirmed=2, probable=2, weak=1, own=2, unknown=1)], [], sample_target=50)[0]
        self.assertEqual("baixa", item["confidence"])
        self.assertEqual(25.0, item["confirmed_no_site_percent"])
        self.assertEqual(8, item["companies_verified"])
        self.assertEqual(50, item["sample_target"])

    def test_unknown_sites_are_not_counted_as_confirmed_absence(self):
        item = rank_niche_opportunities("br", [observation(confirmed=0, probable=0, weak=0, own=10, unknown=40)], [], sample_target=50)[0]
        self.assertEqual(0.0, item["confirmed_no_site_percent"])
        self.assertEqual(40, item["site_unknown_count"])
        self.assertIn("0 estavam sem site confirmado", item["justification"])

    def test_real_crm_history_requires_minimum_sample(self):
        sparse = [{"nicho": "Academia", "commercial_outcome": "Contrato fechado"} for _ in range(3)]
        item = rank_niche_opportunities("br", [observation()], sparse)[0]
        self.assertEqual("estimativa", item["potential_type"])
        enough = sparse + [{"nicho": "Academia", "commercial_outcome": "Contatado"} for _ in range(7)]
        item = rank_niche_opportunities("br", [observation()], enough)[0]
        self.assertEqual("histórico real", item["potential_type"])
        self.assertIn("10 contatos", item["commercial_potential"])

    def test_same_evidence_is_penalized_but_new_evidence_is_not(self):
        first = rank_niche_opportunities("br", [observation()], [])[0]
        history = [{"niche_key": first["niche_key"], "evidence_hash": first["evidence_hash"], "score": first["score"], "metrics_json": json.dumps(first["metrics"])}]
        repeated = rank_niche_opportunities("br", [observation()], [], history=history)[0]
        self.assertEqual(12, repeated["repeat_penalty"])
        self.assertEqual("sem evidência nova", repeated["comparison"]["status"])
        changed = rank_niche_opportunities("br", [observation(verified=50, confirmed=24, probable=3, weak=5, own=13, unknown=5)], [], history=history)[0]
        self.assertEqual(0, changed["repeat_penalty"])
        self.assertEqual("novas evidências", changed["comparison"]["status"])

    def test_dynamic_public_catalog_is_persisted(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "niches.db")
            try:
                application.init_db()
                found = [{"name": "Climatização e ar-condicionado", "count": 14, "source": "OpenStreetMap"}]
                with mock.patch.object(niche_research, "_overpass_public_categories", return_value=found):
                    result = niche_research.discover_public_niches(application.DB_NAME, "br", ["Campinas - SP"], ["Academia"])
                self.assertEqual(found, result["discovered"])
                connection = application.sqlite3.connect(application.DB_NAME)
                stored = connection.execute("SELECT niche_name, observed_businesses FROM dynamic_niche_catalog").fetchone()
                connection.close()
                self.assertEqual(("Climatização e ar-condicionado", 14), stored)
            finally:
                application.DB_NAME = old_db

    def test_dynamic_discovery_respects_openstreetmap_daily_quota(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "quota.db")
            try:
                application.init_db()
                connection = application.sqlite3.connect(application.DB_NAME)
                connection.execute(
                    "INSERT INTO source_usage (usage_date, source, requests) VALUES (date('now'), 'openstreetmap', 1)"
                )
                connection.commit()
                connection.close()
                with mock.patch.object(niche_research, "_overpass_public_categories") as discovery:
                    result = niche_research.discover_public_niches(
                        application.DB_NAME, "br", ["Campinas - SP"], ["Academia"],
                        config={"openstreetmap_daily_limit": 1},
                    )
                self.assertEqual([], result["discovered"])
                discovery.assert_not_called()
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
