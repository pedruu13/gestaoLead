import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as application
from geographic_campaigns import init_geographic_schema
from smart_campaigns import (
    check_and_finalize_smart_goal,
    create_smart_campaign,
    get_latest_active_smart_campaign,
    init_smart_campaigns_schema,
    list_smart_campaigns,
    resolve_auto_locations,
    resolve_auto_niches,
    smart_campaign_detail,
    update_smart_campaign_status,
)


class TestSmartCampaigns(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_name = self.tmp_db.name
        conn = sqlite3.connect(self.db_name)
        init_smart_campaigns_schema(conn)
        conn.close()

    def test_schema_migration_idempotent(self):
        conn = sqlite3.connect(self.db_name)
        init_smart_campaigns_schema(conn)
        cursor = conn.cursor()
        cols = {row[1] for row in cursor.execute("PRAGMA table_info(geographic_campaigns)").fetchall()}
        self.assertIn("target_qualified_leads", cols)
        self.assertIn("min_qualification_score", cols)
        self.assertIn("detailed_status", cols)
        self.assertIn("location_mode", cols)
        self.assertIn("niche_mode", cols)
        conn.close()

    def test_resolve_auto_niches_default_and_exploratory(self):
        niches, is_exploratory = resolve_auto_niches(self.db_name, limit=3)
        self.assertEqual(len(niches), 3)
        self.assertTrue(is_exploratory)
        self.assertIn("Odontologia", niches)

    def test_resolve_auto_locations(self):
        locations, is_exploratory = resolve_auto_locations(self.db_name, limit=5)
        self.assertGreaterEqual(len(locations), 1)
        self.assertIn("id", locations[0])
        self.assertIn("name", locations[0])
        self.assertIn("uf", locations[0])
        self.assertTrue(is_exploratory)
        self.assertGreaterEqual(len({location["uf"] for location in locations}), 4)

    def test_create_smart_campaign_auto(self):
        payload = {
            "location_mode": "auto",
            "niche_mode": "auto",
            "target_qualified_leads": 100,
        }
        campaign = create_smart_campaign(self.db_name, payload)
        self.assertEqual(campaign["status"], "pending")
        self.assertEqual(campaign["detailed_status"], "preparando")
        self.assertEqual(campaign["target_qualified_leads"], 100)
        self.assertEqual(campaign["location_mode"], "auto")
        self.assertEqual(campaign["niche_mode"], "auto")
        self.assertGreater(campaign["total_municipalities"], 0)
        self.assertGreater(campaign["niches_count"], 0)

    def test_create_smart_campaign_custom_meta(self):
        payload = {
            "location_mode": "auto",
            "niche_mode": "manual",
            "niches": ["Energia Solar"],
            "target_qualified_leads": 250,
            "min_qualification_score": 75,
        }
        campaign = create_smart_campaign(self.db_name, payload)
        self.assertEqual(campaign["target_qualified_leads"], 250)
        self.assertEqual(campaign["min_qualification_score"], 75)
        self.assertEqual(campaign["niches"], ["Energia Solar"])

    def test_create_smart_campaign_validation_states(self):
        with self.assertRaises(ValueError):
            create_smart_campaign(self.db_name, {
                "location_mode": "states",
                "states": [],
                "niche_mode": "auto",
            })

    def test_create_smart_campaign_validation_cities(self):
        with self.assertRaises(ValueError):
            create_smart_campaign(self.db_name, {
                "location_mode": "cities",
                "municipality_ids": [],
                "niche_mode": "auto",
            })

    def test_create_smart_campaign_validation_niches(self):
        with self.assertRaises(ValueError):
            create_smart_campaign(self.db_name, {
                "location_mode": "auto",
                "niche_mode": "manual",
                "niches": [],
            })

    def test_pause_resume_cancel_flow(self):
        payload = {"location_mode": "auto", "niche_mode": "auto", "target_qualified_leads": 50}
        campaign = create_smart_campaign(self.db_name, payload)
        cid = campaign["campaign_id"]

        update_smart_campaign_status(self.db_name, cid, status="paused", detailed_status="pausada")
        detail = smart_campaign_detail(self.db_name, cid)
        self.assertEqual(detail["status"], "paused")
        self.assertEqual(detail["detailed_status"], "pausada")

        update_smart_campaign_status(self.db_name, cid, status="running", detailed_status="buscando_empresas")
        detail = smart_campaign_detail(self.db_name, cid)
        self.assertEqual(detail["status"], "running")
        self.assertEqual(detail["detailed_status"], "buscando_empresas")

        update_smart_campaign_status(self.db_name, cid, status="cancelled", detailed_status="cancelada")
        detail = smart_campaign_detail(self.db_name, cid)
        self.assertEqual(detail["status"], "cancelled")
        self.assertEqual(detail["detailed_status"], "cancelada")

    def test_goal_finalization(self):
        payload = {"location_mode": "auto", "niche_mode": "auto", "target_qualified_leads": 50}
        campaign = create_smart_campaign(self.db_name, payload)
        cid = campaign["campaign_id"]

        # Simula alcance de 50 leads qualificados
        conn = sqlite3.connect(self.db_name)
        conn.execute("UPDATE geographic_campaigns SET qualified_leads = 50 WHERE campaign_id = ?", (cid,))
        conn.commit()
        conn.close()

        done = check_and_finalize_smart_goal(self.db_name, cid)
        self.assertTrue(done)

        detail = smart_campaign_detail(self.db_name, cid)
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["detailed_status"], "concluida")
        self.assertEqual(detail["progress_percent"], 100.0)

    def test_get_latest_active_smart_campaign(self):
        payload = {"location_mode": "auto", "niche_mode": "auto", "target_qualified_leads": 100}
        c1 = create_smart_campaign(self.db_name, payload)
        active = get_latest_active_smart_campaign(self.db_name)
        self.assertIsNotNone(active)
        self.assertEqual(active["campaign_id"], c1["campaign_id"])

        update_smart_campaign_status(self.db_name, c1["campaign_id"], status="cancelled", detailed_status="cancelada")
        self.assertIsNone(get_latest_active_smart_campaign(self.db_name))


class TestSmartCampaignsFlaskAPI(unittest.TestCase):
    def setUp(self):
        self.original_db = application.DB_NAME
        handle, self.test_db = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        application.DB_NAME = self.test_db
        application.init_db()
        application.app.config["TESTING"] = True
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["authenticated"] = True
            session["user"] = "teste"

    def tearDown(self):
        application.DB_NAME = self.original_db
        os.unlink(self.test_db)

    def test_api_geo_states(self):
        response = self.client.get("/api/smart-campaigns/geo/states")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["states"]), 27)
        sao_paulo = next((state for state in data["states"] if state["code"] == "SP"), None)
        self.assertIsNotNone(sao_paulo)
        self.assertEqual("São Paulo", sao_paulo["name"])

    def test_api_niches_popular(self):
        response = self.client.get("/api/smart-campaigns/niches/popular")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["niches"]), 5)

    def test_api_geo_search(self):
        response = self.client.get("/api/smart-campaigns/geo/search?q=Campinas&uf=SP")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["municipalities"]), 1)
        self.assertEqual(data["municipalities"][0]["uf"], "SP")

    @patch("app.start_geographic_campaign")
    def test_api_create_smart_campaign(self, mock_start):
        def mark_running(campaign_id):
            update_smart_campaign_status(
                application.DB_NAME, campaign_id, status="running", detailed_status="buscando_empresas"
            )
            return True

        mock_start.side_effect = mark_running
        payload = {
            "location_mode": "auto",
            "niche_mode": "auto",
            "target_qualified_leads": 100,
        }
        response = self.client.post("/api/smart-campaigns", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("campaign_id", data["campaign"])
        self.assertEqual(data["campaign"]["target_qualified_leads"], 100)

        cid = data["campaign"]["campaign_id"]

        # Detail
        detail_resp = self.client.get(f"/api/smart-campaigns/{cid}")
        self.assertEqual(detail_resp.status_code, 200)

        # Actions
        pause_resp = self.client.post(f"/api/smart-campaigns/{cid}/pause")
        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(pause_resp.get_json()["campaign"]["status"], "paused")

        resume_resp = self.client.post(f"/api/smart-campaigns/{cid}/resume")
        self.assertEqual(resume_resp.status_code, 200)
        self.assertEqual(resume_resp.get_json()["campaign"]["status"], "running")

        cancel_resp = self.client.post(f"/api/smart-campaigns/{cid}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.get_json()["campaign"]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
