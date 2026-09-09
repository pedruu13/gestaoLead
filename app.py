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
    
    vendedor = config.get("vendedor_nome", "").strip()
    agencia = config.get("agencia_nome", "").strip()
    
    apresentacao = ""
    if vendedor and agencia:
        apresentacao = f"Aqui é o {vendedor} da {agencia}. "
    elif vendedor:
        apresentacao = f"Aqui é o {vendedor}. "
    
    # 1. Gancho Personalizado Geográfico
    copy = f"Oi {nome_curto}, tudo bem? 👋\n\n{apresentacao}Eu estava mapeando algumas empresas de {nicho} na região de {bairro} e o perfil de vocês no Google chamou muito a minha atenção"
    
    try:
        if float(nota.replace(',', '.')) >= 4.5:
            copy += f", principalmente pela excelente reputação de {nota} estrelas!\n\n"
        else:
            copy += ".\n\n"
    except: 
        copy += ".\n\n"
        
    # 2. Dor Hiper-Específica (Agitação) e 3. Objetivo Claro (CTA de micro-comprometimento)
    if "advogad" in nicho_lower or "escritório" in nicho_lower or "contab" in nicho_lower:
        copy += "Mas sendo bem direto: o cliente de alto padrão é muito desconfiado. Quando ele pesquisa no Google e não encontra um site institucional oficial do escritório, ele acaba fechando com a concorrência por parecer mais 'sólida'.\n\n"
        copy += "Eu sou especialista em posicionamento digital e tomei a liberdade de desenhar uma Página de Captura focada em trazer clientes qualificados para vocês.\n\n"
        copy += "👉 O meu objetivo aqui não é te vender nada hoje. Posso apenas te mandar um print de como ficou para você dar uma olhada?"
        
    elif "estética" in nicho_lower or "beleza" in nicho_lower or "odont" in nicho_lower or "clínica" in nicho_lower or "médic" in nicho_lower:
        copy += "Mas sendo transparente: percebi um gargalo grave no perfil de vocês. Hoje, quem busca tratamentos toma a decisão pelo visual e praticidade. Como vocês não têm um site profissional mostrando a estrutura e um botão de agendamento rápido, muito paciente acaba indo pro concorrente.\n\n"
        copy += "Tomei a liberdade de montar um rascunho de uma Landing Page focada exclusivamente em lotar a agenda da clínica.\n\n"
        copy += "👉 Posso te mandar o link aqui no Whats rapidinho só para você avaliar a ideia?"
        
    elif "imob" in nicho_lower or "corretor" in nicho_lower or "arquitet" in nicho_lower:
        copy += "Percebi que vocês estão deixando muito dinheiro na mesa por não terem uma vitrine digital própria de alto luxo. Ficar dependendo de portal de imóvel ou algoritmo do Instagram espanta os clientes mais qualificados.\n\n"
        copy += "Fiz um rascunho de um site premium com a identidade visual de vocês, focado 100% em conversão.\n\n"
        copy += "👉 Posso te mandar uma imagem de como ficou? É totalmente sem compromisso, só quero sua opinião."
        
    else:
        copy += f"Mas sendo direto: percebi que vocês estão perdendo de 3 a 5 potenciais clientes por semana para os concorrentes do bairro. Isso porque hoje, 80% das pessoas pesquisam no Google, e como vocês não têm um site oficial que passe confiança, eles pulam para o próximo da lista.\n\n"
        copy += "Eu construo máquinas de vendas e tomei a liberdade de desenhar um protótipo de site focado em aumentar os lucros de vocês.\n\n"
        copy += "👉 Posso te enviar o print da tela que eu montei? É 100% de graça dar uma olhada, não vou te cobrar nada por isso."
        
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
    try:
        botoes = page.locator('button')
        for i in range(min(botoes.count(), 30)):
            aria = botoes.nth(i).get_attribute("aria-label")
            if aria and "estrelas" in aria and "avaliações" in aria:
                match_nota = re.search(r'([\d,.]+)\s*estrelas', aria)
                match_qtd = re.search(r'([\d,.]+)\s*avaliações', aria)
                return (match_nota.group(1) if match_nota else "0"), (match_qtd.group(1).replace(".", "") if match_qtd else "0")
    except: pass
    return "0", "0"

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
            <h1 class="text-3xl font-bold mb-2 text-slate-900">Relatório de Presença Digital</h1>
            <h2 class="text-xl text-red-600 font-semibold mb-6">Empresa Auditada: {lead['nome']}</h2>
            
            <p class="text-slate-600 mb-8">Análise automática da presença online do negócio (Nicho: <strong>{lead['nicho']}</strong>) na região de <strong>{lead['bairro']}</strong>.</p>
            
            <div class="flex gap-6 mb-10">
                <div class="flex-1 bg-slate-50 border border-slate-200 p-6 rounded-xl text-center border-b-4 border-b-emerald-500">
                    <span class="block text-4xl font-black text-slate-800 mb-2">{lead['nota']} ⭐</span>
                    <span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Nota no Google Maps</span>
                </div>
                <div class="flex-1 bg-slate-50 border border-slate-200 p-6 rounded-xl text-center border-b-4 border-b-emerald-500">
                    <span class="block text-4xl font-black text-slate-800 mb-2">{lead['avaliacoes']}</span>
                    <span class="text-sm font-bold text-slate-500 uppercase tracking-widest">Volume de Avaliações</span>
                </div>
            </div>

            <div class="bg-red-50 border-l-4 border-red-500 p-6 rounded-r-xl mb-10">
                <h3 class="text-xl font-bold text-red-700 mb-3">⚠️ Ponto Crítico de Conversão Identificado</h3>
                <p class="mb-3">Durante a nossa varredura, constatamos que a empresa <strong>não possui um site profissional próprio</strong> ou página de destino otimizada.</p>
                <p>Isso gera um vazamento invisível de clientes que pesquisam por <em>{lead['nicho']}</em> no Google, encontram a empresa, mas acabam optando por concorrentes que possuem uma vitrine digital mais profissional e confiável.</p>
            </div>

        <div class="bg-blue-50 border-l-4 border-blue-600 p-6 rounded-r-xl">
                <h3 class="text-xl font-bold text-blue-800 mb-3">💡 Recomendação Técnica Imediata</h3>
                <p>Recomendamos o desenvolvimento de uma <strong>Landing Page de Alta Conversão</strong> focada em capturar esses leads locais e direcioná-los automaticamente para o WhatsApp da equipe comercial.</p>
            </div>
            
            <p class="text-center text-xs text-slate-400 mt-12">Relatório gerado via GestãoLead PRO Automation.</p>
        </div>
    </body>
    </html>
    """
    return html

import multiprocessing

def extrator_worker(data, config, queue):
    try:
        import time
        import random
        import re
        from playwright.sync_api import sync_playwright
        
        stats = {"novos_db": 0}
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
            
            for bairro in bairros:
                for nicho in nichos:
                    termo = f"{nicho} em {bairro}"
                    url = f"https://www.google.com/maps/search/{termo.replace(' ', '+')}"
                    
                    try:
                        page.goto(url, timeout=60000)
                        time.sleep(random.uniform(2, 4))
                    except Exception as e:
                        continue
                    
                    try:
                        painel = page.locator('div[role="feed"]').first
                        for _ in range(3): 
                            painel.hover()
                            page.mouse.wheel(0, 4000)
                            time.sleep(random.uniform(1, 2))
                    except: pass
                    
                    try:
                        page.wait_for_selector('a[href*="/maps/place/"]', timeout=10000)
                    except: pass
                    
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
                            except: pass 
                            
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
                            
                            if data.get('strict_bairro') and bairro.split('-')[0].strip().lower() not in endereco.lower(): continue
                            
                            nota_str, qtd_str = extrair_avaliacoes(page)
                            
                            try:
                                nota_float = float(nota_str.replace(',', '.')) if nota_str else 0.0
                                qtd_int = int(qtd_str) if qtd_str else 0
                            except: nota_float, qtd_int = 0.0, 0
                                
                            if nota_float < float(data.get('min_nota', 0)): continue
                            if data.get('req_whatsapp') and not numeros_whats: continue
                            
                            copy_texto = gerar_copy_inteligente(nome, bairro, nota_str, nicho, config) if (data.get('ai_copy') and numeros_whats) else ""
                            whats_link_final = formatar_whatsapp(numeros_whats, copy_texto)
                            
                            lead_data = {
                                "Nome": nome.strip(), "Nicho": nicho, "Bairro": bairro,
                                "Nota Maps": nota_str, "Qtd Avaliações": qtd_str,
                                "Telefone": telefone_raw, "WhatsApp Link": whats_link_final,
                                "E-mail Encontrado": "", "Instagram": "", "Facebook": "", "LinkedIn": "",
                                "Link Inicial": link_encontrado, "Google Maps": href,
                                "Prompt Protótipo": gerar_prompt_prototipo(nome.strip(), nicho)
                            }
                            if save_lead_db(lead_data, place_id):
                                stats["novos_db"] += 1
                        except Exception as e: pass
            browser.close()
            queue.put({"success": True, "salvos": stats["novos_db"]})
            
    except Exception as e:
        queue.put({"success": False, "error": str(e)})

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    if not data.get('nichos') or not data.get('bairros'):
        return jsonify({"success": False, "error": "Nichos ou Bairros vazios"})
        
    config = load_config()
    
    # Roda o scraper num processo 100% isolado (blindado contra crash)
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=extrator_worker, args=(data, config, q))
    p.start()
    p.join()  # Espera o robô terminar
    
    try:
        resultado = q.get_nowait()
        return jsonify(resultado)
    except:
        return jsonify({"success": False, "error": "O processo de extração falhou ou foi abortado abruptamente."})

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
    app.run(debug=True, port=5000, threaded=False, use_reloader=False)
