import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

from preview_studio import (
    build_preview_config,
    render_preview_html,
    validate_preview_html,
    safe_color,
)

DB_NAME = "gestao_leads.db"

STATUS_PENDENTE = "Pendente"
STATUS_PREPARADO = "Preparado"
STATUS_APROVADO = "Aprovado"
STATUS_ENVIADO = "Enviado"
STATUS_RESPONDIDO = "Respondido"

VALID_STATUSES = (
    STATUS_PENDENTE,
    STATUS_PREPARADO,
    STATUS_APROVADO,
    STATUS_ENVIADO,
    STATUS_RESPONDIDO,
)


def get_db_connection(target=DB_NAME):
    if isinstance(target, sqlite3.Connection):
        try:
            target.row_factory = sqlite3.Row
        except Exception:
            pass
        return target, False
    conn = sqlite3.connect(target or DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn, True


def _row_to_dict(row, cursor=None):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    if cursor and cursor.description:
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    return dict(row)


def init_prospecting_schema(db_target=DB_NAME):
    """Cria a tabela de preparação e fila de prospecção comercial se não existir."""
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS commercial_prospecting_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            categoria TEXT,
            nicho TEXT,
            cidade TEXT,
            bairro TEXT,
            endereco TEXT,
            responsavel TEXT,
            telefone TEXT,
            whatsapp_link TEXT,
            canal_atual TEXT,
            website TEXT,
            rating REAL DEFAULT 0.0,
            reviews INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Preparado',
            oportunidade_digital TEXT,
            proposta_json TEXT,
            mensagem_whatsapp TEXT,
            briefing_visual_json TEXT,
            evidencias_json TEXT,
            notas_operador TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            sent_at TIMESTAMP,
            responded_at TIMESTAMP
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prospecting_status ON commercial_prospecting_queue(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prospecting_lead_id ON commercial_prospecting_queue(lead_id)")

    # Migração idempotente para colunas da abordagem em 2 etapas
    for col, tipo in [
        ("mensagem_etapa1", "TEXT"),
        ("mensagem_etapa2", "TEXT"),
        ("variacoes_etapa1_json", "TEXT DEFAULT '[]'"),
        ("etapa_ativa", "INTEGER DEFAULT 1"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE commercial_prospecting_queue ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass

    # Garante a existência da tabela preview_versions para versionamento histórico de layouts
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS preview_versions
        (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL, version INTEGER NOT NULL,
         config_json TEXT NOT NULL, html_content TEXT NOT NULL, screenshot_path TEXT,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         UNIQUE(place_id, version))"""
    )
    for col, tipo in [
        ("public_token", "TEXT"), ("mobile_screenshot_path", "TEXT"),
        ("share_screenshot_path", "TEXT"), ("status", "TEXT DEFAULT 'generated'"),
        ("approval_status", "TEXT DEFAULT 'draft'"), ("validation_json", "TEXT DEFAULT '{}'"),
        ("research_json", "TEXT DEFAULT '{}'"), ("art_direction_json", "TEXT DEFAULT '{}'"),
        ("message_text", "TEXT"), ("approved_at", "TIMESTAMP"),
        ("expires_at", "TIMESTAMP"), ("published_at", "TIMESTAMP"),
        ("sent_at", "TIMESTAMP"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE preview_versions ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_preview_public_token ON preview_versions(public_token)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_preview_place_version ON preview_versions(place_id, version DESC)")

    conn.commit()
    if should_close:
        conn.close()


def get_category_a_leads_data():
    """Retorna os dados auditados e factuais dos 15 leads da Categoria A para preparação comercial."""
    return [
        {
            "lead_id": "lead-euphoria-estetica-limeira",
            "nome": "Euphoria Estética",
            "responsavel": "Dra. Francielle Leite (Enfermeira Esteta)",
            "categoria": "Centro de saúde e beleza",
            "nicho": "Estética Avançada & Harmonização",
            "cidade": "Limeira - SP",
            "bairro": "São Cristóvão",
            "endereco": "Rua Ceará, 306, Sala 2 - São Cristóvão, Limeira - SP",
            "telefone": "(19) 99496-6306",
            "canal_atual": "Página gratuita no Canva (canva.site) e Instagram @euphoria_estetica_",
            "website": "https://www.instagram.com/euphoria_estetica_/",
            "rating": 5.0,
            "reviews": 10,
            "score": 78,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Utiliza página amadora gratuita no Canva (canva.site) para promover procedimentos de alto valor (hidrolipoclasia/lipo sem corte e harmonização). O link gratuito do Canva gera desconfiança para tratamentos invasivos e reduz drasticamente a conversão de pacientes particulares.",
            "proposta": {
                "tipo_solucao": "Landing Page Clínica de Alta Conversão (.com.br)",
                "headline": "Realce sua beleza com procedimentos seguros e resultados naturais em Limeira",
                "secoes": [
                    "Hero com apresentação da Dra. Francielle Leite e botão direto para avaliação",
                    "Especialidades em destaque: Hidrolipoclasia não aspirativa (lipo sem corte) e Harmonização facial",
                    "Galeria de transformações e casos clínicos autorizados",
                    "Diferenciais de biossegurança e acolhimento personalizado",
                    "Localização privilegiada na Rua Ceará com mapa interativo",
                    "Chamada para ação: Agendamento prioritário via WhatsApp"
                ],
                "diferencial_conversao": "Substituição do domínio amador do Canva por um site profissional próprio (.com.br), transmitindo autoridade médica imediata e aumentando a taxa de fechamento de pacientes particulares."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Francielle ou com a responsável pelo atendimento da Euphoria Estética em Limeira?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Francielle ou com a responsável pelo atendimento da Euphoria Estética em Limeira?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Francielle ou com a responsável pelo atendimento da Euphoria Estética em Limeira?",
                "Olá, bom dia! É da clínica Euphoria Estética na Rua Ceará, gostaria de falar com a responsável pelos agendamentos?",
                "Olá, tudo bem? Quem responde pela parte de novos atendimentos da Euphoria Estética por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Analisamos a presença online de clínicas de estética em Limeira e notamos a qualidade dos procedimentos da Euphoria, mas que a divulgação hoje é feita por um link do Canva. Para procedimentos de estética avançada e harmonização, um site institucional próprio (.com.br) transmite muito mais segurança e autoridade para atrair pacientes particulares. Preparamos uma demonstração visual de página clínica para a Euphoria. Posso lhe enviar o link da prévia para você avaliar sem compromisso?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#B76E79",
                    "secundaria": "#F7F4F0",
                    "acento": "#D4AF37",
                    "texto": "#2C2C2C"
                },
                "nomes_cores": "Rose Gold, Bege Nude, Dourado Champanhe e Grafite Escuro",
                "tipografia": "Playfair Display (títulos elegantes) e Inter (corpo limpo e legível)",
                "tom_voz": "Sofisticado, seguro, acolhedor e focado em bem-estar e autoestima",
                "layout_referencia": "Clínica Boutique / Estética Médica Premium"
            },
            "evidencias": [
                {"fonte": "Localização Física", "detalhe": "Rua Ceará, 306, Sala 2, Bairro São Cristóvão, Limeira - SP", "url": "https://maps.google.com/?q=Rua+Ceara+306+Limeira"},
                {"fonte": "Canal Digital Auditado", "detalhe": "Página gratuita ativa em canva.site", "url": "https://euphoriaestetica.my.canva.site/"},
                {"fonte": "Instagram Profissional", "detalhe": "@euphoria_estetica_ (feed ativo com procedimentos)", "url": "https://www.instagram.com/euphoria_estetica_/"},
                {"fonte": "Responsável Técnica", "detalhe": "Dra. Francielle Leite - Pós-graduada em Estética e Harmonização Orofacial", "url": ""}
            ]
        },
        {
            "lead_id": "lead-dra-rafaelle-lucia-indaiatuba",
            "nome": "Dra Rafaelle Lucia - Biomédica Esteta",
            "responsavel": "Dra. Rafaelle Lucia (Biomédica Esteta)",
            "categoria": "Esteticista / Biomedicina Estética",
            "nicho": "Estética Integrativa Avançada",
            "cidade": "Indaiatuba - SP",
            "bairro": "Centro",
            "endereco": "Rua Humaitá, 594, Sala 6 – Centro, Indaiatuba - SP",
            "telefone": "(19) 99220-7345",
            "canal_atual": "Link direto de WhatsApp (api.whatsapp.com) e portais locais",
            "website": "https://api.whatsapp.com/send?phone=5519992207345",
            "rating": 5.0,
            "reviews": 15,
            "score": 86,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Depende exclusivamente de conversas manuais no WhatsApp sem uma página oficial para demonstrar a segurança e a técnica de procedimentos de alto ticket (harmonização facial, bioestimuladores de colágeno, toxina botulínica e rinomodelação sem corte).",
            "proposta": {
                "tipo_solucao": "Landing Page de Autoridade Biomédica",
                "headline": "Biomedicina Estética Integrativa: Rejuvenescimento e Elegância em Indaiatuba",
                "secoes": [
                    "Hero de apresentação clínica com credenciais da Dra. Rafaelle Lucia",
                    "Menu de procedimentos de alto padrão: Botox, Bioestimuladores, Preenchimento e Rinomodelação",
                    "Espaço sobre a abordagem integrativa e protocolos individualizados",
                    "Depoimentos e avaliações reais 5.0 estrelas",
                    "Consultório no Centro de Indaiatuba com estacionamento fácil",
                    "Botão direto para agendamento de consulta de avaliação facial"
                ],
                "diferencial_conversao": "Apresentação detalhada da capacitação biomédica, filtrando pacientes que buscam procedimentos particulares de alto padrão e dispensando explicações repetitivas no WhatsApp."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Rafaelle ou com o atendimento do consultório em Indaiatuba?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Rafaelle ou com o atendimento do consultório em Indaiatuba?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Rafaelle ou com o atendimento do consultório em Indaiatuba?",
                "Olá, bom dia! É do consultório da Dra. Rafaelle Lúcia na Rua Humaitá, gostaria de confirmar se falo com a responsável.",
                "Olá! Quem responde pelos agendamentos e contato institucional da clínica da Dra. Rafaelle por aqui?"
],
            "mensagem_etapa2": "Sou da PH DIGITAL e desenvolvemos páginas profissionais para profissionais da saúde e estética. Pensei em uma apresentação online que ajude a reunir os procedimentos de harmonização e facilite o agendamento de consultas do consultório em Indaiatuba. Preparei uma demonstração visual dessa proposta e gostaria de apresentar a vocês.",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#2D5A52",
                    "secundaria": "#F8FAFC",
                    "acento": "#C5A059",
                    "texto": "#1F2937"
                },
                "nomes_cores": "Verde Esmeralda Suave, Branco Puro, Ouro Fosco e Cinza Chumbo",
                "tipografia": "Cormorant Garamond (títulos refinados) e Plus Jakarta Sans (leitura limpa)",
                "tom_voz": "Clínico, ético, elegante e focado em naturalidade",
                "layout_referencia": "Consultório Integrativo / Harmonização Facial de Alto Padrão"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Humaitá, 594, Sala 6 – Centro, Indaiatuba - SP (CEP: 13330-665)", "url": "https://maps.google.com/?q=Rua+Humaita+594+Indaiatuba"},
                {"fonte": "Contato Comercial", "detalhe": "WhatsApp comercial (19) 99220-7345 confirmado", "url": "https://api.whatsapp.com/send?phone=5519992207345"},
                {"fonte": "Avaliação Pública", "detalhe": "Nota 5.0 com excelência em atendimento presencial", "url": ""}
            ]
        },
        {
            "lead_id": "lead-amabille-estetica-indaiatuba",
            "nome": "Amabille Estética Avançada",
            "responsavel": "Dra. Sarah Amábille (Cirurgiã-Dentista e Esteta)",
            "categoria": "Esteticista / Harmonização Orofacial",
            "nicho": "Harmonização Orofacial e Estética",
            "cidade": "Indaiatuba - SP",
            "bairro": "Jardim Colonial / Vila Magalhães",
            "endereco": "Av. Eng. Fábio Roberto Barnabé, 4420 – Indaiatuba - SP",
            "telefone": "(19) 99308-5806",
            "canal_atual": "Instagram @dra.amabille e WhatsApp",
            "website": "https://www.instagram.com/dra.amabille/",
            "rating": 4.9,
            "reviews": 19,
            "score": 86,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Clínica situada na principal avenida de Indaiatuba que vende tratamentos de R$ 1.500 a R$ 5.000 dependendo exclusivamente do feed do Instagram. Não possui página de captura indexada nas buscas locais do Google.",
            "proposta": {
                "tipo_solucao": "Página Institucional Premium de Harmonização",
                "headline": "Harmonização Orofacial e Corporal com Elegância e Precisão em Indaiatuba",
                "secoes": [
                    "Hero de alto impacto na Av. Fábio Roberto Barnabé",
                    "Procedimentos de destaque: Preenchimento labial, Rinomodelação e Botox preventivo",
                    "Protocolos faciais e corporais com tecnologia de ponta",
                    "Galeria de resultados sutis e naturais",
                    "Formulário rápido para agendamento de horário personalizado"
                ],
                "diferencial_conversao": "Posicionamento da clínica no topo das pesquisas de Indaiatuba no Google, conferindo autoridade condizente com a localização nobre na avenida."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Sarah ou com a responsável pelo atendimento da Amabille Estética?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Sarah ou com a responsável pelo atendimento da Amabille Estética?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Sarah ou com a responsável pelo atendimento da Amabille Estética?",
                "Olá, boa tarde! É da clínica Amabille na Av. Fábio Roberto Barnabé, gostaria de falar com a administração.",
                "Olá, tudo bem? Quem responde pelo setor de agendamentos e novos pacientes da Amabille por aqui?"
],
            "mensagem_etapa2": "Sou da PH DIGITAL e desenvolvemos páginas profissionais para clínicas de estética. Pensei em uma estrutura online que ajude a apresentar os tratamentos da Amabille Estética de forma clara para quem busca atendimento em Indaiatuba. Preparei uma demonstração visual desse modelo e gostaria de apresentar a vocês.",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#C87D65",
                    "secundaria": "#F5F2EB",
                    "acento": "#CCA43B",
                    "texto": "#1A1A1A"
                },
                "nomes_cores": "Terracota Nobre, Areia Clássica, Dourado Ouro e Preto Profundo",
                "tipografia": "Cinzel / Marcellus (títulos nobres) e Montserrat (corpo contemporâneo)",
                "tom_voz": "Exclusividade, simetria facial e cuidado detalhista",
                "layout_referencia": "Estética Orofacial / Dermatologia Cosmética"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Av. Eng. Fábio Roberto Barnabé, 4420 – Indaiatuba - SP (CEP: 13348-670)", "url": "https://maps.google.com/?q=Av+Eng+Fabio+Roberto+Barnabe+4420+Indaiatuba"},
                {"fonte": "Instagram Oficial", "detalhe": "@dra.amabille (conteúdo de harmonização orofacial e estética)", "url": "https://www.instagram.com/dra.amabille/"},
                {"fonte": "Avaliações", "detalhe": "Nota 4.9 com pacientes particulares atendidos na cidade", "url": ""}
            ]
        },
        {
            "lead_id": "lead-dra-daniela-andrade-indaiatuba",
            "nome": "Dra. Daniela Andrade - Harmonização Facial e Corporal em Indaiatuba",
            "responsavel": "Dra. Daniela Andrade",
            "categoria": "Centro de saúde e beleza",
            "nicho": "Harmonização Facial e Corporal",
            "cidade": "Indaiatuba - SP",
            "bairro": "Vila Sfeir",
            "endereco": "Rua Sete de Setembro, 441 - Vila Sfeir, Indaiatuba - SP",
            "telefone": "(19) 99539-4878",
            "canal_atual": "Apenas Google Maps (sem site próprio e sem link ativo)",
            "website": "",
            "rating": 5.0,
            "reviews": 10,
            "score": 79,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Total invisibilidade digital fora da ficha do Google Maps. Uma especialista com consultório em ponto nobre de Indaiatuba (Vila Sfeir) perdendo pacientes que buscam no Google por procedimentos de harmonização e rejuvenescimento.",
            "proposta": {
                "tipo_solucao": "Landing Page de Alta Conversão com SEO Local",
                "headline": "Harmonização Facial e Corporal Personalizada em Indaiatuba",
                "secoes": [
                    "Apresentação da Dra. Daniela Andrade e filosofia de atendimento",
                    "Tratamentos faciais: toxina, preenchedores, bioestimuladores e fios",
                    "Tratamentos corporais para flacidez e definição",
                    "Dúvidas frequentes sobre tempo de recuperação e durabilidade",
                    "Localização nobre na Rua Sete de Setembro com agendamento direto"
                ],
                "diferencial_conversao": "Presença online profissional estruturada com SEO local para indexar no Google de Indaiatuba e direcionar contatos qualificados diretamente para o WhatsApp do consultório."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Daniela Andrade ou com a recepção do consultório em Indaiatuba?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Daniela Andrade ou com a recepção do consultório em Indaiatuba?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Daniela Andrade ou com a recepção do consultório em Indaiatuba?",
                "Olá, bom dia! É do consultório da Dra. Daniela na Rua Sete de Setembro, gostaria de falar com a responsável.",
                "Olá! Quem cuida dos atendimentos e novos agendamentos do consultório da Dra. Daniela por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Vimos as ótimas avaliações do seu consultório na Vila Sfeir em Indaiatuba na área de harmonização facial e corporal. Identificamos que o consultório ainda não possui um site próprio nas buscas do Google na região, onde muitos pacientes pesquisam por tratamentos estéticos. Montamos uma demonstração de página de autoridade clínica para o seu consultório. Posso compartilhar o link com você para avaliar?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#6B2D5C",
                    "secundaria": "#FBF8F5",
                    "acento": "#E8C5C8",
                    "texto": "#222222"
                },
                "nomes_cores": "Vinho Marsala, Bege Seda, Rosa Blush e Carvão Suave",
                "tipografia": "Prata (títulos delicados) e Lato (texto claro)",
                "tom_voz": "Acolhedor, técnico, discreto e focado em bem-estar integral",
                "layout_referencia": "Consultório Privado / Estética Médica Facial"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Sete de Setembro, 441 - Vila Sfeir, Indaiatuba - SP (CEP: 13330-350)", "url": "https://maps.google.com/?q=Rua+Sete+de+Setembro+441+Indaiatuba"},
                {"fonte": "Google Maps", "detalhe": "Nota 5.0 estrelas e atuação consolidada no bairro", "url": ""},
                {"fonte": "Telefone Validado", "detalhe": "(19) 99539-4878 (WhatsApp móvel da mesma DDD de Indaiatuba)", "url": ""}
            ]
        },
        {
            "lead_id": "lead-dra-bruna-madeira-limeira",
            "nome": "Dra Bruna Madeira | Harmonização Facial",
            "responsavel": "Dra. Bruna Madeira (Cirurgiã-Dentista e Endodontista)",
            "categoria": "Cirurgião dentista / Endodontia",
            "nicho": "Endodontia Especializada e Harmonização Facial",
            "cidade": "Limeira - SP",
            "bairro": "Vila Cristovam",
            "endereco": "Rua Sergipe, 733 – Vila Cristovam, Limeira - SP",
            "telefone": "(19) 99734-3610",
            "canal_atual": "Google Maps e cadastros em diretórios de saúde",
            "website": "",
            "rating": 5.0,
            "reviews": 12,
            "score": 79,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Combina duas áreas de altíssimo valor (endodontia microscópica e harmonização orofacial), mas não possui uma página própria para explicar aos pacientes a tecnologia do tratamento de canal sem dor e a harmonia facial.",
            "proposta": {
                "tipo_solucao": "Landing Page Odontológica Especializada",
                "headline": "Odontologia de Alta Precisão e Harmonização Orofacial em Limeira",
                "secoes": [
                    "Hero de autoridade odontológica com a Dra. Bruna Madeira",
                    "Endodontia Microscópica: Como a tecnologia garante tratamentos seguros e confortáveis",
                    "Harmonização Orofacial: Protocolos para equilíbrio do sorriso e rejuvenescimento",
                    "Depoimentos de pacientes e padrão de biossegurança",
                    "Consultório na Vila Cristovam com agendamento facilitado"
                ],
                "diferencial_conversao": "Desmistificação do tratamento de canal e valorização da harmonização facial, gerando confiança para pacientes com dores agudas ou que buscam estética dental avançada."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Bruna Madeira ou com a recepção do consultório em Limeira?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Bruna Madeira ou com a recepção do consultório em Limeira?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Bruna Madeira ou com a recepção do consultório em Limeira?",
                "Olá, bom dia! É do consultório odontológico da Dra. Bruna na Rua Sergipe, gostaria de falar com a responsável.",
                "Olá! Quem coordena os agendamentos e o atendimento do consultório da Dra. Bruna por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Vimos a atuação do seu consultório na Vila Cristovam em Limeira, unindo endodontia especializada e harmonização facial. Procedimentos odontológicos de alta precisão convertem muito melhor quando o paciente encontra uma página própria explicando a segurança e a tecnologia do consultório. Desenhamos uma prévia demonstrativa de site para o consultório. Teria um minuto para ver como ficou?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#0F2B48",
                    "secundaria": "#FFFFFF",
                    "acento": "#4A90E2",
                    "texto": "#1E293B"
                },
                "nomes_cores": "Azul Marinho Cirúrgico, Branco Neve, Azul Céu Acento e Chumbo",
                "tipografia": "Montserrat (títulos sólidos e modernos) e Open Sans (leitura fluida)",
                "tom_voz": "Científico, seguro, acolhedor e altamente resolutivo",
                "layout_referencia": "Clínica Odontológica de Alta Especialização"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Sergipe, 733 – Vila Cristovam, Limeira - SP (CEP: 13480-530)", "url": "https://maps.google.com/?q=Rua+Sergipe+733+Limeira"},
                {"fonte": "Especialidades Verificadas", "detalhe": "Endodontia Especializada e Harmonização Orofacial registradas", "url": ""},
                {"fonte": "Telefone Validado", "detalhe": "(19) 99734-3610 (celular comercial WhatsApp)", "url": ""}
            ]
        },
        {
            "lead_id": "lead-cmo-curitiba",
            "nome": "Centro Médico Odontológico",
            "responsavel": "Diretoria Clínica CMO",
            "categoria": "Clínica odontológica",
            "nicho": "Odontologia Completa, Implantes e Ortodontia",
            "cidade": "Sítio Cercado, Curitiba - PR",
            "bairro": "Sítio Cercado",
            "endereco": "Rua Izaac Ferreira da Cruz, 3920 – Sítio Cercado, Curitiba - PR",
            "telefone": "(41) 99826-3846",
            "canal_atual": "Instagram @cmositiocercado e Google Maps",
            "website": "https://www.instagram.com/cmositiocercado/",
            "rating": 5.0,
            "reviews": 35,
            "score": 86,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Clínica odontológica física com múltiplos consultórios na principal rua comercial do Sítio Cercado que atende de segunda a sábado, mas não possui site. Perde dezenas de pacientes de implantes, próteses e alinhadores que buscam dentistas no Google no bairro.",
            "proposta": {
                "tipo_solucao": "Portal Institucional Odontológico com Agendamento Online",
                "headline": "Seu Sorriso Completo com os Melhores Dentistas do Sítio Cercado",
                "secoes": [
                    "Hero de recepção moderna na Izaac Ferreira da Cruz",
                    "Especialidades completas: Implantes, Alinhadores, Facetas, Clareamento e Odontopediatria",
                    "Corpo clínico experiente e tecnologia de diagnóstico",
                    "Horários estendidos e facilidade de pagamento",
                    "Sistema de triagem e agendamento online integrado com WhatsApp"
                ],
                "diferencial_conversao": "Captação ativa de pacientes particulares na região sul de Curitiba que pesquisam por implantes e ortodontia no Google, reduzindo a dependência de convênios."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Gostaria de falar com o responsável pela administração ou atendimento do CMO Odontologia no Sítio Cercado.",
            "mensagem_etapa1": "Olá, tudo bem? Gostaria de falar com o responsável pela administração ou atendimento do CMO Odontologia no Sítio Cercado.",
            "variacoes_etapa1": [
                "Olá, tudo bem? Gostaria de falar com o responsável pela administração ou atendimento do CMO Odontologia no Sítio Cercado.",
                "Olá, bom dia! É da clínica CMO Odontologia na Rua Izaac Ferreira da Cruz, este canal fala com a coordenação?",
                "Olá! Quem responde pela parte de captação de novos pacientes e gestão do CMO Odontologia por aqui?"
],
            "mensagem_etapa2": "Sou da PH DIGITAL e desenvolvemos sites profissionais para clínicas odontológicas. Pensei em um portal que ajude a apresentar as especialidades de atendimento e facilite o agendamento de consultas do CMO no Sítio Cercado. Preparei uma demonstração visual dessa estrutura e gostaria de apresentar a vocês.",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#114B5F",
                    "secundaria": "#E4F4F3",
                    "acento": "#028090",
                    "texto": "#1F2421"
                },
                "nomes_cores": "Azul Petróleo, Verde Menta Suave, Azul Oceano e Carvão",
                "tipografia": "Poppins (amigável e moderno) e Inter (legibilidade)",
                "tom_voz": "Acolhedor, profissional, familiar e transparente",
                "layout_referencia": "Centro Médico Odontológico Multidisciplinar"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Izaac Ferreira da Cruz, 3920 – Sítio Cercado, Curitiba - PR", "url": "https://maps.google.com/?q=Rua+Izaac+Ferreira+da+Cruz+3920+Curitiba"},
                {"fonte": "Instagram Oficial", "detalhe": "@cmositiocercado (postagens regulares de atendimentos)", "url": "https://www.instagram.com/cmositiocercado/"},
                {"fonte": "Horários Confirmados", "detalhe": "Seg-Sex 9h às 18h30, Sáb 8h às 12h", "url": ""}
            ]
        },
        {
            "lead_id": "lead-marcenaria-sua-casa-contagem",
            "nome": "Marcenaria Sua Casa",
            "responsavel": "Gestão Comercial Marcenaria Sua Casa",
            "categoria": "Fornecedor de móveis planejados",
            "nicho": "Móveis Planejados e Sob Medida",
            "cidade": "Contagem - MG",
            "bairro": "Inconfidentes",
            "endereco": "Rua Avelino Camargos, 155 – Bairro Inconfidentes, Contagem - MG",
            "telefone": "(31) 98707-6785",
            "canal_atual": "Instagram @marcenaria_sua_casa e telefone de fábrica (31) 2510-5611",
            "website": "https://www.instagram.com/marcenaria_sua_casa",
            "rating": 5.0,
            "reviews": 20,
            "score": 86,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Fábrica e marcenaria própria no polo industrial de Contagem produzindo cozinhas, dormitórios e painéis de alto valor, porém sem catálogo web oficial. Os clientes dependem de fotos no WhatsApp ou Instagram para ver ambientes prontos.",
            "proposta": {
                "tipo_solucao": "Catálogo Digital de Ambientes Sob Medida",
                "headline": "Móveis Planejados Direto da Fábrica com Precisão e Acabamento Superior",
                "secoes": [
                    "Hero industrial moderno valorizando a marcenaria própria",
                    "Catálogo interativo por ambiente: Cozinhas integradas, Dormitórios, Home Theaters e Banheiros",
                    "Diferenciais de ferragens, acabamentos e garantia de fábrica",
                    "Vídeos e fotos de montagens reais entregues em Contagem e BH",
                    "Formulário para agendamento de visita técnica e medição no imóvel"
                ],
                "diferencial_conversao": "Apresentação visual de qualidade de alto padrão com formulário direto para solicitação de medição, acelerando o fechamento de contratos de R$ 10.000 a R$ 40.000."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Sua Casa em Contagem?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Sua Casa em Contagem?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Sua Casa em Contagem?",
                "Olá, bom dia! É da fábrica da Marcenaria Sua Casa no Bairro Inconfidentes, gostaria de falar com o responsável comercial.",
                "Olá, tudo bem? Quem responde pelos orçamentos de móveis sob medida da Marcenaria Sua Casa por aqui?"
],
            "mensagem_etapa2": "Sou da PH DIGITAL e desenvolvemos sites profissionais para marcenarias e fabricantes de móveis sob medida. Pensei em um catálogo online por ambientes que ajude a apresentar os projetos de móveis planejados e facilite pedidos de orçamento em Contagem. Preparei uma demonstração visual desse formato e gostaria de apresentar a vocês.",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#8B5A2B",
                    "secundaria": "#F5EBE1",
                    "acento": "#E65F2B",
                    "texto": "#1C1D1F"
                },
                "nomes_cores": "Carvalho Nobre, Bege Marfim, Laranja Marceneiro e Cinza Concreto",
                "tipografia": "Syne (títulos marcantes e estruturais) e Inter (corpo técnico)",
                "tom_voz": "Sólido, artesanal, transparente e focado em durabilidade",
                "layout_referencia": "Indústria Moveleira / Design de Interiores Sob Medida"
            },
            "evidencias": [
                {"fonte": "Fábrica Física", "detalhe": "Rua Avelino Camargos, 155 – Bairro Inconfidentes, Contagem - MG (CEP: 32260-290)", "url": "https://maps.google.com/?q=Rua+Avelino+Camargos+155+Contagem"},
                {"fonte": "Telefones Verificados", "detalhe": "Fixo de fábrica (31) 2510-5611 e celular WhatsApp (31) 98707-6785", "url": ""},
                {"fonte": "Instagram Oficial", "detalhe": "@marcenaria_sua_casa (projetos residenciais entregues)", "url": "https://www.instagram.com/marcenaria_sua_casa"}
            ]
        },
        {
            "lead_id": "lead-linear-moveis-palhoca",
            "nome": "Linear Móveis Sob medida",
            "responsavel": "Linear Moveis Sob Medidas Ltda - ME",
            "categoria": "Moveleiro / Marcenaria Industrial",
            "nicho": "Móveis Planejados Residenciais e Corporativos",
            "cidade": "Palhoça - SC",
            "bairro": "Bela Vista / Alto Aririú",
            "endereco": "Rua Maria Basílio, 138, Palhoça - SC (CEP: 88132-856)",
            "telefone": "(48) 99619-2785",
            "canal_atual": "Instagram @linear_moveis_sobmedidas e Google Maps",
            "website": "https://instagram.com/linear_moveis_sobmedidas",
            "rating": 5.0,
            "reviews": 15,
            "score": 76,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Empresa formalizada (Ltda - ME) com galpão fabril próprio em Palhoça atendendo a Grande Florianópolis, sem catálogo institucional para firmar parcerias com arquitetos, decoradores e condomínios fechados.",
            "proposta": {
                "tipo_solucao": "Portal Institucional & Catálogo de Interiores",
                "headline": "Móveis Sob Medida para Casas, Apartamentos e Empresas na Grande Florianópolis",
                "secoes": [
                    "Hero institucional com vista da fábrica e maquinário",
                    "Soluções completas para residências de alto padrão e salas comerciais",
                    "Área exclusiva para arquitetos e especificadores técnicos",
                    "Galeria de projetos executados em Palhoça, São José e Florianópolis",
                    "Formulário para envio de plantas e solicitação de orçamento técnico"
                ],
                "diferencial_conversao": "Canal profissional para arquitetos e clientes finais enviarem plantas em PDF/DWG diretamente para a equipe técnica orçar com agilidade."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com o responsável pelos projetos e orçamentos da Linear Móveis em Palhoça?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com o responsável pelos projetos e orçamentos da Linear Móveis em Palhoça?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com o responsável pelos projetos e orçamentos da Linear Móveis em Palhoça?",
                "Olá, bom dia! É da marcenaria Linear Móveis na Rua Maria Basílio, gostaria de falar com o responsável comercial.",
                "Olá! Quem coordena o atendimento a clientes e arquitetos da Linear Móveis por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Vimos a estrutura fabril da Linear Móveis em Palhoça e a qualidade dos projetos executados na Grande Florianópolis. Muitas construtoras, arquitetos e proprietários buscam fábricas consolidadas pelo Google e precisam de um canal formal para envio de plantas. Criamos uma demonstração de catálogo institucional para a Linear Móveis. Posso te enviar o link da proposta para você dar uma olhada?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#2E3440",
                    "secundaria": "#ECEFF4",
                    "acento": "#5E81AC",
                    "texto": "#1E1E1E"
                },
                "nomes_cores": "Cinza Chumbo Nórdico, Branco Neve, Azul Aço e Preto Profundo",
                "tipografia": "Space Grotesk (moderno e arquitetônico) e DM Sans (legibilidade)",
                "tom_voz": "Corporativo, preciso, imponente e pontual",
                "layout_referencia": "Indústria Moveleira e Projetos de Arquitetura"
            },
            "evidencias": [
                {"fonte": "Registro Empresarial", "detalhe": "Linear Moveis Sob Medidas Ltda - ME (CNPJ ativo na Receita Federal)", "url": ""},
                {"fonte": "Endereço Físico", "detalhe": "Rua Maria Basílio, 138, Palhoça - SC", "url": "https://maps.google.com/?q=Rua+Maria+Basilio+138+Palhoca"},
                {"fonte": "Instagram Oficial", "detalhe": "@linear_moveis_sobmedidas (ambientes instalados)", "url": "https://instagram.com/linear_moveis_sobmedidas"}
            ]
        },
        {
            "lead_id": "lead-s12-design-palhoca",
            "nome": "S12 Design Móveis sob Medida",
            "responsavel": "Equipe S12 Design",
            "categoria": "Marceneiro / Design de Interiores",
            "nicho": "Móveis Sob Medida de Alto Acabamento",
            "cidade": "Palhoça - SC",
            "bairro": "Rio Grande (Nova Palhoça)",
            "endereco": "Rua Santa Maria, Nova Palhoça, Palhoça - SC",
            "telefone": "(48) 99828-8430",
            "canal_atual": "Instagram e Google Maps",
            "website": "https://www.instagram.com/p/CsvisqqO-DlK38LKj0b67Elgf9lRDVT1DDkFuA0/",
            "rating": 5.0,
            "reviews": 12,
            "score": 76,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Marcenaria com forte apelo visual em design e marcenaria fina, mas que depende de conversas fragmentadas no Instagram sem uma página que filtre metragem e tipo de projeto.",
            "proposta": {
                "tipo_solucao": "Landing Page de Design e Interiores",
                "headline": "Marcenaria de Alto Padrão e Design Inteligente para o Seu Lar",
                "secoes": [
                    "Hero visual com fotografia em alta definição de cozinhas e dormitórios",
                    "Apresentação da consultoria de design e escolha de materiais premium",
                    "Linha do tempo: do projeto 3D à instalação final sem poeira",
                    "Depoimentos de clientes satisfeitos na Grande Florianópolis",
                    "Botão direto para consultoria técnica no WhatsApp"
                ],
                "diferencial_conversao": "Filtro inicial de orçamentos por tipo de ambiente e estilo de acabamento, acelerando o fechamento com clientes de condomínios fechados da região."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com o responsável pelo atendimento e orçamentos da S12 Design em Palhoça?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com o responsável pelo atendimento e orçamentos da S12 Design em Palhoça?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com o responsável pelo atendimento e orçamentos da S12 Design em Palhoça?",
                "Olá, boa tarde! É do studio S12 Design no Bairro Rio Grande, gostaria de falar com a administração.",
                "Olá! Quem cuida dos orçamentos de projetos sob medida da S12 Design por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Acompanhamos o padrão de acabamento dos ambientes sob medida que a S12 Design produz em Palhoça. Notamos que vocês recebem clientes principalmente pelo Instagram, sem uma página estruturada que valorize o design e qualifique os pedidos de orçamento por ambiente. Preparamos uma demonstração visual de site pensada para o estúdio de vocês. Teria interesse em ver o link da prévia?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#18181B",
                    "secundaria": "#F4F4F5",
                    "acento": "#9C6644",
                    "texto": "#27272A"
                },
                "nomes_cores": "Preto Fosco, Cinza Minimalista, Madeira Freijó e Grafite",
                "tipografia": "Playfair Display (sofisticação) e Plus Jakarta Sans (clareza moderna)",
                "tom_voz": "Exclusivo, contemporâneo, detalhista e focado em estética",
                "layout_referencia": "Studio de Design de Interiores / Marcenaria Autoral"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Santa Maria, Bairro Rio Grande (Nova Palhoça), Palhoça - SC", "url": "https://maps.google.com/?q=Rua+Santa+Maria+Palhoca"},
                {"fonte": "Avaliações", "detalhe": "Nota 5.0 estrelas com clientes atendidos na Grande Florianópolis", "url": ""},
                {"fonte": "Telefone Validado", "detalhe": "(48) 99828-8430 (celular WhatsApp direto)", "url": ""}
            ]
        },
        {
            "lead_id": "lead-marcenaria-americana",
            "nome": "Marcenaria Americana | Móveis Planejados",
            "responsavel": "Gestão Comercial Marcenaria Americana",
            "categoria": "Marceneiro / Móveis Planejados",
            "nicho": "Móveis Planejados Residenciais",
            "cidade": "Americana - SP",
            "bairro": "Região Central",
            "endereco": "Rua Antônio Fornaziero, Americana - SP",
            "telefone": "(19) 99559-3749",
            "canal_atual": "Instagram @marcenaria_americana e Google Maps",
            "website": "https://www.instagram.com/marcenaria_americana",
            "rating": 5.0,
            "reviews": 18,
            "score": 76,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Oficina ativa de móveis planejados em Americana sem site institucional. Perde clientes da Região Metropolitana de Campinas que pesquisam no Google por marceneiro confiável na cidade.",
            "proposta": {
                "tipo_solucao": "Catálogo Online de Móveis Planejados",
                "headline": "Móveis Planejados com Qualidade, Pontualidade e Preço Justo em Americana",
                "secoes": [
                    "Hero de recepção destacando a experiência da marcenaria em Americana",
                    "Ambientes sob medida: Cozinhas, Dormitórios, Closets e Home Offices",
                    "Garantia de pontualidade na entrega e pós-venda dedicado",
                    "Fotos de projetos entregues em Americana, Santa Bárbara e Nova Odessa",
                    "Formulário para agendamento de visita de medição sem compromisso"
                ],
                "diferencial_conversao": "Foco na dor do cliente de marcenaria (medo de atraso na entrega), destacando compromisso de prazo e acabamento impecável."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Americana?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Americana?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com o responsável pelos orçamentos da Marcenaria Americana?",
                "Olá, bom dia! É da Marcenaria Americana na Rua Antônio Fornaziero, gostaria de falar com o responsável pela empresa.",
                "Olá! Quem responde pelos novos pedidos e visitas técnicas de móveis planejados por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Vimos o trabalho de móveis planejados de vocês em Americana e o histórico de entregas na região. Clientes que procuram marcenaria de confiança no Google muitas vezes não encontram um catálogo oficial com os ambientes prontos e solicitação de orçamento. Criamos uma demonstração visual de site para a Marcenaria Americana. Posso te enviar o link da prévia para você conhecer sem compromisso?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#1E3A8A",
                    "secundaria": "#F8FAFC",
                    "acento": "#B45309",
                    "texto": "#1F2937"
                },
                "nomes_cores": "Azul Petróleo Confiável, Branco Suave, Âmbar Amadeirado e Chumbo",
                "tipografia": "Rubik (moderno e confiável) e Inter (legibilidade)",
                "tom_voz": "Acessível, confiável, experiente e seguro",
                "layout_referencia": "Marcenaria Tradicional / Fábrica de Móveis Planejados"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Antônio Fornaziero, Americana - SP", "url": "https://maps.google.com/?q=Rua+Antonio+Fornaziero+Americana"},
                {"fonte": "Instagram Oficial", "detalhe": "@marcenaria_americana (projetos residenciais locais)", "url": "https://www.instagram.com/marcenaria_americana"},
                {"fonte": "Telefone Validado", "detalhe": "(19) 99559-3749 com DDD 19 local", "url": ""}
            ]
        },
        {
            "lead_id": "lead-studio-camila-nascimento-bh",
            "nome": "STUDIO DE PILATES E FISIOTERAPIA CAMILA NASCIMENTO",
            "responsavel": "Dra. Camila Nascimento (Fisioterapeuta e Sócia-Administradora)",
            "categoria": "Fisioterapeuta / Pilates",
            "nicho": "Pilates Clínico e Reabilitação Postural",
            "cidade": "Barreiro, Belo Horizonte - MG",
            "bairro": "Diamante / Barreiro",
            "endereco": "Rua Madre Paulina, Bairro Diamante (Barreiro), Belo Horizonte - MG",
            "telefone": "(31) 98430-6606",
            "canal_atual": "Instagram @fisio.camilavno e WhatsApp",
            "website": "https://instagram.com/fisio.camilavno",
            "rating": 5.0,
            "reviews": 16,
            "score": 78,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Empresa formalizada (CNPJ 41.170.009/0001-28 ativo) com estúdio montado no Bairro Diamante/Barreiro, mas sem canal web automatizado para agendamento de aulas experimentais e matrícula de novas alunas particulares.",
            "proposta": {
                "tipo_solucao": "Landing Page de Fisioterapia & Pilates Clínico",
                "headline": "Pilates Clínico e Fisioterapia Especializada para Viver Sem Dor no Barreiro",
                "secoes": [
                    "Hero acolhedor com foto da Dra. Camila Nascimento e espaço de atendimento",
                    "Modalidades: Pilates em Aparelhos, Pilates Gestacional e Fisioterapia Preventiva",
                    "Método individualizado com turmas de no máximo 3 a 4 alunas",
                    "Depoimentos reais de alunas com alívio comprovado de dores nas costas",
                    "Formulário rápido para agendamento da 1ª Aula Experimental Gratuita"
                ],
                "diferencial_conversao": "Foco na aula experimental como isca de alta conversão, gerando fluxo constante de novas matrículas recorrentes."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Camila ou com a coordenação do Studio de Pilates no Barreiro?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Camila ou com a coordenação do Studio de Pilates no Barreiro?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Camila ou com a coordenação do Studio de Pilates no Barreiro?",
                "Olá, bom dia! É do Studio Camila Nascimento na Rua Madre Paulina, gostaria de confirmar se este é o contato da responsável.",
                "Olá! Quem coordena as novas turmas e o atendimento de alunas de pilates por aqui?"
],
            "mensagem_etapa2": "Sou da PH DIGITAL e desenvolvemos páginas profissionais para estúdios de pilates e fisioterapia. Pensei em uma apresentação online que ajude a mostrar as modalidades do Studio Camila Nascimento e facilite o agendamento de aulas no Barreiro. Preparei uma demonstração visual dessa página e gostaria de apresentar a vocês.",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#556B2F",
                    "secundaria": "#F7F5F0",
                    "acento": "#C08081",
                    "texto": "#2D3B23"
                },
                "nomes_cores": "Verde Oliva Terapêutico, Bege Areia, Rosa Chá Acento e Verde Floresta",
                "tipografia": "Lora (calorosa e humana) e Plus Jakarta Sans (leitura limpa)",
                "tom_voz": "Saudável, acolhedor, profissional e focado em autocuidado",
                "layout_referencia": "Studio de Pilates Clínico e Fisioterapia Integrada"
            },
            "evidencias": [
                {"fonte": "Registro Empresarial", "detalhe": "Studio de Pilates e Fisioterapia Camila Nascimento Ltda (CNPJ: 41.170.009/0001-28)", "url": ""},
                {"fonte": "Endereço Físico", "detalhe": "Rua Madre Paulina, Diamante (Barreiro), Belo Horizonte - MG", "url": "https://maps.google.com/?q=Rua+Madre+Paulina+Belo+Horizonte"},
                {"fonte": "Instagram Oficial", "detalhe": "@fisio.camilavno (vídeos de aulas com aparelhos)", "url": "https://instagram.com/fisio.camilavno"}
            ]
        },
        {
            "lead_id": "lead-up-fisio-barreiro",
            "nome": "UP Fisio – Pilates Barreiro",
            "responsavel": "Coordenação Técnica UP Fisio",
            "categoria": "Estúdio de pilates / Fisioterapia",
            "nicho": "Pilates, Fisioterapia e Bem-Estar",
            "cidade": "Barreiro, Belo Horizonte - MG",
            "bairro": "Diamante / Barreiro",
            "endereco": "Rua Aparecida Feitosa Furtado, 672 – Bairro Diamante, Belo Horizonte - MG",
            "telefone": "(31) 98407-7491",
            "canal_atual": "Instagram @upfisiooficial e WhatsApp",
            "website": "https://www.instagram.com/upfisiooficial/",
            "rating": 5.0,
            "reviews": 14,
            "score": 78,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Clínica estruturada que atende planos de bem-estar (Wellhub/TotalPass) com repasses baixos por sessão, sem um canal digital próprio para captar planos anuais e semestrais particulares de alta rentabilidade.",
            "proposta": {
                "tipo_solucao": "Site Institucional para Planos Particulares",
                "headline": "Sua Essência em Movimento: Pilates e Reabilitação Postural no Barreiro",
                "secoes": [
                    "Hero dinâmico com fotos dos aparelhos Reformer e Cadillac",
                    "Diferenciais dos planos particulares: avaliação postural detalhada e atenção exclusiva",
                    "Equipe de fisioterapeutas graduados e especializados",
                    "Planos flexíveis com condições especiais para planos semestrais",
                    "Botão direto para WhatsApp de recepção"
                ],
                "diferencial_conversao": "Estratégia de precificação e atração de alunos particulares que valorizam atendimento personalizado e garantem previsibilidade financeira para o estúdio."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a coordenação ou responsável pelo atendimento da UP Fisio no Barreiro?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a coordenação ou responsável pelo atendimento da UP Fisio no Barreiro?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a coordenação ou responsável pelo atendimento da UP Fisio no Barreiro?",
                "Olá, bom dia! É da UP Fisio na Rua Aparecida Feitosa Furtado, gostaria de falar com o responsável pelo espaço.",
                "Olá! Quem responde pela parte de matrículas e gestão do estúdio de pilates por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Analisamos clínicas de reabilitação e pilates no Barreiro e conhecemos a estrutura da UP Fisio na Rua Aparecida Feitosa Furtado. Notamos que vocês atendem aplicativos corporativos, mas ainda não possuem um site institucional focado em captar alunos particulares para planos semestrais e anuais no Google. Criamos uma demonstração visual de página para a clínica. Posso te enviar o link para você conhecer?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#5B21B6",
                    "secundaria": "#EDE9FE",
                    "acento": "#10B981",
                    "texto": "#1F2937"
                },
                "nomes_cores": "Roxo Ametista, Lilás Suave, Verde Esmeralda e Chumbo",
                "tipografia": "Outfit (moderno e vibrante) e Inter (leitura técnica)",
                "tom_voz": "Energético, técnico, focado em resultados posturais e saúde",
                "layout_referencia": "Centro de Reabilitação Física e Pilates Contemporâneo"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Aparecida Feitosa Furtado, 672 – Diamante, Belo Horizonte - MG (CEP 30627-205)", "url": "https://maps.google.com/?q=Rua+Aparecida+Feitosa+Furtado+672+Belo+Horizonte"},
                {"fonte": "Instagram Oficial", "detalhe": "@upfisiooficial (conteúdo de pilates e fisioterapia)", "url": "https://www.instagram.com/upfisiooficial/"},
                {"fonte": "Parcerias Verificadas", "detalhe": "Credenciado Wellhub e TotalPass no Bairro Diamante", "url": ""}
            ]
        },
        {
            "lead_id": "lead-deborah-rodrigues-pilates-bh",
            "nome": "Déborah Rodrigues Studio de Pilates - Barreiro",
            "responsavel": "Déborah Rodrigues",
            "categoria": "Estúdio de pilates",
            "nicho": "Pilates Clássico com Aparelhos",
            "cidade": "Barreiro, Belo Horizonte - MG",
            "bairro": "Miramar / Barreiro",
            "endereco": "Rua Eridano, 597 - Miramar (Barreiro), Belo Horizonte - MG",
            "telefone": "(31) 98202-4058",
            "canal_atual": "Instagram @deborahrodriguespilates e Google Maps",
            "website": "https://www.instagram.com/deborahrodriguespilates",
            "rating": 5.0,
            "reviews": 12,
            "score": 78,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Estúdio bem localizado com horário estendido em dois turnos (7h-12h e 15h-21h) que gerencia novas matrículas de forma manual pelo direct do Instagram, perdendo interessadas que navegam à noite.",
            "proposta": {
                "tipo_solucao": "Landing Page de Conversão com Grade de Horários",
                "headline": "Transforme sua Postura e Bem-Estar no Studio Déborah Rodrigues",
                "secoes": [
                    "Hero intimista com fotos das alunas executando movimentos nos aparelhos",
                    "Como o método pilates alivia tensões de quem trabalha sentado ou em pé",
                    "Grade interativa de turmas disponíveis de manhã e noite",
                    "Depoimentos em destaque com alunas do bairro Miramar",
                    "Agendamento automático da 1ª aula teste via WhatsApp"
                ],
                "diferencial_conversao": "Exibição clara das vagas nos horários de pico, gerando senso de urgência para fechamento imediato da aula teste."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Déborah ou com a responsável pelo Studio de Pilates no Miramar?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Déborah ou com a responsável pelo Studio de Pilates no Miramar?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Déborah ou com a responsável pelo Studio de Pilates no Miramar?",
                "Olá, bom dia! É do Studio de Pilates na Rua Eridano no Barreiro, gostaria de falar com a Déborah.",
                "Olá, tudo bem? Quem cuida das novas matrículas e horários do estúdio por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Vimos o estúdio de pilates de vocês no Bairro Miramar em Belo Horizonte e o atendimento em dois turnos. Como muitas alunas buscam horários de manhã ou à noite, ter uma página que mostre as turmas e permita solicitar uma aula teste poupa muito tempo de explicação no WhatsApp. Desenhamos uma demonstração visual exclusiva para o estúdio. Posso te enviar o link para dar uma olhada?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#9D5C63",
                    "secundaria": "#FAF7F2",
                    "acento": "#E07A5F",
                    "texto": "#264653"
                },
                "nomes_cores": "Rosa Queimado, Areia Natural, Terracota Quente e Chumbo Petróleo",
                "tipografia": "Fraunces (estilo acolhedor) e Nunito Sans (conforto visual)",
                "tom_voz": "Afetuoso, incentivador, disciplinado e acolhedor",
                "layout_referencia": "Studio Boutique de Pilates Feminino"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Eridano, 597 - Miramar (Barreiro), Belo Horizonte - MG", "url": "https://maps.google.com/?q=Rua+Eridano+597+Belo+Horizonte"},
                {"fonte": "Horários Confirmados", "detalhe": "Seg-Qui 07:00 às 12:00 e 15:00 às 21:00, Sex 07:00 às 12:00", "url": ""},
                {"fonte": "Instagram Oficial", "detalhe": "@deborahrodriguespilates com alunas ativas", "url": "https://www.instagram.com/deborahrodriguespilates"}
            ]
        },
        {
            "lead_id": "lead-pilates-no-barreiro-tiago-magno",
            "nome": "Pilates no Barreiro (Pilates Tiago Magno)",
            "responsavel": "Tiago Magno (Fisioterapeuta)",
            "categoria": "Estúdio de pilates / Fisioterapia",
            "nicho": "Tratamento de Coluna e Pilates Clínico",
            "cidade": "Barreiro, Belo Horizonte - MG",
            "bairro": "Brasil Industrial / Barreiro",
            "endereco": "Rua José Balbino Vieira, 180, Loja A – Brasil Industrial, Belo Horizonte - MG",
            "telefone": "(31) 98889-0437",
            "canal_atual": "WhatsApp direto (api.whatsapp.com) e portais locais",
            "website": "https://api.whatsapp.com/send?l=pt&phone=5531988890437",
            "rating": 5.0,
            "reviews": 11,
            "score": 78,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Loja física comercial com foco técnico em alívio de coluna e fisioterapia, mas que não possui página para sanar dúvidas de pacientes com dor aguda ou hérnia de disco antes do primeiro contato.",
            "proposta": {
                "tipo_solucao": "Landing Page Terapêutica de Reabilitação da Coluna",
                "headline": "Fisioterapia Especializada e Pilates para Alívio Definitivo das Dores na Coluna",
                "secoes": [
                    "Hero clínico com o fisioterapeuta Tiago Magno",
                    "Autoavaliação de sintomas: lombalgia, ciático, cervicalgia e desvios posturais",
                    "Como o pilates clínico devolve a mobilidade sem cirurgias e sem remédios",
                    "Estrutura da Loja A com ambiente silencioso e aparelhos completos",
                    "Agendamento de avaliação funcional da coluna via WhatsApp"
                ],
                "diferencial_conversao": "Foco terapêutico na dor do paciente, posicionando Tiago Magno como autoridade médica em coluna no Barreiro."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com o Dr. Tiago Magno ou com a recepção do estúdio de pilates no Barreiro?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com o Dr. Tiago Magno ou com a recepção do estúdio de pilates no Barreiro?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com o Dr. Tiago Magno ou com a recepção do estúdio de pilates no Barreiro?",
                "Olá, bom dia! É do estúdio na Rua José Balbino Vieira no Brasil Industrial, gostaria de falar com o Tiago.",
                "Olá! Quem responde pelos agendamentos de avaliações posturais e pilates por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Encontramos seu estúdio no Brasil Industrial no Barreiro e o trabalho especializado em reabilitação da coluna e postura. Pacientes com dor crônica costumam pesquisar muito antes de agendar e uma página própria detalhando a metodologia transmite a tranquilidade necessária para marcarem uma consulta. Preparamos uma demonstração visual pensada para o seu estúdio. Gostaria de receber o link para conhecer?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#1E40AF",
                    "secundaria": "#DBEAFE",
                    "acento": "#0D9488",
                    "texto": "#1E293B"
                },
                "nomes_cores": "Azul Real Clínico, Azul Céu Claro, Verde Petróleo Acento e Grafite",
                "tipografia": "Work Sans (sólido e claro) e Roboto (leitura técnica)",
                "tom_voz": "Técnico, resolutivo, empático e focado em alívio da dor",
                "layout_referencia": "Clínica de Fisioterapia e Coluna / Reabilitação Física"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua José Balbino Vieira, 180, Loja A – Brasil Industrial, Belo Horizonte - MG", "url": "https://maps.google.com/?q=Rua+Jose+Balbino+Vieira+180+Belo+Horizonte"},
                {"fonte": "Foco Técnico Confirmado", "detalhe": "Tratamento de Coluna, Fisioterapia e Pilates", "url": ""},
                {"fonte": "Telefone Validado", "detalhe": "(31) 98889-0437 (WhatsApp comercial móvel)", "url": ""}
            ]
        },
        {
            "lead_id": "lead-dra-fernanda-oliveira-indaiatuba",
            "nome": "Dra Fernanda Oliveira - Especialista em Harmonização facial",
            "responsavel": "Dra. Fernanda Oliveira (Cirurgiã-Dentista e Especialista em Harmonização)",
            "categoria": "Clínica especializada / Harmonização Facial",
            "nicho": "Harmonização Orofacial de Alto Ticket",
            "cidade": "Indaiatuba - SP",
            "bairro": "Vila Magalhães",
            "endereco": "Rua Leonor de Barros, Vila Magalhães, Indaiatuba - SP",
            "telefone": "(11) 97828-5259",
            "canal_atual": "Instagram @drafernandaoliveiraa e Google Maps",
            "website": "https://www.instagram.com/drafernandaoliveiraa",
            "rating": 4.9,
            "reviews": 14,
            "score": 80,
            "status": STATUS_PREPARADO,
            "oportunidade_digital": "Atende em consultório na Vila Magalhães em Indaiatuba de segunda a sábado, porém utiliza celular com DDD 11 (São Paulo Capital). Ter uma página própria focada na praça de Indaiatuba neutraliza a desconfiança de pacientes locais e consolida sua reputação na cidade.",
            "proposta": {
                "tipo_solucao": "Landing Page de Harmonização Facial com Foco em Indaiatuba",
                "headline": "Harmonização Facial com Naturalidade e Segurança Médica em Indaiatuba",
                "secoes": [
                    "Hero sofisticado destacando o atendimento exclusivo em Indaiatuba",
                    "Procedimentos: Toxina botulínica, Preenchimento labial, Malar e Mandibular",
                    "Filosofia de resultados imperceptíveis: realçar traços sem exageros",
                    "Localização e horários de atendimento na Vila Magalhães",
                    "Botão direto para WhatsApp com canal exclusivo de agendamento"
                ],
                "diferencial_conversao": "Eliminação do atrito do DDD 11, demonstrando que o consultório opera ativamente na cidade com endereço físico e atendimento regular."
            },
            "mensagem_whatsapp": "Olá, tudo bem? Falo com a Dra. Fernanda Oliveira ou com a recepção do consultório em Indaiatuba?",
            "mensagem_etapa1": "Olá, tudo bem? Falo com a Dra. Fernanda Oliveira ou com a recepção do consultório em Indaiatuba?",
            "variacoes_etapa1": [
                "Olá, tudo bem? Falo com a Dra. Fernanda Oliveira ou com a recepção do consultório em Indaiatuba?",
                "Olá, boa tarde! É do consultório da Dra. Fernanda na Rua Leonor de Barros, gostaria de confirmar se falo com a responsável.",
                "Olá! Quem cuida dos atendimentos e consultas de harmonização facial da Dra. Fernanda por aqui?"
],
            "mensagem_etapa2": "Olá! Sou da PH DIGITAL. Acompanhamos o padrão do seu consultório de harmonização facial na Vila Magalhães em Indaiatuba. Como o seu contato utiliza DDD 11, ter uma página própria (.com.br) destacando o endereço físico e os procedimentos em Indaiatuba elimina qualquer desconfiança de pacientes locais e fortalece a captação na cidade. Criamos uma prévia demonstrativa de landing page para o seu consultório. Posso te enviar o link para você avaliar?",
            "etapa_ativa": 1,
            "briefing_visual": {
                "paleta_cores": {
                    "primaria": "#1C1917",
                    "secundaria": "#F3E8DF",
                    "acento": "#D4A373",
                    "texto": "#292524"
                },
                "nomes_cores": "Preto Acetinado, Champanhe Suave, Nude Dourado e Cinza Café",
                "tipografia": "Italiana (elegância editorial) e Inter (leitura técnica fluida)",
                "tom_voz": "Exclusivo, refinado, ético e focado em harmonia estética",
                "layout_referencia": "Consultório de Harmonização Facial de Alta Categoria"
            },
            "evidencias": [
                {"fonte": "Endereço Físico", "detalhe": "Rua Leonor de Barros, Vila Magalhães, Indaiatuba - SP", "url": "https://maps.google.com/?q=Rua+Leonor+de+Barros+Indaiatuba"},
                {"fonte": "Horários Confirmados", "detalhe": "Segunda a Sexta 9h às 18h, Sábado 9h às 12h", "url": ""},
                {"fonte": "Instagram Oficial", "detalhe": "@drafernandaoliveiraa (casos de harmonização orofacial)", "url": "https://www.instagram.com/drafernandaoliveiraa"}
            ]
        }
    ]


def seed_prospecting_queue(db_target=DB_NAME):
    """Inicializa a tabela e semeia os 15 leads da Categoria A com status 'Preparado'."""
    init_prospecting_schema(db_target)
    leads_data = get_category_a_leads_data()
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    seeded_count = 0
    updated_count = 0
    
    for lead in leads_data:
        # Formatar link do WhatsApp
        digits = "".join(filter(str.isdigit, lead["telefone"]))
        wa_link = f"https://wa.me/55{digits}" if digits else ""
        
        proposta_str = json.dumps(lead["proposta"], ensure_ascii=False)
        briefing_str = json.dumps(lead["briefing_visual"], ensure_ascii=False)
        evidencias_str = json.dumps(lead["evidencias"], ensure_ascii=False)
        variacoes_str = json.dumps(lead.get("variacoes_etapa1", []), ensure_ascii=False)
        msg_etapa1 = lead.get("mensagem_etapa1") or lead.get("mensagem_whatsapp") or ""
        msg_etapa2 = lead.get("mensagem_etapa2") or ""
        etapa_ativa = lead.get("etapa_ativa") or 1

        # Verificar se já existe
        row = cursor.execute("SELECT id, status, notas_operador, mensagem_etapa1, mensagem_etapa2 FROM commercial_prospecting_queue WHERE lead_id = ?", (lead["lead_id"],)).fetchone()
        if not row:
            cursor.execute(
                """INSERT INTO commercial_prospecting_queue (
                    lead_id, nome, categoria, nicho, cidade, bairro, endereco, responsavel,
                    telefone, whatsapp_link, canal_atual, website, rating, reviews, score,
                    status, oportunidade_digital, proposta_json, mensagem_whatsapp,
                    briefing_visual_json, evidencias_json, notas_operador,
                    mensagem_etapa1, mensagem_etapa2, variacoes_etapa1_json, etapa_ativa
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lead["lead_id"], lead["nome"], lead["categoria"], lead["nicho"],
                    lead["cidade"], lead["bairro"], lead["endereco"], lead["responsavel"],
                    lead["telefone"], wa_link, lead["canal_atual"], lead["website"],
                    lead["rating"], lead["reviews"], lead["score"], lead["status"],
                    lead["oportunidade_digital"], proposta_str, msg_etapa1,
                    briefing_str, evidencias_str, "",
                    msg_etapa1, msg_etapa2, variacoes_str, etapa_ativa
                )
            )
            seeded_count += 1
        else:
            # Preserva status e notas existentes, atualiza dados da proposta e preenche etapas se vazias
            db_dict = _row_to_dict(row, cursor)
            atual_msg1 = db_dict.get("mensagem_etapa1") if db_dict.get("mensagem_etapa1") else msg_etapa1
            atual_msg2 = db_dict.get("mensagem_etapa2") if db_dict.get("mensagem_etapa2") else msg_etapa2

            cursor.execute(
                """UPDATE commercial_prospecting_queue
                   SET nome = ?, categoria = ?, nicho = ?, cidade = ?, bairro = ?,
                       endereco = ?, responsavel = ?, telefone = ?, whatsapp_link = ?,
                       canal_atual = ?, website = ?, rating = ?, reviews = ?, score = ?,
                       oportunidade_digital = ?, proposta_json = ?,
                       briefing_visual_json = ?, evidencias_json = ?,
                       mensagem_etapa1 = ?, mensagem_etapa2 = ?,
                       variacoes_etapa1_json = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE lead_id = ?""",
                (
                    lead["nome"], lead["categoria"], lead["nicho"], lead["cidade"], lead["bairro"],
                    lead["endereco"], lead["responsavel"], lead["telefone"], wa_link,
                    lead["canal_atual"], lead["website"], lead["rating"], lead["reviews"], lead["score"],
                    lead["oportunidade_digital"], proposta_str,
                    briefing_str, evidencias_str,
                    atual_msg1, atual_msg2, variacoes_str,
                    lead["lead_id"]
                )
            )
            updated_count += 1
            
    conn.commit()
    # Garante a existência da prévia visual para os 15 leads Categoria A
    seed_category_a_previews(conn)
    
    if should_close:
        conn.close()
    return {"seeded": seeded_count, "updated": updated_count, "total": len(leads_data)}


def list_prospecting_queue(status_filter=None, db_target=DB_NAME):
    """Lista os leads da fila de prospecção comercial com contadores."""
    init_prospecting_schema(db_target)
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    # Contadores de status
    counts = {s: 0 for s in VALID_STATUSES}
    counts["Todos"] = 0
    for row in cursor.execute("SELECT status, count(*) FROM commercial_prospecting_queue GROUP BY status").fetchall():
        st = row[0]
        cnt = row[1]
        if st in counts:
            counts[st] = cnt
        counts["Todos"] += cnt
        
    query = "SELECT * FROM commercial_prospecting_queue"
    params = []
    if status_filter and status_filter in VALID_STATUSES:
        query += " WHERE status = ?"
        params.append(status_filter)
        
    query += " ORDER BY score DESC, rating DESC, id ASC"
    
    rows = cursor.execute(query, params).fetchall()
    leads = []
    for r in rows:
        lead_dict = _row_to_dict(r, cursor)
        try:
            lead_dict["proposta"] = json.loads(lead_dict.get("proposta_json") or "{}")
        except Exception:
            lead_dict["proposta"] = {}
        try:
            lead_dict["briefing_visual"] = json.loads(lead_dict.get("briefing_visual_json") or "{}")
        except Exception:
            lead_dict["briefing_visual"] = {}
        try:
            lead_dict["evidencias"] = json.loads(lead_dict.get("evidencias_json") or "[]")
        except Exception:
            lead_dict["evidencias"] = []
        try:
            lead_dict["variacoes_etapa1"] = json.loads(lead_dict.get("variacoes_etapa1_json") or "[]")
        except Exception:
            lead_dict["variacoes_etapa1"] = []
        if not lead_dict.get("mensagem_etapa1"):
            lead_dict["mensagem_etapa1"] = lead_dict.get("mensagem_whatsapp") or ""
        if not lead_dict.get("etapa_ativa"):
            lead_dict["etapa_ativa"] = 1
        leads.append(lead_dict)
        
    if should_close:
        conn.close()
    return {"leads": leads, "counts": counts, "active_filter": status_filter or "Todos"}


def get_prospecting_lead(lead_id, db_target=DB_NAME):
    """Retorna os dados completos da ficha comercial de um lead."""
    init_prospecting_schema(db_target)
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM commercial_prospecting_queue WHERE lead_id = ?", (lead_id,)).fetchone()
    if not row:
        if should_close:
            conn.close()
        return None
    lead_dict = _row_to_dict(row, cursor)
    if should_close:
        conn.close()
    try:
        lead_dict["proposta"] = json.loads(lead_dict.get("proposta_json") or "{}")
    except Exception:
        lead_dict["proposta"] = {}
    try:
        lead_dict["briefing_visual"] = json.loads(lead_dict.get("briefing_visual_json") or "{}")
    except Exception:
        lead_dict["briefing_visual"] = {}
    try:
        lead_dict["evidencias"] = json.loads(lead_dict.get("evidencias_json") or "[]")
    except Exception:
        lead_dict["evidencias"] = []
    try:
        lead_dict["variacoes_etapa1"] = json.loads(lead_dict.get("variacoes_etapa1_json") or "[]")
    except Exception:
        lead_dict["variacoes_etapa1"] = []
    if not lead_dict.get("mensagem_etapa1"):
        lead_dict["mensagem_etapa1"] = lead_dict.get("mensagem_whatsapp") or ""
    if not lead_dict.get("etapa_ativa"):
        lead_dict["etapa_ativa"] = 1
    return lead_dict


def update_prospecting_status(lead_id, new_status, notas=None, db_target=DB_NAME):
    """Atualiza o status do lead na fila de prospecção comercial."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Status inválido: {new_status}. Permitidos: {VALID_STATUSES}")
        
    init_prospecting_schema(db_target)
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time_column = None
    if new_status == STATUS_APROVADO:
        time_column = "approved_at"
    elif new_status == STATUS_ENVIADO:
        time_column = "sent_at"
    elif new_status == STATUS_RESPONDIDO:
        time_column = "responded_at"
        
    sql = "UPDATE commercial_prospecting_queue SET status = ?, updated_at = CURRENT_TIMESTAMP"
    params = [new_status]
    
    if time_column:
        sql += f", {time_column} = ?"
        params.append(timestamp)
        
    if notas is not None:
        sql += ", notas_operador = ?"
        params.append(notas)
        
    sql += " WHERE lead_id = ?"
    params.append(lead_id)
    
    cursor.execute(sql, params)
    conn.commit()
    affected = cursor.rowcount
    if should_close:
        conn.close()
    return affected > 0


def update_prospecting_content(lead_id, data, db_target=DB_NAME):
    """Permite editar mensagem de WhatsApp, proposta ou notas antes da aprovação."""
    init_prospecting_schema(db_target)
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if "mensagem_whatsapp" in data:
        updates.append("mensagem_whatsapp = ?")
        params.append(data["mensagem_whatsapp"])

    if "mensagem_etapa1" in data:
        updates.append("mensagem_etapa1 = ?")
        params.append(data["mensagem_etapa1"])

    if "mensagem_etapa2" in data:
        updates.append("mensagem_etapa2 = ?")
        params.append(data["mensagem_etapa2"])

    if "variacoes_etapa1" in data:
        updates.append("variacoes_etapa1_json = ?")
        params.append(json.dumps(data["variacoes_etapa1"], ensure_ascii=False))

    if "etapa_ativa" in data:
        updates.append("etapa_ativa = ?")
        params.append(int(data["etapa_ativa"]))
        
    if "oportunidade_digital" in data:
        updates.append("oportunidade_digital = ?")
        params.append(data["oportunidade_digital"])
        
    if "proposta" in data:
        updates.append("proposta_json = ?")
        params.append(json.dumps(data["proposta"], ensure_ascii=False))
        
    if "briefing_visual" in data:
        updates.append("briefing_visual_json = ?")
        params.append(json.dumps(data["briefing_visual"], ensure_ascii=False))
        
    if "notas_operador" in data:
        updates.append("notas_operador = ?")
        params.append(data["notas_operador"])
        
    if not updates:
        if should_close:
            conn.close()
        return True
        
    updates.append("updated_at = CURRENT_TIMESTAMP")
    sql = f"UPDATE commercial_prospecting_queue SET {', '.join(updates)} WHERE lead_id = ?"
    params.append(lead_id)
    
    cursor.execute(sql, params)
    conn.commit()
    affected = cursor.rowcount
    if should_close:
        conn.close()
    return affected > 0


def get_lead_preview_versions(lead_id, db_target=DB_NAME):
    """Retorna todas as versões de preview já geradas para o lead em ordem decrescente."""
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT * FROM preview_versions WHERE place_id = ? ORDER BY version DESC",
        (lead_id,)
    ).fetchall()
    
    previews = []
    for r in rows:
        item = _row_to_dict(r, cursor)
        try:
            item["config"] = json.loads(item.get("config_json") or "{}")
        except Exception:
            item["config"] = {}
        try:
            item["validation"] = json.loads(item.get("validation_json") or "{}")
        except Exception:
            item["validation"] = {}
        item["html"] = item.get("html_content")
        previews.append(item)
        
    if should_close:
        conn.close()
    return previews


def _detect_template_for_lead(lead):
    """Determina o template de design ideal a partir do nicho e briefing."""
    nicho = (lead.get("nicho") or "").casefold()
    ref = (lead.get("briefing_visual", {}).get("layout_referencia") or "").casefold()
    
    if any(k in nicho for k in ("marcenaria", "móvel", "moveis", "planejado")) or "portfólio" in ref:
        return "portfolio"
    if any(k in nicho for k in ("estética", "harmonização", "pele", "facial")) or "editorial" in ref or "boutique" in ref:
        return "editorial"
    if "pilates" in nicho:
        if "fisioterapia" in nicho or "clínico" in ref or "postural" in ref:
            return "technical"
        return "care"
    if any(k in nicho for k in ("odont", "médic", "saúde", "dentista")):
        return "care"
    return "care"


def generate_prospecting_preview(lead_id, overrides=None, db_target=DB_NAME):
    """Gera uma prévia visual personalizada para o lead utilizando o motor oficial Preview Studio."""
    overrides = overrides or {}
    lead = get_prospecting_lead(lead_id, db_target=db_target)
    if not lead:
        raise ValueError(f"Lead {lead_id} não encontrado na fila comercial.")
        
    briefing = lead.get("briefing_visual") or {}
    paleta = briefing.get("paleta_cores") or briefing.get("paleta") or {}
    proposta = lead.get("proposta") or {}
    
    template = overrides.get("template") or _detect_template_for_lead(lead)
    headline = overrides.get("headline") or proposta.get("headline") or f"Atendimento e serviços de excelência em {lead.get('cidade', '')}"
    cta = overrides.get("cta") or (
        "Solicitar Orçamento de Ambiente" if template == "portfolio"
        else "Agendar Aula Experimental" if "pilates" in lead.get("nicho", "").casefold()
        else "Agendar Avaliação no WhatsApp"
    )
    
    # Seções demonstrativas
    services = overrides.get("services")
    if not services:
        services = proposta.get("secoes") or [
            "Atendimento especializado",
            "Estrutura e diferenciais",
            "Agendamento e orientações"
        ]
    if isinstance(services, str):
        services = [s.strip() for s in services.splitlines() if s.strip()]
        
    primary_color = overrides.get("primary") or paleta.get("primaria") or "#2563eb"
    surface_color = overrides.get("surface") or paleta.get("secundaria") or "#f8fafc"
    ink_color = overrides.get("ink") or paleta.get("texto") or "#1e293b"
    
    subheadline = overrides.get("subheadline") or proposta.get("diferencial") or lead.get("oportunidade_digital") or "Conheça nossas opções e converse diretamente com a nossa equipe."
    
    raw_lead_dict = {
        "Nome": lead.get("nome", ""),
        "Nicho": lead.get("nicho", ""),
        "Categoria Maps": lead.get("categoria", "") or lead.get("nicho", ""),
        "Bairro": lead.get("bairro", ""),
        "Cidade": lead.get("cidade", ""),
        "Telefone": lead.get("telefone", ""),
        "Google Maps": lead.get("website", ""),
        "Link Inicial": lead.get("website", ""),
        "Instagram": "",
    }
    
    merged_overrides = {
        "name": lead.get("nome"),
        "template": template,
        "headline": headline,
        "subheadline": subheadline,
        "cta": cta,
        "services": services[:4],
        "section_title": overrides.get("section_title") or ("Projetos e Especialidades" if template == "portfolio" else "Especialidades e Tratamentos"),
        "primary": primary_color,
        "surface": surface_color,
        "ink": ink_color,
        "heading_font": overrides.get("heading_font") or briefing.get("tipografia"),
        "whatsapp_url": lead.get("whatsapp_link"),
    }
    
    config = build_preview_config(raw_lead_dict, merged_overrides)
    config["whatsapp_url"] = lead.get("whatsapp_link")
    
    html = render_preview_html(config)
    validation = validate_preview_html(html, config)
    
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM preview_versions WHERE place_id = ?", (lead_id,))
    next_version = cursor.fetchone()[0]
    
    public_token = secrets.token_urlsafe(24)
    expires_at = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
    
    cursor.execute(
        """INSERT INTO preview_versions
           (place_id, version, config_json, html_content, public_token, status, approval_status,
            validation_json, research_json, art_direction_json, message_text, expires_at)
           VALUES (?, ?, ?, ?, ?, 'generated', 'draft', ?, ?, ?, ?, ?)""",
        (
            lead_id, next_version, json.dumps(config, ensure_ascii=False), html, public_token,
            json.dumps(validation, ensure_ascii=False), json.dumps(config.get("research") or {}, ensure_ascii=False),
            json.dumps(config.get("art_direction") or {}, ensure_ascii=False), config.get("message_with_image") or "", expires_at
        )
    )
    new_id = cursor.lastrowid
    conn.commit()
    if should_close:
        conn.close()
        
    return {
        "id": new_id,
        "lead_id": lead_id,
        "version": next_version,
        "html_url": f"/preview/{new_id}",
        "html": html,
        "html_content": html,
        "config": config,
        "validation": validation,
        "public_token": public_token
    }


def seed_category_a_previews(db_target=DB_NAME):
    """Garante que todos os 15 leads da Categoria A possuam ao menos uma versão da prévia gerada."""
    leads = get_category_a_leads_data()
    conn, should_close = get_db_connection(db_target)
    cursor = conn.cursor()
    
    created_count = 0
    existing_count = 0
    
    for lead in leads:
        lead_id = lead["lead_id"]
        cursor.execute("SELECT COUNT(*) FROM preview_versions WHERE place_id = ?", (lead_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            generate_prospecting_preview(lead_id, db_target=conn)
            created_count += 1
        else:
            existing_count += 1
            
    conn.commit()
    if should_close:
        conn.close()
    return {"created": created_count, "existing": existing_count, "total": len(leads)}
