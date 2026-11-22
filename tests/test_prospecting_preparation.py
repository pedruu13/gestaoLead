import json
import os
import sqlite3
import tempfile
import unittest

from prospecting_preparation import (
    DB_NAME,
    STATUS_PENDENTE,
    STATUS_PREPARADO,
    STATUS_APROVADO,
    STATUS_ENVIADO,
    STATUS_RESPONDIDO,
    VALID_STATUSES,
    init_prospecting_schema,
    get_category_a_leads_data,
    seed_prospecting_queue,
    list_prospecting_queue,
    get_prospecting_lead,
    update_prospecting_status,
    update_prospecting_content,
    get_lead_preview_versions,
    generate_prospecting_preview,
    seed_category_a_previews,
)
from app import app


class TestProspectingPreparation(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        import app as app_module
        self.app_module = app_module
        self.orig_db = app_module.DB_NAME
        app_module.DB_NAME = self.temp_db_path
        app.config["TESTING"] = True
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "teste_admin"
            sess["csrf_token"] = "valid-token"

    def tearDown(self):
        self.app_module.DB_NAME = self.orig_db
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_schema_creation_and_idempotence(self):
        """Verifica se o schema da tabela commercial_prospecting_queue é criado com integridade."""
        init_prospecting_schema(self.temp_db_path)
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()
        
        # Verificar existência da tabela
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commercial_prospecting_queue'")
        self.assertIsNotNone(cursor.fetchone(), "Tabela commercial_prospecting_queue deve existir")
        
        # Verificar colunas essenciais
        cursor.execute("PRAGMA table_info(commercial_prospecting_queue)")
        columns = [row[1] for row in cursor.fetchall()]
        expected_columns = [
            "lead_id", "nome", "categoria", "nicho", "cidade", "telefone", "whatsapp_link",
            "score", "status", "oportunidade_digital", "proposta_json", "mensagem_whatsapp",
            "briefing_visual_json", "evidencias_json", "notas_operador"
        ]
        for col in expected_columns:
            self.assertIn(col, columns, f"Coluna {col} deve estar presente na tabela")
            
        conn.close()
        
        # Idempotência: rodar novamente não deve lançar exceção
        init_prospecting_schema(self.temp_db_path)

    def test_category_a_leads_quality_and_count(self):
        """Valida se os 15 leads da Categoria A possuem todos os requisitos comerciais."""
        leads = get_category_a_leads_data()
        self.assertEqual(len(leads), 15, "Devem haver exatamente 15 leads na Categoria A")
        
        for lead in leads:
            self.assertTrue(lead["lead_id"].startswith("lead-"), "Lead deve ter um identificador único")
            self.assertTrue(len(lead["nome"]) > 2, "Nome da empresa deve ser válido")
            self.assertTrue(len(lead["cidade"]) > 2, "Cidade deve ser informada")
            self.assertTrue(len(lead["telefone"]) >= 10, "Telefone deve ser informado com DDD")
            self.assertTrue(lead["score"] >= 60, "Lead de Categoria A deve ter score >= 60")
            
            # Oportunidade digital específica (sem generalismo)
            self.assertTrue(len(lead["oportunidade_digital"]) > 30, "Oportunidade digital deve ser detalhada")
            
            # Proposta de site
            prop = lead["proposta"]
            self.assertTrue(len(prop["tipo_solucao"]) > 3, "Proposta deve ter tipo de solução")
            self.assertTrue(len(prop["headline"]) > 10, "Proposta deve ter headline de valor")
            self.assertTrue(len(prop["secoes"]) >= 3, "Proposta deve sugerir ao menos 3 seções")
            
            # Mensagem curta para WhatsApp (comercial e respeitosa)
            msg = lead["mensagem_whatsapp"]
            self.assertTrue(len(msg) > 30, "Mensagem WhatsApp deve ter corpo substantivo")
            self.assertTrue(len(msg) < 800, "Mensagem WhatsApp não deve ser prolixa (menos de 800 chars)")
            
            # Briefing visual para prévia
            brief = lead["briefing_visual"]
            self.assertTrue("paleta_cores" in brief or "paleta" in brief, "Briefing visual deve conter paleta de cores")
            paleta = brief.get("paleta_cores") or brief.get("paleta")
            self.assertTrue(len(paleta) >= 3, "Paleta deve conter pelo menos 3 cores")
            self.assertIn("tipografia", brief, "Briefing deve sugerir tipografia")
            self.assertTrue("tom_voz" in brief or "tom_de_voz" in brief, "Briefing deve sugerir tom de voz")
            
            # Evidências e links
            self.assertTrue(len(lead["evidencias"]) >= 2, "Devem existir ao menos 2 evidências auditadas")

    def test_seed_and_idempotent_refresh(self):
        """Testa o seeding inicial da fila e atualização idempotente sem perda de dados."""
        # Seeding inicial
        res1 = seed_prospecting_queue(self.temp_db_path)
        self.assertEqual(res1["seeded"], 15)
        self.assertEqual(res1["updated"], 0)
        
        # Simula alteração do status de um lead pelo operador
        update_prospecting_status("lead-euphoria-estetica-limeira", STATUS_APROVADO, db_target=self.temp_db_path)
        
        # Segundo seed não deve sobrescrever o status do lead que foi aprovado
        res2 = seed_prospecting_queue(self.temp_db_path)
        self.assertEqual(res2["seeded"], 0)
        self.assertEqual(res2["updated"], 15)
        
        lead = get_prospecting_lead("lead-euphoria-estetica-limeira", db_target=self.temp_db_path)
        self.assertEqual(lead["status"], STATUS_APROVADO, "Status alterado pelo operador deve ser preservado no seed")

    def test_list_prospecting_queue_and_filters(self):
        """Testa a listagem e contadores por status."""
        seed_prospecting_queue(self.temp_db_path)
        
        # Inicialmente todos estão como 'Preparado'
        q = list_prospecting_queue(db_target=self.temp_db_path)
        self.assertEqual(q["counts"]["Todos"], 15)
        self.assertEqual(q["counts"][STATUS_PREPARADO], 15)
        self.assertEqual(len(q["leads"]), 15)
        
        # Mudar status de 2 leads
        update_prospecting_status("lead-euphoria-estetica-limeira", STATUS_APROVADO, db_target=self.temp_db_path)
        update_prospecting_status("lead-dra-rafaelle-lucia-indaiatuba", STATUS_ENVIADO, db_target=self.temp_db_path)
        
        q_after = list_prospecting_queue(db_target=self.temp_db_path)
        self.assertEqual(q_after["counts"][STATUS_APROVADO], 1)
        self.assertEqual(q_after["counts"][STATUS_ENVIADO], 1)
        self.assertEqual(q_after["counts"][STATUS_PREPARADO], 13)
        
        # Filtrar por Aprovado
        q_aprovados = list_prospecting_queue(status_filter=STATUS_APROVADO, db_target=self.temp_db_path)
        self.assertEqual(len(q_aprovados["leads"]), 1)
        self.assertEqual(q_aprovados["leads"][0]["lead_id"], "lead-euphoria-estetica-limeira")

    def test_update_prospecting_content(self):
        """Testa edição personalizada da mensagem e notas do operador."""
        seed_prospecting_queue(self.temp_db_path)
        lead_id = "lead-marcenaria-sua-casa-contagem"
        
        nova_msg = "Olá Tiago! Vi seu showroom no Cidade Industrial. Segue prévia do site exclusivo."
        novas_notas = "Cliente demonstrou interesse via WhatsApp, reunião agendada para sexta 14h."
        
        update_prospecting_content(lead_id, {
            "mensagem_whatsapp": nova_msg,
            "notas_operador": novas_notas
        }, db_target=self.temp_db_path)
        
        lead = get_prospecting_lead(lead_id, db_target=self.temp_db_path)
        self.assertEqual(lead["mensagem_whatsapp"], nova_msg)
        self.assertEqual(lead["notas_operador"], novas_notas)

    def test_status_transition_timestamps(self):
        """Verifica se a transição para Aprovado, Enviado e Respondido registra o timestamp correto."""
        seed_prospecting_queue(self.temp_db_path)
        lead_id = "lead-linear-moveis-palhoca"
        
        # 1. Aprovado
        update_prospecting_status(lead_id, STATUS_APROVADO, db_target=self.temp_db_path)
        lead = get_prospecting_lead(lead_id, db_target=self.temp_db_path)
        self.assertEqual(lead["status"], STATUS_APROVADO)
        self.assertIsNotNone(lead["approved_at"])
        
        # 2. Enviado
        update_prospecting_status(lead_id, STATUS_ENVIADO, db_target=self.temp_db_path)
        lead = get_prospecting_lead(lead_id, db_target=self.temp_db_path)
        self.assertEqual(lead["status"], STATUS_ENVIADO)
        self.assertIsNotNone(lead["sent_at"])
        
        # 3. Respondido
        update_prospecting_status(lead_id, STATUS_RESPONDIDO, db_target=self.temp_db_path)
        lead = get_prospecting_lead(lead_id, db_target=self.temp_db_path)
        self.assertEqual(lead["status"], STATUS_RESPONDIDO)
        self.assertIsNotNone(lead["responded_at"])

    def test_web_routes_and_api_endpoints(self):
        """Testa as rotas Web do Flask e endpoints JSON de API."""
        seed_prospecting_queue(self.temp_db_path)
        with app.app_context():
            # GET /prospeccao
            resp = self.client.get("/prospeccao")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"Fila de Preparacao Comercial", resp.data.replace(b"\xc3\xa7\xc3\xa3", b"ca"))
            self.assertIn(b"Euphoria Est", resp.data)
            
            # GET /prospeccao com filtro
            resp_filtered = self.client.get("/prospeccao?status=Preparado")
            self.assertEqual(resp_filtered.status_code, 200)
            
            # GET /prospeccao/<lead_id>
            resp_ficha = self.client.get("/prospeccao/lead-euphoria-estetica-limeira")
            self.assertEqual(resp_ficha.status_code, 200)
            self.assertIn(b"Euphoria Est", resp_ficha.data)
            self.assertIn(b"Briefing Visual", resp_ficha.data)
            self.assertIn(b"Abrir WhatsApp", resp_ficha.data)
            
            # GET lead inexistente redireciona
            resp_404 = self.client.get("/prospeccao/lead-fantasma-inexistente")
            self.assertEqual(resp_404.status_code, 302)
            
            # POST /api/prospeccao/<lead_id>/status
            resp_status = self.client.post(
                "/api/prospeccao/lead-euphoria-estetica-limeira/status",
                data=json.dumps({"status": "Aprovado", "notas": "Revisado pela equipe"}),
                content_type="application/json"
            )
            self.assertEqual(resp_status.status_code, 200)
            json_data = resp_status.get_json()
            self.assertTrue(json_data["success"])
            self.assertEqual(json_data["status"], "Aprovado")
            
            # POST /api/prospeccao/<lead_id>/update
            resp_update = self.client.post(
                "/api/prospeccao/lead-euphoria-estetica-limeira/update",
                data=json.dumps({"mensagem_whatsapp": "Mensagem atualizada de teste"}),
                content_type="application/json"
            )
            self.assertEqual(resp_update.status_code, 200)
            json_update = resp_update.get_json()
            self.assertTrue(json_update["success"])
            
            # Rejeição de status inválido
            resp_invalid = self.client.post(
                "/api/prospeccao/lead-euphoria-estetica-limeira/status",
                data=json.dumps({"status": "StatusInvalidoQualquer"}),
                content_type="application/json"
            )
            self.assertEqual(resp_invalid.status_code, 400)

    def test_preview_studio_integration_seed_and_versions(self):
        """Verifica a geração automática das prévias para os 15 leads de Categoria A."""
        seed_prospecting_queue(self.temp_db_path)
        res = seed_category_a_previews(self.temp_db_path)
        self.assertEqual(res["total"], 15, "Devem existir prévias para todos os 15 leads")
        self.assertEqual(res["existing"], 15, "Todas as 15 prévias já foram semeadas")
        
        # Testar um lead de estética
        estetica_vers = get_lead_preview_versions("lead-euphoria-estetica-limeira", db_target=self.temp_db_path)
        self.assertGreaterEqual(len(estetica_vers), 1)
        v1_est = estetica_vers[0]
        self.assertEqual(v1_est["version"], 1)
        self.assertIn("Euphoria", v1_est["html"])
        self.assertEqual(v1_est["config"]["template"], "editorial")
        self.assertGreaterEqual(v1_est["validation"]["score"], 90)

        # Testar um lead de marcenaria (deve usar template portfolio)
        marcenaria_vers = get_lead_preview_versions("lead-marcenaria-sua-casa-contagem", db_target=self.temp_db_path)
        self.assertGreaterEqual(len(marcenaria_vers), 1)
        v1_mar = marcenaria_vers[0]
        self.assertEqual(v1_mar["config"]["template"], "portfolio")
        self.assertIn("Marcenaria Sua Casa", v1_mar["html"])

        # Testar um lead de pilates (deve usar template technical)
        pilates_vers = get_lead_preview_versions("lead-studio-camila-nascimento-bh", db_target=self.temp_db_path)
        self.assertGreaterEqual(len(pilates_vers), 1)
        v1_pil = pilates_vers[0]
        self.assertEqual(v1_pil["config"]["template"], "technical")
        self.assertIn("Camila Nascimento", v1_pil["html"])

    def test_preview_studio_custom_generation_and_versioning(self):
        """Testa geração de versões incrementais sem sobrescrever as anteriores."""
        seed_prospecting_queue(self.temp_db_path)
        lead_id = "lead-linear-moveis-palhoca"
        
        # Versão 1 já foi criada no seed
        vers_inicial = get_lead_preview_versions(lead_id, db_target=self.temp_db_path)
        self.assertEqual(len(vers_inicial), 1)
        self.assertEqual(vers_inicial[0]["version"], 1)
        
        # Gera versão 2 com customizações
        custom_headline = "Móveis Sob Medida de Alto Padrão em Palhoça e Grande Florianópolis"
        custom_cta = "Solicitar Projeto 3D no WhatsApp"
        p2 = generate_prospecting_preview(lead_id, overrides={
            "template": "portfolio",
            "headline": custom_headline,
            "cta": custom_cta,
            "primary": "#d97706"
        }, db_target=self.temp_db_path)
        self.assertEqual(p2["version"], 2)
        self.assertIn(custom_headline, p2["html"])
        self.assertIn(custom_cta, p2["html"])
        
        # Histórico deve conter ambas as versões (mais recente primeiro)
        vers = get_lead_preview_versions(lead_id, db_target=self.temp_db_path)
        self.assertEqual(len(vers), 2)
        self.assertEqual(vers[0]["version"], 2)
        self.assertEqual(vers[1]["version"], 1)

    def test_preview_studio_web_routes(self):
        """Testa endpoints web e API do Preview Studio para a prospecção."""
        seed_prospecting_queue(self.temp_db_path)
        lead_id = "lead-amabille-estetica-indaiatuba"
        
        with app.app_context():
            # GET /api/prospeccao/<lead_id>/previews
            resp_list = self.client.get(f"/api/prospeccao/{lead_id}/previews")
            self.assertEqual(resp_list.status_code, 200)
            data_list = resp_list.get_json()
            self.assertTrue(data_list["success"])
            self.assertGreaterEqual(len(data_list["previews"]), 1)
            initial_count = len(data_list["previews"])
            
            # POST /api/prospeccao/<lead_id>/preview/generate
            resp_gen = self.client.post(
                f"/api/prospeccao/{lead_id}/preview/generate",
                data=json.dumps({"headline": "Nova Headline Teste API"}),
                content_type="application/json"
            )
            self.assertEqual(resp_gen.status_code, 200)
            data_gen = resp_gen.get_json()
            self.assertTrue(data_gen["success"])
            self.assertGreaterEqual(data_gen["preview"]["version"], initial_count + 1)
            
            # GET /preview/<preview_id> (HTML do Preview Studio)
            preview_id = data_gen["preview"]["id"]
            resp_html = self.client.get(f"/preview/{preview_id}")
            self.assertEqual(resp_html.status_code, 200)
            self.assertIn(b"Nova Headline Teste API", resp_html.data)
            self.assertIn(b"Demonstra", resp_html.data.replace(b"\xc3\xa7\xc3\xa3", b"ca"))
            
            # GET /prospeccao/<lead_id> deve renderizar o iframe do preview
            resp_ficha = self.client.get(f"/prospeccao/{lead_id}")
            self.assertEqual(resp_ficha.status_code, 200)
            self.assertIn(f"/preview/{preview_id}".encode("utf-8"), resp_ficha.data)
            self.assertIn(b"id=\"preview-iframe\"", resp_ficha.data)



if __name__ == "__main__":
    unittest.main()
