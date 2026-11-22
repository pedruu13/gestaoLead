import unittest
from lead_scoring import score_lead


class TestAestheticNicheSemanticScoring(unittest.TestCase):
    """
    Testes específicos para qualificação semântica do nicho de estética e beleza:
    1. Alto potencial: clínicas estruturadas, biomédicas, injetáveis e harmonização facial (fit_raw = 10).
    2. Potencial reduzido: profissionais individuais de sobrancelhas, cílios, unhas, depilação simples e micropigmentação (fit_raw = 4, score <= 54).
    3. Não classificar apenas pela palavra 'estética': estética geral sem clínica estruturada não recebe nota máxima cega (fit_raw = 8).
    4. Não penalizar clínicas completas que também ofereçam serviços básicos: clínicas estruturadas mantêm fit_raw = 10.
    """

    def test_structured_clinic_high_potential(self):
        """Clínica estruturada com procedimentos de harmonização e injetáveis atinge Alta Prioridade (fit_raw = 10)."""
        lead = {
            "Nome": "Dra Rafaelle Lucia - Biomédica Esteta",
            "Categoria Maps": "Esteticista",
            "Telefone": "(19) 99220-7345",
            "Cidade": "Indaiatuba",
            "Nota Maps": 5.0,
            "Qtd Avaliacoes": 25,
            "Link Inicial": "https://wa.me/5519992207345",
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
        }
        res = score_lead(lead, has_own_site=False)
        self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 25)
        self.assertGreaterEqual(res["score"], 80)
        self.assertEqual(res["classification"], "Alta prioridade")
        self.assertIn("Clínica de estética estruturada", res["dimensions"]["adequacao_servico"]["evidence"])

    def test_facial_harmonization_high_potential(self):
        """Profissional/clínica com foco em harmonização facial recebe fit_raw = 10."""
        lead = {
            "Nome": "Dra. Daniela Andrade - Harmonização Facial e Corporal em Indaiatuba",
            "Categoria Maps": "Centro de saúde e beleza",
            "Telefone": "(19) 99539-4878",
            "Cidade": "Indaiatuba",
            "Nota Maps": 5.0,
            "Qtd Avaliacoes": 10,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "PROVÁVEL",
        }
        res = score_lead(lead, has_own_site=False)
        self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 25)
        self.assertIn("Clínica de estética estruturada", res["dimensions"]["adequacao_servico"]["evidence"])

    def test_individual_eyebrow_lash_reduced_potential(self):
        """Profissionais individuais de sobrancelhas e cílios têm potencial reduzido (fit_raw = 4, score <= 54)."""
        leads_baixo_ticket = [
            {
                "Nome": "Laís Almeida - Cílios , Sobrancelhas e Cursos",
                "Categoria Maps": "Salão de Beleza",
                "Telefone": "(41) 98410-3723",
                "Cidade": "Colombo",
                "Nota Maps": 5.0,
                "Qtd Avaliacoes": 12,
            },
            {
                "Nome": "Izabele Ferreira Sobrancelhas Microblading",
                "Categoria Maps": "Salão de Beleza",
                "Telefone": "(41) 99506-0139",
                "Cidade": "Colombo",
                "Nota Maps": 5.0,
                "Qtd Avaliacoes": 15,
            },
            {
                "Nome": "Mari Slociak | Studio de beleza e estética",
                "Categoria Maps": "Salão de sobrancelhas",
                "Telefone": "(41) 99729-0129",
                "Cidade": "Colombo",
                "Nota Maps": 4.9,
                "Qtd Avaliacoes": 8,
            },
            {
                "Nome": "Cristina Santos Studio micropigmentação e Estética",
                "Categoria Maps": "Clínica de maquiagem definitiva",
                "Telefone": "(41) 99700-0342",
                "Cidade": "Colombo",
                "Nota Maps": 5.0,
                "Qtd Avaliacoes": 30,
            },
            {
                "Nome": "Studio Nails & Esmalteria",
                "Categoria Maps": "Manicure e pedicure",
                "Telefone": "(11) 98888-7777",
                "Cidade": "São Paulo",
                "Nota Maps": 4.8,
                "Qtd Avaliacoes": 18,
            },
        ]
        for lead in leads_baixo_ticket:
            with self.subTest(lead=lead["Nome"]):
                res = score_lead(lead, has_own_site=False)
                self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 10)  # 4/10 * 25 = 10
                self.assertLessEqual(res["score"], 54)
                self.assertNotEqual(res["classification"], "Alta prioridade")
                self.assertNotEqual(res["classification"], "Boa oportunidade")
                self.assertIn("microsserviços de beleza/estética de ticket reduzido", res["dimensions"]["adequacao_servico"]["evidence"])

    def test_complete_clinic_offering_basic_services_not_penalized(self):
        """Regra de Ouro: Clínicas completas com injetáveis/harmonização que também oferecem sobrancelhas NÃO são penalizadas."""
        lead_clinica_completa = {
            "Nome": "Clínica de Estética Integrada Dra. Amanda",
            "Categoria Maps": "Clínica de estética",
            "Serviços": "Harmonização facial, bioestimulador de colágeno, botox, sobrancelhas e unhas",
            "Telefone": "(19) 99888-1122",
            "Cidade": "Limeira",
            "Nota Maps": 5.0,
            "Qtd Avaliacoes": 40,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "CONFIRMADO",
        }
        res = score_lead(lead_clinica_completa, has_own_site=False)
        self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 25)  # 10/10 * 25 = 25
        self.assertGreaterEqual(res["score"], 80)
        self.assertEqual(res["classification"], "Alta prioridade")
        self.assertIn("Clínica de estética estruturada", res["dimensions"]["adequacao_servico"]["evidence"])

    def test_generic_aesthetic_not_blindly_max_scored(self):
        """Não classificar apenas pela palavra 'estética': estética geral sem clínica estruturada recebe fit intermediário (fit_raw = 8)."""
        lead_estetica_geral = {
            "Nome": "Studio Bela Estética e Massagem",
            "Categoria Maps": "Esteticista",
            "Telefone": "(19) 99777-3344",
            "Cidade": "Limeira",
            "Nota Maps": 4.7,
            "Qtd Avaliacoes": 10,
            "Status Validação": "CONFIRMADO",
            "Confiança do Site": "PROVÁVEL",
        }
        res = score_lead(lead_estetica_geral, has_own_site=False)
        # fit_raw = 8 -> 8/10 * 25 = 20 pts
        self.assertEqual(res["dimensions"]["adequacao_servico"]["score"], 20)
        self.assertIn("Estética geral ou serviços de beleza intermediários", res["dimensions"]["adequacao_servico"]["evidence"])


if __name__ == "__main__":
    unittest.main()
