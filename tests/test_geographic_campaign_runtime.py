import os
import sqlite3
import tempfile
import unittest

from geographic_campaigns import (
    claim_campaign_worker,
    complete_location,
    finalize_campaign_if_done,
)
from smart_campaigns import create_smart_campaign, init_smart_campaigns_schema, smart_campaign_detail


class TestGeographicCampaignRuntime(unittest.TestCase):
    def setUp(self):
        handle, self.db_name = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        connection = sqlite3.connect(self.db_name)
        init_smart_campaigns_schema(connection)
        connection.close()

    def tearDown(self):
        os.unlink(self.db_name)

    def create_campaign(self):
        return create_smart_campaign(self.db_name, {
            "location_mode": "auto",
            "locations_limit": 1,
            "niche_mode": "manual",
            "niches": ["Advocacia"],
            "target_qualified_leads": 5,
            "batch_size": 1,
        })

    def first_location_id(self, campaign_id):
        connection = sqlite3.connect(self.db_name)
        try:
            return connection.execute(
                "SELECT id FROM geographic_campaign_locations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
        finally:
            connection.close()

    def test_only_one_worker_can_claim_an_active_campaign(self):
        campaign = self.create_campaign()
        self.assertTrue(claim_campaign_worker(self.db_name, campaign["campaign_id"], "worker-a"))
        self.assertFalse(claim_campaign_worker(self.db_name, campaign["campaign_id"], "worker-b"))

    def test_campaign_with_no_real_query_fails_instead_of_completing(self):
        campaign = self.create_campaign()
        campaign_id = campaign["campaign_id"]
        self.assertTrue(claim_campaign_worker(self.db_name, campaign_id, "worker-a"))
        complete_location(self.db_name, self.first_location_id(campaign_id), {})
        self.assertTrue(finalize_campaign_if_done(self.db_name, campaign_id))

        detail = smart_campaign_detail(self.db_name, campaign_id)
        self.assertEqual("failed", detail["status"])
        self.assertEqual("falha", detail["detailed_status"])
        self.assertIn("sem executar consultas", detail["error"])

    def test_campaign_completes_after_a_real_query_even_with_zero_leads(self):
        campaign = self.create_campaign()
        campaign_id = campaign["campaign_id"]
        self.assertTrue(claim_campaign_worker(self.db_name, campaign_id, "worker-a"))
        complete_location(self.db_name, self.first_location_id(campaign_id), {
            "tentativas_busca": 1,
            "consultas_concluidas": 1,
            "encontrados": 0,
            "salvos": 0,
        })
        self.assertTrue(finalize_campaign_if_done(self.db_name, campaign_id))

        detail = smart_campaign_detail(self.db_name, campaign_id)
        self.assertEqual("completed", detail["status"])
        self.assertEqual(1, detail["queries_completed"])
        self.assertEqual(0, detail["qualified_leads"])

    def test_completed_location_recovers_interrupted_parent(self):
        campaign = self.create_campaign()
        campaign_id = campaign["campaign_id"]
        self.assertTrue(claim_campaign_worker(self.db_name, campaign_id, "worker-a"))
        complete_location(self.db_name, self.first_location_id(campaign_id), {
            "tentativas_busca": 1,
            "consultas_concluidas": 1,
            "encontrados": 9,
            "salvos": 5,
        })
        connection = sqlite3.connect(self.db_name)
        connection.execute("UPDATE geographic_campaigns SET status = 'interrupted' WHERE campaign_id = ?", (campaign_id,))
        connection.commit()
        connection.close()

        self.assertTrue(finalize_campaign_if_done(self.db_name, campaign_id))
        detail = smart_campaign_detail(self.db_name, campaign_id)
        self.assertEqual("completed", detail["status"])
        self.assertEqual(9, detail["companies_found"])
        self.assertEqual(5, detail["qualified_leads"])


if __name__ == "__main__":
    unittest.main()
