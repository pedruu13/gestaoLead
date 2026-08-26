import customtkinter as ctk
import threading
import queue
import time
import random
import csv
import os
import re
from playwright.sync_api import sync_playwright

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

ARQUIVO_SAIDA = "leads_sem_site_pro.csv"
CAMPOS_CSV = ["nome", "nicho", "bairro", "endereco", "telefone", "whatsapp_link", "link_encontrado", "tipo_link", "google_maps"]
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

def formatar_whatsapp(telefone: str) -> str:
    if not telefone: return ""
    # Remove tudo que não for número
    numeros = re.sub(r'\D', '', telefone)
    # Verifica se tem tamanho suficiente para ser celular no Brasil (DDD + 9 dígitos = 11)
    if len(numeros) >= 10:
        if not numeros.startswith('55'):
            numeros = '55' + numeros
        return f"https://wa.me/{numeros}"
    return ""

def normalizar_chave(nome: str, endereco: str) -> str:
    return f"{nome.strip().lower()}|{endereco.strip().lower()}"

class AppLeads(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Buscador de Leads PRO")
        self.geometry("750x650")
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.is_running = False
        self.create_widgets()
        self.check_queue()

    def create_widgets(self):
        # Configuração do Grid principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Nichos
        ctk.CTkLabel(self, text="Nichos (separados por vírgula):", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=10, pady=(15,0), sticky="w")
        self.entry_nichos = ctk.CTkTextbox(self, height=60)
        self.entry_nichos.grid(row=0, column=1, padx=10, pady=(15,0), sticky="ew")
        self.entry_nichos.insert("1.0", "advogado, clinica de estetica, arquiteto")

        # Bairros
        ctk.CTkLabel(self, text="Bairros (separados por vírgula):", font=("Arial", 14, "bold")).grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.entry_bairros = ctk.CTkTextbox(self, height=60)
        self.entry_bairros.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        self.entry_bairros.insert("1.0", "Moema - São Paulo, Tatuapé - São Paulo")

        # Opções
        self.frame_opcoes = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_opcoes.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        self.check_visivel = ctk.CTkCheckBox(self.frame_opcoes, text="Navegador Visível (Ajuda a evitar bloqueios do Google)")
        self.check_visivel.pack(side="left", padx=10)
        self.check_visivel.select() # Default true

        self.check_imagens = ctk.CTkCheckBox(self.frame_opcoes, text="Carregar Imagens (Desmarque para extração +Rápida)")
        self.check_imagens.pack(side="left", padx=10)
        # Default False (não selecionado = não carrega imagens) = Modo rápido por padrão

        # Botões
        self.frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes.grid(row=4, column=0, columnspan=2, padx=10, pady=10)

        self.btn_iniciar = ctk.CTkButton(self.frame_botoes, text="▶ Iniciar Busca", command=self.start_scraping, fg_color="green", hover_color="darkgreen")
        self.btn_iniciar.pack(side="left", padx=10)

        self.btn_parar = ctk.CTkButton(self.frame_botoes, text="⏹ Parar Busca", command=self.stop_scraping, fg_color="red", hover_color="darkred", state="disabled")
        self.btn_parar.pack(side="left", padx=10)

        # Logs
        ctk.CTkLabel(self, text="Progresso / Logs:", font=("Arial", 12, "bold")).grid(row=3, column=0, padx=10, pady=(10,0), sticky="nw")
        self.log_box = ctk.CTkTextbox(self)
        self.log_box.grid(row=3, column=1, padx=10, pady=(10,0), sticky="nsew")
        self.log_box.configure(state="disabled")

    def log(self, message):
        self.log_queue.put(message)

    def check_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(100, self.check_queue)

    def start_scraping(self):
        if self.is_running: return
        
        nichos_raw = self.entry_nichos.get("1.0", "end").strip()
        bairros_raw = self.entry_bairros.get("1.0", "end").strip()
        
        if not nichos_raw or not bairros_raw:
            self.log("⚠️ Preencha os campos de nichos e bairros!")
            return

        nichos = [n.strip() for n in nichos_raw.split(",") if n.strip()]
        bairros = [b.strip() for b in bairros_raw.split(",") if b.strip()]
        
        visivel = self.check_visivel.get() == 1
        carregar_img = self.check_imagens.get() == 1

        self.is_running = True
        self.stop_event.clear()
        self.btn_iniciar.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        
        self.log("🚀 Iniciando buscador PRO...")

        # Inicia a thread separada para não congelar a interface
        threading.Thread(target=self.run_scraper, args=(nichos, bairros, visivel, carregar_img), daemon=True).start()

    def stop_scraping(self):
        self.log("🛑 Parada solicitada. Aguarde o ciclo atual encerrar...")
        self.stop_event.set()

    def run_scraper(self, nichos, bairros, visivel, carregar_img):
        try:
            self.garantir_csv()
            ja_salvos = self.carregar_ja_salvos()
            total_novos = 0

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=not visivel)
                context = browser.new_context(locale="pt-BR", viewport={'width': 1280, 'height': 800})
                page = context.new_page()

                # Otimização de bloqueio de recursos
                if not carregar_img:
                    page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
                    self.log("⚡ Modo veloz ativado (bloqueando imagens/fontes).")

                for bairro in bairros:
                    if self.stop_event.is_set(): break
                    for nicho in nichos:
                        if self.stop_event.is_set(): break
                        
                        termo = f"{nicho} em {bairro}"
                        self.log(f"\n🔍 Buscando: {termo}...")
                        
                        resultados = self.buscar_no_maps(page, termo)
                        
                        for r in resultados:
                            if self.stop_event.is_set(): break
                            
                            tipo_link = classificar_link(r["link_encontrado"])
                            # Só queremos quem NÃO tem site
                            if tipo_link == "site_proprio":
                                continue

                            chave = normalizar_chave(r["nome"], r["endereco"])
                            if chave in ja_salvos:
                                continue

                            ja_salvos.add(chave)
                            lead = {
                                "nome": r["nome"],
                                "nicho": nicho,
                                "bairro": bairro,
                                "endereco": r["endereco"],
                                "telefone": r["telefone"],
                                "whatsapp_link": formatar_whatsapp(r["telefone"]),
                                "link_encontrado": r["link_encontrado"],
                                "tipo_link": tipo_link,
                                "google_maps": r["google_maps"],
                            }
                            self.salvar_lead(lead)
                            total_novos += 1
                            self.log(f"  ✅ Lead Salvo: {r['nome']} ({tipo_link})")

                browser.close()
            
            if self.stop_event.is_set():
                self.log(f"\n⏹ Busca cancelada pelo usuário. Total de novos leads salvos: {total_novos}")
            else:
                self.log(f"\n🎉 Busca concluída com sucesso! Total de novos leads salvos: {total_novos}")

        except Exception as e:
            self.log(f"❌ Erro crítico: {e}")
        finally:
            self.is_running = False
            self.btn_iniciar.configure(state="normal")
            self.btn_parar.configure(state="disabled")

    def buscar_no_maps(self, page, termo: str):
        resultados = []
        url = f"https://www.google.com/maps/search/{termo.replace(' ', '+')}"
        try:
            page.goto(url, timeout=30000)
            pausa(2, 4)
            
            # Tentar rolar a lista algumas vezes para carregar mais resultados
            try:
                painel = page.locator('div[role="feed"]').first
                for _ in range(3):
                    if self.stop_event.is_set(): return resultados
                    painel.hover()
                    page.mouse.wheel(0, 3000)
                    pausa(1, 2)
            except: pass

            links = page.locator('a[href*="/maps/place/"]')
            total = min(links.count(), 15) # Limite para não demorar muito por termo
            hrefs = []
            for i in range(total):
                h = links.nth(i).get_attribute("href")
                if h and h not in hrefs: hrefs.append(h)

            self.log(f"  Encontrados {len(hrefs)} locais. Extraindo dados...")

            for i, href in enumerate(hrefs):
                if self.stop_event.is_set(): break
                try:
                    page.goto(href, timeout=20000)
                    pausa(1.5, 2.5) # Espera curta otimizada

                    nome_el = page.locator("h1").first
                    nome = nome_el.inner_text() if nome_el.count() > 0 else "Sem nome"

                    link_el = page.locator('a[data-item-id="authority"]')
                    link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""

                    tel_el = page.locator('button[data-item-id^="phone"]')
                    telefone = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""

                    end_el = page.locator('button[data-item-id="address"]')
                    endereco = end_el.first.get_attribute("aria-label").replace("Endereço: ", "").strip() if end_el.count() > 0 else ""

                    resultados.append({
                        "nome": nome.strip(),
                        "link_encontrado": link_encontrado,
                        "telefone": telefone,
                        "endereco": endereco,
                        "google_maps": href,
                    })
                except Exception as e:
                    self.log(f"  [aviso] Falha ao extrair um local. Pulando...")
                    
        except Exception as e:
            self.log(f"  [erro] Falha ao pesquisar termo: {e}")
            
        return resultados

    def garantir_csv(self):
        if not os.path.exists(ARQUIVO_SAIDA):
            with open(ARQUIVO_SAIDA, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
                writer.writeheader()

    def carregar_ja_salvos(self):
        vistos = set()
        if os.path.exists(ARQUIVO_SAIDA):
            with open(ARQUIVO_SAIDA, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "nome" in row and "endereco" in row:
                        vistos.add(normalizar_chave(row["nome"], row["endereco"]))
        return vistos

    def salvar_lead(self, lead):
        with open(ARQUIVO_SAIDA, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
            writer.writerow(lead)

if __name__ == "__main__":
    app = AppLeads()
    app.mainloop()
