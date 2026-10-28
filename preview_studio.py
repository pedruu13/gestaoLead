import os
import re
from html import escape

from commercial_intelligence import analyze_lead, clean_text


SEGMENT_PROFILES = {
    "saúde": {"template": "care", "primary": "#147d74", "surface": "#f4fbfa", "ink": "#12302d", "headline": "Cuidado explicado com clareza, antes mesmo da consulta.", "cta": "Agendar atendimento", "services": ["Atendimentos e especialidades", "Orientações para a primeira consulta", "Equipe e estrutura"], "section_title": "Informação que acolhe e facilita a decisão."},
    "odontologia": {"template": "care", "primary": "#0877a9", "surface": "#f2f9fc", "ink": "#102f3e", "headline": "Um sorriso começa com confiança e informação clara.", "cta": "Agendar avaliação", "services": ["Tratamentos odontológicos", "Como funciona a avaliação", "Estrutura e atendimento"], "section_title": "Tudo o que o paciente precisa saber para agendar."},
    "estética": {"template": "editorial", "primary": "#a64265", "surface": "#fff8f8", "ink": "#3b1e29", "headline": "Beleza com propósito, técnica e atendimento próximo.", "cta": "Quero uma avaliação", "services": ["Procedimentos e indicações", "Avaliação personalizada", "Cuidados antes e depois"], "section_title": "Uma experiência digital à altura do atendimento."},
    "advocacia": {"template": "authority", "primary": "#b78a3d", "surface": "#f4f1ea", "ink": "#171a1f", "headline": "Orientação jurídica com seriedade desde o primeiro contato.", "cta": "Falar com o escritório", "services": ["Áreas de atuação", "Como o atendimento funciona", "Contato confidencial"], "section_title": "Clareza para quem precisa tomar uma decisão importante."},
    "arquitetura": {"template": "portfolio", "primary": "#b65d3f", "surface": "#f5f1eb", "ink": "#24211d", "headline": "Projetos que transformam rotina, espaço e experiência.", "cta": "Apresentar meu projeto", "services": ["Projetos residenciais", "Interiores e ambientes", "Acompanhamento de obra"], "section_title": "Um portfólio que deixa o trabalho falar primeiro."},
    "reformas": {"template": "technical", "primary": "#dc6b20", "surface": "#f8f6f1", "ink": "#242424", "headline": "Reforma bem planejada, do orçamento à entrega.", "cta": "Solicitar orçamento", "services": ["Reformas residenciais", "Planejamento e orçamento", "Execução e acompanhamento"], "section_title": "Processo claro para reduzir dúvidas antes da obra."},
    "contabilidade": {"template": "authority", "primary": "#295fb8", "surface": "#f4f7fb", "ink": "#172641", "headline": "Contabilidade próxima para decisões mais seguras.", "cta": "Falar com um especialista", "services": ["Abertura e regularização", "Rotina fiscal e contábil", "Consultoria para empresas"], "section_title": "Serviços organizados para o empresário encontrar respostas."},
    "engenharia": {"template": "technical", "primary": "#3e6477", "surface": "#f3f6f7", "ink": "#152b35", "headline": "Engenharia aplicada com método, precisão e responsabilidade.", "cta": "Solicitar análise", "services": ["Projetos e laudos", "Execução técnica", "Consultoria especializada"], "section_title": "Capacidade técnica apresentada de forma objetiva."},
    "manutenção": {"template": "technical", "primary": "#d55324", "surface": "#f8f5f1", "ink": "#28221f", "headline": "Solução rápida, serviço explicado e contato sem complicação.", "cta": "Pedir atendimento", "services": ["Serviços disponíveis", "Regiões atendidas", "Orçamento e chamado"], "section_title": "Quem precisa resolver agora encontra o caminho certo."},
    "gastronomia": {"template": "hospitality", "primary": "#bd3d2b", "surface": "#fff8ed", "ink": "#311b16", "headline": "Uma experiência que começa antes de chegar à mesa.", "cta": "Fazer uma reserva", "services": ["Cardápio e especialidades", "Horários e localização", "Reservas e eventos"], "section_title": "Sabor, ambiente e informação no mesmo lugar."},
}

DEFAULT_PROFILE = {"template": "professional", "primary": "#2563eb", "surface": "#f6f8fb", "ink": "#13213b", "headline": "Serviço bem apresentado para facilitar a próxima decisão.", "cta": "Falar com a equipe", "services": ["Serviços e especialidades", "Como funciona o atendimento", "Contato e orçamento"], "section_title": "Informação organizada para quem já está procurando."}
ALLOWED_TEMPLATES = {"care", "editorial", "authority", "portfolio", "technical", "hospitality", "professional"}


def safe_color(value, fallback):
    value = clean_text(value, 20)
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def safe_data_image(value, max_length=1_800_000):
    value = str(value or "").strip()
    if len(value) > max_length:
        return ""
    return value if re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+", value) else ""


def build_preview_config(lead, overrides=None):
    analysis = analyze_lead(lead, preview_available=True)
    profile = SEGMENT_PROFILES.get(analysis["segment"], DEFAULT_PROFILE)
    overrides = overrides or {}
    name = clean_text(overrides.get("name") or analysis["name"], 90)
    category = clean_text(analysis["category"], 120)
    location = clean_text(analysis["location"], 120)
    services_value = overrides.get("services")
    if isinstance(services_value, str):
        services = [clean_text(item, 70) for item in services_value.splitlines() if clean_text(item, 70)]
    elif isinstance(services_value, list):
        services = [clean_text(item, 70) for item in services_value if clean_text(item, 70)]
    else:
        services = list(profile["services"])
    selected_template = clean_text(overrides.get("template"), 30)
    if selected_template not in ALLOWED_TEMPLATES:
        selected_template = profile["template"]
    return {
        "name": name,
        "segment": analysis["segment"],
        "category": category,
        "location": location,
        "template": selected_template,
        "headline": clean_text(overrides.get("headline") or profile["headline"], 150),
        "subheadline": clean_text(overrides.get("subheadline") or f"Uma proposta digital para apresentar o trabalho de {name} e facilitar o contato de quem já procura pelo serviço{f' em {location}' if location else ''}.", 260),
        "cta": clean_text(overrides.get("cta") or profile["cta"], 45),
        "services": services[:6] or list(profile["services"]),
        "section_title": clean_text(overrides.get("section_title") or profile["section_title"], 150),
        "primary": safe_color(overrides.get("primary"), profile["primary"]),
        "surface": safe_color(overrides.get("surface"), profile["surface"]),
        "ink": safe_color(overrides.get("ink"), profile["ink"]),
        "hero_image": safe_data_image(overrides.get("hero_image") or lead.get("Imagem do Negócio")),
        "brand_logo": safe_data_image(overrides.get("brand_logo") or lead.get("Logo do Negócio"), 700_000),
        "disclaimer": "Demonstração conceitual não oficial — conteúdo sujeito à validação da empresa",
    }


def _visual(config, data):
    hero_image = config.get("hero_image")
    logo = config.get("brand_logo")
    image_style = f' style="background-image:linear-gradient(180deg,transparent 25%,rgba(0,0,0,.62)),url(\'{hero_image}\')"' if hero_image else ""
    logo_html = f'<img class="logo" src="{logo}" alt="Logo fornecido para a demonstração">' if logo else f'<span class="wordmark">{escape(config["name"][:2].upper())}</span>'
    label = data.get("location") or data.get("category") or "Apresentação do negócio"
    return f'<div class="visual {"has-photo" if hero_image else "no-photo"}"{image_style}><div class="visual-top">{logo_html}<span>{data["segment"]}</span></div><p>{label}</p></div>'


def render_preview_html(config):
    data = {key: escape(str(value)) for key, value in config.items() if key not in {"services", "hero_image", "brand_logo"}}
    cards = "".join(f'<article class="service"><span>0{index}</span><h3>{escape(service)}</h3><p>Bloco demonstrativo para explicar este serviço com clareza e direcionar o contato.</p></article>' for index, service in enumerate(config.get("services", []), 1))
    visual = _visual(config, data)
    if data["template"] in {"portfolio", "hospitality", "editorial"}:
        hero = f'<section class="hero hero-image-first">{visual}<div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><a class="button" href="#contato">{data["cta"]}</a></div></section>'
    elif data["template"] == "authority":
        hero = f'<section class="hero hero-authority"><div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><div class="actions"><a class="button" href="#contato">{data["cta"]}</a><span>Atendimento responsável<br>e informações objetivas</span></div></div>{visual}</section>'
    else:
        hero = f'<section class="hero"><div class="hero-copy"><div class="eyebrow">{data["category"]}</div><h1>{data["headline"]}</h1><p>{data["subheadline"]}</p><a class="button" href="#contato">{data["cta"]}</a></div>{visual}</section>'
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{data['name']} — demonstração</title><style>
:root{{--primary:{data['primary']};--surface:{data['surface']};--ink:{data['ink']};--line:color-mix(in srgb,var(--ink) 14%,transparent)}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--surface);color:var(--ink);font-family:Georgia,"Times New Roman",serif}}a{{color:inherit;text-decoration:none}}.shell{{min-height:100vh;overflow:hidden}}.notice{{padding:9px 5vw;background:var(--ink);color:white;text-align:center;font:700 10px/1.4 ui-sans-serif,system-ui;letter-spacing:.13em;text-transform:uppercase}}header{{display:flex;align-items:center;justify-content:space-between;padding:24px 6vw;border-bottom:1px solid var(--line)}}.brand{{font-size:22px;font-weight:800;letter-spacing:-.04em}}nav{{display:flex;gap:28px;font:700 12px/1 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.08em}}.button{{display:inline-flex;align-items:center;justify-content:center;padding:15px 22px;border-radius:3px;background:var(--primary);color:white;font:800 12px/1 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.08em}}
.hero{{display:grid;grid-template-columns:1.05fr .95fr;gap:6vw;align-items:center;padding:72px 6vw 82px;min-height:650px}}.hero-copy{{position:relative;z-index:2}}.eyebrow{{color:var(--primary);font:900 11px/1.4 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.18em}}h1{{font-size:clamp(48px,6.4vw,92px);line-height:.96;letter-spacing:-.055em;margin:24px 0 28px;max-width:960px}}.hero-copy>p{{font:400 clamp(16px,1.7vw,20px)/1.65 ui-sans-serif,system-ui;max-width:670px;opacity:.72;margin:0 0 34px}}.visual{{min-height:480px;border-radius:2px;background:var(--ink);color:white;padding:28px;background-size:cover;background-position:center;display:flex;flex-direction:column;justify-content:space-between;box-shadow:24px 28px 0 color-mix(in srgb,var(--primary) 20%,transparent)}}.visual.no-photo{{background-image:linear-gradient(135deg,color-mix(in srgb,var(--primary) 72%,var(--ink)),var(--ink));position:relative;overflow:hidden}}.visual.no-photo:after{{content:"";position:absolute;width:420px;height:420px;border:1px solid rgba(255,255,255,.18);border-radius:50%;right:-180px;bottom:-180px}}.visual-top{{display:flex;justify-content:space-between;align-items:center;font:800 10px/1 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.13em;position:relative;z-index:1}}.logo{{display:block;max-width:150px;max-height:70px;object-fit:contain;background:white;padding:8px}}.wordmark{{display:grid;place-items:center;width:64px;height:64px;border:1px solid rgba(255,255,255,.35);font:900 24px/1 ui-sans-serif,system-ui}}.visual>p{{position:relative;z-index:1;font:700 13px/1.5 ui-sans-serif,system-ui;max-width:250px}}
.hero-image-first{{grid-template-columns:1.12fr .88fr;padding-top:46px}}.hero-image-first .visual{{min-height:610px;order:0}}.hero-image-first .hero-copy{{order:1}}.hero-authority{{background:var(--ink);color:white}}.actions{{display:flex;align-items:center;gap:28px}}.actions span{{font:600 11px/1.5 ui-sans-serif,system-ui;opacity:.6;text-transform:uppercase;letter-spacing:.08em}}.services-wrap{{padding:76px 6vw 96px;background:white}}.section-head{{display:flex;justify-content:space-between;gap:34px;align-items:end;margin-bottom:46px}}h2{{font-size:clamp(36px,5vw,64px);letter-spacing:-.05em;line-height:1;margin:0;max-width:780px}}.section-head p{{font:400 14px/1.7 ui-sans-serif,system-ui;max-width:410px;opacity:.62}}.services{{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-left:1px solid var(--line)}}.service{{padding:34px;min-height:235px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}}.service span{{color:var(--primary);font:900 11px/1 ui-sans-serif,system-ui}}.service h3{{font-size:25px;line-height:1.1;margin:48px 0 14px}}.service p{{font:400 13px/1.65 ui-sans-serif,system-ui;opacity:.62}}.contact{{margin:0 6vw 76px;padding:58px;background:var(--primary);color:white;display:flex;align-items:center;justify-content:space-between;gap:42px}}.contact h2{{max-width:760px}}.contact .button{{background:white;color:var(--ink);flex:none}}footer{{padding:30px 6vw;border-top:1px solid var(--line);display:flex;justify-content:space-between;font:600 11px/1.4 ui-sans-serif,system-ui;opacity:.65}}
@media(max-width:760px){{nav{{display:none}}header{{padding:18px 5vw}}.hero,.hero-image-first{{grid-template-columns:1fr;padding:54px 5vw 64px;min-height:auto}}.hero-image-first .visual{{min-height:420px;order:1}}.hero-image-first .hero-copy{{order:0}}h1{{font-size:49px}}.visual{{min-height:350px;box-shadow:12px 14px 0 color-mix(in srgb,var(--primary) 20%,transparent)}}.services-wrap{{padding:58px 5vw}}.section-head{{display:block}}.services{{grid-template-columns:1fr}}.service{{min-height:185px}}.contact{{margin:0 5vw 50px;padding:34px;display:block}}.contact .button{{margin-top:24px}}footer{{padding:24px 5vw;gap:18px;flex-direction:column}}}}
</style></head><body><div class="shell"><div class="notice">{data['disclaimer']}</div><header><a class="brand" href="#">{data['name']}</a><nav><a href="#servicos">Serviços</a><a href="#sobre">Sobre</a><a href="#contato">Contato</a></nav><a class="button" href="#contato">{data['cta']}</a></header><main>{hero}<section class="services-wrap" id="servicos"><div class="section-head"><h2>{data['section_title']}</h2><p>Estrutura criada para este segmento. Textos, fotos, marca e informações finais devem ser aprovados pela empresa.</p></div><div class="services">{cards}</div></section><section class="contact" id="contato"><h2>Transforme interesse em um próximo passo claro.</h2><a class="button" href="#">{data['cta']}</a></section></main><footer><strong>{data['name']}</strong><span>{data['location'] or 'Localização a confirmar'} · Demonstração não oficial</span></footer></div></body></html>"""


def capture_preview_png(html, destination, width=1440, height=1100):
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.set_content(html, wait_until="domcontentloaded")
            page.wait_for_timeout(100)
            page.screenshot(path=destination, full_page=True, animations="disabled")
        finally:
            browser.close()
    return destination
