import streamlit as st
import time
import random
import pandas as pd
import re
import io
import urllib.parse
import sqlite3
import base64
from playwright.sync_api import sync_playwright
from datetime import datetime

# --- CONFIGURAÇÃO DO BANCO DE DADOS (CRM) ---
DB_NAME = 'gestao_leads.db'

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

def load_leads_df():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM leads ORDER BY data_adicao DESC", conn)
    conn.close()
    return df

# --- FUNÇÕES DE ROTINA (Scraping) ---
DOMINIOS_REDE_SOCIAL = [
    "instagram.com", "linktr.ee", "linktree", "wa.me", "whatsapp.com",
    "facebook.com", "wix.com/website-builder", "beacons.ai", "bio.link",
]

def pausa(min_s=1.0, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))

def classificar_link(url: str) -> str:
    if not url: return "sem_link"
    url_lower = url.lower()
    for dominio in DOMINIOS_REDE_SOCIAL:
        if dominio in url_lower: return "rede_social"
    return "site_proprio"

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
    if copy_texto:
        url += f"?text={urllib.parse.quote(copy_texto)}"
    return url

def gerar_copy_inteligente(nome, bairro, nota):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    copy = f"Olá, encontrei o perfil de {nome_curto} aqui no Google Maps! "
    try:
        if float(nota.replace(',', '.')) >= 4.5:
            copy += f"Parabéns pela excelente avaliação de {nota} estrelas. "
    except: pass
    copy += f"Vi que vocês são da região de {bairro}, mas notei que a empresa ainda não possui um site profissional próprio. Gostaria de apresentar uma proposta rápida sem compromisso?"
    return copy

def gerar_prompt_prototipo(nome, nicho):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    return f"UI/UX web design of a modern, high-converting landing page for a {nicho} business named '{nome_curto}'. Clean layout, professional typography, hero section with a clear call-to-action button, services overview section, testimonials, WhatsApp floating button. Dribbble style, Behance style, 8k resolution, modern corporate colors."

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
                nota = match_nota.group(1) if match_nota else "0"
                qtd = match_qtd.group(1).replace(".", "") if match_qtd else "0"
                return nota, qtd
    except: pass
    return "0", "0"

def vasculhar_pagina_profundamente(context, url):
    resultado = {"emails": "", "instagram": "", "facebook": "", "linkedin": ""}
    if not url or "wa.me" in url or "whatsapp.com" in url:
        return resultado
    try:
        temp_page = context.new_page()
        temp_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        temp_page.goto(url, timeout=15000)
        
        texto = temp_page.inner_text("body")
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto)
        resultado["emails"] = ", ".join(list(set([e for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])))
        
        todos_links = temp_page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
        for l in todos_links:
            if not l: continue
            l_lower = l.lower()
            if "instagram.com/" in l_lower and not resultado["instagram"]: resultado["instagram"] = l
            elif "facebook.com/" in l_lower and not resultado["facebook"]: resultado["facebook"] = l
            elif "linkedin.com/" in l_lower and not resultado["linkedin"]: resultado["linkedin"] = l
        temp_page.close()
    except Exception:
        try: temp_page.close()
        except: pass
    return resultado

def gerar_dossie_html(nome, nicho, bairro, nota, avaliacoes):
    """ Gera o HTML estruturado do dossiê de auditoria """
    nome_limpo = nome.split(" - ")[0].split("|")[0].strip()
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Auditoria Digital - {nome_limpo}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 40px; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); border-top: 6px solid #d93025; }}
            h1 {{ color: #1a1a1a; font-size: 28px; margin-bottom: 5px; }}
            h2 {{ color: #d93025; font-size: 20px; margin-top: 0; font-weight: 500; }}
            .alert-box {{ background: #fff3f3; border-left: 4px solid #d93025; padding: 20px; border-radius: 4px; margin: 30px 0; }}
            .metrics {{ display: flex; gap: 20px; margin-top: 30px; }}
            .metric-card {{ flex: 1; background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #eaeaea; }}
            .metric-card.good {{ border-bottom: 4px solid #34a853; }}
            .metric-val {{ font-size: 24px; font-weight: bold; color: #1a1a1a; display: block; }}
            .metric-label {{ font-size: 14px; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
            .recommendation {{ background: #f0f7ff; padding: 20px; border-radius: 8px; margin-top: 30px; border-left: 4px solid #4b6cb7; }}
            .footer {{ text-align: center; margin-top: 40px; font-size: 12px; color: #999; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Relatório de Presença Digital</h1>
            <h2>Empresa Auditada: {nome_limpo}</h2>
            
            <p>Este relatório automático analisou a presença online da empresa <strong>{nome_limpo}</strong>, do nicho de <em>{nicho}</em> localizada em <em>{bairro}</em>.</p>
            
            <div class="metrics">
                <div class="metric-card good">
                    <span class="metric-val">{nota} ⭐</span>
                    <span class="metric-label">Nota no Google Maps</span>
                </div>
                <div class="metric-card good">
                    <span class="metric-val">{avaliacoes}</span>
                    <span class="metric-label">Volume de Avaliações</span>
                </div>
            </div>

            <div class="alert-box">
                <h3 style="margin-top:0; color:#d93025;">⚠️ Ponto Crítico de Conversão Identificado</h3>
                <p>Durante a nossa varredura nos sistemas do Google, constatamos que a empresa <strong>não possui um site profissional próprio</strong> ou página de destino otimizada ligada ao perfil do Google Maps.</p>
                <p>Isso gera um vazamento de clientes: pessoas procuram por serviços de <em>{nicho}</em> na região de <em>{bairro}</em>, encontram a empresa, mas não têm um site institucional para gerar confiança ou visualizar portfólio de serviços antes do contato.</p>
            </div>

            <div class="recommendation">
                <h3 style="margin-top:0; color:#4b6cb7;">💡 Recomendação Técnica</h3>
                <p>Recomendamos o desenvolvimento imediato de uma <strong>Landing Page de Alta Conversão</strong> focada em capturar leads e direcioná-los automaticamente para o WhatsApp da equipe comercial.</p>
            </div>
            
            <div class="footer">
                Relatório gerado via GestãoLead PRO Automation. 
            </div>
        </div>
    </body>
    </html>
    """
    return html


# --- INICIALIZAÇÃO E UI ---
init_db()

st.set_page_config(page_title="GestãoLead PRO", page_icon="🚀", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    h1 { background: -webkit-linear-gradient(45deg, #4b6cb7, #182848); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; text-align: center; margin-bottom:0;}
    .subtitle { text-align: center; color: #888; font-size: 1.1rem; margin-bottom: 2rem; margin-top:0;}
    div.stButton > button:first-child { background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%); color: white; border-radius: 8px; border: none; height: 45px; font-weight: bold; width: 100%; transition: all 0.3s; }
    div.stButton > button:first-child:hover { transform: translateY(-2px); box-shadow: 0 8px 16px rgba(75, 108, 183, 0.4); }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1>GestãoLead PRO</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>Plataforma Comercial Completa (CRM + Extrator em Nuvem)</p>", unsafe_allow_html=True)

# Navegação Principal
menu = st.sidebar.radio("📌 Navegação do Sistema", ["🚀 Motor de Busca (Agência)", "🏢 Meu CRM (Base de Leads)"])
st.sidebar.divider()

if menu == "🚀 Motor de Busca (Agência)":
    with st.sidebar:
        st.markdown("### ⚙️ Configurações da Extração")
        with st.expander("🎛️ Filtros de Qualificação", expanded=True):
            filtro_nota = st.slider("Nota Mínima", 0.0, 5.0, 0.0, 0.1)
            filtro_avaliacoes = st.number_input("Mín. de Avaliações", 0, 0)
            filtro_whatsapp = st.checkbox("Obrigatório ter WhatsApp", False)
            filtro_bairro_estrito = st.checkbox("📍 Endereço Estrito", False)

        with st.expander("🧠 Inteligência & Extração", expanded=True):
            ativar_copy = st.checkbox("🤖 Gerar Copy de Vendas", True)
            ativar_cacador = st.checkbox("🕵️ Mapear Redes & E-mails", False)
            
        with st.expander("🛠️ Sistema", expanded=False):
            carregar_img = st.checkbox("Carregar imagens web", True)

    st.markdown("### Defina seu Público-Alvo ou Envie uma Lista em Lote")
    
    tab_manual, tab_massa = st.tabs(["✍️ Busca Manual", "🏭 Busca em Massa (Planilha)"])
    
    nichos, bairros = [], []
    iniciar_busca = False
    
    with tab_manual:
        col1, col2 = st.columns(2)
        with col1:
            n_raw = st.text_area("Nichos (separados por vírgula):", "advogado, clinica de estetica", height=100)
        with col2:
            b_raw = st.text_area("Bairros (separados por vírgula):", "Moema - São Paulo", height=100)
        
        if st.button("🚀 INICIAR EXTRAÇÃO MANUAL", key="btn_manual"):
            nichos = [n.strip() for n in n_raw.split(",") if n.strip()]
            bairros = [b.strip() for b in b_raw.split(",") if b.strip()]
            iniciar_busca = True
            
    with tab_massa:
        st.info("Faça upload de um arquivo TXT contendo as buscas que você quer rodar de madrugada. O formato deve ser: 1 linha por busca, separando o nicho e o bairro por um traço (-). Ex: `advogado - Moema, SP`")
        arquivo_up = st.file_uploader("Subir arquivo de Lote (.txt)", type=["txt"])
        
        if st.button("🚀 INICIAR MOTOR DE LOTE (Massa)", key="btn_massa"):
            if arquivo_up:
                linhas = arquivo_up.getvalue().decode("utf-8").splitlines()
                # Para simplificar na arquitetura atual, vamos tratar cada linha como 1 nicho para 1 bairro
                for linha in linhas:
                    if "-" in linha:
                        n, b = linha.split("-", 1)
                        nichos.append(n.strip())
                        bairros.append(b.strip())
                iniciar_busca = True
            else:
                st.error("Faça o upload do arquivo primeiro.")

    if iniciar_busca:
        if not nichos or not bairros:
            st.error("⚠️ Parâmetros vazios. Preencha nichos e bairros!")
            st.stop()
            
        st.divider()
        st.markdown("### 📊 Operação de Extração Ativa")
        
        col_m1, col_m2, col_m3 = st.columns(3)
        metric_total = col_m1.empty()
        metric_filtrados = col_m2.empty()
        metric_salvos_db = col_m3.empty()
        
        metric_total.metric("Analisados", 0)
        metric_filtrados.metric("Descartados (Lixo/Duplicado)", 0)
        metric_salvos_db.metric("Salvos no CRM", 0)
        
        progress_bar = st.progress(0)
        log_area = st.empty()
        
        stats = {"analisados": 0, "descartados": 0, "novos_db": 0}
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(locale="pt-BR", viewport={'width': 1280, 'height': 800})
                page = context.new_page()
                
                if not carregar_img:
                    page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
                
                # Se for lote de 1 para 1 (Upload txt), pareamos nicho e bairro. 
                # Mas pela lógica original de manual (todos x todos):
                is_batch = len(nichos) == len(bairros) and len(nichos) > 5
                
                total_buscas = len(nichos) if is_batch else len(nichos) * len(bairros)
                buscas_feitas = 0
                
                # Lógica de Loop adaptável
                pares_busca = zip(nichos, bairros) if is_batch else [(n, b) for b in bairros for n in nichos]
                
                for nicho, bairro in pares_busca:
                    termo = f"{nicho} em {bairro}"
                    log_area.info(f"🔍 Buscando no Maps: {termo}")
                    
                    url = f"https://www.google.com/maps/search/{termo.replace(' ', '+')}"
                    page.goto(url, timeout=30000)
                    pausa(2, 4)
                    
                    try:
                        painel = page.locator('div[role="feed"]').first
                        for _ in range(4): 
                            painel.hover()
                            page.mouse.wheel(0, 4000)
                            pausa(1.5, 2.5)
                    except: pass
                    
                    links = page.locator('a[href*="/maps/place/"]')
                    total_links = min(links.count(), 20)
                    hrefs = []
                    for i in range(total_links):
                        h = links.nth(i).get_attribute("href")
                        if h and h not in hrefs: hrefs.append(h)
                        
                    for i, href in enumerate(hrefs):
                        log_area.text(f"Extraindo dados rigorosamente... ({i+1}/{len(hrefs)}) de '{termo}'")
                        stats["analisados"] += 1
                        
                        place_id = extrair_id_unico(href)
                        
                        try:
                            page.goto(href, timeout=20000)
                            try: page.wait_for_selector("h1", timeout=8000)
                            except: pass 
                            
                            pausa(1.5, 2.5)
                            nome_el = page.locator("h1").first
                            nome = nome_el.inner_text() if nome_el.count() > 0 else ""
                            if not nome: continue 

                            link_el = page.locator('a[data-item-id="authority"]')
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            tipo_link = classificar_link(link_encontrado)
                            if tipo_link == "site_proprio":
                                stats["descartados"] += 1
                                continue
                                
                            tel_el = page.locator('button[data-item-id^="phone"]')
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)

                            end_el = page.locator('button[data-item-id="address"]')
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereço: ", "").strip() if end_el.count() > 0 else ""
                            
                            if filtro_bairro_estrito:
                                bairro_limpo = bairro.split('-')[0].strip().lower()
                                if bairro_limpo not in endereco.lower():
                                    stats["descartados"] += 1
                                    continue
                            
                            nota_str, qtd_str = extrair_avaliacoes(page)
                            
                            try:
                                nota_float = float(nota_str.replace(',', '.')) if nota_str else 0.0
                                qtd_int = int(qtd_str) if qtd_str else 0
                            except:
                                nota_float, qtd_int = 0.0, 0
                                
                            if nota_float < filtro_nota or qtd_int < filtro_avaliacoes:
                                stats["descartados"] += 1
                                continue
                            
                            if filtro_whatsapp and not numeros_whats:
                                stats["descartados"] += 1
                                continue
                            
                            copy_texto = gerar_copy_inteligente(nome, bairro, nota_str) if (ativar_copy and numeros_whats) else ""
                            whats_link_final = formatar_whatsapp(numeros_whats, copy_texto)
                            
                            dados_profundos = {"emails": "", "instagram": "", "facebook": "", "linkedin": ""}
                            if ativar_cacador and link_encontrado:
                                log_area.text(f"🕵️ Vasculhando redes de: {nome}")
                                dados_profundos = vasculhar_pagina_profundamente(context, link_encontrado)
                            
                            lead_data = {
                                "Nome": nome.strip(),
                                "Nicho": nicho,
                                "Bairro": bairro,
                                "Nota Maps": nota_str,
                                "Qtd Avaliações": qtd_str,
                                "Telefone": telefone_raw,
                                "WhatsApp Link": whats_link_final,
                                "E-mail Encontrado": dados_profundos["emails"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                                "Link Inicial": link_encontrado,
                                "Google Maps": href,
                                "Prompt Protótipo": gerar_prompt_prototipo(nome.strip(), nicho)
                            }
                            
                            # SALVAR NO BANCO DE DADOS LOCAL (CRM)
                            inseriu = save_lead_db(lead_data, place_id)
                            if inseriu:
                                stats["novos_db"] += 1
                            else:
                                stats["descartados"] += 1 # Já existia no DB
                                
                            metric_total.metric("Analisados", stats["analisados"])
                            metric_filtrados.metric("Descartados (Lixo/Duplicado)", stats["descartados"])
                            metric_salvos_db.metric("Salvos no CRM", stats["novos_db"])
                            
                        except Exception as e:
                            pass
                    
                    buscas_feitas += 1
                    progress_bar.progress(buscas_feitas / total_buscas)
                            
            browser.close()
            log_area.empty()
            st.success(f"🎉 Extração Finalizada! {stats['novos_db']} leads novos e exclusivos adicionados ao seu CRM.")
            st.info("Vá para a página '🏢 Meu CRM' no menu lateral para visualizar e gerenciar estes leads.")
            
        except Exception as e:
            st.error(f"❌ Ocorreu um erro na extração: {e}")

elif menu == "🏢 Meu CRM (Base de Leads)":
    st.markdown("### Seu Pipeline de Negócios")
    st.write("Gerencie seus leads, atualize o status da prospecção e gere Dossiês de Venda automaticamente.")
    
    df = load_leads_df()
    
    if df.empty:
        st.warning("Seu CRM está vazio. Vá para o Motor de Busca e inicie uma extração!")
    else:
        # Layout de métricas do CRM
        st.write(f"**Total de Leads na Base:** {len(df)}")
        
        # Filtros de visualização do CRM
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            status_filter = st.multiselect("Filtrar por Status", ["Novo", "Contato Feito", "Em Negociação", "Proposta Enviada", "Fechado", "Descartado"], default=["Novo", "Contato Feito", "Em Negociação"])
        with col_f2:
            nicho_filter = st.multiselect("Filtrar por Nicho", df['nicho'].unique())
            
        # Aplicar filtros
        df_view = df.copy()
        if status_filter: df_view = df_view[df_view['status'].isin(status_filter)]
        if nicho_filter: df_view = df_view[df_view['nicho'].isin(nicho_filter)]
        
        st.divider()
        
        # Tabela Editável (O Core do Mini-CRM)
        st.markdown("👇 **Gerencie os status diretamente na tabela (clique na coluna Status para alterar):**")
        edited_df = st.data_editor(
            df_view,
            column_config={
                "status": st.column_config.SelectboxColumn("Status", options=["Novo", "Contato Feito", "Em Negociação", "Proposta Enviada", "Fechado", "Descartado"], required=True),
                "whatsapp_link": st.column_config.LinkColumn("WhatsApp Automático"),
                "google_maps": st.column_config.LinkColumn("Ver no Maps")
            },
            hide_index=True,
            disabled=["place_id", "nome", "nicho", "bairro", "nota", "avaliacoes", "telefone", "email", "instagram", "facebook", "linkedin", "link_inicial", "google_maps", "prompt_design", "data_adicao"],
            height=400,
            use_container_width=True
        )
        
        # Salvar alterações do Data Editor para o Banco de Dados
        if st.button("💾 Salvar Alterações de Status", type="primary"):
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            for idx, row in edited_df.iterrows():
                c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (row['status'], row['place_id']))
            conn.commit()
            conn.close()
            st.success("✅ CRM Atualizado com sucesso!")
            time.sleep(1)
            st.rerun()
            
        st.divider()
        
        # --- GERADOR DE DOSSIÊ DE AUDITORIA ---
        st.markdown("### 📄 Máquina de Vendas (Gerador de Dossiê)")
        st.write("Selecione um Lead da sua base para gerar um PDF/HTML de Auditoria para usar como Isca de Vendas.")
        
        lead_selecionado = st.selectbox("Selecione a Empresa:", df_view['nome'].tolist())
        
        if lead_selecionado:
            lead_info = df_view[df_view['nome'] == lead_selecionado].iloc[0]
            
            html_dossie = gerar_dossie_html(
                nome=lead_info['nome'],
                nicho=lead_info['nicho'],
                bairro=lead_info['bairro'],
                nota=lead_info['nota'],
                avaliacoes=lead_info['avaliacoes']
            )
            
            b64_html = base64.b64encode(html_dossie.encode('utf-8')).decode('utf-8')
            href = f'<a href="data:text/html;base64,{b64_html}" download="auditoria_{lead_info["nome"].split()[0]}.html" style="text-decoration: none; padding: 10px 20px; background-color: #d93025; color: white; border-radius: 5px; font-weight: bold;">📥 Baixar Dossiê (HTML)</a>'
            
            col_d1, col_d2 = st.columns([1, 2])
            with col_d1:
                st.markdown(href, unsafe_allow_html=True)
                st.caption("O arquivo HTML abrirá direto no navegador do seu cliente como um site interativo!")
                
        st.divider()
        st.markdown("### ⬇️ Exportação Final")
        col_down1, col_down2 = st.columns(2)
        
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        col_down1.download_button("📄 Baixar toda a Base do CRM (CSV)", data=csv_buffer.getvalue(), file_name="meu_crm_completo.csv", mime="text/csv")
        
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='BaseCRM')
        col_down2.download_button("📊 Baixar toda a Base do CRM (Excel)", data=excel_buffer.getvalue(), file_name="meu_crm_completo.xlsx")
