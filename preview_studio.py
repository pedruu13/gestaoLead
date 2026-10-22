import os
import re
from html import escape

from commercial_intelligence import analyze_lead, clean_text


PALETTES = {
    "saúde": ("#0f766e", "#ecfeff", "#083344"),
    "odontologia": ("#0369a1", "#eff6ff", "#082f49"),
    "estética": ("#9d174d", "#fff1f2", "#4c0519"),
    "advocacia": ("#a16207", "#fffbeb", "#1c1917"),
    "arquitetura": ("#7c3f2c", "#fff7ed", "#292524"),
    "reformas": ("#b45309", "#fffbeb", "#292524"),
    "contabilidade": ("#1d4ed8", "#eff6ff", "#172554"),
    "engenharia": ("#334155", "#f8fafc", "#0f172a"),
    "manutenção": ("#c2410c", "#fff7ed", "#292524"),
    "gastronomia": ("#b91c1c", "#fff7ed", "#450a0a"),
}


def safe_color(value, fallback):
    value = clean_text(value, 20)
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def build_preview_config(lead, overrides=None):
    analysis = analyze_lead(lead, preview_available=True)
    primary, surface, ink = PALETTES.get(analysis["segment"], ("#2563eb", "#f8fafc", "#0f172a"))
    overrides = overrides or {}
    name = clean_text(overrides.get("name") or analysis["name"], 90)
    category = clean_text(analysis["category"], 120)
    location = clean_text(analysis["location"], 120)
    headline = clean_text(overrides.get("headline") or f"{category.capitalize()} com informação clara e contato simples", 150)
    subheadline = clean_text(overrides.get("subheadline") or f"Uma proposta de apresentação digital para {name}{f' em {location}' if location else ''}.", 240)
    cta = clean_text(overrides.get("cta") or "Falar com a equipe", 45)
    services_value = overrides.get("services")
    if isinstance(services_value, str):
        services = [clean_text(item, 70) for item in services_value.splitlines() if clean_text(item, 70)]
    elif isinstance(services_value, list):
        services = [clean_text(item, 70) for item in services_value if clean_text(item, 70)]
    else:
        services = ["Serviços e especialidades", "Área de atendimento", "Contato e orçamento"]
    services = services[:6] or ["Serviços e especialidades", "Área de atendimento", "Contato e orçamento"]
    return {
        "name": name,
        "segment": analysis["segment"],
        "category": category,
        "location": location,
        "headline": headline,
        "subheadline": subheadline,
        "cta": cta,
        "services": services,
        "primary": safe_color(overrides.get("primary"), primary),
        "surface": safe_color(overrides.get("surface"), surface),
        "ink": safe_color(overrides.get("ink"), ink),
        "disclaimer": "Demonstração conceitual não oficial",
    }


def render_preview_html(config):
    data = {key: escape(str(value)) for key, value in config.items() if key != "services"}
    cards = "".join(
        f'<article class="service"><span>0{index}</span><h3>{escape(service)}</h3><p>Conteúdo demonstrativo para organizar a apresentação do negócio.</p></article>'
        for index, service in enumerate(config.get("services", []), 1)
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{data['name']} — demonstração</title>
<style>
:root{{--primary:{data['primary']};--surface:{data['surface']};--ink:{data['ink']};--line:color-mix(in srgb,var(--ink) 14%,transparent)}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--surface);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.shell{{min-height:100vh;overflow:hidden}} .notice{{padding:10px 5vw;background:var(--ink);color:white;text-align:center;font-size:12px;letter-spacing:.08em;text-transform:uppercase}}
header{{display:flex;align-items:center;justify-content:space-between;padding:24px 6vw;border-bottom:1px solid var(--line)}}
.brand{{font-weight:850;letter-spacing:-.04em;font-size:20px}} nav{{display:flex;gap:28px;font-size:13px;font-weight:700}} a{{color:inherit;text-decoration:none}}
.button{{display:inline-flex;align-items:center;justify-content:center;padding:14px 20px;border-radius:999px;background:var(--primary);color:white;font-weight:800;border:0}}
.hero{{display:grid;grid-template-columns:1.25fr .75fr;gap:7vw;align-items:center;padding:90px 6vw 76px;min-height:620px}}
.eyebrow{{display:flex;align-items:center;gap:9px;color:var(--primary);font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:.14em}} .eyebrow:before{{content:"";width:28px;height:2px;background:var(--primary)}}
h1{{font-size:clamp(46px,7vw,94px);line-height:.94;letter-spacing:-.065em;margin:24px 0;max-width:930px}} .lead{{font-size:clamp(17px,2vw,21px);line-height:1.65;max-width:650px;opacity:.72;margin-bottom:34px}}
.visual{{position:relative;min-height:430px;border-radius:34px;background:var(--ink);color:white;padding:34px;display:flex;flex-direction:column;justify-content:space-between;box-shadow:0 28px 80px color-mix(in srgb,var(--ink) 24%,transparent)}}
.visual:before{{content:"";position:absolute;inset:24px;border:1px solid rgba(255,255,255,.18);border-radius:24px}} .metric{{position:relative;font-size:12px;text-transform:uppercase;letter-spacing:.12em;opacity:.66}} .monogram{{position:relative;font-size:clamp(90px,12vw,170px);line-height:1;font-weight:900;color:var(--primary);letter-spacing:-.09em}} .caption{{position:relative;max-width:260px;line-height:1.5}}
.services-wrap{{padding:70px 6vw 94px;background:white}} .section-head{{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:42px}} h2{{font-size:clamp(34px,5vw,58px);letter-spacing:-.05em;margin:0;max-width:670px}} .section-head p{{max-width:430px;line-height:1.6;opacity:.65}}
.services{{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-left:1px solid var(--line)}} .service{{padding:32px;min-height:230px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}} .service span{{color:var(--primary);font-size:12px;font-weight:900}} .service h3{{font-size:23px;letter-spacing:-.03em;margin:46px 0 12px}} .service p{{font-size:14px;line-height:1.6;opacity:.62}}
.contact{{margin:0 6vw 72px;padding:56px;border-radius:30px;background:var(--primary);color:white;display:flex;align-items:center;justify-content:space-between;gap:40px}} .contact h2{{max-width:760px}} .contact .button{{background:white;color:var(--ink);flex:none}}
footer{{padding:30px 6vw;border-top:1px solid var(--line);display:flex;justify-content:space-between;font-size:12px;opacity:.65}}
@media(max-width:760px){{nav{{display:none}} header{{padding:18px 5vw}} .hero{{grid-template-columns:1fr;padding:62px 5vw 54px;min-height:auto}} h1{{font-size:48px}} .visual{{min-height:330px}} .services-wrap{{padding:58px 5vw}} .section-head{{display:block}} .services{{grid-template-columns:1fr}} .service{{min-height:190px}} .contact{{margin:0 5vw 50px;padding:34px;display:block}} .contact .button{{margin-top:24px}} footer{{padding:24px 5vw;gap:20px;flex-direction:column}}}}
</style></head><body><div class="shell"><div class="notice">{data['disclaimer']}</div>
<header><a class="brand" href="#">{data['name']}</a><nav><a href="#servicos">Serviços</a><a href="#sobre">Sobre</a><a href="#contato">Contato</a></nav><a class="button" href="#contato">{data['cta']}</a></header>
<main><section class="hero"><div><div class="eyebrow">{data['category']}</div><h1>{data['headline']}</h1><p class="lead">{data['subheadline']}</p><a class="button" href="#contato">{data['cta']}</a></div><div class="visual"><div class="metric">Proposta visual · {data['segment']}</div><div class="monogram">{escape(config['name'][:1].upper())}</div><div class="caption">Uma presença própria para apresentar o essencial e conduzir o próximo passo.</div></div></section>
<section class="services-wrap" id="servicos"><div class="section-head"><h2>Informação organizada para quem já está procurando.</h2><p>Estrutura conceitual editável. Os textos finais devem ser validados pela empresa antes de qualquer publicação.</p></div><div class="services">{cards}</div></section>
<section class="contact" id="contato"><h2>Um caminho direto entre interesse e atendimento.</h2><a class="button" href="#">{data['cta']}</a></section></main>
<footer><strong>{data['name']}</strong><span>{data['location'] or 'Localização a confirmar'} · Demonstração não oficial</span></footer></div></body></html>"""


def capture_preview_png(html, destination, width=1440, height=1100):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.set_content(html, wait_until="domcontentloaded")
            page.wait_for_timeout(150)
            try:
                page.screenshot(path=destination, full_page=True, animations="disabled")
            except Exception:
                page.screenshot(path=destination, full_page=False, animations="disabled")
        finally:
            browser.close()
    return destination
