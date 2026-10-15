import os
import json
import time
import random
import re
import urllib.parse
import sqlite3
import multiprocessing
import hmac
from datetime import timedelta
import threading
import psutil
import pandas as pd
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from markupsafe import escape
import google.generativeai as genai

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
    for col in ["copy_texto", "analise_ia", "estrategia_ia"]:
        try: c.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")
        except: pass
    conn.commit()
    conn.close()

init_db()

def load_leads():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM leads ORDER BY data_adicao DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(ix) for ix in rows]

def save_lead_db(lead, place_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO leads (place_id, nome, nicho, bairro, nota, avaliacoes, telefone, whatsapp_link, email, instagram, facebook, linkedin, link_inicial, google_maps, prompt_design, status, copy_texto, analise_ia, estrategia_ia)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Novo', ?, ?, ?)""",
                  (place_id, lead.get("Nome",""), lead.get("Nicho",""), lead.get("Bairro",""), lead.get("Nota Maps",""),
                   lead.get("Qtd Avaliacoes",""), lead.get("Telefone",""), lead.get("WhatsApp Link",""), lead.get("E-mail Encontrado",""),
                   lead.get("Instagram",""), lead.get("Facebook",""), lead.get("LinkedIn",""), lead.get("Link Inicial",""),
                   lead.get("Google Maps",""), lead.get("Prompt Prototipo",""), lead.get("Copy Texto", ""), lead.get("Analise IA", ""), lead.get("Estrategia IA", "")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_lead_ai(place_id, copy_texto, analise_ia, estrategia_ia, whatsapp_link):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """UPDATE leads
               SET copy_texto = ?, analise_ia = ?, estrategia_ia = ?, whatsapp_link = ?
               WHERE place_id = ?""",
            (copy_texto, analise_ia, estrategia_ia, whatsapp_link, place_id),
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
    msg = adicionar_triagem_responsavel(msg, is_intl)

    aviso_motivo = f" [Alerta: {motivo}]" if motivo else ""
    return {
        'analise': f"Contingência setorial aplicada com base em dados reais do lead.{aviso_motivo}",
        'estrategia': estrategia,
        'mensagem': msg,
        'gerada_por_ia': False,
    }

def gerar_copy_inteligente(dados_lead, config, is_intl=False):
    import google.generativeai as genai
    import json
    import time
    
    nome_curto = dados_lead.get('Nome', '').split(' - ')[0].split('|')[0].strip()
    vendedor = config.get('vendedor_nome', '').strip() or 'aqui'
    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or config.get('gemini_api_key', '').strip()
    
    if not api_key:
        return obter_copy_contingencia(dados_lead, vendedor, motivo="Chave de API do Gemini não configurada", is_intl=is_intl)
        
    try:
        genai.configure(api_key=api_key)
        
        categoria = dados_lead.get('Categoria Maps') or dados_lead.get('Nicho', '')
        resumo = dados_lead.get('Resumo Maps', '')
        titulo_site = dados_lead.get('Título do Site', '')
        descricao_site = dados_lead.get('Descrição do Site', '')
        contexto_site = dados_lead.get('Contexto do Site', '')
        site_encontrado = dados_lead.get('Link Inicial', '')
        tem_site = bool(site_encontrado and not is_social_or_directory(site_encontrado))
        
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
- Status de Site: {'JÁ POSSUI SITE PRÓPRIO (' + site_encontrado + ')' if tem_site else 'NÃO POSSUI SITE PRÓPRIO (ou apenas rede social/diretório)'}
- Meu Nome: {vendedor}

### DIRETRIZES DA ABORDAGEM:
1. FOCO DA PROPOSTA:
   - Se a empresa NÃO tem site: Apresente a oportunidade de transformar quem já acha a empresa no Google em contatos qualificados. Mostre que você já preparou um modelo/protótipo visual específico para o segmento deles e pergunte se pode enviar uma imagem/prévia.
   - Se a empresa JÁ tem site: Reconheça a presença atual e apresente uma oportunidade clara de otimização (conversão mobile, velocidade, apresentação de serviços ou retenção). Mostre que rascunhou uma sugestão visual sem compromisso.
2. ADAPTAÇÃO AO NICHO:
   - Advocacia: Sobriedade institucional, respeito ao código da OAB (sem promessas de causas/ganhos, foco em clareza das áreas e contato ético).
   - Saúde/Odonto/Clínicas: Credibilidade, apresentação dos tratamentos e facilidade de agendamento/tira-dúvidas.
   - Imobiliária/Corretores: Captação de proprietários, destaque visual dos imóveis e atendimento ágil.
   - Móveis/Arquitetura: Portfólio, projetos concluídos e solicitação de orçamento.
   - Gastronomia/Comércio: Praticidade mobile, cardápio rápido e pedidos/reservas.
3. ESTILO DE REDAÇÃO:
   - Tom natural, humano, direto e profissional.
   - A parte comercial deve ter entre 220 e 480 caracteres, pois uma abertura de triagem será incluída pelo sistema.
   - NUNCA use clichês como: "próximo nível", "potencialize sua presença", "transforme sua presença", "solução personalizada", "alavanque resultados".
   - CTA (Chamada de Ação) de baixíssima fricção no final: "Posso te mandar uma imagem para você ver?", "Quer que eu te envie para dar uma olhada?", "Posso te mostrar o que preparei?".
   - Nunca pergunte "vamos marcar reunião" ou "posso enviar proposta comercial". O objetivo é apenas conseguir a permissão para mostrar a demonstração.
    - Diga explicitamente que a sugestão é de um SITE. A palavra "site" deve aparecer naturalmente na mensagem; não use apenas "página", "presença digital" ou "layout" de forma vaga.
    - Se o Nicho de Busca contrariar a Categoria Real ou o conteúdo do Site, use a Categoria Real e o conteúdo do Site. Nunca escreva uma abordagem de estética para uma empresa jurídica, por exemplo.
    - Cite apenas um detalhe que esteja nos dados reais acima. Se não houver detalhe confiável, use uma abordagem neutra do segmento, sem inventar serviços.
4. CONTATO DE RECEPÇÃO/AGENDAMENTO:
   - O número do Google Maps pode ser de recepção, agendamento ou atendimento. Não assuma que a pessoa é dona da empresa.
   - Escreva apenas a parte comercial da mensagem. O sistema adicionará antes uma pergunta educada pedindo o responsável por marketing/comercial e solicitando encaminhamento caso seja recepção ou agendamento.

### FORMATO DE SAÍDA OBRIGATÓRIO (JSON):
Retorne estritamente um objeto JSON com as chaves:
{{
  "diagnostico": "Resumo em 1-2 frases do diagnóstico da presença digital da empresa.",
  "estrategia": "Explicação do ângulo comercial adotado e o porquê.",
  "mensagem": "Texto completo e final da mensagem de abordagem para o WhatsApp."
}}
"""
        if is_intl:
            super_prompt += '\n\nIMPORTANTE: Escreva a chave "mensagem" em INGLÊS natural.'
        
        modelos_candidatos = [
            'gemini-3.5-flash-lite',
            'gemini-flash-lite-latest',
            'gemini-3.1-flash-lite',
            'gemini-3.5-flash',
            'gemini-flash-latest'
        ]
        resposta_bruta = ""
        for m_name in modelos_candidatos:
            try:
                model = genai.GenerativeModel(
                    m_name,
                    generation_config={"response_mime_type": "application/json"}
                )
                response = model.generate_content(super_prompt)
                if response and response.text:
                    resposta_bruta = response.text
                    break
            except Exception as e:
                print(f"[WORKER] Modelo {m_name} indisponível: {str(e)[:100]}")
                continue

        if not resposta_bruta:
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Modelos Gemini atingiram limite de quota diária (429)", is_intl=is_intl)

        resposta_bruta = re.sub(r"^```(?:json)?\s*|\s*```$", "", resposta_bruta.strip(), flags=re.IGNORECASE)
        parsed = json.loads(resposta_bruta)
        mensagem = parsed.get("mensagem", "").strip()
        diagnostico = parsed.get("diagnostico", "").strip()
        estrategia = parsed.get("estrategia", "").strip()
        
        if not mensagem_parece_personalizada(mensagem, nome_curto):
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Resposta da IA sem personalização suficiente", is_intl=is_intl)
        mensagem = adicionar_triagem_responsavel(mensagem, is_intl)

        return {
            'analise': f"DIAGNÓSTICO:\n{diagnostico}" if diagnostico else "Análise concluída via IA.",
            'estrategia': estrategia or "Abordagem consultiva com proposta de melhoria/protótipo de site.",
            'mensagem': mensagem,
            'gerada_por_ia': True,
        }
        
    except Exception as e:
        print(f'[WORKER] Erro AI: {e}')
        return obter_copy_contingencia(dados_lead, vendedor, motivo=f"Erro na execução da IA: {e}", is_intl=is_intl)




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
    if request.endpoint in ("static", "login"):
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
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.route("/")
def index():
    return render_template("search.html")

@app.route("/crm")
def crm():
    todos = load_leads()
    ativos = [l for l in todos if l.get("status") != "Descartado"]
    leads_com_site = sum(1 for lead in ativos if possui_site_proprio(lead.get("link_inicial")))
    return render_template("crm.html", leads=ativos, leads_com_site=leads_com_site, is_descartados=False)

@app.route("/crm/descartados")
def crm_descartados():
    todos = load_leads()
    descartados = [l for l in todos if l.get("status") == "Descartado"]
    return render_template("crm.html", leads=descartados, leads_com_site=0, is_descartados=True)

@app.route("/estatisticas")
def estatisticas():
    leads = load_leads()
    total_leads = len(leads)
    com_whats = sum(1 for l in leads if l.get("whatsapp_link"))
    fechados = sum(1 for l in leads if l.get("status") == "Fechado")
    em_negociacao = sum(1 for l in leads if l.get("status") == "Em Negociação")
    return render_template("estatisticas.html", total=total_leads, whats=com_whats, fechados=fechados, em_negociacao=em_negociacao, leads=leads)

@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        data = load_config()
        nova_configuracao = request.form.to_dict()
        api_key = nova_configuracao.pop("gemini_api_key", "").strip()
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
    status_validos = {"Novo", "Contato Feito", "Em Negociação", "Fechado", "Descartado"}
    if not place_id or status not in status_validos:
        return jsonify({"success": False, "error": "Status ou lead inválido"}), 400
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (status, place_id))
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
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
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
                texto = None
                for m_name in ['gemini-3.5-flash-lite', 'gemini-flash-lite-latest', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-flash-latest']:
                    try:
                        model = genai.GenerativeModel(m_name)
                        response = model.generate_content(prompt)
                        if response and response.text:
                            texto = response.text.replace("```json", "").replace("```", "").strip()
                            break
                    except Exception:
                        continue

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
        c.execute("DELETE FROM leads")
        conn.commit()
        conn.close()
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
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        candidatos = [
            'gemini-3.5-flash-lite',
            'gemini-flash-lite-latest',
            'gemini-3.1-flash-lite',
            'gemini-3.5-flash',
            'gemini-flash-latest'
        ]
        
        ultimo_erro = None
        for m_name in candidatos:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content("Diga apenas 'ok'")
                if response and response.text:
                    if chave_enviada:
                        cfg = load_config()
                        cfg["gemini_api_key"] = api_key
                        save_config(cfg)
                        os.environ["GEMINI_API_KEY"] = api_key
                    return jsonify({
                        "success": True,
                        "message": f"Conexão bem-sucedida! Modelo ativo: {m_name}"
                    })
            except Exception as e:
                ultimo_erro = e
                continue
                
        return jsonify({"success": False, "error": f"Erro na API do Gemini: {ultimo_erro}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)










