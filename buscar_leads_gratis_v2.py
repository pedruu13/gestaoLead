"""
Buscador Automático de Leads sem Site — 100% GRATUITO (sem API key, sem cartão)
=================================================================================
VERSÃO 2 — melhorias:
  - Detecta quando o "site" cadastrado é na real um link de Instagram/Linktree/
    WhatsApp (ou seja, o negócio NÃO tem site de verdade, só rede social)
  - Evita leads duplicados entre buscas diferentes (ex: um advogado que aparece
    tanto na busca "advogado Moema" quanto "advogado Vila Mariana")
  - Salva progresso incrementalmente: a cada busca concluída, já grava no CSV,
    então se você cancelar (Ctrl+C) no meio, não perde o que já foi coletado

COMO INSTALAR (uma vez só):
    pip install playwright
    playwright install chromium

COMO USAR:
1. Edite as listas NICHOS e BAIRROS lá embaixo.
2. Rode: python buscar_leads_gratis.py
3. O resultado vai sendo salvo em "leads_sem_site.csv" conforme roda.

OBSERVAÇÕES IMPORTANTES:
- Janela de navegador fica visível de propósito, pra imitar navegação humana.
- Tem pausas entre as ações — não remova, evitam bloqueio temporário da sessão.
- Rode em lotes pequenos (poucos nichos/bairros por vez).
"""

import csv
import os
import random
import time
from playwright.sync_api import sync_playwright

# ============ CONFIGURAÇÃO ============

NICHOS = [
    "advogado",
    "clinica de estetica",
    "arquiteto",
    "psicologo",
    "dentista",
]

BAIRROS = [
    "Moema, São Paulo",
    "Vila Mariana, São Paulo",
    "Tatuapé, São Paulo",
]

MAX_RESULTADOS_POR_BUSCA = 15  # quantos negócios checar por combinação nicho+bairro
ARQUIVO_SAIDA = "leads_sem_site.csv"

# domínios que indicam que "o site" é na real só uma rede social, não site próprio
DOMINIOS_REDE_SOCIAL = [
    "instagram.com", "linktr.ee", "linktree", "wa.me", "whatsapp.com",
    "facebook.com", "wix.com/website-builder", "beacons.ai", "bio.link",
]

CAMPOS_CSV = ["nome", "nicho", "bairro", "endereco", "telefone", "link_encontrado", "tipo_link", "google_maps"]

# ============ NÃO PRECISA MEXER DAQUI PRA BAIXO ============


def pausa(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))


def classificar_link(url: str) -> str:
    """Retorna 'rede_social' se o link for Instagram/Linktree/etc, senão 'site_proprio'."""
    if not url:
        return "sem_link"
    url_lower = url.lower()
    for dominio in DOMINIOS_REDE_SOCIAL:
        if dominio in url_lower:
            return "rede_social"
    return "site_proprio"


def normalizar_chave(nome: str, endereco: str) -> str:
    """Cria uma chave única pra detectar duplicados entre buscas diferentes."""
    return f"{nome.strip().lower()}|{endereco.strip().lower()}"


def carregar_ja_salvos() -> set:
    """Se o CSV já existe de uma execução anterior, carrega as chaves já salvas."""
    vistos = set()
    if os.path.exists(ARQUIVO_SAIDA):
        with open(ARQUIVO_SAIDA, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vistos.add(normalizar_chave(row["nome"], row["endereco"]))
    return vistos


def garantir_csv_com_cabecalho():
    if not os.path.exists(ARQUIVO_SAIDA):
        with open(ARQUIVO_SAIDA, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
            writer.writeheader()


def salvar_lead(lead: dict):
    with open(ARQUIVO_SAIDA, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        writer.writerow(lead)


def buscar_no_maps(page, termo: str) -> list[dict]:
    url = f"https://www.google.com/maps/search/{termo.replace(' ', '+')}"
    page.goto(url, timeout=30000)
    pausa(3, 5)

    try:
        painel = page.locator('div[role="feed"]').first
        for _ in range(4):
            painel.hover()
            page.mouse.wheel(0, 2000)
            pausa(1, 2)
    except Exception:
        pass

    links = page.locator('a[href*="/maps/place/"]')
    total = min(links.count(), MAX_RESULTADOS_POR_BUSCA)

    hrefs = []
    for i in range(total):
        href = links.nth(i).get_attribute("href")
        if href and href not in hrefs:
            hrefs.append(href)

    resultados = []
    for href in hrefs:
        try:
            page.goto(href, timeout=20000)
            pausa(2, 3)

            nome_el = page.locator("h1").first
            nome = nome_el.inner_text() if nome_el.count() > 0 else "Sem nome"

            # link de site (pode ser site próprio, Instagram, Linktree etc.)
            link_el = page.locator('a[data-item-id="authority"]')
            link_encontrado = ""
            if link_el.count() > 0:
                link_encontrado = link_el.first.get_attribute("href") or ""

            tel_el = page.locator('button[data-item-id^="phone"]')
            telefone = ""
            if tel_el.count() > 0:
                aria = tel_el.first.get_attribute("aria-label") or ""
                telefone = aria.replace("Telefone: ", "").strip()

            end_el = page.locator('button[data-item-id="address"]')
            endereco = ""
            if end_el.count() > 0:
                aria = end_el.first.get_attribute("aria-label") or ""
                endereco = aria.replace("Endereço: ", "").strip()

            resultados.append({
                "nome": nome.strip(),
                "link_encontrado": link_encontrado,
                "telefone": telefone,
                "endereco": endereco,
                "google_maps": href,
            })
        except Exception as e:
            print(f"    [aviso] falhou ao abrir um resultado: {e}")
            continue

    return resultados


def main():
    garantir_csv_com_cabecalho()
    ja_salvos = carregar_ja_salvos()
    total_verificado = 0
    total_novos = 0
    total_duplicados = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(locale="pt-BR")

        for bairro in BAIRROS:
            for nicho in NICHOS:
                termo = f"{nicho} em {bairro}"
                print(f"Buscando: {termo}...")

                resultados = buscar_no_maps(page, termo)
                total_verificado += len(resultados)

                for r in resultados:
                    tipo_link = classificar_link(r["link_encontrado"])

                    # só nos interessa quem NÃO tem site próprio de verdade
                    if tipo_link == "site_proprio":
                        continue

                    chave = normalizar_chave(r["nome"], r["endereco"])
                    if chave in ja_salvos:
                        total_duplicados += 1
                        continue

                    ja_salvos.add(chave)
                    lead = {
                        "nome": r["nome"],
                        "nicho": nicho,
                        "bairro": bairro,
                        "endereco": r["endereco"],
                        "telefone": r["telefone"],
                        "link_encontrado": r["link_encontrado"],
                        "tipo_link": tipo_link,  # "rede_social" ou "sem_link"
                        "google_maps": r["google_maps"],
                    }
                    salvar_lead(lead)
                    total_novos += 1

                print(f"  -> {total_novos} leads novos salvos até agora ({total_duplicados} duplicados ignorados)")
                pausa(3, 6)

        browser.close()

    print(f"\n✅ Concluído! {total_novos} leads novos de {total_verificado} verificados.")
    print(f"   ({total_duplicados} duplicados ignorados automaticamente)")
    print(f"Arquivo salvo em: {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    main()
