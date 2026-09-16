import os
import json
import time
import random
import re
import urllib.parse
import sqlite3
import pandas as pd
from io import StringIO
from flask import Flask, render_template, request, jsonify, Response
from playwright.sync_api import sync_playwright

app = Flask(__name__)
DB_NAME = 'gestao_leads.db'
CONFIG_FILE = 'config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"vendedor_nome": "", "agencia_nome": "", "velocidade": "normal", "headless": True}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except: return {"vendedor_nome": "", "agencia_nome": "", "velocidade": "normal", "headless": True}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

STATUS_FILE = 'search_status.json'

def atualizar_status(dados):
    import os
    try:
        dados["pid"] = os.getpid()
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar status: {e}")

def ler_status():
    import os
    import psutil
    if not os.path.exists(STATUS_FILE):
        return {"rodando": False, "mensagem": "Nenhuma busca realizada ainda.", "leads_salvos": 0}
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Verifica se o processo morreu inesperadamente (OOMKill)
            if data.get("rodando") and data.get("pid"):
                if not psutil.pid_exists(data["pid"]):
                    data["rodando"] = False
                    data["mensagem"] = "O processo foi interrompido inesperadamente (possível limite de memória do Render)."
            return data
    except Exception:
        return {"rodando": False, "mensagem": "Status indisponível.", "leads_salvos": 0}

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS leads
                 (place_id TEXT PRIMARY KEY, nome TEXT, nicho TEXT, bairro TEXT, nota TEXT, 
                  avaliacoes TEXT, telefone TEXT, whatsapp_link TEXT, email TEXT, 
                  instagram TEXT, facebook TEXT, linkedin TEXT, link_inicial TEXT, 
                  google_maps TEXT, prompt_design TEXT, status TEXT, data_adicao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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
        c.execute('''INSERT INTO leads (place_id, nome, nicho, bairro, nota, avaliacoes, telefone, whatsapp_link, email, instagram, facebook, linkedin, link_inicial, google_maps, prompt_design, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Novo')''', 
                  (place_id, lead["Nome"], lead["Nicho"], lead["Bairro"], lead["Nota Maps"], 
                   lead["Qtd Avaliações"], lead["Telefone"], lead["WhatsApp Link"], lead["E-mail Encontrado"], 
                   lead["Instagram"], lead["Facebook"], lead["LinkedIn"], lead["Link Inicial"], 
                   lead["Google Maps"], lead["Prompt Protótipo"]))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# --- SCRAPER HELPERS ---
def tratar_consentimento_cookies(page):
    """Fecha a tela de consentimento de cookies do Google, comum em IPs de datacenter (Render)."""
    try:
        import time
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

def extrair_apenas_numeros(telefone: str) -> str:
    if not telefone: return ""
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) >= 10:
        if not numeros.startswith('55'): numeros = '55' + numeros
        return numeros
    return ""

def formatar_whatsapp(numeros: str, copy_texto: str = "") -> str:
    if not numeros: return ""
    url = f"https://wa.me/{numeros}"
    if copy_texto: url += f"?text={urllib.parse.quote(copy_texto)}"
    return url

def gerar_copy_inteligente(nome, bairro, nota, nicho, config):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    nicho_lower = nicho.lower()
    
    vendedor = config.get("vendedor_nome", "").strip() or "aqui"
    
    # Textos curtos, diretos e profissionais
    copy = f"Olá, tudo bem?\n\n"
    
    if vendedor != "aqui":
        copy += f"Meu nome é {vendedor}. "
        
    copy += f"Estava pesquisando no Google Maps na região de {bairro} e encontrei o perfil da {nome_curto}. "
    
    try:
        nota_float = float(nota.replace(',', '.'))
        if nota_float >= 4.5:
            copy += f"Gostei muito de ver a excelente nota de {nota} estrelas que vocês têm!\n\n"
        else:
            copy += "\n\n"
    except: 
        copy += "\n\n"
        
    # Adaptação para nichos onde quem responde é recepcionista (saúde, beleza, estética)
    if "estética" in nicho_lower or "beleza" in nicho_lower or "odont" in nicho_lower or "clínica" in nicho_lower or "médic" in nicho_lower or "dentist" in nicho_lower:
        copy += f"Sei que esse provavelmente é o número de agendamentos, mas você conseguiria encaminhar essa mensagem para a pessoa responsável pela gestão da clínica, por gentileza?\n\n"
        copy += f"Eu trabalho com posicionamento digital e notei que a {nome_curto} não tem um site oficial focado em conversão cadastrado lá no Google. Como hoje os pacientes decidem muito pelo visual, tomei a liberdade de montar um rascunho de uma página focada exclusivamente em lotar a agenda de vocês.\n\n"
        copy += "👉 Posso enviar a imagem aqui de como ficou? Se puder mostrar para a direção, é totalmente sem compromisso."
    
    # Advogados e Contadores (Geralmente secretárias ou direto com o profissional)
    elif "advogad" in nicho_lower or "escritório" in nicho_lower or "contab" in nicho_lower:
        copy += "Notei que vocês não têm um site oficial cadastrado, apenas as redes sociais. Hoje em dia, clientes mais exigentes pesquisam no Google e acabam escolhendo o concorrente quando não encontram um site que transmita mais segurança e prestígio de imediato.\n\n"
        copy += "Como trabalho com autoridade digital, tomei a liberdade de montar um rascunho de um site profissional para vocês, focado em atrair clientes de alto padrão para o escritório.\n\n"
        copy += "👉 Posso enviar uma imagem aqui de como ficou? É totalmente sem compromisso, apenas para vocês darem uma olhada."
        
    else:
        copy += "Notei que vocês não têm um site oficial cadastrado, apenas as redes sociais. Hoje em dia, muitos clientes pesquisam no Google e acabam escolhendo o concorrente quando não encontram um site que transmita mais autoridade e confiança de imediato.\n\n"
        copy += "Como trabalho com posicionamento digital, tomei a liberdade de montar um rascunho de um site profissional para vocês, focado em atrair clientes mais qualificados para o WhatsApp.\n\n"
        copy += "👉 Posso enviar uma imagem aqui de como ficou? É totalmente sem compromisso, apenas para vocês darem uma olhada."
        
    return copy

def gerar_prompt_prototipo(nome, nicho):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    base = f"UI/UX web design of a modern, high-converting landing page for a {nicho} business named '{nome_curto}'. "
    design = "Clean layout, professional typography, hero section with a clear call-to-action button, services overview section, testimonials, WhatsApp floating button. Modern corporate colors, highly trustworthy."
    return base + design + " Dribbble style, Behance style, 8k resolution, photorealistic ui."

def extrair_id_unico(href: str) -> str:
    if not href: return str(random.random())
    match = re.search(r'1s(0x[^:]+:0x[a-f0-9]+)', href)
    return match.group(1) if match else href.split('?')[0]

def extrair_avaliacoes(page):
    nota = "0"
    qtd = "0"
    try:
        # Pega todos os elementos com aria-label que pode ter estrelas ou avaliações
        elementos = page.locator('[aria-label]')
        for i in range(min(elementos.count(), 100)):
            aria = elementos.nth(i).get_attribute("aria-label")
            if not aria: continue
            
            # Pega a nota ("4,5 estrelas") - ignora as que falam "5 estrelas, 100 avaliações" (filtros)
            if "estrelas" in aria and nota == "0" and "avalia" not in aria:
                match_nota = re.search(r'([\d,.]+)\s*estrelas', aria)
                if match_nota: nota = match_nota.group(1)
            
            # Pega a quantidade ("1.200 avaliações")
            if "avalia" in aria and qtd == "0" and "estrelas" not in aria and "resumo" not in aria:
                match_qtd = re.search(r'([\d,.]+)\s*avalia', aria)
                if match_qtd: qtd = match_qtd.group(1).replace(".", "")
                
            if nota != "0" and qtd != "0":
                break
    except Exception as e: print("Aviso interno:", e)
    return nota, qtd

# --- SEGURANÇA BÁSICA ---
def check_auth(username, password):
    # Senha padrão: admin / 123456 (Pode ser mudado via variáveis de ambiente)
    valid_user = os.environ.get('APP_USER', 'admin')
    valid_pass = os.environ.get('APP_PASS', '123456')
    return username == valid_user and password == valid_pass

def authenticate():
    return Response(
    'Login necessário para acessar o CRM.\n'
    'Use "admin" e "123456" se não tiver alterado as credenciais.', 401,
    {'WWW-Authenticate': 'Basic realm="GestaoLead Login"'})

@app.before_request
def require_login():
    # Permite acessar rotas estáticas sem login se houver
    if request.endpoint == 'static': return
    
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('search.html')

@app.route('/crm')
def crm():
    leads = load_leads()
    return render_template('crm.html', leads=leads)

@app.route('/estatisticas')
def estatisticas():
    leads = load_leads()
    total_leads = len(leads)
    com_whats = sum(1 for l in leads if l.get('whatsapp_link'))
    fechados = sum(1 for l in leads if l.get('status') == 'Fechado')
    em_negociacao = sum(1 for l in leads if l.get('status') == 'Em Negociação')
    
    return render_template('estatisticas.html', 
                           total=total_leads, 
                           whats=com_whats,
                           fechados=fechados,
                           em_negociacao=em_negociacao,
                           leads=leads)

@app.route('/configuracoes', methods=['GET', 'POST'])
def configuracoes():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['headless'] = 'headless' in data
        save_config(data)
        return render_template('configuracoes.html', config=data, success=True)
    
    return render_template('configuracoes.html', config=load_config(), success=False)

@app.route('/api/update_status', methods=['POST'])
def update_status():
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (data['status'], data['place_id']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/export/csv')
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM leads", conn)
    conn.close()
    csv_data = df.to_csv(index=False)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=meu_crm_completo.csv"}
    )

@app.route('/dossie/<place_id>')
def dossie(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,))
    lead = c.fetchone()
    conn.close()
    
    if not lead: return "Lead não encontrado", 404
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Auditoria Digital - {lead['nome']}</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans p-8">
        <div class="max-w-3xl mx-auto bg-white p-10 rounded-2xl shadow-xl border-t-8 border-red-500">
            <div class="flex justify-between items-start mb-6">
                <div>
                    <h1 class="text-3xl font-bold mb-2 text-slate-900">Auditoria de Presença Digital</h1>
                    <h2 class="text-xl text-red-600 font-semibold">Empresa: {lead['nome']}</h2>
                </div>
                <div class="text-right">
                    <span class="inline-block bg-slate-100 text-slate-600 px-3 py-1 rounded-full text-sm font-semibold uppercase tracking-wide">{lead['nicho']}</span>
                </div>
            </div>
            
            <p class="text-slate-600 mb-8 border-b pb-6">Análise detalhada da presença online na região de <strong>{lead['bairro']}</strong>. O objetivo desta auditoria é identificar gargalos onde a empresa está perdendo clientes para a concorrência local.</p>
            
            <div class="grid grid-cols-2 gap-6 mb-8">
                <div class="bg-slate-50 border border-slate-200 p-6 rounded-xl text-center border-b-4 border-b-emerald-500">
                    <span class="block text-4xl font-black text-slate-800 mb-2">{lead['nota']} ⭐</span>
                    <span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Nota no Google Maps</span>
                </div>
                <div class="bg-slate-50 border border-slate-200 p-6 rounded-xl text-center border-b-4 border-b-emerald-500">
                    <span class="block text-4xl font-black text-slate-800 mb-2">{lead['avaliacoes']}</span>
                    <span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Volume de Avaliações</span>
                </div>
            </div>

            <div class="mb-8">
                <h3 class="text-lg font-bold text-slate-800 mb-4 border-b pb-2">📍 Dados Encontrados Publicamente</h3>
                <ul class="space-y-3 text-slate-600">
                    <li><strong>Telefone/WhatsApp:</strong> {lead['telefone'] or 'Não disponível'}</li>
                    <li><strong>E-mail Público:</strong> {lead['email'] or '<span class="text-red-500 font-bold">Vazamento: Nenhum e-mail de contato encontrado.</span>'}</li>
                    <li><strong>Instagram:</strong> {f"<a href='{lead['instagram']}' class='text-blue-500 underline' target='_blank'>Acessar Perfil</a>" if lead['instagram'] else '<span class="text-orange-500">Não localizado</span>'}</li>
                    <li><strong>LinkedIn:</strong> {f"<a href='{lead['linkedin']}' class='text-blue-500 underline' target='_blank'>Acessar Perfil</a>" if lead['linkedin'] else 'Não localizado'}</li>
                    <li><strong>Link Atual (Google):</strong> {f"<a href='{lead['link_inicial']}' class='text-blue-500 underline' target='_blank'>Visualizar</a>" if lead['link_inicial'] else '<span class="text-red-500 font-bold">Nenhum link cadastrado no Google!</span>'}</li>
                </ul>
            </div>

            <div class="bg-red-50 border-l-4 border-red-500 p-6 rounded-r-xl mb-8">
                <h3 class="text-xl font-bold text-red-700 mb-3">⚠️ Ponto Crítico de Conversão Identificado</h3>
                <p class="mb-3">Constatamos que a <strong>{lead['nome']}</strong> atualmente <strong>não possui um site institucional oficial e profissional</strong>.</p>
                <p>Mesmo possuindo {lead['avaliacoes']} avaliações no Google, isso gera um "vazamento invisível" de clientes. Quando clientes premium pesquisam por <em>{lead['nicho']} em {lead['bairro']}</em>, eles encontram a empresa, mas acabam optando por concorrentes que demonstram mais autoridade através de uma vitrine digital oficial e bem estruturada.</p>
            </div>

            <div class="bg-blue-50 border-l-4 border-blue-600 p-6 rounded-r-xl">
                <h3 class="text-xl font-bold text-blue-800 mb-3">💡 Recomendação Técnica Imediata</h3>
                <p>Para maximizar a captação de clientes que já buscam por serviços no Google, recomendamos urgentemente a criação de uma <strong>Página de Alta Conversão (Landing Page)</strong> com a identidade visual da empresa, focada em transmitir confiança e direcionar contatos diretamente para o WhatsApp do time comercial.</p>
            </div>
            
            <p class="text-center text-xs text-slate-400 mt-12">Relatório Confidencial gerado via GestãoLead PRO Automation.</p>
        </div>
    </body>
    </html>
    """
    return html

import multiprocessing

def cacar_dados_profundos(context, url):
    dados = {"email": "", "instagram": "", "facebook": "", "linkedin": ""}
    if not url: return dados
    
    url_lower = url.lower()
    if "instagram.com" in url_lower:
        dados["instagram"] = url
        return dados
    if "facebook.com" in url_lower:
        dados["facebook"] = url
        return dados
    if "linkedin.com" in url_lower:
        dados["linkedin"] = url
        return dados
        
    page = None
    try:
        page = context.new_page()
        # Aborta imagens e fontes também na nova página para ir rápido
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        content = page.content()
        
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', content)
        emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.mp4')) and "sentry" not in e and "example" not in e and "wix" not in e]
        if emails: dados["email"] = emails[0]
        
        ig = re.search(r'https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+', content)
        if ig: dados["instagram"] = ig.group(0)
        
        fb = re.search(r'https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+', content)
        if fb: dados["facebook"] = fb.group(0)
        
        li = re.search(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_.-]+', content)
        if li: dados["linkedin"] = li.group(0)
        
    except Exception as e:
        print(f"Erro no Caçador Profundo para {url}: {e}")
    finally:
        if page:
            try: page.close()
            except Exception as e: print("Aviso interno:", e)
            
    return dados

def extrator_worker(data, config, queue):
    try:
        import time
        import random
        import re
        from playwright.sync_api import sync_playwright
        import urllib.parse
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        mem_inicial = process.memory_info().rss / (1024 * 1024)
        print(f"[WORKER] Iniciando. Memória RAM uso atual: {mem_inicial:.2f} MB")
        
        stats = {"novos_db": 0}
        atualizar_status({"rodando": True, "mensagem": "Abrindo navegador...", "leads_salvos": 0})
        
        nichos = [n.strip() for n in data['nichos'].split(",") if n.strip()]
        bairros = [b.strip() for b in data['bairros'].split(",") if b.strip()]
        is_headless = config.get("headless", True)
        GRANDES_REDES = ['odontocompany', 'smart fit', 'smartfit', 'mcdonalds', 'boticario', 'cacau show', 'subway', 'sorridents', 'amorasaude', 'bluefit', 'pague menos', 'raia', 'drogasil', 'localiza', 'unidas', 'movida']
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=is_headless)
            context = browser.new_context(locale="pt-BR", viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            
            if is_headless:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            
            consent_ok = False
            for bairro in bairros:
                for nicho in nichos:
                    busca = f"{nicho} em {bairro}"
                    atualizar_status({"rodando": True, "mensagem": f"Buscando '{nicho}' em '{bairro}'...", "leads_salvos": stats["novos_db"]})
                    url = f"https://www.google.com/maps/search/{urllib.parse.quote(busca)}"
                    
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        if not consent_ok:
                            tratar_consentimento_cookies(page)
                            consent_ok = True
                        time.sleep(3)
                    except Exception as e:
                        print(f"[WORKER] Erro ao carregar página: {e}")
                        continue
                    
                    try:
                        page.wait_for_selector('a[href*="/maps/place/"]', timeout=10000)
                    except Exception as e:
                        continue
                    
                    try:
                        painel = page.locator('div[role="feed"]').first
                        for _ in range(3): 
                            painel.hover()
                            page.mouse.wheel(0, 4000)
                            time.sleep(random.uniform(1, 2))
                    except Exception as e: print("Aviso interno:", e)
                    
                    try:
                        page.wait_for_selector('a[href*="/maps/place/"]', timeout=10000)
                    except Exception as e: print("Aviso interno:", e)
                    
                    links = page.locator('a[href*="/maps/place/"]')
                    hrefs = []
                    for i in range(min(links.count(), 10)):
                        h = links.nth(i).get_attribute("href")
                        if h and h not in hrefs: hrefs.append(h)
                        
                    for href in hrefs:
                        place_id = extrair_id_unico(href)
                        try:
                            page.goto(href, timeout=20000)
                            try: page.wait_for_selector("h1", timeout=5000)
                            except Exception as e: print("Aviso interno:", e) 
                            
                            nome_el = page.locator("h1").first
                            if nome_el.count() > 0:
                                nome = nome_el.inner_text()
                            else:
                                nome = page.title().split(" - Google")[0]
                                
                            if not nome or "Google Maps" in nome: continue 
                            
                            if data.get('anti_franchise') and any(rede in nome.lower() for rede in GRANDES_REDES):
                                continue
                            
                            link_el = page.locator('a[data-item-id="authority"]')
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            
                            if data.get('strict_no_socials') and link_encontrado:
                                continue
                                
                            tel_el = page.locator('button[data-item-id^="phone"]')
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)
                            
                            if data.get('strict_mobile'):
                                if len(numeros_whats) < 12 or numeros_whats[4] != '9':
                                    continue

                            end_el = page.locator('button[data-item-id="address"]')
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereço: ", "").strip() if end_el.count() > 0 else ""
                            
                            if data.get('strict_bairro') and bairro.split('-')[0].strip().lower() not in endereco.lower():
                                continue
                                
                            nota_str, avaliacoes_str = extrair_avaliacoes(page)
                            try:
                                nota_float = float(nota_str.replace(',', '.'))
                            except ValueError:
                                nota_float = 0.0

                            if nota_float < float(data.get('min_nota', 0)):
                                print(f"[WORKER] Ignorando {nome} - Nota {nota_float} muito baixa")
                                continue
                            if data.get('req_whatsapp') and not numeros_whats:
                                print(f"[WORKER] Ignorando {nome} - Sem WhatsApp")
                                continue

                            copy_texto = gerar_copy_inteligente(nome, bairro, nota_str, nicho, config) if (data.get('ai_copy') and numeros_whats) else ""
                            whats_link_final = formatar_whatsapp(numeros_whats, copy_texto)

                            print(f"[WORKER] Iniciando caçador profundo para {nome}...")
                            dados_profundos = cacar_dados_profundos(context, link_encontrado)

                            lead_data = {
                                "Nome": nome,
                                "Nicho": nicho,
                                "Bairro": bairro,
                                "Nota Maps": nota_str,
                                "Qtd Avaliações": avaliacoes_str,
                                "Telefone": telefone_raw,
                                "WhatsApp Link": whats_link_final,
                                "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                                "Link Inicial": link_encontrado,
                                "Google Maps": href,
                                "Prompt Protótipo": gerar_prompt_prototipo(nome, nicho),
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
            print(f"[WORKER] Finalizando. Memória RAM uso final: {mem_final:.2f} MB")
            
            atualizar_status({"rodando": False, "mensagem": "Busca finalizada.", "leads_salvos": stats["novos_db"]})
            browser.close()
            
        print("[WORKER] Finalizado com sucesso.")
        if queue: queue.put(stats)
    except Exception as e:
        print(f"[WORKER] ERRO FATAL: {e}")
        atualizar_status({"rodando": False, "mensagem": f"Erro: {e}", "leads_salvos": 0})
        if queue: queue.put({"error": str(e)})

@app.route('/api/status')
def api_status():
    return jsonify(ler_status())

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    if not data.get('nichos') or not data.get('bairros'):
        return jsonify({"success": False, "error": "Nichos ou Bairros vazios"})
        
    config = load_config()
    
    atualizar_status({"rodando": True, "mensagem": "Busca iniciada, abrindo navegador...", "leads_salvos": 0})
    
    # IMPORTANTE: Forçar spawn para não quebrar o Chromium no Linux (Render)
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
    
    # Roda o scraper num processo 100% isolado em SEGUNDO PLANO
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=extrator_worker, args=(data, config, q))
    p.start()
    
    return jsonify({"success": True, "salvos": "Vários (em andamento)", "message": "Busca iniciada em segundo plano."})

@app.route('/api/limpar_crm', methods=['POST'])
def limpar_crm():
    try:
        import sqlite3
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM leads")
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    init_db()
    # Usando 0.0.0.0 para funcionar em servidores externos (Render, Oracle, etc)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False, use_reloader=False)
