import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest import mock

import app as application
from commercial_intelligence import (
    analyze_lead,
    build_generation_prompt,
    evaluate_pitches,
    generate_fallback_pitches,
    normalize_lead_context,
    plan_commercial_angle,
    recommend_contact_strategy,
    review_pitch,
)
from preview_studio import build_preview_config, render_preview_html
from lead_scoring import SCORE_VERSION, score_lead


application.app.config["TESTING"] = True


BUSINESS_CASES = (
    ("Ateliê Norte Arquitetura", "Arquitetos", "arquitetura"),
    ("Sorriso Centro", "Dentistas", "odontologia"),
    ("Pele Clara", "Clínica de estética", "estética"),
    ("Lima & Ramos", "Advogados", "advocacia"),
    ("Reforma Certa", "Empresa de reformas", "reformas"),
    ("Conta Simples", "Contadores", "contabilidade"),
    ("Eixo Projetos", "Escritório de engenharia", "engenharia"),
    ("Pronto Reparo", "Empresa de manutenção", "manutenção"),
    ("Mesa da Vila", "Restaurante", "gastronomia"),
    ("Apoio Local", "Prestadores de serviços locais", "Prestadores de serviços locais"),
)

TWENTY_BUSINESS_CASES = (
    ("Dra. Rosiene Silva de Brito", "Dentista"),
    ("Studio Belle Estética Avançada", "Clínica de estética"),
    ("Dr. Marcos Pereira Advocacia", "Advogado"),
    ("Traço Vivo Arquitetura Ltda", "Arquitetos"),
    ("Reforma Certa", "Empresa de reformas"),
    ("Conta Simples Contabilidade", "Contadores"),
    ("Eixo Projetos", "Escritório de engenharia"),
    ("Pronto Reparo 24 Horas", "Empresa de manutenção"),
    ("Mesa da Vila", "Restaurante"),
    ("Clínica Veterinária Amigo Fiel", "Veterinário"),
    ("Lar & Chave Negócios Imobiliários", "Imobiliária"),
    ("Sol Forte Energia", "Empresa de energia solar"),
    ("Ana Souza Psicologia Clínica", "Psicólogo"),
    ("Movimento Fisioterapia", "Fisioterapeuta"),
    ("Colégio Novo Horizonte", "Escola particular"),
    ("Academia Corpo Ativo", "Academia"),
    ("Hotel Serra Azul", "Hotel"),
    ("Clara Luz Fotografia", "Fotógrafo"),
    ("Auto Center Avenida", "Oficina mecânica"),
    ("Norte Gestão", "Consultoria empresarial"),
)


def sample_lead(name="Sorriso Centro", category="Dentistas"):
    return {
        "Nome": name,
        "Nicho": category,
        "Categoria Maps": category,
        "Bairro": "Campinas, SP",
        "Nota Maps": "4.7",
        "Qtd Avaliacoes": "32",
        "Telefone": "(19) 99999-9999",
        "E-mail Encontrado": "contato@example.com",
        "Instagram": "https://instagram.com/exemplo",
        "Link Inicial": "",
    }


class CommercialIntelligenceTests(unittest.TestCase):
    def test_mutating_routes_require_csrf_token_for_session_authentication(self):
        previous_testing = application.app.config["TESTING"]
        application.app.config["TESTING"] = False
        try:
            client = application.app.test_client()
            with client.session_transaction() as session:
                session["authenticated"] = True
                session["user"] = "teste"
                session["csrf_token"] = "known-token"
            rejected = client.post("/api/update_status", json={})
            accepted_by_csrf = client.post(
                "/api/update_status",
                json={},
                headers={"X-CSRF-Token": "known-token"},
            )
            self.assertEqual(403, rejected.status_code)
            self.assertEqual(400, accepted_by_csrf.status_code)
        finally:
            application.app.config["TESTING"] = previous_testing

    def test_login_rate_limit_tracks_and_clears_failures(self):
        client_key = "audit-test-client"
        application.clear_login_failures(client_key)
        for index in range(application.LOGIN_MAX_ATTEMPTS):
            self.assertEqual(index + 1, application.record_login_failure(client_key, now=1000 + index))
        self.assertEqual(application.LOGIN_MAX_ATTEMPTS, len(application.login_rate_state(client_key, now=1001)))
        application.clear_login_failures(client_key)
        self.assertEqual([], application.login_rate_state(client_key, now=1001))

    def test_pitch_must_present_the_seller_and_make_an_explicit_site_offer(self):
        analysis = analyze_lead(sample_lead())
        generic = (
            "Olá, tudo bem? Muita gente escolhe onde marcar uma consulta depois de entender os tratamentos. "
            "Um site bem organizado pode explicar essas etapas e conduzir o paciente ao agendamento. "
            "Se fizer sentido, posso te mandar três ideias práticas para essa página?"
        )
        review = review_pitch(generic, analysis, "consultiva")
        self.assertFalse(review["approved"])
        self.assertIn("não apresenta quem oferece o serviço", review["issues"])
        self.assertIn("não faz uma proposta comercial explícita de site", review["issues"])

    def test_bad_legacy_pitch_is_rejected_by_quality_review(self):
        analysis = analyze_lead(sample_lead("Dra. Rosiene Silva de Brito", "Dentista"))
        legacy = (
            "Oi, equipe da Dra. Rosiene Silva de Brito. Quem compara opções de Dentista costuma precisar "
            "entender o serviço e o próximo passo antes de entrar em contato. No perfil público consultado, "
            "não identifiquei um site próprio no perfil do Google consultado. A oportunidade mais clara é "
            "organizar tratamentos, orientações iniciais e o caminho para agendamento. Um site objetivo pode "
            "organizar essas respostas e levar a pessoa interessada ao canal que vocês já usam. Posso "
            "compartilhar a estrutura que recomendaria para avaliação?"
        )
        review = review_pitch(legacy, analysis, "consultiva")
        self.assertFalse(review["approved"])
        self.assertGreaterEqual(len(review["issues"]), 4)

    def test_normalization_and_plan_do_not_expose_raw_google_language(self):
        context = normalize_lead_context(sample_lead("Dra. Rosiene Silva de Brito", "Dentista"))
        plan = plan_commercial_angle(context)
        self.assertEqual("odontologia", context["segment"])
        self.assertNotEqual(context["raw_category"], context["commercial_category"])
        self.assertNotIn("Rosiene Silva de Brito", context["salutation"])
        self.assertIn("agendamento", plan["benefit"])
        self.assertNotIn("perfil público", json.dumps(plan, ensure_ascii=False).casefold())

    def test_fast_search_pitch_does_not_wait_for_external_ai(self):
        with mock.patch.object(application, "generate_text") as generator:
            result = application.gerar_copy_profissional(
                sample_lead(), {"gemini_api_key": "configured"}, use_external_ai=False
            )
        generator.assert_not_called()
        self.assertTrue(result["qualidade"]["approved"])
        self.assertIn("site", result["mensagem"].casefold())

    def test_deep_contact_search_only_uses_web_email_lookup_when_requested(self):
        with mock.patch.object(application, "buscar_email_web", return_value="contato@empresa.com") as lookup:
            without_lookup = application.cacar_dados_profundos(
                None, "", nome="Empresa Teste", bairro="Campinas", buscar_email_externo=False
            )
            with_lookup = application.cacar_dados_profundos(
                None, "", nome="Empresa Teste", bairro="Campinas", buscar_email_externo=True
            )
        self.assertEqual("", without_lookup["email"])
        self.assertEqual("contato@empresa.com", with_lookup["email"])
        lookup.assert_called_once()

    def test_health_whatsapp_defaults_to_reception_forwarding_message(self):
        lead = sample_lead("Sorriso Centro", "Dentistas")
        strategy = recommend_contact_strategy(lead)
        analysis = analyze_lead(lead)
        message = generate_fallback_pitches(analysis)["recepcao"]
        self.assertEqual("recepcao", strategy["recommended_mode"])
        self.assertIn("Recepção/agendamento", strategy["label"])
        self.assertIn("encaminhar", message.casefold())
        self.assertIn("melhor contato", message.casefold())
        self.assertIn("proposta de site", message.casefold())
        self.assertNotIn(lead["Nome"], message)

    def test_general_business_keeps_consultative_mode_and_email_only_uses_email(self):
        architecture = sample_lead("Ateliê Norte", "Arquitetos")
        email_only = sample_lead("Sorriso Centro", "Dentistas")
        email_only["Telefone"] = ""
        self.assertEqual("consultiva", recommend_contact_strategy(architecture)["recommended_mode"])
        self.assertEqual("email", recommend_contact_strategy(email_only)["recommended_mode"])

    def test_score_v2_is_transparent_and_keeps_lower_potential_leads(self):
        priority = score_lead(sample_lead(), has_own_site=False)
        exploration = score_lead({"Nome": "Negócio sem dados"}, has_own_site=True)
        self.assertEqual(SCORE_VERSION, priority["version"])
        self.assertEqual(100, sum(priority["weights"].values()))
        self.assertLessEqual(priority["score"], 100)
        self.assertEqual("Prioridade", priority["range"])
        self.assertEqual("Exploração", exploration["range"])
        self.assertEqual(5, len(priority["dimensions"]))
        self.assertIn("não probabilidade", priority["disclaimer"])

    def test_site_opportunity_changes_need_score_without_discarding_the_lead(self):
        weak_site = sample_lead()
        weak_site["Oportunidade do Site"] = "Site com oportunidade de melhoria"
        healthy_site = sample_lead()
        healthy_site["Oportunidade do Site"] = "Site encontrado — sem sinal claro"
        weak_score = score_lead(weak_site, has_own_site=True)
        healthy_score = score_lead(healthy_site, has_own_site=True)
        self.assertGreater(weak_score["score"], healthy_score["score"])
        self.assertIn("sinais objetivos", weak_score["dimensions"]["necessidade_digital"]["evidence"])

    def test_site_audit_uses_only_objective_signals(self):
        missing = application.assess_site_opportunity("")
        weak = application.assess_site_opportunity(
            "http://example.com", "", "", "Página inicial curta"
        )
        healthy = application.assess_site_opportunity(
            "https://example.com",
            "Clínica Exemplo",
            "Conheça os tratamentos e fale com nossa equipe.",
            "Informações sobre tratamentos, equipe, contato e agendamento online.",
        )
        self.assertEqual("Construção de site", missing["status"])
        self.assertEqual("Site com oportunidade de melhoria", weak["status"])
        self.assertEqual("Site encontrado — sem sinal claro", healthy["status"])

    def test_site_audit_blocks_internal_and_unsafe_urls(self):
        with self.assertRaises(ValueError):
            application.validar_url_publica("file:///etc/passwd")
        with mock.patch.object(application.socket, "getaddrinfo", return_value=[
            (application.socket.AF_INET, application.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]):
            with self.assertRaises(ValueError):
                application.validar_url_publica("http://internal.example")
        with mock.patch.object(application.socket, "getaddrinfo", return_value=[
            (application.socket.AF_INET, application.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ]):
            self.assertEqual("https://public.example/page", application.validar_url_publica("https://public.example/page"))

    def test_site_filter_defaults_to_only_businesses_without_a_site(self):
        default = application.normalizar_modo_filtro_site({})
        weak_sites = application.normalizar_modo_filtro_site({"site_filter_mode": "without_and_weak"})
        all_businesses = application.normalizar_modo_filtro_site({"site_filter_mode": "all"})
        self.assertEqual("only_without_site", default["site_filter_mode"])
        self.assertTrue(default["strict_no_socials"])
        self.assertFalse(default["include_site_opportunities"])
        self.assertTrue(weak_sites["strict_no_socials"])
        self.assertTrue(weak_sites["include_site_opportunities"])
        self.assertFalse(all_businesses["strict_no_socials"])

    def test_whatsapp_requires_a_plausible_mobile_number(self):
        self.assertTrue(application.eh_celular_valido(application.extrair_apenas_numeros("(19) 99999-1234")))
        self.assertFalse(application.eh_celular_valido(application.extrair_apenas_numeros("(19) 3333-1234")))
        self.assertFalse(application.eh_celular_valido("5509999999999"))
        self.assertFalse(application.eh_celular_valido("5519999999999"))
        self.assertTrue(application.eh_celular_valido("13055550100"))

    def test_twenty_business_types_generate_distinct_natural_approved_pitches(self):
        opportunities = set()
        personalized = set()
        forbidden = (
            "perfil público consultado",
            "oportunidade mais clara",
            "estrutura que recomendaria",
        )
        for name, category in TWENTY_BUSINESS_CASES:
            with self.subTest(category=category):
                analysis = analyze_lead(sample_lead(name, category))
                pitches = generate_fallback_pitches(analysis)
                quality = evaluate_pitches(pitches, analysis)
                self.assertTrue(quality["approved"], quality["reasons"])
                self.assertNotIn(name, pitches["consultiva"])
                self.assertNotIn("responsável pelo comercial", pitches["consultiva"].casefold())
                self.assertNotIn("prévia", pitches["consultiva"].casefold())
                self.assertFalse(any(term in pitches["consultiva"].casefold() for term in forbidden))
                self.assertTrue(
                    any(term in pitches["consultiva"].casefold() for term in ("desenvolvo sites", "criação de sites", "criamos sites")),
                    pitches["consultiva"],
                )
                self.assertIn("site próprio vinculado", pitches["consultiva"].casefold())
                self.assertNotIn("se fizer sentido", pitches["consultiva"].casefold())
                self.assertNotIn("três ideias práticas", pitches["consultiva"].casefold())
                self.assertFalse(
                    any(error in " ".join(pitches.values()).casefold() for error in ("uma atendimento", "uma escritório", "uma restaurante")),
                    pitches,
                )
                self.assertIn("site", pitches["recepcao"].casefold())
                self.assertTrue(pitches["email"].casefold().startswith(("assunto:", "subject:")))
                opportunities.add(analysis["opportunity"])
                personalized.add(pitches["personalizada"])
        self.assertGreaterEqual(len(opportunities), 14)
        self.assertEqual(20, len(personalized))

    def test_each_pitch_mode_uses_a_different_ending(self):
        analysis = analyze_lead(sample_lead())
        pitches = generate_fallback_pitches(analysis)
        endings = {mode: text.rstrip().split(".")[-1].strip().casefold() for mode, text in pitches.items()}
        self.assertEqual(len(endings), len(set(endings.values())))

    def test_ai_response_is_rejected_then_retried_with_review_feedback(self):
        lead = sample_lead("Dra. Rosiene Silva de Brito", "Dentista")
        analysis = analyze_lead(lead)
        approved = generate_fallback_pitches(analysis)
        rejected = dict(approved)
        rejected["consultiva"] = (
            "Oi, equipe da Dra. Rosiene Silva de Brito. No perfil público consultado, a oportunidade mais clara "
            "é ter um site para organizar o atendimento. Posso compartilhar a estrutura que recomendaria para "
            "avaliação com a pessoa responsável por essa decisão dentro da clínica?"
        )
        responses = [
            json.dumps({"versoes": rejected}, ensure_ascii=False),
            json.dumps({"versoes": approved}, ensure_ascii=False),
        ]
        with mock.patch.object(application, "generate_text", side_effect=responses) as generator:
            result = application.gerar_copy_profissional(lead, {"gemini_api_key": "test-key"})
        self.assertTrue(result["gerada_por_ia"])
        self.assertEqual(2, generator.call_count)
        self.assertIn("versão anterior foi rejeitada", generator.call_args_list[1].args[2])
        self.assertNotIn("perfil público consultado", result["mensagem"].casefold())

    def test_configured_seller_identity_is_used_in_the_pitch(self):
        result = application.gerar_copy_profissional(
            sample_lead(),
            {
                "vendedor_nome": "Pedro Henrique",
                "agencia_nome": "PH Digital",
                "posicionamento_comercial": "Sites comerciais claros e rápidos",
                "prova_comercial": "Case documentado disponível para avaliação",
                "portfolio_url": "https://phdigital.example",
            },
        )
        self.assertIn("Sou Pedro, da PH Digital", result["mensagem"])
        self.assertIn("desenvolvo sites", result["mensagem"].casefold())
        self.assertIn("minha proposta", result["mensagem"].casefold())
        prompt = build_generation_prompt(result["inteligencia"], ["consultiva"])
        self.assertIn("Sites comerciais claros e rápidos", prompt)
        self.assertIn("Case documentado disponível", prompt)

    def test_international_fallback_remains_approved(self):
        result = application.gerar_copy_profissional(sample_lead(), {}, is_intl=True)
        self.assertTrue(result["qualidade"]["approved"], result["qualidade"]["reasons"])
        self.assertTrue(result["versoes"]["email"].startswith("Subject:"))

    def test_preview_pitch_only_exists_after_real_preview(self):
        analysis = analyze_lead(sample_lead(), preview_available=False)
        self.assertNotIn("previa_visual", generate_fallback_pitches(analysis))
        analysis = analyze_lead(sample_lead(), preview_available=True)
        pitches = generate_fallback_pitches(analysis)
        self.assertIn("previa_visual", pitches)
        self.assertTrue(evaluate_pitches(pitches, analysis, require_preview=True)["approved"])


class PreviewStudioTests(unittest.TestCase):
    def test_html_is_responsive_and_has_no_external_resources_or_scripts(self):
        config = build_preview_config(sample_lead())
        html = render_preview_html(config)
        self.assertIn("Demonstração conceitual não oficial", html)
        self.assertIn("@media(max-width:760px)", html)
        self.assertNotIn("<script", html.casefold())
        self.assertNotIn("src=\"http", html.casefold())

    def test_preview_direction_changes_by_segment_and_accepts_real_assets(self):
        dentist = build_preview_config(sample_lead("Clínica Sorriso", "Dentistas"))
        lawyer = build_preview_config(sample_lead("Lima Advocacia", "Advogados"))
        image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
        portfolio = build_preview_config(
            sample_lead("Traço Vivo", "Arquitetos"),
            {"hero_image": image, "brand_logo": image},
        )
        self.assertEqual("care", dentist["template"])
        self.assertEqual("authority", lawyer["template"])
        self.assertEqual("portfolio", portfolio["template"])
        self.assertNotEqual(dentist["headline"], lawyer["headline"])
        html = render_preview_html(portfolio)
        self.assertIn("Campinas, SP", html)
        self.assertIn(image, html)
        rejected = build_preview_config(sample_lead(), {"hero_image": "https://example.com/photo.jpg"})
        self.assertEqual("", rejected["hero_image"])

    def test_generate_preview_route_persists_version_and_exports_real_png(self):
        old_db = application.DB_NAME
        old_preview_dir = application.PREVIEW_DIR
        old_backup_dir = application.BACKUP_DIR
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "test.db")
            application.PREVIEW_DIR = os.path.join(temp_dir, "previews")
            application.BACKUP_DIR = os.path.join(temp_dir, "backups")
            application.load_config = lambda: {}
            try:
                application.init_db()
                lead = sample_lead()
                lead.update({
                    "WhatsApp Link": "https://wa.me/5519999999999",
                    "Google Maps": "https://maps.google.com/example",
                    "Potencial": 80,
                    "Motivo Potencial": "sem site próprio, reputação alta",
                    "Faixa Potencial": "Prioridade",
                })
                self.assertTrue(application.save_lead_db(lead, "test-place"))
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                regenerated = client.post("/api/leads/test-place/regenerate-pitches")
                self.assertEqual(200, regenerated.status_code, regenerated.get_data(as_text=True))
                regenerated_data = regenerated.get_json()
                self.assertTrue(regenerated_data["success"])
                self.assertTrue(regenerated_data["qualidade"]["approved"], regenerated_data["qualidade"]["reasons"])
                self.assertNotIn("perfil público consultado", regenerated_data["versoes"]["consultiva"].casefold())

                response = client.post("/api/leads/test-place/previews", json={"headline": "Um sorriso começa com informação clara"})
                self.assertEqual(200, response.status_code, response.get_data(as_text=True))
                result = response.get_json()
                self.assertTrue(result["success"])
                self.assertFalse(result["screenshot_ready"])
                self.assertTrue(result["png_deferred"])
                png_response = client.get(result["png_url"])
                self.assertEqual(200, png_response.status_code)
                self.assertTrue(png_response.data.startswith(b"\x89PNG\r\n\x1a\n"))
                png_response.close()
                conn = sqlite3.connect(application.DB_NAME)
                row = conn.execute("SELECT version, config_json, html_content, screenshot_path FROM preview_versions").fetchone()
                conn.close()
                self.assertEqual(1, row[0])
                self.assertEqual("Um sorriso começa com informação clara", json.loads(row[1])["headline"])
                self.assertIn("Demonstração conceitual não oficial", row[2])
                self.assertTrue(os.path.exists(row[3]))

                contacted = client.post("/api/leads/test-place/contacted", json={
                    "channel": "WhatsApp",
                    "pitch_mode": "consultiva",
                    "message": regenerated_data["versoes"]["consultiva"],
                })
                self.assertEqual(200, contacted.status_code, contacted.get_data(as_text=True))
                contacted_data = contacted.get_json()
                self.assertEqual("Contatado", contacted_data["status"])
                self.assertIn("T", contacted_data["next_action_at"])
                conn = sqlite3.connect(application.DB_NAME)
                contact_state = conn.execute(
                    "SELECT status, contact_count, last_contact_channel, last_pitch_mode, next_action_at FROM leads WHERE place_id = 'test-place'"
                ).fetchone()
                contact_interaction = conn.execute(
                    "SELECT interaction_type, channel, content FROM lead_interactions WHERE place_id = 'test-place' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                conn.close()
                self.assertEqual(("Contatado", 1, "WhatsApp", "consultiva"), contact_state[:4])
                self.assertTrue(contact_state[4])
                self.assertEqual("abordagem", contact_interaction[0])
                self.assertEqual("WhatsApp", contact_interaction[1])
                self.assertIn("site", contact_interaction[2].casefold())

                follow_up = client.post("/api/leads/test-place/follow-up", json={
                    "response": "Gostei da ideia, pode enviar a demonstração.",
                    "channel": "WhatsApp",
                    "sentiment": "interessado",
                    "next_action_at": "2026-10-30T10:00",
                })
                self.assertEqual(200, follow_up.status_code)
                follow_up_data = follow_up.get_json()
                self.assertEqual("Interessado", follow_up_data["status"])
                self.assertIn("prévia visual", follow_up_data["next_action"])

                blocked = client.post("/api/leads/test-place/do-not-contact", json={
                    "blocked": True,
                    "reason": "Solicitou encerramento do contato",
                })
                self.assertEqual(200, blocked.status_code)
                blocked_contact = client.post("/api/leads/test-place/contacted", json={
                    "channel": "WhatsApp",
                    "message": "Nova tentativa de contato",
                })
                self.assertEqual(409, blocked_contact.status_code)
                detail = client.get("/leads/test-place")
                self.assertEqual(200, detail.status_code)
                detail_html = detail.get_data(as_text=True)
                self.assertIn("Contato bloqueado", detail_html)
                self.assertNotIn("Abrir WhatsApp", detail_html)

                conn = sqlite3.connect(application.DB_NAME)
                lead_state = conn.execute("SELECT do_not_contact, status, next_action FROM leads WHERE place_id = 'test-place'").fetchone()
                interaction_count = conn.execute("SELECT COUNT(*) FROM lead_interactions WHERE place_id = 'test-place'").fetchone()[0]
                conn.close()
                self.assertEqual(1, lead_state[0])
                self.assertEqual("Perdido", lead_state[1])
                self.assertTrue(lead_state[2])
                self.assertEqual(3, interaction_count)

                health = client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertEqual("ok", health.get_json()["status"])
                self.assertEqual("2026.10.29-crm-whatsapp-v2", health.get_json()["commercial_release"])
                self.assertEqual("4.1", health.get_json()["pitch_pipeline_version"])

                stage_change = client.post("/api/update_status", json={"place_id": "test-place", "status": "Proposta enviada"})
                self.assertEqual(200, stage_change.status_code)
                dashboard = client.get("/estatisticas")
                self.assertEqual(200, dashboard.status_code)
                self.assertIn("Taxa de proposta", dashboard.get_data(as_text=True))

                cleared = client.post("/api/limpar_crm")
                self.assertEqual(200, cleared.status_code)
                backup_path = os.path.join(application.BACKUP_DIR, cleared.get_json()["backup"])
                self.assertTrue(os.path.isfile(backup_path))
                with zipfile.ZipFile(backup_path) as archive:
                    self.assertIn("gestao_leads.db", archive.namelist())
                conn = sqlite3.connect(application.DB_NAME)
                self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0])
                self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM preview_versions").fetchone()[0])
                self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM lead_interactions").fetchone()[0])
                conn.close()
                self.assertFalse(os.path.exists(row[3]))
            finally:
                application.DB_NAME = old_db
                application.PREVIEW_DIR = old_preview_dir
                application.BACKUP_DIR = old_backup_dir
                application.load_config = old_load_config

    def test_search_creates_a_traceable_campaign(self):
        old_db = application.DB_NAME
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "campaigns.db")
            application.load_config = lambda: {}
            try:
                application.init_db()
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                with mock.patch.object(application, "ler_status", return_value={"rodando": False}), \
                     mock.patch.object(application, "ler_status_investigacao", return_value={"rodando": False}), \
                     mock.patch.object(application, "atualizar_status"), \
                     mock.patch.object(application.threading, "Thread") as thread:
                    response = client.post("/api/search", json={
                        "campaign_name": "Dentistas de Campinas",
                        "mercado": "br",
                        "nichos": "Dentista",
                        "bairros": "Campinas - SP",
                        "site_filter_mode": "only_without_site",
                    })
                self.assertEqual(200, response.status_code)
                data = response.get_json()
                self.assertTrue(data["success"])
                self.assertTrue(data["run_id"])
                thread.return_value.start.assert_called_once()
                worker_payload = thread.call_args.kwargs["args"][0]
                self.assertTrue(worker_payload["strict_no_socials"])
                self.assertFalse(worker_payload["include_site_opportunities"])
                conn = sqlite3.connect(application.DB_NAME)
                run = conn.execute("SELECT name, market, status FROM search_runs WHERE run_id = ?", (data["run_id"],)).fetchone()
                conn.close()
                self.assertEqual(("Dentistas de Campinas", "br", "running"), run)
                application.finish_search_run(data["run_id"], "completed", {"salvos": 3})
                dashboard = client.get("/estatisticas")
                self.assertIn("Dentistas de Campinas", dashboard.get_data(as_text=True))
            finally:
                application.DB_NAME = old_db
                application.load_config = old_load_config

    def test_site_audit_preserves_weak_sites_and_discards_only_sites_without_signal(self):
        old_db = application.DB_NAME
        old_status_file = application.SITE_AUDIT_STATUS_FILE
        old_hunter = application.cacar_dados_profundos
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "site-audit.db")
            application.SITE_AUDIT_STATUS_FILE = os.path.join(temp_dir, "site-audit-status.json")
            try:
                application.init_db()
                weak = sample_lead("Site Fraco", "Dentistas")
                weak["Link Inicial"] = "http://weak.example"
                healthy = sample_lead("Site Saudável", "Dentistas")
                healthy["Link Inicial"] = "https://healthy.example"
                self.assertTrue(application.save_lead_db(weak, "weak-site"))
                self.assertTrue(application.save_lead_db(healthy, "healthy-site"))

                def fake_hunter(context, url, nome="", bairro=""):
                    if "weak" in url:
                        return {"email": "", "instagram": "", "facebook": "", "linkedin": "", "titulo_site": "", "descricao_site": "", "contexto_site": "Página curta"}
                    return {"email": "", "instagram": "", "facebook": "", "linkedin": "", "titulo_site": "Clínica", "descricao_site": "Tratamentos e contato com a equipe.", "contexto_site": "Conheça tratamentos, equipe e faça seu agendamento pelo formulário de contato."}

                application.cacar_dados_profundos = fake_hunter
                application.worker_auditar_sites_existentes()
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                response = client.post("/api/descartar_com_site")
                self.assertEqual(200, response.status_code)
                self.assertEqual(1, response.get_json()["descartados"])
                conn = sqlite3.connect(application.DB_NAME)
                states = dict(conn.execute("SELECT place_id, status FROM leads").fetchall())
                opportunities = dict(conn.execute("SELECT place_id, site_opportunity_status FROM leads").fetchall())
                conn.close()
                self.assertNotEqual("Descartado", states["weak-site"])
                self.assertEqual("Descartado", states["healthy-site"])
                self.assertEqual("Site com oportunidade de melhoria", opportunities["weak-site"])
                self.assertEqual("Site encontrado — sem sinal claro", opportunities["healthy-site"])
            finally:
                application.DB_NAME = old_db
                application.SITE_AUDIT_STATUS_FILE = old_status_file
                application.cacar_dados_profundos = old_hunter

    def test_crm_paginates_large_lead_lists(self):
        old_db = application.DB_NAME
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "pagination.db")
            application.load_config = lambda: {}
            try:
                application.init_db()
                for index in range(45):
                    lead = sample_lead(f"Empresa {index:02d}", "Dentistas")
                    self.assertTrue(application.save_lead_db(lead, f"lead-{index:02d}"))
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                first_page = client.get("/crm").get_data(as_text=True)
                second_page = client.get("/crm?page=2").get_data(as_text=True)
                self.assertIn("Página <strong class=\"text-white\">1</strong> de 3", first_page)
                self.assertIn("Página <strong class=\"text-white\">2</strong> de 3", second_page)
                self.assertEqual(40, first_page.count('class="lead-item'))
                self.assertEqual(40, second_page.count('class="lead-item'))
            finally:
                application.DB_NAME = old_db
                application.load_config = old_load_config

    def test_crm_filters_are_server_side_and_survive_pagination(self):
        old_db = application.DB_NAME
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "filtered-pagination.db")
            application.load_config = lambda: {}
            try:
                application.init_db()
                for index in range(45):
                    lead = sample_lead(f"Empresa {index:02d}", "Academia")
                    self.assertTrue(application.save_lead_db(lead, f"filtered-{index:02d}"))
                connection = sqlite3.connect(application.DB_NAME)
                for index in range(45):
                    if index < 25:
                        connection.execute(
                            """UPDATE leads SET status = 'Mensagem preparada',
                                      site_opportunity_status = 'Construção de site'
                               WHERE place_id = ?""",
                            (f"filtered-{index:02d}",),
                        )
                    else:
                        connection.execute(
                            """UPDATE leads SET status = 'Novo',
                                      site_opportunity_status = 'Site encontrado — sem sinal claro'
                               WHERE place_id = ?""",
                            (f"filtered-{index:02d}",),
                        )
                connection.commit()
                connection.close()
                client = application.app.test_client()
                with client.session_transaction() as session:
                    session["authenticated"] = True
                    session["user"] = "teste"
                query = "status=Mensagem+preparada&site=Constru%C3%A7%C3%A3o+de+site"
                first_page = client.get(f"/crm?{query}").get_data(as_text=True)
                second_page = client.get(f"/crm?page=2&{query}").get_data(as_text=True)
                self.assertIn('value="Mensagem preparada" selected', first_page)
                self.assertIn('value="Construção de site" selected', first_page)
                self.assertIn("Página <strong class=\"text-white\">1</strong> de 2", first_page)
                self.assertIn("Página <strong class=\"text-white\">2</strong> de 2", second_page)
                self.assertEqual(40, first_page.count('class="lead-item'))
                self.assertEqual(10, second_page.count('class="lead-item'))
                self.assertIn("status=Mensagem+preparada", first_page)
                self.assertIn("site=Constru%C3%A7%C3%A3o+de+site", first_page)
            finally:
                application.DB_NAME = old_db
                application.load_config = old_load_config

    def test_invalid_existing_whatsapp_links_are_removed(self):
        old_db = application.DB_NAME
        old_load_config = application.load_config
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DB_NAME = os.path.join(temp_dir, "whatsapp-cleanup.db")
            application.load_config = lambda: {}
            try:
                application.init_db()
                landline = sample_lead("Telefone Fixo", "Contabilidade")
                landline["Telefone"] = "(19) 3333-1234"
                landline["WhatsApp Link"] = "https://wa.me/551933331234"
                mobile = sample_lead("Celular Válido", "Academia")
                mobile["Telefone"] = "(19) 99876-1234"
                mobile["WhatsApp Link"] = "https://wa.me/5519999991234"
                self.assertTrue(application.save_lead_db(landline, "landline"))
                self.assertTrue(application.save_lead_db(mobile, "mobile"))
                self.assertEqual(1, application.remover_whatsapps_invalidos_existentes())
                connection = sqlite3.connect(application.DB_NAME)
                links = dict(connection.execute("SELECT place_id, whatsapp_link FROM leads").fetchall())
                connection.close()
                self.assertEqual("", links["landline"])
                self.assertTrue(links["mobile"].startswith("https://wa.me/"))
            finally:
                application.DB_NAME = old_db
                application.load_config = old_load_config


if __name__ == "__main__":
    unittest.main()
