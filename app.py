import os
import json
import time
import random
import re
import urllib.parse
import sqlite3
import multiprocessing
import hmac
from datetime import datetime, timedelta
import threading
import psutil
import pandas as pd
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for, send_file
from markupsafe import escape
from ai_provider import MODEL_CANDIDATES, first_available_response, generate_text
from commercial_intelligence import analyze_lead, build_generation_prompt, evaluate_pitches, generate_fallback_pitches
from preview_studio import build_preview_config, capture_preview_png, render_preview_html
from lead_scoring import DEFAULT_WEIGHTS, SCORE_VERSION, score_lead

# NOTA: sync_playwright é importado DENTRO de extrator_worker para evitar
# travamento quando o processo filho (spawn) reimporta este módulo.
import traceback
from bs4 import BeautifulSoup
from multiprocessing import Process
from dotenv import load_dotenv

# Carrega ou cria .env para variáveis de ambiente seguras
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=60)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DB_NAME = "gestao_leads.db"
CONFIG_FILE = "config.json"
PREVIEW_DIR = os.path.join(os.path.dirname(__file__), "generated_previews")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"vendedor_nome": "", "agencia_nome": "", "velocidade": "normal", "headless": True}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return {"vendedor_nome": "", "agencia_nome": "", "velocidade": "normal", "headless": True}

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def config_publica(config):
    config_segura = dict(config)
    config_segura["gemini_configurada"] = bool(
        os.environ.get("GEMINI_API_KEY") or config_segura.get("gemini_api_key")
    )
    config_segura.pop("gemini_api_key", None)
    return config_segura

STATUS_FILE = "search_status.json"
SEARCH_LOCK = threading.Lock()

def atualizar_status(dados):
    try:
        dados["pid"] = os.getpid()
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar status: {e}")

def ler_status():
    if not os.path.exists(STATUS_FILE):
        return {"rodando": False, "mensagem": "Nenhuma busca realizada ainda.", "leads_salvos": 0}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("rodando") and data.get("pid"):
                if not psutil.pid_exists(data["pid"]):
                    data["rodando"] = False
                    data["mensagem"] = "O processo foi interrompido inesperadamente (possivel limite de memoria do servidor)."
            return data
    except Exception:
        return {"rodando": False, "mensagem": "Status indisponivel.", "leads_salvos": 0}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS leads
                 (place_id TEXT PRIMARY KEY, nome TEXT, nicho TEXT, bairro TEXT, nota TEXT,
                  avaliacoes TEXT, telefone TEXT, whatsapp_link TEXT, email TEXT,
                  instagram TEXT, facebook TEXT, linkedin TEXT, link_inicial TEXT,
                  google_maps TEXT, prompt_design TEXT, status TEXT, data_adicao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  copy_texto TEXT, analise_ia TEXT, estrategia_ia TEXT)""")
    # Fallback to alter table if columns are missing
    for col, tipo in [("copy_texto", "TEXT"), ("analise_ia", "TEXT"), ("estrategia_ia", "TEXT"), ("potencial", "INTEGER"), ("motivo_potencial", "TEXT"), ("faixa_potencial", "TEXT"), ("score_breakdown", "TEXT"), ("score_version", "TEXT"), ("copies_pitch", "TEXT"), ("inteligencia_comercial", "TEXT"), ("qualidade_pitch", "TEXT"), ("do_not_contact", "INTEGER DEFAULT 0"), ("do_not_contact_reason", "TEXT"), ("do_not_contact_at", "TIMESTAMP"), ("last_response", "TEXT"), ("next_action", "TEXT"), ("next_action_at", "TIMESTAMP")]:
        try: c.execute(f"ALTER TABLE leads ADD COLUMN {col} {tipo}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS preview_versions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL, version INTEGER NOT NULL,
                  config_json TEXT NOT NULL, html_content TEXT NOT NULL, screenshot_path TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(place_id, version))""")
    c.execute("""CREATE TABLE IF NOT EXISTS lead_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL,
                  interaction_type TEXT NOT NULL, channel TEXT, content TEXT NOT NULL,
                  sentiment TEXT, next_action TEXT, next_action_at TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    legacy_rows = c.execute(
        """SELECT place_id, nome, nicho, bairro, nota, avaliacoes, telefone, email,
                  instagram, facebook, linkedin, link_inicial, google_maps, copies_pitch, copy_texto
           FROM leads"""
    ).fetchall()
    for row in legacy_rows:
        stored_copies = row[13] or ""
        stored_primary = row[14] or ""
        legacy_phrases = (
            "responsável pelo comercial ou marketing",
            "perfil público consultado",
            "oportunidade mais clara",
            "estrutura que recomendaria",
            "pelas informações públicas disponíveis",
        )
        is_legacy = (
            not stored_copies
            or '"personalizada"' not in stored_copies
            or '"recepcao"' not in stored_copies
            or '"email"' not in stored_copies
            or any(phrase in stored_primary.casefold() for phrase in legacy_phrases)
        )
        if not is_legacy:
            continue
        place_id = row[0]
        preview_available = bool(c.execute("SELECT 1 FROM preview_versions WHERE place_id = ? LIMIT 1", (place_id,)).fetchone())
        raw = {
            "Nome": row[1] or "", "Nicho": row[2] or "", "Categoria Maps": row[2] or "",
            "Bairro": row[3] or "", "Nota Maps": row[4] or "", "Qtd Avaliacoes": row[5] or "",
            "Telefone": row[6] or "", "E-mail Encontrado": row[7] or "", "Instagram": row[8] or "",
            "Facebook": row[9] or "", "LinkedIn": row[10] or "", "Link Inicial": row[11] or "",
            "Google Maps": row[12] or "",
        }
        intelligence = analyze_lead(raw, preview_available=preview_available)
        pitches = generate_fallback_pitches(intelligence)
        quality = evaluate_pitches(pitches, intelligence, require_preview=preview_available)
        diagnosis = f"Confiança da análise: {intelligence['confidence']}%. Oportunidade: {intelligence['opportunity']}."
        c.execute(
            """UPDATE leads SET copy_texto = ?, copies_pitch = ?, inteligencia_comercial = ?,
                      qualidade_pitch = ?, analise_ia = ?, estrategia_ia = ?,
                      status = CASE WHEN status = 'Novo' THEN 'Mensagem preparada' ELSE status END
               WHERE place_id = ?""",
            (pitches["consultiva"], json.dumps(pitches, ensure_ascii=False),
             json.dumps(intelligence, ensure_ascii=False), json.dumps(quality, ensure_ascii=False),
             diagnosis, intelligence["main_argument"], place_id),
        )
    conn.commit()
    conn.close()

init_db()

def load_leads():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""SELECT leads.*,
                 (SELECT id FROM preview_versions WHERE preview_versions.place_id = leads.place_id ORDER BY version DESC LIMIT 1) AS latest_preview_id
                 FROM leads ORDER BY data_adicao DESC""")
    rows = c.fetchall()
    conn.close()
    leads = [dict(ix) for ix in rows]
    configured_weights = load_config().get("lead_score_weights")
    for lead in leads:
        scoring = calcular_score_lead(lead, configured_weights=configured_weights)
        lead["potencial"] = scoring["score"]
        lead["motivo_potencial"] = scoring["reason"]
        lead["faixa_potencial"] = scoring["range"]
        lead["score_breakdown"] = scoring
        lead["score_version"] = scoring["version"]
    for lead in leads:
        try:
            lead["copies_pitch"] = json.loads(lead.get("copies_pitch") or "{}")
        except (TypeError, json.JSONDecodeError):
            lead["copies_pitch"] = {}
        for field_name in ("inteligencia_comercial", "qualidade_pitch"):
            try:
                lead[field_name] = json.loads(lead.get(field_name) or "{}")
            except (TypeError, json.JSONDecodeError):
                lead[field_name] = {}
    return leads

def save_lead_db(lead, place_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO leads (place_id, nome, nicho, bairro, nota, avaliacoes, telefone, whatsapp_link, email, instagram, facebook, linkedin, link_inicial, google_maps, prompt_design, status, copy_texto, analise_ia, estrategia_ia, potencial, motivo_potencial, faixa_potencial, score_breakdown, score_version)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Novo', ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (place_id, lead.get("Nome",""), lead.get("Nicho",""), lead.get("Bairro",""), lead.get("Nota Maps",""),
                   lead.get("Qtd Avaliacoes",""), lead.get("Telefone",""), lead.get("WhatsApp Link",""), lead.get("E-mail Encontrado",""),
                   lead.get("Instagram",""), lead.get("Facebook",""), lead.get("LinkedIn",""), lead.get("Link Inicial",""),
                   lead.get("Google Maps",""), lead.get("Prompt Prototipo",""), lead.get("Copy Texto", ""), lead.get("Analise IA", ""), lead.get("Estrategia IA", ""), lead.get("Potencial", 0), lead.get("Motivo Potencial", ""), lead.get("Faixa Potencial", "Oportunidade secundária"), json.dumps(lead.get("Score Breakdown", {}), ensure_ascii=False), lead.get("Score Version", SCORE_VERSION)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_lead_ai(place_id, copy_texto, analise_ia, estrategia_ia, whatsapp_link, copies_pitch=None, inteligencia=None, qualidade=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """UPDATE leads
               SET copy_texto = ?, analise_ia = ?, estrategia_ia = ?, whatsapp_link = ?, copies_pitch = ?,
                   inteligencia_comercial = ?, qualidade_pitch = ?,
                   status = CASE WHEN status = 'Novo' THEN 'Mensagem preparada' ELSE status END
               WHERE place_id = ?""",
            (copy_texto, analise_ia, estrategia_ia, whatsapp_link, json.dumps(copies_pitch or {}, ensure_ascii=False),
             json.dumps(inteligencia or {}, ensure_ascii=False), json.dumps(qualidade or {}, ensure_ascii=False), place_id),
        )
        conn.commit()
    finally:
        conn.close()

def load_existing_place_ids():
    conn = sqlite3.connect(DB_NAME)
    try:
        return {row[0] for row in conn.execute("SELECT place_id FROM leads")}
    finally:
        conn.close()

def tratar_consentimento_cookies(page):
    try:
        seletores = [
            'button:has-text("Aceitar tudo")',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'form[action*="consent"] button',
        ]
        for seletor in seletores:
            botao = page.locator(seletor).first
            if botao.count() > 0 and botao.is_visible(timeout=2000):
                botao.click(timeout=3000)
                print("[WORKER] Tela de consentimento fechada.")
                time.sleep(1)
                return True
    except Exception as e:
        print(f"[WORKER] Sem tela de consentimento (ou falhou ao fechar): {e}")
    return False

def pausa(min_s=1.0, max_s=2.5, config=None):
    if config:
        if config.get("velocidade") == "rapido": min_s, max_s = min_s * 0.5, max_s * 0.5
        elif config.get("velocidade") == "lento": min_s, max_s = min_s * 1.5, max_s * 1.5
    time.sleep(random.uniform(min_s, max_s))

def extrair_apenas_numeros(telefone):
    if not telefone: return ""
    has_plus = telefone.startswith("+")
    numeros = re.sub(r"\D", "", telefone)
    
    if len(numeros) < 10:
        return ""
        
    if has_plus:
        return numeros
        
    if len(numeros) == 10 or len(numeros) == 11:
        return "55" + numeros
        
    return numeros

def eh_celular_valido(numeros):
    if not numeros: return False
    if numeros.startswith("55") and len(numeros) == 13:
        return numeros[4] == "9"
    if not numeros.startswith("55"):
        return True # Aceita internacionais
    return False

def formatar_whatsapp(numeros, copy_texto=""):
    if not numeros: return ""
    url = f"https://wa.me/{numeros}"
    if copy_texto: url += f"?text={urllib.parse.quote(copy_texto)}"
    return url

def normalizar_texto(texto, limite=900):
    return re.sub(r"\s+", " ", texto or "").strip()[:limite]

def extrair_numero_avaliacoes(valor):
    numeros = re.findall(r"\d+", str(valor or "").replace(".", "").replace(",", ""))
    return int("".join(numeros)) if numeros else 0

def calcular_score_lead(lead, tem_site=None, configured_weights=None):
    if tem_site is None:
        tem_site = possui_site_proprio(lead.get("Link Inicial") or lead.get("link_inicial"))
    return score_lead(lead, tem_site, configured_weights)


def calcular_potencial_lead(nota, avaliacoes, telefone, email, instagram, linkedin, tem_site, nicho="", bairro="", facebook="", configured_weights=None):
    scoring = calcular_score_lead({
        "Nota Maps": nota,
        "Qtd Avaliacoes": avaliacoes,
        "Telefone": telefone,
        "E-mail Encontrado": email,
        "Instagram": instagram,
        "Facebook": facebook,
        "LinkedIn": linkedin,
        "Nicho": nicho,
        "Bairro": bairro,
    }, tem_site=tem_site, configured_weights=configured_weights)
    return scoring["score"], scoring["reason"]

def classificar_potencial(potencial, minimo_prioridade=55):
    try:
        potencial = int(potencial or 0)
    except (TypeError, ValueError):
        potencial = 0
    if potencial >= minimo_prioridade:
        return "Prioridade"
    if potencial >= 35:
        return "Oportunidade secundária"
    return "Exploração"


def classificar_prazo_followup(value):
    if not value:
        return "sem_acao"
    try:
        due = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return "sem_acao"
    today = datetime.now().date()
    if due.date() < today:
        return "atrasado"
    if due.date() == today:
        return "hoje"
    return "proximo"

def necessidade_digital_do_nicho(nicho):
    nicho = (nicho or "").casefold()
    if any(termo in nicho for termo in ["odont", "dentist", "clinic", "medic", "saud", "dermat", "estetic"]):
        return "não consegue entender tratamentos, transmitir confiança ou pedir uma avaliação de forma simples"
    if any(termo in nicho for termo in ["advoc", "jurid", "direito"]):
        return "não consegue identificar rapidamente as áreas atendidas nem encontrar um caminho claro para falar com o escritório"
    if any(termo in nicho for termo in ["imob", "corret", "imove"]):
        return "não consegue ver imóveis, diferenciais ou solicitar atendimento sem depender de várias mensagens"
    if any(termo in nicho for termo in ["move", "planejad", "marcen", "arquitet", "interiores", "decor"]):
        return "não consegue ver projetos, perceber o padrão do trabalho ou pedir orçamento com segurança"
    if any(termo in nicho for termo in ["restauran", "bar", "pizz", "hamburg", "caf", "padar", "gastronom"]):
        return "não consegue consultar cardápio, horários e reservas de forma rápida pelo celular"
    return "não encontra uma explicação clara dos serviços nem uma forma simples de iniciar o atendimento"

def normalizar_dados_pitch(dados_lead):
    nome = normalizar_texto(dados_lead.get("Nome", "").split(" - ")[0].split("|")[0], 90)
    categoria = normalizar_texto(dados_lead.get("Categoria Maps") or dados_lead.get("Nicho"), 120)
    site = extrair_destino_externo(dados_lead.get("Link Inicial", ""))
    tem_site = bool(site and not is_social_or_directory(site))
    instagram = extrair_destino_externo(dados_lead.get("Instagram", ""))
    evidencias = []
    if categoria:
        evidencias.append(f"atua em {categoria}")
    if dados_lead.get("Bairro"):
        evidencias.append(f"atende em {normalizar_texto(dados_lead.get('Bairro'), 90)}")
    if instagram:
        evidencias.append("tem Instagram identificado")
    if tem_site:
        evidencias.append("tem site próprio identificado")
    else:
        evidencias.append("não há site próprio identificado no perfil do Google")
    return {
        "nome": nome or "a empresa",
        "categoria": categoria or "o segmento",
        "bairro": normalizar_texto(dados_lead.get("Bairro"), 90),
        "tem_site": tem_site,
        "tem_instagram": bool(instagram),
        "evidencias": evidencias,
        "necessidade": necessidade_digital_do_nicho(categoria or dados_lead.get("Nicho", "")),
    }

def gerar_variacoes_contingencia(dados_lead, is_intl=False):
    dados = normalizar_dados_pitch(dados_lead)
    nome = dados["nome"]
    local = f" em {dados['bairro']}" if dados["bairro"] else ""
    if is_intl:
        base = f"I found {nome}{local} on Google. When someone looks for a {dados['categoria']}, they often need clear information before deciding to get in touch."
        if dados["tem_site"]:
            oportunidade = "There may be an opportunity to make the current website clearer on mobile and easier for visitors to take the next step."
        else:
            oportunidade = "I could not identify a standalone website on the Google profile, so visitors may have to piece together the information before contacting you."
        variacoes = {
            "consultiva": f"{base} {oportunidade} A focused website can organize the essentials and make the next step simpler. Would it be useful if I shared a quick idea?",
            "direta": f"Hi! For {nome}, a clear website can help visitors understand the service and contact the right person without relying only on social profiles. Would you like to see what that could look like?",
            "curiosidade": f"Hi! I noticed an opportunity in how {nome} is presented online{local}. What if a visitor could understand the service and take action in one place? Would you be open to a quick example?",
        }
    else:
        observacao = "não identifiquei um site próprio no perfil do Google" if not dados["tem_site"] else "identifiquei que vocês já possuem um site"
        complemento_instagram = " O Instagram ajuda na descoberta, mas não organiza toda a decisão do cliente." if dados["tem_instagram"] and not dados["tem_site"] else ""
        variacoes = {
            "consultiva": f"Oi! Encontrei a {nome}{local} no Google e {observacao}. Para quem procura {dados['categoria']}, muitas vezes é importante entender o serviço e o próximo passo antes de chamar. Hoje, sem um espaço próprio, a pessoa {dados['necessidade']}.{complemento_instagram} Um site bem organizado pode resolver isso. Posso te mostrar uma ideia?",
            "direta": f"Oi! Vi a {nome}{local} no Google. Quando alguém busca {dados['categoria']}, ter um site claro ajuda a apresentar o essencial e evita que o interesse esfrie antes do contato. {observacao.capitalize()}. Faz sentido eu te mostrar uma possibilidade?",
            "curiosidade": f"Oi! Uma dúvida sobre a {nome}: quando alguém encontra vocês no Google, consegue entender rapidamente o serviço e avançar para o contato? {observacao.capitalize()}. Um site pode concentrar isso em um só lugar. Posso te explicar a ideia em uma imagem?",
        }
    return {estilo: adicionar_triagem_responsavel(texto, is_intl) for estilo, texto in variacoes.items()}

def validar_variacoes_pitch(variacoes, nome_empresa, is_intl=False):
    estilos = ("consultiva", "direta", "curiosidade")
    proibidos = ("próximo nível", "potencialize", "alavanque", "solução personalizada", "desconto", "preço")
    if not isinstance(variacoes, dict) or any(not normalizar_texto(variacoes.get(estilo, "")) for estilo in estilos):
        return False
    textos = [normalizar_texto(variacoes[estilo], 1200) for estilo in estilos]
    if len({texto.casefold() for texto in textos}) != len(textos):
        return False
    marca = normalizar_texto(nome_empresa, 90).casefold()
    for texto in textos:
        palavras = len(texto.split())
        if palavras < 55 or palavras > 125 or ("site" not in texto.casefold() and "website" not in texto.casefold()):
            return False
        if any(termo in texto.casefold() for termo in proibidos):
            return False
        if marca and marca not in texto.casefold():
            return False
    return True

def mensagem_parece_personalizada(mensagem, nome_empresa):
    if len(mensagem.strip()) < 120:
        return False
    palavras_ignoradas = {
        "advocacia", "agencia", "clínica", "clinica", "comércio", "comercio",
        "empresa", "escritório", "escritorio", "ltda", "serviços", "servicos",
    }
    termos_da_marca = [
        termo for termo in re.findall(r"[\wÀ-ÿ]+", nome_empresa.casefold())
        if len(termo) >= 4 and termo not in palavras_ignoradas
    ]
    menciona_marca = not termos_da_marca or any(termo in mensagem.casefold() for termo in termos_da_marca)
    menciona_site = "site" in mensagem.casefold() or "website" in mensagem.casefold()
    return menciona_marca and menciona_site

def adicionar_triagem_responsavel(mensagem, is_intl=False):
    if is_intl:
        abertura = "Hi! Could you please confirm whether this is the contact for the person responsible for marketing or commercial decisions? If this number is used for appointments or reception, could you kindly forward this message to the right person?"
    else:
        abertura = "Olá! Este contato é da pessoa responsável pelo comercial ou marketing? Se este número for de agendamento ou recepção, poderia encaminhar esta mensagem para quem cuida dessa área, por favor?"
    return f"{abertura}\n\n{mensagem}"

def obter_copy_contingencia(dados_lead, vendedor, motivo="", is_intl=False):
    nome_curto = dados_lead.get('Nome', '').split(' - ')[0].split('|')[0].strip()
    nicho = " ".join([
        dados_lead.get('Categoria Maps', ''),
        dados_lead.get('Nicho', ''),
        dados_lead.get('Contexto do Site', ''),
    ]).lower()
    bairro = dados_lead.get('Bairro', '')
    site = dados_lead.get('Link Inicial')
    regiao = f" em {bairro}" if bairro else ""
    
    if any(k in nicho for k in ['advoc', 'jurid', 'direito']):
        if site:
            msg = f"Olá, tudo bem? Localizei o escritório da {nome_curto}{regiao} no Google. Preparei um comparativo visual mostrando como deixar a apresentação das áreas de atuação e o botão de atendimento consultivo mais objetivos para novos clientes. Posso te encaminhar essa sugestão para avaliar?"
        else:
            msg = f"Olá, tudo bem? Localizei o escritório da {nome_curto}{regiao} no Google e notei que vocês têm presença de destaque, mas quem busca atendimento online não encontra uma página institucional rápida com as áreas de atuação. Desenvolvi um modelo visual de apresentação institucional para o escritório. Posso te enviar para você ver?"
        estrategia = "Contingência Setorial: Advocacia (respeito a sobriedade e código de ética, foco em apresentação institucional das áreas e atendimento consultivo)."
    elif any(k in nicho for k in ['odont', 'dentist', 'clinic', 'medic', 'saud', 'dermat', 'estetic']):
        if site:
            msg = f"Olá, tudo bem? Vi a {nome_curto}{regiao} no Google. Estruturei uma proposta visual rápida para otimizar a experiência mobile e facilitar o agendamento de consultas/avaliações direto pelo WhatsApp. Posso te mandar uma prévia para dar uma olhada?"
        else:
            msg = f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google com ótimas avaliações. Notei que os pacientes que encontram a clínica online ainda não têm uma página exclusiva para conhecer os tratamentos e agendar com facilidade. Criei um layout demonstrativo de agendamento online focado nos serviços de vocês. Posso te enviar?"
        estrategia = "Contingência Setorial: Saúde/Estética (foco em confiança, apresentação dos procedimentos e facilidade de agendamento)."
    elif any(k in nicho for k in ['imob', 'corret', 'imove']):
        if site:
            msg = f"Olá, tudo bem? Vi a {nome_curto} atuando no mercado imobiliário{regiao}. Analisei o posicionamento online de vocês e desenhei uma melhoria visual focada em reter proprietários e compradores qualificados direto na página principal, antes que cliquem em concorrentes. Posso te enviar um print da ideia?"
        else:
            msg = f"Olá, tudo bem? Localizei a {nome_curto}{regiao} no Google Maps. Quem busca imóveis na região tem forte interesse visual e praticidade, e notei que vocês ainda não possuem uma página própria para destacar as oportunidades e captar contatos diretos. Desenvolvi um protótipo de landing page imobiliária para vocês. Posso te mostrar?"
        estrategia = "Contingência Setorial: Imobiliário (foco em captação de proprietários e compradores de alto valor)."
    elif any(k in nicho for k in ['move', 'planejad', 'marcen', 'arquitet', 'interiores', 'decor']):
        if site:
            msg = f"Olá, tudo bem? Acompanhei o trabalho da {nome_curto}{regiao} no Google. Montei um layout demonstrativo mostrando como organizar o portfólio de projetos para valorizar ainda mais o padrão de acabamento e estimular pedidos de orçamento qualificados. Posso te enviar uma imagem do projeto?"
        else:
            msg = f"Olá, tudo bem? Vi os projetos e avaliações da {nome_curto}{regiao} no Google Maps. Como o mercado de projetos exige forte apelo visual, preparei um protótipo de portfólio digital para apresentar os trabalhos e direcionar novos clientes para orçamento no WhatsApp. Posso te mostrar como ficou?"
        estrategia = "Contingência Setorial: Arquitetura/Móveis (foco em autoridade visual, acabamento e orçamento)."
    elif any(k in nicho for k in ['restauran', 'bar', 'pizz', 'hamburg', 'caf', 'padar', 'gastronom']):
        if site:
            msg = f"Olá! Encontrei a {nome_curto}{regiao} no Google. Analisei a presença digital de vocês e preparei um rascunho de página otimizada para carregar o cardápio rápido no celular e direcionar reservas sem fricção. Posso te mandar o print?"
        else:
            msg = f"Olá! Vi a {nome_curto}{regiao} no Google com excelente recomendação. Percebi que vocês ainda não contam com uma página rápida com o cardápio e botão de pedidos/reservas direto para quem pesquisa a casa no Google. Criei um modelo visual prático para o espaço de vocês. Quer que eu te envie para ver?"
        estrategia = "Contingência Setorial: Gastronomia (foco em cardápio rápido mobile e reserva/pedido)."
    else:
        if site:
            msg = f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google. Analisei o posicionamento online do segmento de vocês e preparei uma demonstração visual mostrando como simplificar o caminho do visitante até o contato comercial direto. Posso te enviar para dar uma olhada?"
        else:
            msg = f"Olá, tudo bem? Localizei a {nome_curto}{regiao} no Google Maps e vi que vocês já possuem boa visibilidade. Desenvolvi um protótipo visual demonstrando como uma página focada em conversão pode transformar quem já pesquisa pela empresa no Google em contatos reais no WhatsApp. Posso te mostrar como ficou?"
        estrategia = "Contingência Setorial Geral (proposta consultiva de melhoria de conversão/site)."

    if "site" not in msg.casefold() and "website" not in msg.casefold():
        msg = msg.replace(
            " Posso", " A sugestão é para um site pensado para esse atendimento. Posso", 1
        )
    if not site:
        necessidade = necessidade_digital_do_nicho(nicho)
        msg = (
            f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google. Hoje, quem procura vocês ali "
            f"{necessidade}. Sem um site que organize essas informações e conduza o próximo passo, parte desse interesse "
            f"acaba esfriando antes do contato. Posso te mostrar uma ideia simples de como resolver isso para a empresa?"
        )
    versoes = gerar_variacoes_contingencia(dados_lead, is_intl)
    msg = versoes["consultiva"]

    aviso_motivo = f" [Alerta: {motivo}]" if motivo else ""
    return {
        'analise': f"Contingência setorial aplicada com base em dados reais do lead.{aviso_motivo}",
        'estrategia': estrategia,
        'mensagem': msg,
        'versoes': versoes,
        'gerada_por_ia': False,
    }

def gerar_copy_inteligente(dados_lead, config, is_intl=False):
    import json
    import time
    
    nome_curto = dados_lead.get('Nome', '').split(' - ')[0].split('|')[0].strip()
    vendedor = config.get('vendedor_nome', '').strip() or 'aqui'
    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or config.get('gemini_api_key', '').strip()
    
    if not api_key:
        return obter_copy_contingencia(dados_lead, vendedor, motivo="Chave de API do Gemini não configurada", is_intl=is_intl)
        
    try:
        categoria = dados_lead.get('Categoria Maps') or dados_lead.get('Nicho', '')
        resumo = dados_lead.get('Resumo Maps', '')
        titulo_site = dados_lead.get('Título do Site', '')
        descricao_site = dados_lead.get('Descrição do Site', '')
        contexto_site = dados_lead.get('Contexto do Site', '')
        site_encontrado = dados_lead.get('Link Inicial', '')
        tem_site = bool(site_encontrado and not is_social_or_directory(site_encontrado))
        dados_normalizados = normalizar_dados_pitch(dados_lead)
        
        super_prompt = f"""Você é um especialista em prospecção consultiva B2B e criação de sites de alta conversão.
Sua missão é gerar uma mensagem curta e humana de primeiro contato para o WhatsApp do responsável por esta empresa local encontrada no Google Maps.

### DADOS REAIS DO NEGÓCIO:
- Nome da Empresa: {nome_curto}
- Nicho de Busca: {dados_lead.get('Nicho', '')}
- Categoria Real no Google Maps: {categoria}
- Resumo/Atuação: {resumo if resumo else 'Não informado'}
- Título do Site: {titulo_site if titulo_site else 'Não informado'}
- Descrição do Site: {descricao_site if descricao_site else 'Não informada'}
- Serviços/temas visíveis no Site: {contexto_site if contexto_site else 'Não informado'}
- Localização/Bairro: {dados_lead.get('Bairro', '')}
- Prova Social: Nota {dados_lead.get('Nota Maps', 'N/A')} ({dados_lead.get('Qtd Avaliacoes', '0')} avaliações no Google)
- Status de Site: {'SITE PRÓPRIO IDENTIFICADO (' + site_encontrado + ')' if tem_site else 'NENHUM SITE PRÓPRIO IDENTIFICADO NO PERFIL DO GOOGLE — não afirmar ausência absoluta'}
- Evidências verificadas: {"; ".join(dados_normalizados['evidencias'])}
- Meu Nome: {vendedor}

### DIRETRIZES DA ABORDAGEM:
1. FOCO DA PROPOSTA:
   - Se a empresa NÃO tem site: Comece pela necessidade percebida do cliente. Explique, sem alarmismo, o que uma pessoa que encontra a empresa no Google ainda não consegue fazer, entender ou decidir sem um site. Mostre a consequência prática: parte do interesse esfria, vira dúvida ou segue para outra opção antes do contato. Só depois apresente o site como o caminho natural para resolver esse problema.
   - Se a empresa JÁ tem site: Reconheça a presença atual e apresente uma oportunidade clara de otimização (conversão mobile, velocidade, apresentação de serviços ou retenção). Mostre que rascunhou uma sugestão visual sem compromisso.
2. ADAPTAÇÃO AO NICHO:
   - Advocacia: Sobriedade institucional, respeito ao código da OAB (sem promessas de causas/ganhos, foco em clareza das áreas e contato ético).
   - Saúde/Odonto/Clínicas: Credibilidade, apresentação dos tratamentos e facilidade de agendamento/tira-dúvidas.
   - Imobiliária/Corretores: Captação de proprietários, destaque visual dos imóveis e atendimento ágil.
   - Móveis/Arquitetura: Portfólio, projetos concluídos e solicitação de orçamento.
   - Gastronomia/Comércio: Praticidade mobile, cardápio rápido e pedidos/reservas.
3. ESTILO DE REDAÇÃO:
   - Tom natural, humano, direto e profissional.
   - Cada versão deve ter entre 45 e 90 palavras. Uma abertura de triagem será incluída pelo sistema depois.
   - NUNCA use clichês como: "próximo nível", "potencialize sua presença", "transforme sua presença", "solução personalizada", "alavanque resultados".
   - CTA (Chamada de Ação) de baixíssima fricção no final: uma pergunta simples para continuar a conversa, sem pedir reunião ou proposta.
   - Nunca pergunte "vamos marcar reunião" ou "posso enviar proposta comercial". O objetivo é apenas conseguir a permissão para mostrar a demonstração.
    - Diga explicitamente que a sugestão é de um SITE. A palavra "site" deve aparecer naturalmente na mensagem; não use apenas "página", "presença digital" ou "layout" de forma vaga.
    - Se o Nicho de Busca contrariar a Categoria Real ou o conteúdo do Site, use a Categoria Real e o conteúdo do Site. Nunca escreva uma abordagem de estética para uma empresa jurídica, por exemplo.
    - Cite apenas um detalhe que esteja nos dados reais acima. Se não houver detalhe confiável, use uma abordagem neutra do segmento, sem inventar serviços.
   - Não fale como um vendedor oferecendo um serviço, não comece com "preparei um site", "tenho uma proposta" ou "quero vender". A mensagem deve soar como uma observação útil sobre uma oportunidade que o próprio negócio está deixando passar.
4. CONTATO DE RECEPÇÃO/AGENDAMENTO:
   - O número do Google Maps pode ser de recepção, agendamento ou atendimento. Não assuma que a pessoa é dona da empresa.
   - Escreva apenas a parte comercial da mensagem. O sistema adicionará antes uma pergunta educada pedindo o responsável por marketing/comercial e solicitando encaminhamento caso seja recepção ou agendamento.

5. VARIAÇÕES:
   - Crie três abordagens realmente diferentes: consultiva (observação + contexto), direta (benefício específico) e curiosidade (pergunta que abre uma conversa).
   - Não invente serviços, problemas técnicos, números, site ausente ou conteúdo de rede social. Se os dados forem insuficientes, use uma observação exploratória.

### FORMATO DE SAÍDA OBRIGATÓRIO (JSON):
Retorne estritamente um objeto JSON com as chaves:
{{
  "diagnostico": "Resumo em 1-2 frases do diagnóstico da presença digital da empresa.",
  "estrategia": "Explicação do ângulo comercial adotado e o porquê.",
  "versoes": {{
    "consultiva": "Mensagem consultiva completa.",
    "direta": "Mensagem direta completa.",
    "curiosidade": "Mensagem de curiosidade completa."
  }}
}}
"""
        if is_intl:
            super_prompt += '\n\nIMPORTANTE: Escreva as três mensagens em INGLÊS natural.'
        
        modelos_candidatos = MODEL_CANDIDATES
        resposta_bruta = ""
        for m_name in modelos_candidatos:
            try:
                response_text = generate_text(api_key, m_name, super_prompt, json_mode=True)
                if response_text:
                    resposta_bruta = response_text
                    break
            except Exception as e:
                print(f"[WORKER] Modelo {m_name} indisponível: {str(e)[:100]}")
                continue

        if not resposta_bruta:
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Modelos Gemini atingiram limite de quota diária (429)", is_intl=is_intl)

        resposta_bruta = re.sub(r"^```(?:json)?\s*|\s*```$", "", resposta_bruta.strip(), flags=re.IGNORECASE)
        parsed = json.loads(resposta_bruta)
        versoes_sem_triagem = parsed.get("versoes", {})
        diagnostico = parsed.get("diagnostico", "").strip()
        estrategia = parsed.get("estrategia", "").strip()
        versoes = {
            estilo: adicionar_triagem_responsavel(normalizar_texto(versoes_sem_triagem.get(estilo, ""), 900), is_intl)
            for estilo in ("consultiva", "direta", "curiosidade")
        }
        if not validar_variacoes_pitch(versoes, nome_curto, is_intl):
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Resposta da IA sem variações personalizadas e verificáveis", is_intl=is_intl)
        mensagem = versoes["consultiva"]

        return {
            'analise': f"DIAGNÓSTICO:\n{diagnostico}" if diagnostico else "Análise concluída via IA.",
            'estrategia': estrategia or "Abordagem consultiva com proposta de melhoria/protótipo de site.",
            'mensagem': mensagem,
            'versoes': versoes,
            'gerada_por_ia': True,
        }
        
    except Exception as e:
        print(f'[WORKER] Erro AI: {e}')
        return obter_copy_contingencia(dados_lead, vendedor, motivo=f"Erro na execução da IA: {e}", is_intl=is_intl)


def gerar_copy_profissional(dados_lead, config, is_intl=False, preview_available=False):
    inteligencia = analyze_lead(dados_lead, preview_available=preview_available)
    inteligencia["language"] = "en" if is_intl else "pt-BR"
    fallback = generate_fallback_pitches(inteligencia, is_intl=is_intl)
    qualidade_fallback = evaluate_pitches(fallback, inteligencia, require_preview=preview_available)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or config.get("gemini_api_key", "").strip()
    versoes = fallback
    gerada_por_ia = False
    motivo = "Modelo profissional local aplicado"

    if api_key:
        modos = ["consultiva", "direta", "personalizada", "recepcao", "email"]
        if preview_available:
            modos.append("previa_visual")
        tentativas = 0
        feedback = None
        for model_name in MODEL_CANDIDATES:
            if tentativas >= 2:
                break
            tentativas += 1
            try:
                prompt = build_generation_prompt(inteligencia, modos, feedback=feedback, is_intl=is_intl)
                response_text = generate_text(api_key, model_name, prompt, json_mode=True)
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.IGNORECASE)
                candidate = json.loads(raw).get("versoes", {})
                candidate = {mode: normalizar_texto(candidate.get(mode, ""), 1200) for mode in modos}
                candidate = {**fallback, **candidate}
                qualidade = evaluate_pitches(candidate, inteligencia, require_preview=preview_available)
                if qualidade["approved"]:
                    versoes = candidate
                    qualidade_fallback = qualidade
                    gerada_por_ia = True
                    motivo = f"Aprovada após {tentativas} tentativa(s) de IA"
                    break
                feedback = qualidade["reasons"]
                motivo = f"IA reprovada na tentativa {tentativas}: {qualidade['reasons']}"
            except Exception as error:
                motivo = f"IA indisponível na tentativa {tentativas}: {str(error)[:160]}"

    evidencias = inteligencia.get("verified", [])
    resumo = "\n".join(f"• {item['claim']} — Fonte: {item['source']}" for item in evidencias)
    analise = (
        f"Confiança da análise: {inteligencia['confidence']}%.\n"
        f"Oportunidade: {inteligencia['opportunity']}.\n"
        f"Evidências verificadas:\n{resumo}"
    )
    qualidade_fallback["processing_note"] = motivo
    return {
        "analise": analise,
        "estrategia": inteligencia["main_argument"],
        "mensagem": versoes["consultiva"],
        "versoes": versoes,
        "inteligencia": inteligencia,
        "qualidade": qualidade_fallback,
        "gerada_por_ia": gerada_por_ia,
    }


gerar_copy_inteligente = gerar_copy_profissional


def gerar_prompt_prototipo(nome, nicho):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    base = f"UI/UX web design of a modern, high-converting landing page for a {nicho} business named '{nome_curto}'. "
    design = "Clean layout, professional typography, hero section with a clear call-to-action button, services overview section, testimonials, WhatsApp floating button. Modern corporate colors, highly trustworthy."
    return base + design + " Dribbble style, Behance style, 8k resolution, photorealistic ui."

def extrair_id_unico(href):
    if not href: return str(random.random())
    match = re.search(r"1s(0x[^:]+:0x[a-f0-9]+)", href)
    return match.group(1) if match else href.split("?")[0]

def extrair_avaliacoes(page):
    nota = "0"
    qtd = "0"
    try:
        elementos = page.locator("[aria-label]")
        for i in range(min(elementos.count(), 300)):
            aria = elementos.nth(i).get_attribute("aria-label")
            if not aria: continue
            aria_normalizado = aria.lower()
            if nota == "0":
                match_nota = re.search(r"([\d,.]+)\s*(?:estrelas?|stars?)", aria_normalizado)
                if match_nota: nota = match_nota.group(1)
            if qtd == "0":
                match_qtd = re.search(r"([\d,.]+)\s*(?:avalia(?:cao|coes|ção|ções)|reviews?)", aria_normalizado)
                if match_qtd: qtd = match_qtd.group(1).replace(".", "").replace(",", "")
            if nota != "0" and qtd != "0":
                break
    except Exception as e: print("Aviso interno:", e)
    return nota, qtd

def check_auth(username, password):
    valid_user = os.environ.get("APP_USER", "")
    valid_pass = os.environ.get("APP_PASS", "")
    return bool(valid_user and valid_pass and username and password) and (
        hmac.compare_digest(username, valid_user) and hmac.compare_digest(password, valid_pass)
    )

@app.before_request
def require_login():
    if request.endpoint in ("static", "login", "health"):
        return
    
    # Suporte para requisições com Authorization Header (compatibilidade com automações/curl)
    auth = request.authorization
    if auth and check_auth(auth.username, auth.password):
        return

    # Autenticação via Sessão Web duradoura (cookie)
    if not session.get("authenticated"):
        if request.path.startswith("/api/") or request.path.startswith("/status_"):
            return jsonify({"success": False, "error": "Não autenticado"}), 401
        dest = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=dest))

    # Validação de origem em requisições de mutação
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != request.host:
            return jsonify({"success": False, "error": "Origem da requisição não permitida"}), 403

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    
    erro = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if check_auth(username, password):
            session.permanent = True
            session["authenticated"] = True
            session["user"] = username
            
            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("index")
            return redirect(next_url)
        else:
            erro = "Usuário ou senha incorretos. Verifique suas credenciais."
            
    return render_template("login.html", erro=erro)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.after_request
def aplicar_cabecalhos_seguranca(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if request.endpoint == "preview_document" else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.endpoint == "preview_document":
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; script-src 'none'; connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    if request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.route("/")
def index():
    return render_template("search.html")


@app.route("/health")
def health():
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("SELECT 1").fetchone()
        preview_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preview_versions'").fetchone()
        interaction_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lead_interactions'").fetchone()
        conn.close()
        ready = bool(preview_table and interaction_table)
        return jsonify({
            "status": "ok" if ready else "degraded",
            "database": "ok",
            "studio": bool(preview_table),
            "follow_up": bool(interaction_table),
            "commercial_release": "2026.10",
            "lead_score_version": SCORE_VERSION,
            "pitch_modes": 5,
        }), 200 if ready else 503
    except Exception:
        return jsonify({"status": "error", "database": "unavailable"}), 503

@app.route("/crm")
def crm():
    todos = load_leads()
    ativos = [l for l in todos if l.get("status") != "Descartado"]
    for lead in ativos:
        lead["follow_up_state"] = classificar_prazo_followup(lead.get("next_action_at"))
    leads_com_site = sum(1 for lead in ativos if possui_site_proprio(lead.get("link_inicial")))
    follow_up_counts = {state: sum(1 for lead in ativos if lead["follow_up_state"] == state) for state in ("atrasado", "hoje", "proximo", "sem_acao")}
    return render_template("crm.html", leads=ativos, leads_com_site=leads_com_site, is_descartados=False, follow_up_counts=follow_up_counts)

@app.route("/crm/descartados")
def crm_descartados():
    todos = load_leads()
    descartados = [l for l in todos if l.get("status") == "Descartado"]
    for lead in descartados:
        lead["follow_up_state"] = classificar_prazo_followup(lead.get("next_action_at"))
    return render_template("crm.html", leads=descartados, leads_com_site=0, is_descartados=True, follow_up_counts={})


def get_lead_by_id(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,)).fetchone()
    conn.close()
    if not row:
        return None
    lead = dict(row)
    for field_name in ("copies_pitch", "inteligencia_comercial", "qualidade_pitch", "score_breakdown"):
        try:
            lead[field_name] = json.loads(lead.get(field_name) or "{}")
        except (TypeError, json.JSONDecodeError):
            lead[field_name] = {}
    scoring = calcular_score_lead(lead, configured_weights=load_config().get("lead_score_weights"))
    lead["potencial"] = scoring["score"]
    lead["motivo_potencial"] = scoring["reason"]
    lead["faixa_potencial"] = scoring["range"]
    lead["score_breakdown"] = scoring
    lead["score_version"] = scoring["version"]
    return lead


def lead_to_raw_data(lead):
    return {
        "Nome": lead.get("nome", ""), "Nicho": lead.get("nicho", ""),
        "Categoria Maps": lead.get("nicho", ""), "Bairro": lead.get("bairro", ""),
        "Nota Maps": lead.get("nota", ""), "Qtd Avaliacoes": lead.get("avaliacoes", ""),
        "Telefone": lead.get("telefone", ""), "E-mail Encontrado": lead.get("email", ""),
        "Instagram": lead.get("instagram", ""), "Facebook": lead.get("facebook", ""),
        "LinkedIn": lead.get("linkedin", ""), "Link Inicial": lead.get("link_inicial", ""),
        "Google Maps": lead.get("google_maps", ""),
    }


def lead_is_international(lead):
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    if phone and not phone.startswith("55"):
        return True
    location = (lead.get("bairro", "") or "").casefold()
    markers = ("usa", "united states", "portugal", "lisboa", "lisbon", "europe", "europa", "london", "madrid", "miami", "new york")
    return any(marker in location for marker in markers)


def get_preview_versions(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, place_id, version, config_json, screenshot_path, created_at FROM preview_versions WHERE place_id = ? ORDER BY version DESC",
        (place_id,),
    ).fetchall()
    conn.close()
    previews = []
    for row in rows:
        preview = dict(row)
        try:
            preview["config"] = json.loads(preview.pop("config_json"))
        except (TypeError, json.JSONDecodeError):
            preview["config"] = {}
        previews.append(preview)
    return previews


def get_lead_interactions(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM lead_interactions WHERE place_id = ? ORDER BY created_at DESC, id DESC",
        (place_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def suggest_next_action(response_text, sentiment, preview_available=False):
    response = (response_text or "").casefold()
    if sentiment == "não contatar" or any(term in response for term in ("não tenho interesse", "nao tenho interesse", "não chamar", "nao chamar", "remover contato")):
        return "Marcar como não contatar e encerrar a abordagem."
    if sentiment == "interessado" or any(term in response for term in ("tenho interesse", "pode enviar", "manda", "gostei", "quero ver")):
        return "Enviar a prévia visual e confirmar qual objetivo do site deve receber prioridade." if preview_available else "Gerar uma prévia visual e confirmar qual objetivo do site deve receber prioridade."
    if sentiment == "objeção" or any(term in response for term in ("preço", "valor", "caro", "orçamento", "orcamento")):
        return "Entender o escopo necessário antes de falar em investimento e responder sem pressionar."
    if sentiment == "sem momento" or any(term in response for term in ("agora não", "agora nao", "depois", "outro momento")):
        return "Registrar o prazo indicado pelo lead e fazer apenas um retorno na data combinada."
    if response_text:
        return "Revisar a resposta, esclarecer a dúvida apresentada e definir um único próximo passo."
    return "Fazer um acompanhamento curto em três dias úteis, sem repetir a mensagem inicial."


@app.route("/leads/<path:place_id>")
def lead_detail(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return "Lead não encontrado", 404
    previews = get_preview_versions(place_id)
    intelligence = lead.get("inteligencia_comercial") or analyze_lead(lead_to_raw_data(lead), preview_available=bool(previews))
    interactions = get_lead_interactions(place_id)
    return render_template("lead_detail.html", lead=lead, intelligence=intelligence, previews=previews, interactions=interactions)


@app.route("/leads/<path:place_id>/studio")
def preview_studio(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return "Lead não encontrado", 404
    previews = get_preview_versions(place_id)
    initial_config = previews[0]["config"] if previews else build_preview_config(lead_to_raw_data(lead))
    return render_template("studio.html", lead=lead, previews=previews, initial_config=initial_config)


@app.route("/api/leads/<path:place_id>/previews", methods=["POST"])
def create_preview(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or request.form.to_dict()
    config = build_preview_config(lead_to_raw_data(lead), payload)
    html = render_preview_html(config)
    conn = sqlite3.connect(DB_NAME)
    try:
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM preview_versions WHERE place_id = ?", (place_id,)).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO preview_versions (place_id, version, config_json, html_content) VALUES (?, ?, ?, ?)",
            (place_id, version, json.dumps(config, ensure_ascii=False), html),
        )
        preview_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    screenshot_path = os.path.join(PREVIEW_DIR, f"preview_{preview_id}.png")
    screenshot_error = ""
    try:
        capture_preview_png(html, screenshot_path)
        conn = sqlite3.connect(DB_NAME)
        conn.execute("UPDATE preview_versions SET screenshot_path = ? WHERE id = ?", (screenshot_path, preview_id))
        conn.commit()
        conn.close()
    except Exception as error:
        screenshot_error = str(error)[:240]

    raw = lead_to_raw_data(lead)
    result = gerar_copy_inteligente(raw, load_config(), is_intl=lead_is_international(lead), preview_available=True)
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    whatsapp = formatar_whatsapp(phone, result["mensagem"]) if phone else lead.get("whatsapp_link", "")
    update_lead_ai(place_id, result["mensagem"], result["analise"], result["estrategia"], whatsapp,
                   result["versoes"], result["inteligencia"], result["qualidade"])
    return jsonify({
        "success": True, "preview_id": preview_id, "version": version,
        "preview_url": url_for("preview_document", preview_id=preview_id),
        "png_url": url_for("preview_png", preview_id=preview_id),
        "screenshot_ready": not bool(screenshot_error), "screenshot_error": screenshot_error,
    })


@app.route("/preview/<int:preview_id>")
def preview_document(preview_id):
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute("SELECT html_content FROM preview_versions WHERE id = ?", (preview_id,)).fetchone()
    conn.close()
    if not row:
        return "Prévia não encontrada", 404
    return Response(row[0], mimetype="text/html")


@app.route("/preview/<int:preview_id>/png")
def preview_png(preview_id):
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute("SELECT html_content, screenshot_path FROM preview_versions WHERE id = ?", (preview_id,)).fetchone()
    conn.close()
    if not row:
        return "Prévia não encontrada", 404
    screenshot_path = row[1] or os.path.join(PREVIEW_DIR, f"preview_{preview_id}.png")
    if not os.path.exists(screenshot_path):
        try:
            capture_preview_png(row[0], screenshot_path)
            conn = sqlite3.connect(DB_NAME)
            conn.execute("UPDATE preview_versions SET screenshot_path = ? WHERE id = ?", (screenshot_path, preview_id))
            conn.commit()
            conn.close()
        except Exception as error:
            return jsonify({"success": False, "error": f"Não foi possível gerar o PNG: {error}"}), 503
    return send_file(screenshot_path, mimetype="image/png", as_attachment=True, download_name=f"previa-site-{preview_id}.png")


@app.route("/api/leads/<path:place_id>/regenerate-pitches", methods=["POST"])
def regenerate_lead_pitches(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    previews = get_preview_versions(place_id)
    result = gerar_copy_inteligente(lead_to_raw_data(lead), load_config(), is_intl=lead_is_international(lead), preview_available=bool(previews))
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    whatsapp = formatar_whatsapp(phone, result["mensagem"]) if phone else lead.get("whatsapp_link", "")
    update_lead_ai(place_id, result["mensagem"], result["analise"], result["estrategia"], whatsapp,
                   result["versoes"], result["inteligencia"], result["qualidade"])
    return jsonify({"success": True, "versoes": result["versoes"], "qualidade": result["qualidade"]})


@app.route("/api/leads/<path:place_id>/pitch", methods=["PATCH"])
def save_lead_pitch(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "")
    text = normalizar_texto(payload.get("text", ""), 1400)
    allowed = {"consultiva", "direta", "personalizada", "recepcao", "email", "previa_visual"}
    if mode not in allowed or not text:
        return jsonify({"success": False, "error": "Modalidade ou texto inválido"}), 400
    copies = dict(lead.get("copies_pitch") or {})
    copies[mode] = text
    intelligence = lead.get("inteligencia_comercial") or analyze_lead(lead_to_raw_data(lead), bool(get_preview_versions(place_id)))
    quality = evaluate_pitches(copies, intelligence, require_preview=bool(get_preview_versions(place_id)))
    primary = copies.get("consultiva") or text
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    whatsapp = formatar_whatsapp(phone, primary) if phone else lead.get("whatsapp_link", "")
    update_lead_ai(place_id, primary, lead.get("analise_ia", ""), lead.get("estrategia_ia", ""), whatsapp,
                   copies, intelligence, quality)
    return jsonify({"success": True, "qualidade": quality})


@app.route("/api/leads/<path:place_id>/follow-up", methods=["POST"])
def save_lead_follow_up(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    response_text = normalizar_texto(payload.get("response", ""), 1800)
    channel = normalizar_texto(payload.get("channel", "WhatsApp"), 40)
    sentiment = normalizar_texto(payload.get("sentiment", "neutro"), 40).casefold()
    allowed_sentiments = {"neutro", "interessado", "objeção", "sem momento", "não contatar"}
    if sentiment not in allowed_sentiments:
        return jsonify({"success": False, "error": "Classificação da resposta inválida"}), 400
    next_action = normalizar_texto(payload.get("next_action", ""), 700)
    if not next_action:
        next_action = suggest_next_action(response_text, sentiment, bool(get_preview_versions(place_id)))
    next_action_at = normalizar_texto(payload.get("next_action_at", ""), 30) or None
    if next_action_at and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?", next_action_at):
        return jsonify({"success": False, "error": "Data da próxima ação inválida"}), 400
    if not response_text and not next_action:
        return jsonify({"success": False, "error": "Informe uma resposta ou próxima ação"}), 400

    status = "Interessado" if sentiment == "interessado" else "Respondeu" if response_text else lead.get("status", "Novo")
    do_not_contact = sentiment == "não contatar"
    if do_not_contact:
        status = "Perdido"
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """INSERT INTO lead_interactions
               (place_id, interaction_type, channel, content, sentiment, next_action, next_action_at)
               VALUES (?, 'resposta', ?, ?, ?, ?, ?)""",
            (place_id, channel, response_text or "Próxima ação registrada", sentiment, next_action, next_action_at),
        )
        conn.execute(
            """UPDATE leads SET last_response = ?, next_action = ?, next_action_at = ?, status = ?,
               do_not_contact = CASE WHEN ? THEN 1 ELSE do_not_contact END,
               do_not_contact_reason = CASE WHEN ? THEN ? ELSE do_not_contact_reason END,
               do_not_contact_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE do_not_contact_at END
               WHERE place_id = ?""",
            (response_text, next_action, next_action_at, status, do_not_contact, do_not_contact,
             response_text or "Preferência registrada", do_not_contact, place_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "next_action": next_action, "status": status, "do_not_contact": do_not_contact})


@app.route("/api/leads/<path:place_id>/do-not-contact", methods=["POST"])
def update_do_not_contact(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    blocked = bool(payload.get("blocked", True))
    reason = normalizar_texto(payload.get("reason", "Preferência de não contato registrada"), 500)
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """UPDATE leads SET do_not_contact = ?, do_not_contact_reason = ?,
               do_not_contact_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
               status = CASE WHEN ? THEN 'Perdido' ELSE 'Respondeu' END WHERE place_id = ?""",
            (int(blocked), reason if blocked else "", blocked, blocked, place_id),
        )
        conn.execute(
            "INSERT INTO lead_interactions (place_id, interaction_type, channel, content, sentiment) VALUES (?, 'preferencia', 'Sistema', ?, ?)",
            (place_id, reason if blocked else "Permissão de contato reaberta manualmente", "não contatar" if blocked else "neutro"),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "blocked": blocked})

@app.route("/estatisticas")
def estatisticas():
    leads = load_leads()
    total_leads = len(leads)
    com_whats = sum(1 for l in leads if l.get("whatsapp_link"))
    fechados = sum(1 for l in leads if l.get("status") == "Fechado")
    em_negociacao = sum(1 for l in leads if l.get("status") in ("Interessado", "Proposta enviada", "Negociação", "Em Negociação"))
    contacted_statuses = {"Contatado", "Contato Feito", "Respondeu", "Interessado", "Proposta enviada", "Negociação", "Em Negociação", "Fechado"}
    response_statuses = {"Respondeu", "Interessado", "Proposta enviada", "Negociação", "Em Negociação", "Fechado"}
    interest_statuses = {"Interessado", "Proposta enviada", "Negociação", "Em Negociação", "Fechado"}
    proposal_statuses = {"Proposta enviada", "Negociação", "Em Negociação", "Fechado"}
    contato_feito = sum(1 for l in leads if l.get("status") in contacted_statuses)
    responderam = sum(1 for l in leads if l.get("status") in response_statuses)
    interessados = sum(1 for l in leads if l.get("status") in interest_statuses)
    propostas = sum(1 for l in leads if l.get("status") in proposal_statuses)
    qualificados = sum(1 for l in leads if l.get("faixa_potencial") == "Prioridade")
    descartados = sum(1 for l in leads if l.get("status") == "Descartado")
    novos = sum(1 for l in leads if l.get("status") in ("Novo", None, ""))
    sem_site = sum(1 for l in leads if not possui_site_proprio(l.get("link_inicial")))
    com_site = total_leads - sem_site
    com_email = sum(1 for l in leads if l.get("email"))

    taxa_sem_site = round((sem_site / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_whats = round((com_whats / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_fechamento = round((fechados / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_resposta = round((responderam / contato_feito * 100), 1) if contato_feito else 0
    taxa_interesse = round((interessados / responderam * 100), 1) if responderam else 0
    taxa_proposta = round((propostas / interessados * 100), 1) if interessados else 0
    taxa_conversao_contato = round((fechados / contato_feito * 100), 1) if contato_feito else 0

    return render_template(
        "estatisticas.html",
        total=total_leads,
        whats=com_whats,
        fechados=fechados,
        em_negociacao=em_negociacao,
        contato_feito=contato_feito,
        responderam=responderam,
        interessados=interessados,
        propostas=propostas,
        qualificados=qualificados,
        descartados=descartados,
        novos=novos,
        sem_site=sem_site,
        com_site=com_site,
        com_email=com_email,
        taxa_sem_site=taxa_sem_site,
        taxa_whats=taxa_whats,
        taxa_fechamento=taxa_fechamento,
        taxa_resposta=taxa_resposta,
        taxa_interesse=taxa_interesse,
        taxa_proposta=taxa_proposta,
        taxa_conversao_contato=taxa_conversao_contato,
        leads=leads,
    )

@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        data = load_config()
        nova_configuracao = request.form.to_dict()
        api_key = nova_configuracao.pop("gemini_api_key", "").strip()
        score_weights = {}
        for key, default in DEFAULT_WEIGHTS.items():
            raw_value = nova_configuracao.pop(f"score_{key}", str(default))
            try:
                score_weights[key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                score_weights[key] = default
        if sum(score_weights.values()) == 100:
            data["lead_score_weights"] = score_weights
        data.update(nova_configuracao)
        if api_key:
            data["gemini_api_key"] = api_key
        data["headless"] = "headless" in nova_configuracao
        save_config(data)
        return render_template("configuracoes.html", config=config_publica(data), success=True)
    return render_template("configuracoes.html", config=config_publica(load_config()), success=False)

@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.get_json(silent=True) or {}
    place_id = data.get("place_id", "")
    status = data.get("status", "")
    status_validos = {
        "Novo", "Analisado", "Mensagem preparada", "Contatado", "Respondeu",
        "Interessado", "Proposta enviada", "Negociação", "Fechado", "Perdido", "Descartado",
        "Contato Feito", "Em Negociação",
    }
    if not place_id or status not in status_validos:
        return jsonify({"success": False, "error": "Status ou lead inválido"}), 400
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (status, place_id))
    if c.rowcount > 0:
        c.execute(
            "INSERT INTO lead_interactions (place_id, interaction_type, channel, content, sentiment) VALUES (?, 'mudanca_etapa', 'Sistema', ?, 'neutro')",
            (place_id, f"Etapa alterada para {status}"),
        )
    conn.commit()
    atualizado = c.rowcount > 0
    conn.close()
    if not atualizado:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    return jsonify({"success": True})

@app.route("/export/csv")
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM leads", conn)
    conn.close()
    csv_data = df.to_csv(index=False)
    return Response(csv_data, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=meu_crm_completo.csv"})

@app.route("/dossie/<place_id>")
def dossie(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,))
    lead = c.fetchone()
    conn.close()
    if not lead: return "Lead nao encontrado", 404
    lead_original = dict(lead)
    instagram_url = extrair_destino_externo(lead_original.get("instagram"))
    linkedin_url = extrair_destino_externo(lead_original.get("linkedin"))
    site_url = extrair_destino_externo(lead_original.get("link_inicial"))
    lead = {campo: texto_html_seguro(valor) for campo, valor in lead_original.items()}
    instagram_link = f"<a href='{texto_html_seguro(instagram_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Acessar Perfil</a>" if instagram_url else "<span class='text-orange-500'>Nao localizado</span>"
    linkedin_link = f"<a href='{texto_html_seguro(linkedin_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Acessar Perfil</a>" if linkedin_url else "Nao localizado"
    site_link = f"<a href='{texto_html_seguro(site_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Visualizar</a>" if site_url else "<span class='text-red-500 font-bold'>Nenhum link cadastrado no Google!</span>"
    email_info = lead["email"] or "<span class='text-red-500 font-bold'>Vazamento: Nenhum e-mail de contato encontrado.</span>"
    
    analise_ia = lead['analise_ia'] if 'analise_ia' in lead.keys() and lead['analise_ia'] else 'N/A'
    estrategia_ia = lead['estrategia_ia'] if 'estrategia_ia' in lead.keys() and lead['estrategia_ia'] else 'N/A'
    copy_texto = lead['copy_texto'] if 'copy_texto' in lead.keys() and lead['copy_texto'] else 'N/A'
    
    diagnostico_site = (
        "A empresa já possui um site cadastrado no Google. A oportunidade é melhorar como ele apresenta serviços e converte visitas em contatos."
        if possui_site_proprio(lead_original.get("link_inicial"))
        else "A empresa ainda não possui um site institucional próprio cadastrado no Google, o que pode dificultar a conversão de pessoas que já a encontram online."
    )
    html = f"""<!DOCTYPE html><html lang="pt-BR" class="dark"><head><meta charset="UTF-8"><title>Auditoria Digital - {lead['nome']}</title><script src="https://cdn.tailwindcss.com"></script><link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"><style>body{{font-family:'Plus Jakarta Sans',sans-serif;}}</style></head>
    <body class="bg-[#090a0f] text-[#f0f6fc] p-6 md:p-10 antialiased">
    <div class="max-w-3xl mx-auto bg-[#12151c] p-8 md:p-10 rounded-2xl shadow-2xl border border-[#222733]">
    <div class="flex justify-between items-start mb-6 pb-6 border-b border-[#222733]"><div><h1 class="text-2xl md:text-3xl font-black mb-1 text-white">Auditoria de Presença Digital</h1><h2 class="text-lg text-slate-300 font-semibold">{lead['nome']}</h2></div><div class="text-right"><span class="inline-block bg-[#161b26] border border-[#262c3a] text-slate-300 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider">{lead['nicho']}</span></div></div>
    <p class="text-slate-400 text-sm mb-8">Análise de presença comercial e captação na região de <strong class="text-white">{lead['bairro']}</strong>.</p>
    <div class="grid grid-cols-2 gap-4 mb-8"><div class="bg-[#090d14] border border-[#222733] p-5 rounded-xl text-center"><span class="block text-3xl font-black text-white mb-1">{lead['nota']} ★</span><span class="text-[11px] font-bold text-slate-500 uppercase tracking-widest">Nota no Google Maps</span></div><div class="bg-[#090d14] border border-[#222733] p-5 rounded-xl text-center"><span class="block text-3xl font-black text-white mb-1">{lead['avaliacoes']}</span><span class="text-[11px] font-bold text-slate-500 uppercase tracking-widest">Avaliações Públicas</span></div></div>
    <div class="mb-8"><h3 class="text-sm font-bold text-white uppercase tracking-wider mb-4 border-b border-[#222733] pb-2">Canais de Contato Detectados</h3><ul class="space-y-2.5 text-xs text-slate-300"><li><strong class="text-slate-400">Telefone / WhatsApp:</strong> {lead['telefone'] or 'Não disponível'}</li><li><strong class="text-slate-400">E-mail:</strong> {email_info}</li><li><strong class="text-slate-400">Instagram:</strong> {instagram_link}</li><li><strong class="text-slate-400">LinkedIn:</strong> {linkedin_link}</li><li><strong class="text-slate-400">Website Oficial:</strong> {site_link}</li></ul></div>
    
    <div class="mb-8 bg-[#090d14] rounded-xl p-5 border border-[#222733]">
        <h3 class="text-sm font-black text-white uppercase tracking-wider mb-4 border-b border-[#222733] pb-2">Diagnóstico Comercial & Abordagem</h3>
        <div class="mb-4">
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">1. Diagnóstico do Negócio</h4>
            <p class="text-slate-200 text-xs bg-[#12151c] p-3 rounded-lg border border-[#222733]">{analise_ia}</p>
        </div>
        <div class="mb-4">
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">2. Ângulo de Venda Recomendado</h4>
            <p class="text-slate-200 text-xs bg-[#12151c] p-3 rounded-lg border border-[#222733]">{estrategia_ia}</p>
        </div>
        <div>
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">3. Abordagem WhatsApp</h4>
            <div class="text-slate-200 bg-[#12151c] p-4 rounded-lg border border-[#222733] text-xs shadow-inner whitespace-pre-wrap">{copy_texto}</div>
        </div>
    </div>
    
    <div class="bg-[#161b26] border border-[#262c3a] p-5 rounded-xl mb-4"><h3 class="text-sm font-bold text-white mb-2">Diagnóstico de Presença</h3><p class="text-xs text-slate-300 leading-relaxed mb-2">{texto_html_seguro(diagnostico_site)}</p><p class="text-xs text-slate-400">Oportunidade para aumentar a taxa de conversão entre quem pesquisa no Google e quem chama no WhatsApp.</p></div>
    <div class="bg-[#12151c] border border-[#222733] p-5 rounded-xl"><h3 class="text-sm font-bold text-white mb-2">Recomendação Comercial</h3><p class="text-xs text-slate-300 leading-relaxed">Desenvolvimento de uma <strong>Landing Page de Alta Conversão</strong> focada em velocidade mobile e contato direto via WhatsApp.</p></div>
    <p class="text-center text-[11px] text-slate-500 mt-8">Relatório emitido via GestãoLead PRO &bull; Antigravity Architecture</p></div></body></html>"""
    return html

import urllib.request
import urllib.parse

def buscar_email_web(nome, bairro):
    busca = f'"{nome}" {bairro} email'
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(busca)
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", "ignore")
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
        emails = [e for e in emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")) and "sentry" not in e and "example" not in e and "wix" not in e and "sitedobem" not in e]
        return emails[0] if emails else ""
    except Exception as e:
        return ""

def is_social_or_directory(url):
    if not url: return False
    url = url.lower()
    domains = ["facebook.com", "instagram.com", "linkedin.com", "linktr.ee", "wa.me", "api.whatsapp", "yelp.", "tripadvisor.", "yellowpages.", "foursquare."]
    return any(d in url for d in domains)

def extrair_destino_externo(url):
    if not url:
        return ""
    url = str(url).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("google.com"):
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", params.get("q", [url]))[0]
    return url if url.startswith(("http://", "https://")) else ""

def possui_site_proprio(url):
    destino = extrair_destino_externo(url)
    return bool(destino and not is_social_or_directory(destino))

def texto_html_seguro(valor):
    return str(escape(valor or ""))

def cacar_dados_profundos(context, url, nome="", bairro=""):
    dados = {
        "email": "", "instagram": "", "facebook": "", "linkedin": "",
        "titulo_site": "", "descricao_site": "", "contexto_site": "",
    }
    
    # Se tem URL, tenta extrair da URL
    if url and not is_social_or_directory(url):
        try:
            req_url = url if url.startswith(("http://", "https://")) else "http://" + url
            req = urllib.request.Request(
                req_url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read(400_000).decode("utf-8", "replace")
            soup = BeautifulSoup(content, "html.parser")
            dados["titulo_site"] = normalizar_texto(
                soup.title.get_text(" ", strip=True) if soup.title else "", 180
            )
            meta_descricao = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
            dados["descricao_site"] = normalizar_texto(
                meta_descricao.get("content", "") if meta_descricao else "", 400
            )
            titulos = [
                normalizar_texto(tag.get_text(" ", strip=True), 160)
                for tag in soup.find_all(["h1", "h2"])[:8]
            ]
            dados["contexto_site"] = normalizar_texto(
                " | ".join(titulo for titulo in titulos if titulo), 700
            )
                
            emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
            emails = [e for e in emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")) and "sentry" not in e and "example" not in e]
            if emails: dados["email"] = emails[0]
            
            ig = re.search(r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+", content)
            if ig: dados["instagram"] = ig.group(0)
            
            fb = re.search(r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+", content)
            if fb: dados["facebook"] = fb.group(0)
            
            li = re.search(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_.-]+", content)
            if li: dados["linkedin"] = li.group(0)
            
        except Exception as e:
            print(f"[WORKER] Erro ao buscar HTML de {url}: {e}")
            pass

    if url:
        url_lower = url.lower()
        if "instagram.com" in url_lower: dados["instagram"] = url
        if "facebook.com" in url_lower: dados["facebook"] = url
        if "linkedin.com" in url_lower: dados["linkedin"] = url

    # Se ainda nao tem email (ex: empresa sem site), faz busca web profunda!
    if not dados["email"] and nome:
        print(f"[WORKER] Sem email no site/sem site para {nome}. Buscando na web...")
        dados["email"] = buscar_email_web(nome, bairro)
        
    return dados

def extrator_worker(data, config, queue):
    try:
        from playwright.sync_api import sync_playwright  # Import aqui para spawn funcionar
        process = psutil.Process(os.getpid())
        mem_inicial = process.memory_info().rss / (1024 * 1024)
        print(f"[WORKER] Iniciando. Memoria RAM uso atual: {mem_inicial:.2f} MB")
        stats = {
            "encontrados": 0,
            "analisados": 0,
            "salvos": 0,
            "duplicados": 0,
            "com_site": 0,
            "franquias": 0,
            "fora_regiao": 0,
            "telefone_invalido": 0,
            "nota_baixa": 0,
            "sem_whatsapp": 0,
            "sem_email": 0,
            "prioridade": 0,
            "oportunidade_secundaria": 0,
            "exploracao": 0,
            "erros": 0,
        }
        existing_place_ids = load_existing_place_ids()

        def publicar_status(mensagem, rodando=True):
            cancelamento_solicitado = ler_status().get("cancelamento_solicitado", False)
            atualizar_status({
                "rodando": rodando,
                "mensagem": mensagem,
                "leads_salvos": stats["salvos"],
                "metricas": stats.copy(),
                "cancelamento_solicitado": cancelamento_solicitado,
            })

        def busca_cancelada():
            if not ler_status().get("cancelamento_solicitado", False):
                return False
            publicar_status("Busca cancelada. Os leads já salvos foram mantidos.", rodando=False)
            return True

        publicar_status("Abrindo navegador...")
        nichos = [n.strip() for n in data["nichos"].split(",") if n.strip()]
        bairros = [b.strip() for b in data["bairros"].split(",") if b.strip()]
        print(f"[WORKER] nichos={nichos}, bairros={bairros}")
        is_headless = config.get("headless", True)
        GRANDES_REDES = ["odontocompany","smart fit","smartfit","mcdonalds","boticario","cacau show","subway","sorridents","amorasaude","bluefit","pague menos","raia","drogasil","localiza","unidas","movida"]
        with sync_playwright() as p:
            args = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--disable-software-rasterizer"
            ]
            browser = p.chromium.launch(headless=is_headless, args=args)
            print("[WORKER] Browser aberto.")
            context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 800})
            page = context.new_page()
            if is_headless:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            consent_ok = False
            for bairro in bairros:
                if busca_cancelada():
                    browser.close()
                    return
                for nicho in nichos:
                    if busca_cancelada():
                        browser.close()
                        return
                    busca = f"{nicho} {bairro}"
                    print(f"[WORKER] Buscando: {busca}")
                    publicar_status(f"Buscando '{nicho}' em '{bairro}'...")
                    url = f"https://www.google.com/maps/search/{urllib.parse.quote(busca)}"
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        print(f"[WORKER] Pagina: {page.title()} | {page.url}")
                        if not consent_ok:
                            tratar_consentimento_cookies(page)
                            consent_ok = True
                        time.sleep(3)
                    except Exception as e:
                        print(f"[WORKER] Erro ao carregar pagina: {e}"); continue
                    try:
                        page.wait_for_selector("a.hfpxzc", state="attached", timeout=8000)
                        print("[WORKER] Resultados encontrados!")
                    except Exception as e:
                        print(f"[WORKER] Timeout inicial a.hfpxzc: {e} | titulo: {page.title()}")
                    try:
                        painel = page.locator("div[role='feed']").first
                        if painel.count() > 0:
                            for _ in range(8):
                                painel.evaluate("node => node.scrollTop = node.scrollHeight")
                                time.sleep(random.uniform(0.5, 1.2))
                                page.keyboard.press("PageDown") # Fallback
                    except Exception as e: print("Aviso interno painel:", e)
                    
                    links = page.locator("a.hfpxzc")
                    if links.count() == 0:
                        links = page.locator("a[href*='/maps/place/']")
                        
                    if links.count() == 0:
                        print("[WORKER] Definitivamente nenhum lead encontrado.")
                        continue
                    hrefs = []
                    for i in range(min(links.count(), 50)):
                        h = links.nth(i).get_attribute("href")
                        if h and h not in hrefs: hrefs.append(h)
                    stats["encontrados"] += len(hrefs)
                    for index, href in enumerate(hrefs):
                        if busca_cancelada():
                            browser.close()
                            return
                        place_id = extrair_id_unico(href)
                        if place_id in existing_place_ids:
                            stats["duplicados"] += 1
                            publicar_status(f"Ignorando duplicado {index+1}/{len(hrefs)}...")
                            continue
                        try:
                            stats["analisados"] += 1
                            publicar_status(f"Analisando lead {index+1}/{len(hrefs)}...")
                            page.goto(href, wait_until="domcontentloaded", timeout=20000)
                            try: page.wait_for_selector("h1", timeout=5000)
                            except Exception as e: print("Aviso interno:", e)
                            
                            time.sleep(2) # Aguarda renderizacao basica
                            
                            # Tenta esperar explicitamente pelo elemento do site caso ele demore mais que o h1
                            try: page.wait_for_selector("a[data-item-id='authority']", timeout=3000)
                            except: pass
                            
                            nome_el = page.locator("h1").first
                            nome = nome_el.inner_text() if nome_el.count() > 0 else page.title().split(" - Google")[0]
                            if not nome or "Google Maps" in nome: continue
                            if data.get("anti_franchise") and any(rede in nome.lower() for rede in GRANDES_REDES):
                                stats["franquias"] += 1
                                continue
                            
                            link_el = page.locator("a[data-item-id='authority'], a[data-tooltip='Abrir website'], a[data-tooltip='Open website']")
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            link_encontrado = extrair_destino_externo(link_encontrado)
                            if not link_encontrado:
                                # Fallback robusto via regex de atributo aria-label e links externos
                                fallback = page.locator("a[aria-label*='ebsite'], a[aria-label*='site'], a[href^='http']").all()
                                for f in fallback:
                                    hf = extrair_destino_externo(f.get_attribute("href"))
                                    if hf:
                                        link_encontrado = hf
                                        break
                                        
                            is_real_website = possui_site_proprio(link_encontrado)
                            if data.get("strict_no_socials") and is_real_website:
                                stats["com_site"] += 1
                                print(f"[WORKER] Ignorando {nome} - Possui SITE REAL ({link_encontrado}) e o filtro de EXCLUIR COM SITE esta ativo.")
                                continue

                            tel_el = page.locator("button[data-item-id^='phone']")
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)
                            if data.get("strict_mobile") and not eh_celular_valido(numeros_whats):
                                stats["telefone_invalido"] += 1
                                continue
                            end_el = page.locator("button[data-item-id='address']")
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereco: ", "").strip() if end_el.count() > 0 else ""
                            if data.get("strict_bairro") and bairro.split("-")[0].strip().lower() not in endereco.lower():
                                stats["fora_regiao"] += 1
                                continue
                            nota_str, avaliacoes_str = extrair_avaliacoes(page)
                            try: nota_float = float(nota_str.replace(",", "."))
                            except ValueError: nota_float = 0.0
                            if nota_float < float(data.get("min_nota", 0)):
                                stats["nota_baixa"] += 1
                                print(f"[WORKER] Ignorando {nome} - Nota {nota_float} muito baixa")
                                continue
                            if data.get("req_whatsapp") and not numeros_whats:
                                stats["sem_whatsapp"] += 1
                                print(f"[WORKER] Ignorando {nome} - Sem WhatsApp")
                                continue
                            categoria_el = page.locator("button[jsaction*='pane.rating.category'], span[jsaction*='pane.rating.category'], button[data-item-id='address'] + div button, div.fontBodyMedium button").first
                            categoria_maps = ""
                            try:
                                if categoria_el.count() > 0:
                                    categoria_maps = categoria_el.inner_text().strip()
                            except Exception:
                                pass

                            resumo_el = page.locator("div[aria-label*='Sobre'], div.PYvSYb, div[jslog*='metadata']").first
                            resumo_maps = ""
                            try:
                                if resumo_el.count() > 0:
                                    resumo_maps = resumo_el.inner_text().strip()[:200]
                            except Exception:
                                pass

                            print(f"[WORKER] Iniciando cacador profundo para {nome}...")
                            dados_profundos = cacar_dados_profundos(context, link_encontrado, nome=nome, bairro=bairro)
                            if data.get("req_email") and not dados_profundos["email"]:
                                stats["sem_email"] += 1
                                print(f"[WORKER] Ignorando {nome} - Sem e-mail encontrado")
                                continue

                            scoring = calcular_score_lead({
                                "Nicho": nicho,
                                "Categoria Maps": categoria_maps or nicho,
                                "Bairro": bairro,
                                "Nota Maps": nota_str,
                                "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw,
                                "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                            }, tem_site=is_real_website, configured_weights=config.get("lead_score_weights"))
                            potencial = scoring["score"]
                            motivo_potencial = scoring["reason"]
                            try:
                                minimo_potencial = max(0, min(100, int(data.get("min_potencial", 55))))
                            except (TypeError, ValueError):
                                minimo_potencial = 55
                            faixa_potencial = classificar_potencial(potencial, minimo_prioridade=minimo_potencial)
                            if faixa_potencial == "Prioridade":
                                stats["prioridade"] += 1
                            elif faixa_potencial == "Oportunidade secundária":
                                stats["oportunidade_secundaria"] += 1
                            else:
                                stats["exploracao"] += 1
                            
                            dados_raw = {
                                "Nome": nome, "Nicho": nicho, "Bairro": bairro,
                                "Categoria Maps": categoria_maps or nicho,
                                "Resumo Maps": resumo_maps,
                                "Nota Maps": nota_str, "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw, "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Link Inicial": link_encontrado,
                                "Título do Site": dados_profundos["titulo_site"],
                                "Descrição do Site": dados_profundos["descricao_site"],
                                "Contexto do Site": dados_profundos["contexto_site"],
                            }
                            
                            is_intl = data.get("mercado", "br") != "br"
                            whats_link_final = formatar_whatsapp(numeros_whats, "") if numeros_whats else ""
                            lead_data = {
                                "Nome": nome, "Nicho": nicho, "Bairro": bairro,
                                "Nota Maps": nota_str, "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw, "WhatsApp Link": whats_link_final,
                                "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                                "Link Inicial": link_encontrado,
                                "Google Maps": href,
                                "Prompt Prototipo": gerar_prompt_prototipo(nome, nicho),
                                "Potencial": potencial,
                                "Motivo Potencial": motivo_potencial,
                                "Faixa Potencial": faixa_potencial,
                                "Score Breakdown": scoring,
                                "Score Version": scoring["version"],
                                "Copy Texto": "",
                                "Analise IA": "",
                                "Estrategia IA": ""
                            }
                            salvo = save_lead_db(lead_data, place_id)
                            if salvo:
                                print(f"[WORKER] Salvo com sucesso: {nome}")
                                existing_place_ids.add(place_id)
                                stats["salvos"] += 1
                                publicar_status(f"Lead salvo: {nome}")

                                if data.get("ai_copy"):
                                    publicar_status(f"Gerando mensagem para: {nome}")
                                    resultado_ia = gerar_copy_inteligente(dados_raw, config, is_intl)
                                    copy_texto = resultado_ia.get("mensagem", "")
                                    analise_ia = resultado_ia.get("analise", "")
                                    estrategia_ia = resultado_ia.get("estrategia", "")
                                    if resultado_ia.get("gerada_por_ia"):
                                        publicar_status(f"Mensagem personalizada pronta: {nome}")
                                    else:
                                        publicar_status(f"Mensagem de contingência criada: {nome}")
                                        print(f"[WORKER] Gemini indisponível para {nome}; revise a mensagem antes de enviar.")
                                    whats_link_final = formatar_whatsapp(numeros_whats, copy_texto) if numeros_whats else ""
                                    update_lead_ai(
                                        place_id,
                                        copy_texto,
                                        analise_ia,
                                        estrategia_ia,
                                        whats_link_final,
                                        resultado_ia.get("versoes", {}),
                                        resultado_ia.get("inteligencia", {}),
                                        resultado_ia.get("qualidade", {}),
                                    )
                        except Exception as e:
                            stats["erros"] += 1
                            print(f"[WORKER] Erro no lead {href}: {e}")
            print("[WORKER] Fechando navegador.")
            mem_final = process.memory_info().rss / (1024 * 1024)
            print(f"[WORKER] Finalizando. Memoria RAM uso final: {mem_final:.2f} MB")
            publicar_status("Busca finalizada.", rodando=False)
            browser.close()
        print("[WORKER] Finalizado com sucesso.")
    except Exception as e:
        print(f"[WORKER] ERRO FATAL: {e}")
        atualizar_status({"rodando": False, "mensagem": f"Erro: {e}", "leads_salvos": 0})

@app.route("/api/status")
def api_status():
    return jsonify(ler_status())

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(silent=True) or {}
    if not data.get("nichos") or not data.get("bairros"):
        return jsonify({"success": False, "error": "Nichos ou Bairros vazios"})
    with SEARCH_LOCK:
        if ler_status().get("rodando"):
            return jsonify({"success": False, "error": "Já existe uma busca em andamento."}), 409
        config = load_config()
        atualizar_status({"rodando": True, "mensagem": "Busca iniciada, abrindo navegador...", "leads_salvos": 0, "cancelamento_solicitado": False})
        t = threading.Thread(target=extrator_worker, args=(data, config, None), daemon=True)
        t.start()
    return jsonify({"success": True, "salvos": "Em andamento", "message": "Busca iniciada em segundo plano."})

@app.route("/api/cancelar_busca", methods=["POST"])
def cancelar_busca():
    with SEARCH_LOCK:
        status = ler_status()
        if not status.get("rodando"):
            return jsonify({"success": False, "error": "Não há uma busca em andamento."}), 409
        status["cancelamento_solicitado"] = True
        status["mensagem"] = "Cancelamento solicitado. Finalizando o lead atual..."
        atualizar_status(status)
    return jsonify({"success": True, "message": "Cancelamento solicitado."})

@app.route("/api/sugerir_alvos", methods=["GET"])
def sugerir_alvos():
    try:
        regiao = request.args.get('regiao', 'br').lower()
        mercados = {
            "br": {
                "descricao": "no Brasil",
                "cidades": ["Alphaville - SP", "Moema - Sao Paulo", "Balneario Camboriu - SC", "Nova Lima - MG", "Batel - Curitiba", "Itaim Bibi - Sao Paulo", "Leblon - Rio de Janeiro", "Jardins - Sao Paulo", "Campinas - SP", "Lago Sul - Brasilia"],
            },
            "us": {
                "descricao": "somente nos Estados Unidos",
                "cidades": ["Miami - FL", "Boca Raton - FL", "Naples - FL", "Scottsdale - AZ", "Austin - TX", "Beverly Hills - CA", "Irvine - CA", "Dallas - TX", "Manhattan - NY", "Greenwich - CT"],
            },
            "europa": {
                "descricao": "somente em paises europeus",
                "cidades": ["London - UK", "Dublin - Ireland", "Amsterdam - Netherlands", "Madrid - Spain", "Barcelona - Spain", "Milan - Italy", "Lisbon - Portugal", "Porto - Portugal", "Zurich - Switzerland", "Paris - France"],
            },
        }
        if regiao not in mercados:
            return jsonify({"erro": "Mercado invalido."}), 400
        import random
        cidades_permitidas = mercados[regiao]["cidades"]
        config = load_config()
        api_key = os.environ.get("GEMINI_API_KEY", "").strip() or config.get("gemini_api_key", "").strip()
        
        if api_key:
            try:
                contexto_regiao = mercados[regiao]["descricao"]
                
                prompt = f"""Atue como um estrategista de vendas B2B.
Eu prospecto empresas no Google Maps para vender criação de Sites de Alta Conversão.
Preciso que você me sugira 5 Nichos de Alto Valor (High-Ticket) e 5 Cidades com alto poder aquisitivo {contexto_regiao}.

Regras:
1. Nichos devem ser muito lucrativos (ex: cirurgia plástica, móveis planejados, arquitetura de luxo, energia solar, clínicas especializadas).
2. Os nichos devem fazer sentido para {contexto_regiao}.
3. Retorne EXATAMENTE UM JSON válido e mais nada. O formato deve ser:
{{
  "nichos": ["Nicho 1", "Nicho 2", "Nicho 3", "Nicho 4", "Nicho 5"],
  "cidades": ["Cidade 1", "Cidade 2", "Cidade 3", "Cidade 4", "Cidade 5"]
}}"""
                texto, _ = first_available_response(api_key, prompt, json_mode=True, attempt_limit=2)
                texto = texto.replace("```json", "").replace("```", "").strip()

                if texto:
                    import json
                    dados_ia = json.loads(texto)
                    return jsonify({
                        "nichos": dados_ia.get("nichos", [])[:5],
                        "cidades": random.sample(cidades_permitidas, 5)
                    })
            except Exception as e:
                print(f"[IA] Erro ao gerar sugestões: {e}")
                # Fallback para o hardcoded se a IA falhar
        
        # Fallback Hardcoded
        nichos_ht = [
            "Advogado Trabalhista", "CirurgiÃƒÆ’Ã‚Â£o PlÃƒÆ’Ã‚Â¡stico", "ClÃƒÆ’Ã‚Â­nica de EstÃƒÆ’Ã‚Â©tica", "ImobiliÃƒÆ’Ã‚Â¡ria de Alto PadrÃƒÆ’Ã‚Â£o",
            "ClÃƒÆ’Ã‚Â­nica OdontolÃƒÆ’Ã‚Â³gica", "EscritÃƒÆ’Ã‚Â³rio de Contabilidade", "Energia Solar", "Arquitetura e Interiores",
            "Construtora", "ClÃƒÆ’Ã‚Â­nica VeterinÃƒÆ’Ã‚Â¡ria", "ConcessionÃƒÆ’Ã‚Â¡ria de VeÃƒÆ’Ã‚Â­culos", "Consultoria Financeira",
            "Personal Trainer de Elite", "Psiquiatra", "Dermatologista", "MÃƒÆ’Ã‚Â³veis Planejados", "Seguros"
        ]
        
        cidades_br = [
            "Alphaville SP", "Moema SÃƒÆ’Ã‚Â£o Paulo", "BalneÃƒÆ’Ã‚Â¡rio CamboriÃƒÆ’Ã‚Âº SC", "Nova Lima MG", 
            "Batel Curitiba", "Itaim Bibi SP", "Leblon RJ", "JurerÃƒÆ’Ã‚Âª Internacional SC",
            "Campinas SP", "RibeirÃƒÆ’Ã‚Â£o Preto SP", "Jardins SÃƒÆ’Ã‚Â£o Paulo", "Lago Sul BrasÃƒÆ’Ã‚Â­lia"
        ]
        cidades_intl = [
            "Miami FL", "Orlando FL", "Beverly Hills CA", "Brickell Miami", "Boca Raton FL",
            "Manhattan NY", "Kensington London", "Dubai Marina", "Aventura FL", "Sunny Isles Beach FL"
        ]
        
        cidades_pool = cidades_permitidas
        
        selecionados_nichos = random.sample(nichos_ht, 5)
        selecionados_cidades = random.sample(cidades_pool, 5)
        
        return jsonify({
            "nichos": selecionados_nichos,
            "cidades": selecionados_cidades
        })
    except Exception as e:
        print("[ERRO IA SugestÃƒÆ’Ã‚Â£o]:", e)
        return jsonify({"erro": str(e)}), 500

@app.route("/api/limpar_crm", methods=["POST"])
def limpar_crm():
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        screenshot_paths = [row[0] for row in c.execute("SELECT screenshot_path FROM preview_versions WHERE screenshot_path IS NOT NULL").fetchall()]
        c.execute("DELETE FROM lead_interactions")
        c.execute("DELETE FROM preview_versions")
        c.execute("DELETE FROM leads")
        conn.commit()
        conn.close()
        preview_root = os.path.abspath(PREVIEW_DIR)
        for screenshot_path in screenshot_paths:
            absolute_path = os.path.abspath(screenshot_path)
            if os.path.commonpath((preview_root, absolute_path)) == preview_root and os.path.isfile(absolute_path):
                os.remove(absolute_path)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/descartar_com_site", methods=["POST"])
def descartar_com_site():
    conn = sqlite3.connect(DB_NAME)
    try:
        rows = conn.execute(
            "SELECT place_id, link_inicial FROM leads WHERE status != 'Descartado'"
        ).fetchall()
        place_ids = [place_id for place_id, link in rows if possui_site_proprio(link)]
        if place_ids:
            conn.executemany(
                "UPDATE leads SET status = 'Descartado' WHERE place_id = ?",
                [(place_id,) for place_id in place_ids],
            )
            conn.commit()
        return jsonify({"success": True, "descartados": len(place_ids)})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": "Não foi possível classificar os leads"}), 500
    finally:
        conn.close()

@app.route("/api/test_gemini", methods=["POST"])
def test_gemini():
    data = request.json or {}
    api_key = data.get("key", "").strip()
    chave_enviada = bool(api_key)
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip() or load_config().get("gemini_api_key", "").strip()
        
    if not api_key:
        return jsonify({"success": False, "error": "Informe uma API Key para testar."})
        
    try:
        _, model_name = first_available_response(api_key, "Diga apenas 'ok'", attempt_limit=2)
        if chave_enviada:
            cfg = load_config()
            cfg["gemini_api_key"] = api_key
            save_config(cfg)
            os.environ["GEMINI_API_KEY"] = api_key
        return jsonify({"success": True, "message": f"Conexão bem-sucedida! Modelo ativo: {model_name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

STATUS_REGEN = {
    "rodando": False,
    "total": 0,
    "processados": 0,
    "mensagem": "",
    "concluido": False,
}
REGEN_LOCK = threading.Lock()

def worker_regenerar_copys():
    global STATUS_REGEN
    try:
        config = load_config()
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM leads ORDER BY data_adicao DESC")
        leads = [dict(ix) for ix in c.fetchall()]
        conn.close()

        total = len(leads)
        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = True
            STATUS_REGEN["total"] = total
            STATUS_REGEN["processados"] = 0
            STATUS_REGEN["concluido"] = False
            STATUS_REGEN["mensagem"] = f"Iniciando regeneração de {total} copys..."

        for idx, lead in enumerate(leads, 1):
            place_id = lead.get("place_id")
            nome = lead.get("nome", "Lead")
            with REGEN_LOCK:
                STATUS_REGEN["processados"] = idx
                STATUS_REGEN["mensagem"] = f"Atualizando ({idx}/{total}): {nome[:30]}"

            dados_raw = {
                "Nome": lead.get("nome", "") or "",
                "Nicho": lead.get("nicho", "") or "",
                "Categoria Maps": lead.get("nicho", "") or "",
                "Bairro": lead.get("bairro", "") or "",
                "Nota Maps": lead.get("nota", "") or "",
                "Qtd Avaliacoes": lead.get("avaliacoes", "0") or "0",
                "Telefone": lead.get("telefone", "") or "",
                "E-mail Encontrado": lead.get("email", "") or "",
                "Instagram": lead.get("instagram", "") or "",
                "Facebook": lead.get("facebook", "") or "",
                "LinkedIn": lead.get("linkedin", "") or "",
                "Link Inicial": lead.get("link_inicial", "") or "",
                "Google Maps": lead.get("google_maps", "") or "",
                "Prompt Prototipo": lead.get("prompt_design", "") or "",
            }

            tel = extrair_apenas_numeros(lead.get("telefone", ""))
            is_intl = bool(tel and not tel.startswith("55"))
            if not is_intl:
                local = (lead.get("bairro", "") or "").lower()
                intl_kws = ["usa", "fl", "ny", "tx", "ca", "london", "uk", "portugal", "lisbon", "spain", "madrid", "united states"]
                is_intl = any(k in local for k in intl_kws)

            try:
                res_ia = gerar_copy_inteligente(dados_raw, config, is_intl=is_intl)
                c_texto = res_ia.get("mensagem", "")
                a_ia = res_ia.get("analise", "")
                e_ia = res_ia.get("estrategia", "")
                v_pitch = res_ia.get("versoes", {})

                w_link = formatar_whatsapp(tel, c_texto) if tel and eh_celular_valido(tel) else lead.get("whatsapp_link", "")

                update_lead_ai(
                    place_id,
                    c_texto,
                    a_ia,
                    e_ia,
                    w_link,
                    v_pitch,
                    res_ia.get("inteligencia", {}),
                    res_ia.get("qualidade", {}),
                )
            except Exception as e:
                print(f"[REGEN] Erro no lead {nome}: {e}")

            time.sleep(0.8)

        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = False
            STATUS_REGEN["concluido"] = True
            STATUS_REGEN["mensagem"] = f"Todas as {total} copys foram atualizadas com sucesso!"
    except Exception as e:
        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = False
            STATUS_REGEN["mensagem"] = f"Erro na regeneração: {e}"

@app.route("/api/regenerar_copys", methods=["POST"])
def api_regenerar_copys():
    with REGEN_LOCK:
        if STATUS_REGEN["rodando"]:
            return jsonify({"success": False, "error": "Já existe uma regeneração em andamento."}), 409
        t = threading.Thread(target=worker_regenerar_copys, daemon=True)
        t.start()
    return jsonify({"success": True, "message": "Regeneração de copys iniciada em segundo plano."})

@app.route("/api/status_regenerar_copys", methods=["GET"])
def api_status_regenerar_copys():
    with REGEN_LOCK:
        return jsonify(dict(STATUS_REGEN))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)










