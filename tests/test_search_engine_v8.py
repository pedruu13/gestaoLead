import os
import tempfile
import unittest
from unittest import mock

import app as application
from contact_quality import assess_phone
from target_intelligence import search_terms_for_niche, suggest_targets


class SearchEngineV8Tests(unittest.TestCase):
    def authenticate(self, client):
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["user"] = "teste"
            session["csrf_token"] = "search-v8-token"
        return {"X-CSRF-Token": "search-v8-token"}

    def test_phone_quality_separates_invalid_fixed_and_mobile(self):
        self.assertFalse(assess_phone("11999999999", "br")["valid"])
        self.assertEqual("telefone fixo", assess_phone("1130550100", "br")["kind"])
        mobile = assess_phone("(11) 98765-1234", "br")
        self.assertTrue(mobile["whatsapp_candidate"])
        self.assertEqual("5511987651234", mobile["digits"])

    def test_search_terms_have_fallbacks_for_commercial_label(self):
        terms = search_terms_for_niche("br", "Academia e treinamento")
        self.assertEqual("academia", terms[0])
        self.assertGreaterEqual(len(terms), 3)
        self.assertIn("treinamento funcional", terms)

    def test_suggestion_evidence_uses_commercial_results(self):
        rows = [
            {"nicho": "Academia", "bairro": "Campinas - SP", "link_inicial": "", "telefone": "11987654321", "whatsapp_link": "", "email": "", "avaliacoes": "30", "status": "Conversando"},
            {"nicho": "Academia", "bairro": "Campinas - SP", "link_inicial": "", "telefone": "11987654322", "whatsapp_link": "", "email": "", "avaliacoes": "20", "status": "Fechado"},
        ]
        result = suggest_targets("br", rows, focus_niches=["Academia"], focus_locations=["Campinas - SP"])
        self.assertIn("2 resposta(s)", result["pracas"][0]["evidencia"])
        self.assertIn("1 fechamento(s)", result["pracas"][0]["evidencia"])

    def test_direct_whatsapp_records_contact_after_official_api_acceptance(self):
        old_db = application.DB_NAME
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "whatsapp-cloud.db")
            try:
                application.init_db()
                application.save_lead_db({
                    "Nome": "Academia Teste", "Nicho": "Academia", "Bairro": "Campinas - SP",
                    "Telefone": "11987651234", "WhatsApp Link": "https://wa.me/5511987651234",
                    "Potencial": 70, "Faixa Potencial": "Prioridade",
                }, "place-whatsapp")
                client = application.app.test_client()
                headers = self.authenticate(client)
                self.assertIn("WhatsApp oficial", client.get("/configuracoes").get_data(as_text=True))
                self.assertIn("central_whatsapp_cloud", client.get("/crm").get_data(as_text=True))
                with mock.patch.object(application, "send_approved_template", return_value={"message_id": "wamid.test"}):
                    response = client.post(
                        "/api/leads/place-whatsapp/whatsapp", headers=headers,
                        json={"message": "Olá, gostaria de falar sobre o site da empresa."},
                    )
                self.assertEqual(200, response.status_code, response.get_json())
                lead = application.get_lead_by_id("place-whatsapp")
                self.assertEqual("Contatado", lead["status"])
                self.assertEqual("WhatsApp Cloud API", lead["last_contact_channel"])
            finally:
                application.DB_NAME = old_db


if __name__ == "__main__":
    unittest.main()
