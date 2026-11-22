import unittest
from discovery_sources import extract_rating_and_reviews_safely
from contact_quality import assess_phone, validate_phone_city_compatibility
from lead_scoring import score_lead
from app import eh_celular_valido, formatar_whatsapp


class TestDataQualityFixes(unittest.TestCase):
    def test_ddd_41_not_interpreted_as_41_reviews(self):
        """DDD 41 no telefone jamais deve ser extraído como 41 avaliações."""
        raw_text = "Centro Médico Odontológico (41) 99826-3846 Aberto até 18:00 R. Izaac Ferreira da Cruz"
        rating, reviews = extract_rating_and_reviews_safely(raw_text, phone="(41) 99826-3846")
        self.assertEqual(reviews, 0, f"Reviews deveria ser 0, mas foi extraído como {reviews}")
        self.assertEqual(rating, 0.0)

    def test_ddd_31_not_interpreted_as_31_reviews(self):
        """DDD 31 no telefone jamais deve ser extraído como 31 avaliações."""
        raw_text = "Marcenaria Sua Casa (31) 98707-6785 Av. Babita Camargos Aberto"
        rating, reviews = extract_rating_and_reviews_safely(raw_text, phone="(31) 98707-6785")
        self.assertEqual(reviews, 0, f"Reviews deveria ser 0, mas foi extraído como {reviews}")

    def test_ddd_19_and_48_not_interpreted_as_reviews(self):
        """DDDs 19 e 48 não devem ser interpretados como quantidade de avaliações."""
        text_19 = "Clínica Estética Indaiatuba (19) 99308-5806 Aberto"
        _, rev_19 = extract_rating_and_reviews_safely(text_19, phone="(19) 99308-5806")
        self.assertEqual(rev_19, 0)

        text_48 = "S12 Design Móveis (48) 99828-8430 Palhoça"
        _, rev_48 = extract_rating_and_reviews_safely(text_48, phone="(48) 99828-8430")
        self.assertEqual(rev_48, 0)

    def test_real_reviews_extracted_correctly(self):
        """Avaliações reais acompanhadas de nota ou texto 'avaliações' devem ser extraídas com precisão."""
        # Caso A: nota com estrelas e quantidade entre parênteses
        text_a = "Dra. Thayrine (41) 99581-5416 5,0 ★ (120) Dentista em Curitiba"
        rat_a, rev_a = extract_rating_and_reviews_safely(text_a, phone="(41) 99581-5416")
        self.assertEqual(rat_a, 5.0)
        self.assertEqual(rev_a, 120)

        # Caso B: texto explícito com palavra avaliações
        text_b = "Santa e Campos Solar (31) 98321-9448 4.9 estrelas 140 avaliações"
        rat_b, rev_b = extract_rating_and_reviews_safely(text_b, phone="(31) 98321-9448")
        self.assertEqual(rat_b, 4.9)
        self.assertEqual(rev_b, 140)

    def test_fixed_landline_not_classified_as_mobile(self):
        """Telefone fixo nunca deve ser classificado como celular ou candidato a WhatsApp."""
        fixed = "(19) 3478-1208"
        ass = assess_phone(fixed, "br")
        self.assertTrue(ass["valid"])
        self.assertFalse(ass["mobile"], "Telefone fixo foi marcado como celular")
        self.assertFalse(ass["whatsapp_candidate"], "Telefone fixo foi marcado como candidato a WhatsApp")
        self.assertIn("fixo", ass["kind"])

        # app.py helpers
        self.assertFalse(eh_celular_valido(fixed))
        self.assertEqual(formatar_whatsapp(fixed), "", "formatar_whatsapp gerou link para telefone fixo")

    def test_mobile_classified_correctly(self):
        """Celular com 9º dígito válido deve ser identificado como candidato a WhatsApp."""
        mobile = "(41) 99826-3846"
        ass = assess_phone(mobile, "br")
        self.assertTrue(ass["valid"])
        self.assertTrue(ass["mobile"])
        self.assertTrue(ass["whatsapp_candidate"])
        self.assertTrue(eh_celular_valido(mobile))
        self.assertIn("https://wa.me/5541998263846", formatar_whatsapp(mobile))

    def test_ddd_divergence_generates_alert(self):
        """DDD divergente da praça informada deve gerar alerta sem descartar o número."""
        # Celular DDD 11 em Americana (DDD 19)
        compat = validate_phone_city_compatibility("(11) 98404-7457", "Americana - SP", "br")
        self.assertFalse(compat["compatible"])
        self.assertEqual(compat["level"], "warning")
        self.assertIn("DDD 11 divergente", compat["warning"])
        self.assertEqual(compat["actual_ddd"], "11")
        self.assertIn("19", compat["expected_ddds"])

        # No lead_scoring, deve gerar alerta na dimensão de qualidade_evidencia
        lead = {
            "Nome": "LS Projetista",
            "Categoria Maps": "Marcenaria",
            "Cidade": "Americana - SP",
            "Telefone": "(11) 98404-7457",
            "Nota Maps": 5.0,
            "Qtd Avaliacoes": 0,
            "Status Validação": "CONFIRMADO",
        }
        res = score_lead(lead, has_own_site=False)
        self.assertIn("Alerta: DDD 11 divergente", res["dimensions"]["qualidade_evidencia"]["evidence"])

    def test_compatible_ddd_passes_without_alert(self):
        """DDD compatível com a cidade deve passar com nível 'ok' sem avisos."""
        compat_cwb = validate_phone_city_compatibility("(41) 99826-3846", "Sítio Cercado, Curitiba - PR")
        self.assertTrue(compat_cwb["compatible"])
        self.assertEqual(compat_cwb["level"], "ok")
        self.assertEqual(compat_cwb["warning"], "")

        compat_bh = validate_phone_city_compatibility("(31) 98707-6785", "Barreiro, Belo Horizonte - MG")
        self.assertTrue(compat_bh["compatible"])
        self.assertEqual(compat_bh["level"], "ok")

    def test_missing_data_does_not_generate_artificial_score(self):
        """Empresas sem nota e sem avaliações devem receber rigorosamente 0 pontos em atividade pública."""
        lead_vazio = {
            "Nome": "Empresa Sem Reviews",
            "Categoria Maps": "Marcenaria",
            "Cidade": "Americana - SP",
            "Telefone": "(19) 99559-3749",
            "Nota Maps": 0.0,
            "Qtd Avaliacoes": 0,
            "Status Validação": "PROVÁVEL",
        }
        res = score_lead(lead_vazio, has_own_site=False)
        self.assertEqual(res["dimensions"]["atividade_publica"]["score"], 0)
        self.assertIn("0 pontos", res["dimensions"]["atividade_publica"]["evidence"])

    def test_fixed_landline_capped_at_moderate(self):
        """Empresa que possui exclusivamente telefone fixo (sem celular, email ou rede) não pode ser Alta nem Boa oportunidade."""
        lead_fixo = {
            "Nome": "Marcenaria Tradicional",
            "Categoria Maps": "Móveis planejados",
            "Cidade": "Americana - SP",
            "Telefone": "(19) 3478-1208",
            "Nota Maps": 5.0,
            "Qtd Avaliacoes": 20,
            "Status Validação": "CONFIRMADO",
        }
        res = score_lead(lead_fixo, has_own_site=False)
        self.assertLessEqual(res["score"], 54, f"Score de empresa exclusivamente com telefone fixo deveria ser máx 54, mas foi {res['score']}")
        self.assertEqual(res["classification"], "Oportunidade moderada")


if __name__ == "__main__":
    unittest.main()
