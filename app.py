import os
import json
import time
import random
import re
import urllib.parse
import sqlite3
import multiprocessing
import psutil
import pandas as pd
from flask import Flask, render_template, request, jsonify, Response
import google.generativeai as genai

# NOTA: sync_playwright Ã© importado DENTRO de extrator_worker para evitar
# travamento quando o processo filho (spawn) reimporta este módulo.

app = Flask(__name__)
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

STATUS_FILE = "search_status.json"

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

def gerar_copy_inteligente(dados_lead, config, is_intl=False):
    nome_curto = dados_lead.get("Nome", "").split(" - ")[0].split("|")[0].strip()
    vendedor = config.get("vendedor_nome", "").strip() or "aqui"
    api_key = config.get("gemini_api_key", "").strip()
    
    # Fallback default se não tiver API key
    if not api_key:
        return {"analise": "Sem API Key.", "estrategia": "Fallback.", "mensagem": f"Olá, vi a {nome_curto} no Google e achei incrível. Posso te enviar um material sobre o posicionamento de vocês?"}
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        super_prompt = f"""Você é um especialista em vendas B2B e prospecção altamente persuasivo.
O objetivo é criar UMA MENSAGEM DE PROSPECÇÃO INICIAL (fria) para o responsável por uma empresa local.
A mensagem NÃO deve vender diretamente, mas sim criar curiosidade, gerar valor imediato e abrir uma conversa para que o lead responda (ex: "Pode mandar").

### DADOS DO LEAD:
- Nome: {nome_curto}
- Segmento: {dados_lead.get("Nicho", "")}
- Localização: {dados_lead.get("Bairro", "")}
- Nota no Google: {dados_lead.get("Nota Maps", "")}
- Avaliações: {dados_lead.get("Qtd Avaliacoes", "")}
- Possui Site: {"Sim" if dados_lead.get("Link Inicial") else "Não"}
- Meu Nome (Vendedor): {vendedor}

### DIRETRIZES DE MENSAGEM:
1. Adapte a lógica comercial ao Segmento. (Ex: Arquitetura = percepção de valor/autoridade; Odontologia = agendamento/confiança; Móveis = orçamento/portfólio, etc).
2. NUNCA use clichês (Ex: "próximo nível", "potencialize sua presença", "solução personalizada", "alavanque resultados").
3. Sem excesso de emojis, linguagem formal demais ou exageradamente comercial.
4. Tamanho: Curto e direto para WhatsApp/Instagram (500 a 900 caracteres).
5. Se a empresa NÃO tiver site: NÃO fale negativamente ("notei que não tem site"). Diga que analisou a presença online deles e encontrou uma excelente oportunidade para melhorar a captação de clientes.
6. Se a empresa TIVER site: NÃO finja que não tem. Diga que analisou o posicionamento digital atual deles e criou um rascunho de melhoria/conversão sem compromisso.
7. CTA (Chamada para ação): Baixa fricção, abrindo conversa. Ex: "Posso te mandar uma imagem para ver como ficou?", "Quer que eu te envie?".
8. Variação: Escolha automaticamente 1 entre 10 estruturas possíveis (ex: elogio à nota, pergunta direta, observação de mercado, foco no bairro, etc).

### FORMATO DE SAÍDA OBRIGATÓRIO (Use as tags exatamente como abaixo):
[ANALISE]
1 parágrafo analisando os dados da empresa.
[ESTRATEGIA]
1 parágrafo explicando qual ângulo comercial/estrutura você escolheu usar e por quê.
[MENSAGEM]
Escreva aqui apenas a MENSAGEM FINAL que será enviada.
"""
        if is_intl:
            super_prompt += "\n\nIMPORTANT: TRANSLATE AND WRITE THE [MENSAGEM] ENTIRELY IN NATIVE ENGLISH."
        
        response = model.generate_content(super_prompt)
        texto = response.text or ""
        
        # Parsando as tags
        analise = ""
        estrategia = ""
        mensagem = ""
        
        import re
        match_a = re.search(r'\[ANALISE\](.*?)\[ESTRATEGIA\]', texto, re.DOTALL)
        match_e = re.search(r'\[ESTRATEGIA\](.*?)\[MENSAGEM\]', texto, re.DOTALL)
        match_m = re.search(r'\[MENSAGEM\](.*)', texto, re.DOTALL)
        
        if match_a: analise = match_a.group(1).strip()
        if match_e: estrategia = match_e.group(1).strip()
        if match_m: mensagem = match_m.group(1).strip()
        else: mensagem = texto.replace("[MENSAGEM]", "").strip() # fallback de parsing
        
        return {
            "analise": analise,
            "estrategia": estrategia,
            "mensagem": mensagem
        }
        
    except Exception as e:
        print(f"[WORKER] Erro na API do Gemini: {e}")
        return {"analise": "Erro", "estrategia": "Erro", "mensagem": f"Olá, vi a {nome_curto} no Google. Posso te enviar um material sobre o seu posicionamento?"}

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
        for i in range(min(elementos.count(), 100)):
            aria = elementos.nth(i).get_attribute("aria-label")
            if not aria: continue
            if "estrelas" in aria and nota == "0" and "avalia" not in aria:
                match_nota = re.search(r"([\d,.]+)\s*estrelas", aria)
                if match_nota: nota = match_nota.group(1)
            if "avalia" in aria and qtd == "0" and "estrelas" not in aria and "resumo" not in aria:
                match_qtd = re.search(r"([\d,.]+)\s*avalia", aria)
                if match_qtd: qtd = match_qtd.group(1).replace(".", "")
            if nota != "0" and qtd != "0":
                break
    except Exception as e: print("Aviso interno:", e)
    return nota, qtd

def check_auth(username, password):
    valid_user = os.environ.get("APP_USER", "admin")
    valid_pass = os.environ.get("APP_PASS", "123456")
    return username == valid_user and password == valid_pass

def authenticate():
    return Response(
        "Login necessario para acessar o CRM.\nUse admin e 123456 se nao tiver alterado as credenciais.", 401,
        {"WWW-Authenticate": 'Basic realm="GestaoLead Login"'})

@app.before_request
def require_login():
    if request.endpoint == "static": return
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

@app.route("/")
def index():
    return render_template("search.html")

@app.route("/crm")
def crm():
    leads = load_leads()
    return render_template("crm.html", leads=leads)

@app.route("/estatisticas")
def estatisticas():
    leads = load_leads()
    total_leads = len(leads)
    com_whats = sum(1 for l in leads if l.get("whatsapp_link"))
    fechados = sum(1 for l in leads if l.get("status") == "Fechado")
    em_negociacao = sum(1 for l in leads if l.get("status") == "Em Negociacao")
    return render_template("estatisticas.html", total=total_leads, whats=com_whats, fechados=fechados, em_negociacao=em_negociacao, leads=leads)

@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        data = request.form.to_dict()
        data["headless"] = "headless" in data
        save_config(data)
        return render_template("configuracoes.html", config=data, success=True)
    return render_template("configuracoes.html", config=load_config(), success=False)

@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (data["status"], data["place_id"]))
    conn.commit()
    conn.close()
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
    instagram_link = f"<a href='{lead['instagram']}' class='text-blue-500 underline' target='_blank'>Acessar Perfil</a>" if lead["instagram"] else "<span class='text-orange-500'>Nao localizado</span>"
    linkedin_link = f"<a href='{lead['linkedin']}' class='text-blue-500 underline' target='_blank'>Acessar Perfil</a>" if lead["linkedin"] else "Nao localizado"
    site_link = f"<a href='{lead['link_inicial']}' class='text-blue-500 underline' target='_blank'>Visualizar</a>" if lead["link_inicial"] else "<span class='text-red-500 font-bold'>Nenhum link cadastrado no Google!</span>"
    email_info = lead["email"] or "<span class='text-red-500 font-bold'>Vazamento: Nenhum e-mail de contato encontrado.</span>"
    
    analise_ia = lead.get('analise_ia') or 'N/A'
    estrategia_ia = lead.get('estrategia_ia') or 'N/A'
    copy_texto = lead.get('copy_texto') or 'N/A'
    
    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>Auditoria Digital - {lead['nome']}</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-50 text-slate-800 font-sans p-8">
    <div class="max-w-3xl mx-auto bg-white p-10 rounded-2xl shadow-xl border-t-8 border-red-500">
    <div class="flex justify-between items-start mb-6"><div><h1 class="text-3xl font-bold mb-2 text-slate-900">Auditoria de Presenca Digital</h1><h2 class="text-xl text-red-600 font-semibold">Empresa: {lead['nome']}</h2></div><div class="text-right"><span class="inline-block bg-slate-100 text-slate-600 px-3 py-1 rounded-full text-sm font-semibold uppercase tracking-wide">{lead['nicho']}</span></div></div>
    <p class="text-slate-600 mb-8 border-b pb-6">Analise detalhada da presenca online na regiao de <strong>{lead['bairro']}</strong>.</p>
    <div class="grid grid-cols-2 gap-6 mb-8"><div class="bg-slate-50 border p-6 rounded-xl text-center border-b-4 border-b-emerald-500"><span class="block text-4xl font-black text-slate-800 mb-2">{lead['nota']} ⭐</span><span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Nota no Google Maps</span></div><div class="bg-slate-50 border p-6 rounded-xl text-center border-b-4 border-b-emerald-500"><span class="block text-4xl font-black text-slate-800 mb-2">{lead['avaliacoes']}</span><span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Volume de Avaliacoes</span></div></div>
    <div class="mb-8"><h3 class="text-lg font-bold text-slate-800 mb-4 border-b pb-2">Dados Encontrados Publicamente</h3><ul class="space-y-3 text-slate-600"><li><strong>Telefone/WhatsApp:</strong> {lead['telefone'] or 'Nao disponivel'}</li><li><strong>E-mail Publico:</strong> {email_info}</li><li><strong>Instagram:</strong> {instagram_link}</li><li><strong>LinkedIn:</strong> {linkedin_link}</li><li><strong>Link Atual (Google):</strong> {site_link}</li></ul></div>
    
    <div class="mb-8 bg-indigo-50 rounded-xl p-6 border border-indigo-100">
        <h3 class="text-lg font-bold text-indigo-900 mb-4 border-b border-indigo-200 pb-2"><i class="fa-solid fa-robot mr-2"></i> Inteligência Artificial SDR</h3>
        <div class="mb-4">
            <h4 class="font-bold text-indigo-800 text-sm uppercase mb-1">1. Análise do Lead</h4>
            <p class="text-slate-700 text-sm bg-white p-3 rounded border border-indigo-100">{analise_ia}</p>
        </div>
        <div class="mb-4">
            <h4 class="font-bold text-indigo-800 text-sm uppercase mb-1">2. Estratégia Adotada</h4>
            <p class="text-slate-700 text-sm bg-white p-3 rounded border border-indigo-100">{estrategia_ia}</p>
        </div>
        <div>
            <h4 class="font-bold text-indigo-800 text-sm uppercase mb-1">3. Mensagem Final (Copy)</h4>
            <div class="text-slate-800 bg-white p-4 rounded-lg border border-indigo-200 shadow-sm whitespace-pre-wrap font-medium">{copy_texto}</div>
        </div>
    </div>
    
    <div class="bg-red-50 border-l-4 border-red-500 p-6 rounded-r-xl mb-8"><h3 class="text-xl font-bold text-red-700 mb-3">Ponto Critico de Conversao Identificado</h3><p class="mb-3">Constatamos que a <strong>{lead['nome']}</strong> atualmente <strong>nao possui um site institucional oficial e profissional</strong>.</p><p>Mesmo possuindo {lead['avaliacoes']} avaliacoes no Google, isso gera um vazamento invisivel de clientes.</p></div>
    <div class="bg-blue-50 border-l-4 border-blue-600 p-6 rounded-r-xl"><h3 class="text-xl font-bold text-blue-800 mb-3">Recomendacao Tecnica Imediata</h3><p>Criacao de uma <strong>Pagina de Alta Conversao (Landing Page)</strong> focada em transmitir confianca e direcionar contatos para o WhatsApp.</p></div>
    <p class="text-center text-xs text-slate-400 mt-12">Relatorio Confidencial gerado via GestaoLead PRO Automation.</p></div></body></html>"""
    return html

def cacar_dados_profundos(context, url):
    dados = {"email": "", "instagram": "", "facebook": "", "linkedin": ""}
    if not url: return dados
    url_lower = url.lower()
    if "instagram.com" in url_lower:
        dados["instagram"] = url; return dados
    if "facebook.com" in url_lower:
        dados["facebook"] = url; return dados
    if "linkedin.com" in url_lower:
        dados["linkedin"] = url; return dados
    page = None
    try:
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        content = page.content()
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
        emails = [e for e in emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")) and "sentry" not in e and "example" not in e and "wix" not in e]
        if emails: dados["email"] = emails[0]
        ig = re.search(r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+", content)
        if ig: dados["instagram"] = ig.group(0)
        fb = re.search(r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+", content)
        if fb: dados["facebook"] = fb.group(0)
        li = re.search(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_.-]+", content)
        if li: dados["linkedin"] = li.group(0)
    except Exception as e:
        print(f"Erro no Cacador Profundo para {url}: {e}")
    finally:
        if page:
            try: page.close()
            except Exception as e: print("Aviso interno:", e)
    return dados

def extrator_worker(data, config, queue):
    try:
        from playwright.sync_api import sync_playwright  # Import aqui para spawn funcionar
        process = psutil.Process(os.getpid())
        mem_inicial = process.memory_info().rss / (1024 * 1024)
        print(f"[WORKER] Iniciando. Memoria RAM uso atual: {mem_inicial:.2f} MB")
        stats = {"novos_db": 0}
        atualizar_status({"rodando": True, "mensagem": "Abrindo navegador...", "leads_salvos": 0})
        nichos = [n.strip() for n in data["nichos"].split(",") if n.strip()]
        bairros = [b.strip() for b in data["bairros"].split(",") if b.strip()]
        print(f"[WORKER] nichos={nichos}, bairros={bairros}")
        is_headless = config.get("headless", True)
        GRANDES_REDES = ["odontocompany","smart fit","smartfit","mcdonalds","boticario","cacau show","subway","sorridents","amorasaude","bluefit","pague menos","raia","drogasil","localiza","unidas","movida"]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=is_headless)
            print("[WORKER] Browser aberto.")
            context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 800})
            page = context.new_page()
            if is_headless:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            consent_ok = False
            for bairro in bairros:
                for nicho in nichos:
                    busca = f"{nicho} {bairro}"
                    print(f"[WORKER] Buscando: {busca}")
                    atualizar_status({"rodando": True, "mensagem": f"Buscando '{nicho}' em '{bairro}'...", "leads_salvos": stats["novos_db"]})
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
                            for _ in range(12):
                                painel.evaluate("node => node.scrollTop = node.scrollHeight")
                                time.sleep(random.uniform(1.5, 2.5))
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
                    for index, href in enumerate(hrefs):
                        place_id = extrair_id_unico(href)
                        try:
                            atualizar_status({"rodando": True, "mensagem": f"Analisando lead {index+1}/{len(hrefs)}...", "leads_salvos": stats["novos_db"]})
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
                            if data.get("anti_franchise") and any(rede in nome.lower() for rede in GRANDES_REDES): continue
                            
                            link_el = page.locator("a[data-item-id='authority'], a[data-tooltip='Abrir website'], a[data-tooltip='Open website']")
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            if not link_encontrado:
                                # Fallback robusto via regex de atributo aria-label e links externos
                                fallback = page.locator("a[aria-label*='ebsite'], a[aria-label*='site'], a[href^='http']").all()
                                for f in fallback:
                                    hf = f.get_attribute("href")
                                    if hf and "google.com" not in hf and "facebook.com" not in hf and "instagram.com" not in hf:
                                        link_encontrado = hf
                                        break
                                        
                            if data.get("strict_no_socials") and link_encontrado: 
                                print(f"[WORKER] Ignorando {nome} - Possui site e o filtro de EXCLUIR COM SITE esta ativo."); continue
                            tel_el = page.locator("button[data-item-id^='phone']")
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)
                            if data.get("strict_mobile") and not eh_celular_valido(numeros_whats): continue
                            end_el = page.locator("button[data-item-id='address']")
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereco: ", "").strip() if end_el.count() > 0 else ""
                            if data.get("strict_bairro") and bairro.split("-")[0].strip().lower() not in endereco.lower(): continue
                            nota_str, avaliacoes_str = extrair_avaliacoes(page)
                            try: nota_float = float(nota_str.replace(",", "."))
                            except ValueError: nota_float = 0.0
                            if nota_float < float(data.get("min_nota", 0)):
                                print(f"[WORKER] Ignorando {nome} - Nota {nota_float} muito baixa"); continue
                            if data.get("req_whatsapp") and not numeros_whats:
                                print(f"[WORKER] Ignorando {nome} - Sem WhatsApp"); continue
                            print(f"[WORKER] Iniciando cacador profundo para {nome}...")
                            dados_profundos = cacar_dados_profundos(context, link_encontrado)
                            
                            dados_raw = {
                                "Nome": nome, "Nicho": nicho, "Bairro": bairro,
                                "Nota Maps": nota_str, "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw, "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Link Inicial": link_encontrado
                            }
                            
                            is_intl = not numeros_whats.startswith("55") if numeros_whats else False
                            copy_texto = ""
                            analise_ia = ""
                            estrategia_ia = ""
                            
                            if data.get("ai_copy"):
                                resultado_ia = gerar_copy_inteligente(dados_raw, config, is_intl)
                                copy_texto = resultado_ia.get("mensagem", "")
                                analise_ia = resultado_ia.get("analise", "")
                                estrategia_ia = resultado_ia.get("estrategia", "")
                                
                            whats_link_final = formatar_whatsapp(numeros_whats, copy_texto) if numeros_whats else ""
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
                                "Copy Texto": copy_texto,
                                "Analise IA": analise_ia,
                                "Estrategia IA": estrategia_ia
                            }
                            salvo = save_lead_db(lead_data, place_id)
                            if salvo:
                                print(f"[WORKER] Salvo com sucesso: {nome}")
                                stats["novos_db"] += 1
                                atualizar_status({"rodando": True, "mensagem": f"Lead salvo: {nome}", "leads_salvos": stats["novos_db"]})
                        except Exception as e:
                            print(f"[WORKER] Erro no lead {href}: {e}")
            print("[WORKER] Fechando navegador.")
            mem_final = process.memory_info().rss / (1024 * 1024)
            print(f"[WORKER] Finalizando. Memoria RAM uso final: {mem_final:.2f} MB")
            atualizar_status({"rodando": False, "mensagem": "Busca finalizada.", "leads_salvos": stats["novos_db"]})
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
    data = request.json
    if not data.get("nichos") or not data.get("bairros"):
        return jsonify({"success": False, "error": "Nichos ou Bairros vazios"})
    config = load_config()
    atualizar_status({"rodando": True, "mensagem": "Busca iniciada, abrindo navegador...", "leads_salvos": 0})
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass
    p = multiprocessing.Process(target=extrator_worker, args=(data, config, None))
    p.start()
    return jsonify({"success": True, "salvos": "Em andamento", "message": "Busca iniciada em segundo plano."})

@app.route("/api/sugerir_alvos", methods=["GET"])
def sugerir_alvos():
    try:
        regiao = request.args.get('regiao', 'br')
        config = load_config()
        api_key = config.get("gemini_api_key", "").strip()
        
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                contexto_regiao = "no BRASIL (Cidades ricas e polos comerciais brasileiros como SP, SC, RJ, MG, etc)." if regiao == "br" else "INTERNACIONALMENTE nos Estados Unidos e Europa (cidades com alto poder aquisitivo como Miami, Londres, Dubai, etc)."
                
                prompt = f"""Atue como um estrategista de vendas B2B.
Eu prospecto empresas no Google Maps para vender criação de Sites de Alta Conversão.
Preciso que você me sugira 5 Nichos de Alto Valor (High-Ticket) e 5 Cidades com alto poder aquisitivo {contexto_regiao}.

Regras:
1. Nichos devem ser muito lucrativos (ex: cirurgia plástica, móveis planejados, arquitetura de luxo, energia solar, clínicas especializadas).
2. As cidades DEVEM SER APENAS {contexto_regiao}. Não misture Brasil com Internacional.
3. Retorne EXATAMENTE UM JSON válido e mais nada. O formato deve ser:
{{
  "nichos": ["Nicho 1", "Nicho 2", "Nicho 3", "Nicho 4", "Nicho 5"],
  "cidades": ["Cidade 1", "Cidade 2", "Cidade 3", "Cidade 4", "Cidade 5"]
}}"""
                response = model.generate_content(prompt)
                texto = response.text.replace("```json", "").replace("```", "").strip()
                import json
                dados_ia = json.loads(texto)
                return jsonify({
                    "nichos": dados_ia.get("nichos", [])[:5],
                    "cidades": dados_ia.get("cidades", [])[:5]
                })
            except Exception as e:
                print(f"[IA] Erro ao gerar sugestões: {e}")
                # Fallback para o hardcoded se a IA falhar
        
        # Fallback Hardcoded
        nichos_ht = [
            "Advogado Trabalhista", "Cirurgião Plástico", "Clínica de Estética", "Imobiliária de Alto Padrão",
            "Clínica Odontológica", "Escritório de Contabilidade", "Energia Solar", "Arquitetura e Interiores",
            "Construtora", "Clínica Veterinária", "Concessionária de Veículos", "Consultoria Financeira",
            "Personal Trainer de Elite", "Psiquiatra", "Dermatologista", "Móveis Planejados", "Seguros"
        ]
        
        cidades_br = [
            "Alphaville SP", "Moema São Paulo", "Balneário Camboriú SC", "Nova Lima MG", 
            "Batel Curitiba", "Itaim Bibi SP", "Leblon RJ", "Jurerê Internacional SC",
            "Campinas SP", "Ribeirão Preto SP", "Jardins São Paulo", "Lago Sul Brasília"
        ]
        cidades_intl = [
            "Miami FL", "Orlando FL", "Beverly Hills CA", "Brickell Miami", "Boca Raton FL",
            "Manhattan NY", "Kensington London", "Dubai Marina", "Aventura FL", "Sunny Isles Beach FL"
        ]
        
        cidades_pool = cidades_intl if regiao == 'intl' else cidades_br
        import random
        
        selecionados_nichos = random.sample(nichos_ht, 5)
        selecionados_cidades = random.sample(cidades_pool, 5)
        
        return jsonify({
            "nichos": selecionados_nichos,
            "cidades": selecionados_cidades
        })
    except Exception as e:
        print("[ERRO IA Sugestão]:", e)
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

@app.route("/api/test_gemini", methods=["POST"])
def test_gemini():
    data = request.json
    api_key = data.get("key", "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "Chave vazia"})
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content("Diga apenas 'ok'")
        if response and response.text:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Sem resposta"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
