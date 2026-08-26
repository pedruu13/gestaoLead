import streamlit as st
import time
import random
import pandas as pd
import re
import io
import urllib.parse
from playwright.sync_api import sync_playwright

# --- Funções Auxiliares ---
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
        if not numeros.startswith('55'):
            numeros = '55' + numeros
        return numeros
    return ""

def formatar_whatsapp(numeros: str, copy_texto: str = "") -> str:
    if not numeros: return ""
    url = f"https://wa.me/{numeros}"
    if copy_texto:
        url += f"?text={urllib.parse.quote(copy_texto)}"
    return url

def gerar_copy_inteligente(nome, bairro, nota):
    """ Gera um texto de vendas persuasivo baseado nos dados do lead """
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    copy = f"Olá, encontrei o perfil de {nome_curto} aqui no Google Maps! "
    try:
        nota_float = float(nota.replace(',', '.')) if nota else 0.0
        if nota_float >= 4.5:
            copy += f"Parabéns pela excelente avaliação de {nota} estrelas. "
    except: pass
    copy += f"Vi que vocês são de {bairro}, mas notei que a empresa ainda não possui um site profissional próprio. Gostaria de apresentar uma proposta rápida sem compromisso?"
    return copy

def gerar_prompt_prototipo(nome, nicho):
    """ Gera um prompt de Inteligência Artificial para ferramentas como Midjourney, DALL-E ou v0.dev """
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    return f"UI/UX web design of a modern, high-converting landing page for a {nicho} business named '{nome_curto}'. Clean layout, professional typography, hero section with a clear call-to-action button, services overview section, testimonials, WhatsApp floating button. Dribbble style, Behance style, 8k resolution, modern corporate colors."

def normalizar_chave(nome: str, endereco: str) -> str:
    return f"{nome.strip().lower()}|{endereco.strip().lower()}"

def extrair_avaliacoes(page):
    try:
        botoes = page.locator('button')
        for i in range(min(botoes.count(), 20)):
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
    """ Visita a página para extrair E-mails e mapear links de Redes Sociais """
    resultado = {"emails": "", "instagram": "", "facebook": "", "linkedin": ""}
    
    if not url or "wa.me" in url or "whatsapp.com" in url:
        return resultado
        
    try:
        temp_page = context.new_page()
        temp_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        temp_page.goto(url, timeout=15000)
        pausa(2, 4) 
        
        # Extrair E-mails do texto
        texto_pagina = temp_page.inner_text("body")
        emails_encontrados = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', texto_pagina)
        emails_limpos = list(set([e for e in emails_encontrados if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]))
        resultado["emails"] = ", ".join(emails_limpos)
        
        # Extrair Redes Sociais mapeando todos os links (tags <a>)
        todos_links = temp_page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
        for l in todos_links:
            if not l: continue
            l_lower = l.lower()
            if "instagram.com/" in l_lower and not resultado["instagram"]: resultado["instagram"] = l
            elif "facebook.com/" in l_lower and not resultado["facebook"]: resultado["facebook"] = l
            elif "linkedin.com/in/" in l_lower or "linkedin.com/company/" in l_lower:
                if not resultado["linkedin"]: resultado["linkedin"] = l

        temp_page.close()
    except Exception:
        try: temp_page.close()
        except: pass
        
    return resultado


# --- Interface da Aplicação Web (Streamlit) ---
st.set_page_config(page_title="Buscador de Leads PRO", page_icon="🕵️‍♂️", layout="wide")

st.title("🌐 Buscador de Leads PRO (Master / Fase 3)")
st.markdown("Extração avançada com Filtros de Qualificação, Copy Inteligente e Mapeamento de Redes.")

# --- BARRA LATERAL (CONFIGURAÇÕES) ---
with st.sidebar:
    st.header("⚙️ Configurações Gerais")
    carregar_img = st.checkbox("Carregar imagens web (Mais lento)", value=False)
    
    st.divider()
    st.header("🕵️ Extração Profunda")
    ativar_cacador = st.checkbox("Mapear E-mails e Redes Sociais", help="Entra nos links para achar e-mails, Instagram, FB e LinkedIn. Deixa a busca mais lenta.")
    
    st.divider()
    st.header("🤖 Copy Inteligente")
    ativar_copy = st.checkbox("Gerar Mensagem de Vendas", value=True, help="O link do WhatsApp já virá com um texto persuasivo pronto usando os dados do Lead.")
    
    st.divider()
    st.header("🎛️ Filtros de Qualificação")
    st.caption("Só salva os leads que passarem nestes filtros:")
    filtro_nota = st.slider("Nota Mínima no Google", min_value=0.0, max_value=5.0, value=0.0, step=0.1)
    filtro_avaliacoes = st.number_input("Mínimo de Avaliações", min_value=0, value=0)
    filtro_whatsapp = st.checkbox("Obrigatório ter WhatsApp", value=False)

# --- CORPO PRINCIPAL ---
col1, col2 = st.columns(2)
with col1:
    nichos_raw = st.text_area("Nichos (separados por vírgula):", "advogado, clinica de estetica", height=100)
with col2:
    bairros_raw = st.text_area("Bairros (separados por vírgula):", "Moema - São Paulo", height=100)

if st.button("▶ Iniciar Busca Master", type="primary"):
    nichos = [n.strip() for n in nichos_raw.split(",") if n.strip()]
    bairros = [b.strip() for b in bairros_raw.split(",") if b.strip()]
    
    if not nichos or not bairros:
        st.warning("⚠️ Preencha os campos de nichos e bairros antes de iniciar!")
        st.stop()
        
    st.divider()
    st.subheader("📊 Dashboard em Tempo Real")
    col_metric1, col_metric2, col_metric3, col_metric4 = st.columns(4)
    metric_total = col_metric1.empty()
    metric_filtrados = col_metric2.empty()
    metric_whats = col_metric3.empty()
    metric_email = col_metric4.empty()
    
    metric_total.metric("Total de Leads Salvos", 0)
    metric_filtrados.metric("Leads Descartados (Filtro)", 0)
    metric_whats.metric("Leads com WhatsApp", 0)
    metric_email.metric("Leads com E-mail", 0)
    
    progress_bar = st.progress(0)
    log_area = st.empty()
    tabela_area = st.empty()
    
    resultados_finais = []
    ja_salvos = set()
    
    stats = {"salvos": 0, "descartados": 0, "com_whats": 0, "com_email": 0}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(locale="pt-BR", viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            
            if not carregar_img:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
                
            total_buscas = len(nichos) * len(bairros)
            buscas_feitas = 0
            
            for bairro in bairros:
                for nicho in nichos:
                    termo = f"{nicho} em {bairro}"
                    log_area.info(f"🔍 Buscando agora: {termo}")
                    
                    url = f"https://www.google.com/maps/search/{termo.replace(' ', '+')}"
                    page.goto(url, timeout=30000)
                    pausa(2, 4)
                    
                    try:
                        painel = page.locator('div[role="feed"]').first
                        for _ in range(3):
                            painel.hover()
                            page.mouse.wheel(0, 3000)
                            pausa(1, 2)
                    except: pass
                    
                    links = page.locator('a[href*="/maps/place/"]')
                    total_links = min(links.count(), 15)
                    hrefs = []
                    for i in range(total_links):
                        h = links.nth(i).get_attribute("href")
                        if h and h not in hrefs: hrefs.append(h)
                        
                    for i, href in enumerate(hrefs):
                        log_area.text(f"Extraindo dados... ({i+1}/{len(hrefs)} locais) de '{termo}'")
                        try:
                            page.goto(href, timeout=20000)
                            pausa(1.5, 2.5)
                            
                            nome_el = page.locator("h1").first
                            nome = nome_el.inner_text() if nome_el.count() > 0 else "Sem nome"

                            link_el = page.locator('a[data-item-id="authority"]')
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            
                            tipo_link = classificar_link(link_encontrado)
                            if tipo_link == "site_proprio":
                                continue
                                
                            tel_el = page.locator('button[data-item-id^="phone"]')
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)

                            end_el = page.locator('button[data-item-id="address"]')
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereço: ", "").strip() if end_el.count() > 0 else ""
                            
                            chave = normalizar_chave(nome, endereco)
                            if chave in ja_salvos: continue
                            ja_salvos.add(chave)
                            
                            # Avaliações do Google
                            nota_str, qtd_str = extrair_avaliacoes(page)
                            
                            # --- 🎛️ APLICAÇÃO DOS FILTROS DE QUALIFICAÇÃO ---
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
                            # ------------------------------------------------
                            
                            # --- 🤖 COPY INTELIGENTE ---
                            copy_texto = ""
                            if ativar_copy and numeros_whats:
                                copy_texto = gerar_copy_inteligente(nome, bairro, nota_str)
                            
                            whats_link_final = formatar_whatsapp(numeros_whats, copy_texto)
                            
                            # --- 🕵️ VASCULHADOR DE REDES E E-MAILS ---
                            dados_profundos = {"emails": "", "instagram": "", "facebook": "", "linkedin": ""}
                            if ativar_cacador and link_encontrado:
                                log_area.text(f"🕵️ Vasculhando redes/e-mails de: {nome}")
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
                            resultados_finais.append(lead_data)
                            
                            # Atualiza as métricas
                            stats["salvos"] += 1
                            if whats_link_final: stats["com_whats"] += 1
                            if dados_profundos["emails"]: stats["com_email"] += 1
                            
                            metric_total.metric("Total de Leads Salvos", stats["salvos"])
                            metric_filtrados.metric("Leads Descartados (Filtro)", stats["descartados"])
                            metric_whats.metric("Leads com WhatsApp", stats["com_whats"])
                            metric_email.metric("Leads com E-mail", stats["com_email"])
                            
                            # Atualizar tabela
                            df_temp = pd.DataFrame(resultados_finais)
                            tabela_area.dataframe(df_temp, use_container_width=True)
                            
                        except Exception as e:
                            pass
                    
                    buscas_feitas += 1
                    progress_bar.progress(buscas_feitas / total_buscas)
                            
            browser.close()
            
        log_area.empty()
        st.success(f"🎉 Busca concluída! {stats['salvos']} leads aprovados pelos filtros.")
        
        if resultados_finais:
            df_final = pd.DataFrame(resultados_finais)
            
            st.subheader("Gráfico de Leads por Nicho")
            st.bar_chart(df_final['Nicho'].value_counts())
            
            st.divider()
            st.subheader("📥 Exportar Resultados")
            col_down1, col_down2 = st.columns(2)
            
            csv_buffer = io.StringIO()
            df_final.to_csv(csv_buffer, index=False)
            col_down1.download_button(
                label="📄 Baixar Planilha (CSV)",
                data=csv_buffer.getvalue(),
                file_name="leads_master.csv",
                mime="text/csv"
            )
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_final.to_excel(writer, index=False, sheet_name='Leads')
            
            col_down2.download_button(
                label="📊 Baixar Planilha (Excel .xlsx)",
                data=excel_buffer.getvalue(),
                file_name="leads_master.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            
    except Exception as e:
        st.error(f"❌ Ocorreu um erro: {e}")
