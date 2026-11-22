import os
import tempfile
import unittest

from app import classificar_potencial
from lead_scoring import SCORE_VERSION, score_lead
from smart_campaigns import (
    AUTO_NICHE_PROFILES,
    create_smart_campaign,
    explain_auto_niches,
    init_smart_campaigns_schema,
    resolve_auto_locations,
    resolve_auto_niches,
)


class TestLeadQualificationIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_name = self.temp_db.name
        import sqlite3
        conn = sqlite3.connect(self.db_name)
        init_smart_campaigns_schema(conn)
        conn.close()

    def tearDown(self):
        if os.path.exists(self.db_name):
            try:
                os.remove(self.db_name)
            except OSError:
                pass

    def test_score_classification_four_tiers(self):
        """Verifica a categorização exata nas 4 faixas comerciais (80-100, 60-79, 40-59, 0-39)."""
        self.assertEqual(classificar_potencial(95), "Alta prioridade")
        self.assertEqual(classificar_potencial(80), "Alta prioridade")
        self.assertEqual(classificar_potencial(79), "Boa oportunidade")
        self.assertEqual(classificar_potencial(60), "Boa oportunidade")
        self.assertEqual(classificar_potencial(59), "Oportunidade moderada")
        self.assertEqual(classificar_potencial(40), "Oportunidade moderada")
        self.assertEqual(classificar_potencial(39), "Baixa prioridade")
        self.assertEqual(classificar_potencial(0), "Baixa prioridade")

    def test_high_priority_lead_profile(self):
        """Verifica se um lead com alto ticket, sem site, com WhatsApp e avaliações atinge Alta Prioridade (80-100)."""
        lead = {
            "Nome": "Dra. Juliana - Harmonização e Estética",
            "Nicho": "Clínica de Estética",
            "Categoria Maps": "Clínica de estética avançada",
            "Bairro": "Moema - São Paulo - SP",
            "Telefone": "11987652341",
            "E-mail Encontrado": "contato@drajuliana.com.br",
            "Instagram": "@drajuliana.estetica",
            "Link Inicial": "https://linktr.ee/drajuliana",
            "Nota Maps": 4.9,
            "Qtd Avaliacoes": 45,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
            "Quantidade de Fontes": 2,
        }
        res = score_lead(lead, has_own_site=False)
        self.assertGreaterEqual(res["score"], 80)
        self.assertEqual(res["classification"], "Alta prioridade")
        self.assertEqual(res["tier"], "Alta prioridade")
        self.assertEqual(res["range"], "Prioridade")
        self.assertEqual(res["priority"], "Alta")
        self.assertIn("Dependência de rede social", res["dimensions"]["necessidade_digital"]["evidence"])

    def test_rule_absence_of_site_is_not_guaranteed_purchase(self):
        """
        Regra fundamental: Não confundir ausência de site com certeza de interesse em contratar.
        Empresa sem site, mas SEM celular/WhatsApp comercial e SEM avaliações/atividade
        NÃO pode ser classificada como Alta prioridade ou Boa oportunidade (trava em máx 54 pontos).
        """
        lead_fantasma = {
            "Nome": "Comércio Desconhecido",
            "Nicho": "Advocacia",
            "Categoria Maps": "Escritório de advocacia",
            "Bairro": "Centro",
            "Telefone": "1133334444",  # Telefone fixo apenas, sem celular/WhatsApp
            "E-mail Encontrado": "",
            "Link Inicial": "",
            "Nota Maps": 0,
            "Qtd Avaliacoes": 0,
            "Status Validação": "PROVÁVEL",
            "Confiança do Site": "CONFIRMADO",
            "Quantidade de Fontes": 2,
        }
        res = score_lead(lead_fantasma, has_own_site=False)
        self.assertLessEqual(res["score"], 54)
        self.assertIn(res["classification"], {"Oportunidade moderada", "Baixa prioridade"})
        self.assertNotEqual(res["classification"], "Alta prioridade")
        self.assertNotEqual(res["classification"], "Boa oportunidade")

    def test_social_bio_link_detection(self):
        """Verifica a identificação de dependência exclusiva de redes sociais/Linktree."""
        lead = {
            "Nome": "Studio Odonto",
            "Nicho": "Odontologia",
            "Categoria Maps": "Clínica odontológica",
            "Bairro": "Batel - Curitiba - PR",
            "Telefone": "41988887777",
            "Link Inicial": "https://bio.site/studio_odonto",
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "PROVÁVEL",
            "Nota Maps": 4.8,
            "Qtd Avaliacoes": 32,
            "Quantidade de Fontes": 2,
        }
        res = score_lead(lead, has_own_site=False)
        self.assertEqual(res["dimensions"]["necessidade_digital"]["score"], 30)
        self.assertIn("Dependência de rede social", res["dimensions"]["necessidade_digital"]["evidence"])

    def test_high_ticket_vs_low_ticket_niche_fit(self):
        """Verifica que nichos de serviços de alto valor agregado pontuam significativamente mais em adequação."""
        high_ticket_lead = {
            "Nome": "Solar Brasil Engenharia",
            "Nicho": "Energia Solar",
            "Categoria Maps": "Instalador de energia solar",
            "Telefone": "11988889999",
            "Status Validação": "CONFIRMADO",
        }
        low_ticket_lead = {
            "Nome": "Borracharia do Zé",
            "Nicho": "Borracharia",
            "Categoria Maps": "Borracharia de esquina",
            "Telefone": "11988889999",
            "Status Validação": "CONFIRMADO",
        }
        res_high = score_lead(high_ticket_lead, has_own_site=False)
        res_low = score_lead(low_ticket_lead, has_own_site=False)

        score_fit_high = res_high["dimensions"]["adequacao_servico"]["score"]
        score_fit_low = res_low["dimensions"]["adequacao_servico"]["score"]

        self.assertGreater(score_fit_high, score_fit_low)
        self.assertEqual(score_fit_high, 25)  # 10/10 * 25 = 25
        self.assertLessEqual(score_fit_low, 10)  # 4/10 * 25 = 10

    def test_explain_auto_niches_returns_rationale(self):
        """Verifica se a recomendação de nichos automáticos entrega justificativas e tickets."""
        explained = explain_auto_niches(self.db_name, limit=4)
        self.assertGreaterEqual(len(explained), 2)
        for item in explained:
            self.assertIn("name", item)
            self.assertIn("reason", item)
            self.assertIn("ticket_tier", item)
            self.assertIn("category", item)
            self.assertTrue(len(item["reason"]) > 10)

    def test_resolve_auto_locations_includes_reasons(self):
        """Verifica se a seleção de cidades do Brasil Inteligente entrega justificativas geográficas."""
        locations, is_exploratory = resolve_auto_locations(self.db_name, limit=5)
        self.assertEqual(len(locations), 5)
        for loc in locations:
            self.assertIn("name", loc)
            self.assertIn("uf", loc)
            self.assertIn("reason", loc)
            self.assertTrue(len(loc["reason"]) > 10)

    def test_smart_campaign_stores_meta_methodology(self):
        """Verifica se a criação de campanha inteligente persiste a metodologia explicada."""
        payload = {
            "target_qualified_leads": 100,
            "min_qualification_score": 75,
            "location_mode": "auto",
            "locations_limit": 4,
            "niche_mode": "auto",
        }
        campaign = create_smart_campaign(self.db_name, payload)
        self.assertEqual(campaign["target_qualified_leads"], 100)
        self.assertEqual(campaign["min_qualification_score"], 75)
        self.assertTrue(len(campaign.get("meta_metodologia", "")) > 10)
        self.assertIn("Nichos recomendados", campaign["meta_metodologia"])

    def test_rule_healthy_site_never_high_priority(self):
        """
        Eliminação de falso positivo: Se a empresa já tem um site saudável e funcional,
        não há oportunidade imediata de venda de site, devendo ser limitada a no máximo 54 pontos.
        """
        lead_site_saudavel = {
            "Nome": "Clínica Médica Exemplo",
            "Nicho": "Clínica Médica",
            "Categoria Maps": "Clínica médica especializada",
            "Bairro": "Jardins - São Paulo",
            "Telefone": "11988887777",
            "E-mail Encontrado": "contato@clinicamedica.com.br",
            "Link Inicial": "https://clinicamedica.com.br",
            "Oportunidade do Site": "Sem problemas identificados",
            "Nota Maps": 4.9,
            "Qtd Avaliacoes": 50,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
            "Quantidade de Fontes": 2,
        }
        res = score_lead(lead_site_saudavel, has_own_site=True)
        self.assertLessEqual(res["score"], 54)
        self.assertNotEqual(res["classification"], "Alta prioridade")
        self.assertNotEqual(res["classification"], "Boa oportunidade")

    def test_rule_low_ticket_informal_niche_capped(self):
        """
        Eliminação de falso positivo: Nichos informais ou de baixo ticket médio
        (borracharia, chaveiro) têm score travado em <= 54 pontos.
        """
        lead_informal = {
            "Nome": "Chaveiro 24h Esquina",
            "Nicho": "Chaveiro",
            "Categoria Maps": "Serviço de chaveiro e carimbos",
            "Telefone": "11999998888",
            "Link Inicial": "",
            "Nota Maps": 4.8,
            "Qtd Avaliacoes": 20,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
        }
        res = score_lead(lead_informal, has_own_site=False)
        self.assertLessEqual(res["score"], 54)
        self.assertNotEqual(res["classification"], "Alta prioridade")
        self.assertNotEqual(res["classification"], "Boa oportunidade")

    def test_rule_uncontactable_lead_capped(self):
        """
        Eliminação de falso positivo: Empresa sem telefone nem e-mail não é acionável,
        devendo ter pontuação travada em <= 49 pontos.
        """
        lead_sem_contato = {
            "Nome": "Escritório de Advocacia Sem Telefone",
            "Nicho": "Advocacia",
            "Categoria Maps": "Escritório de advocacia",
            "Telefone": "",
            "E-mail Encontrado": "",
            "Instagram": "@advocacia_exemplo",
            "Link Inicial": "",
            "Nota Maps": 4.5,
            "Qtd Avaliacoes": 10,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
        }
        res = score_lead(lead_sem_contato, has_own_site=False)
        self.assertLessEqual(res["score"], 49)
        self.assertIn(res["classification"], {"Oportunidade moderada", "Baixa prioridade"})

    def test_accent_insensitive_niche_matching(self):
        """
        Eliminação de falso negativo: Termos de nicho com acentos diversos
        ('Clínica Médica', 'Móveis Planejados', 'Estética') devem pontuar nota máxima de adequação (25 pts).
        """
        lead_acentuado = {
            "Nome": "Consultório & Estética Avançada",
            "Categoria Maps": "Clínica Médica e Estética",
            "Telefone": "11988887777",
            "Status Validação": "CONFIRMADO",
        }
        res = score_lead(lead_acentuado, has_own_site=False)
        self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 25)


if __name__ == "__main__":
    unittest.main()
